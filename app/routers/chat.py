"""Agent chat: SSE streaming for clarification, plus answer submission."""
from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import current_user
from db import SessionLocal, get_db
from models import Attachment, ChatMessage, Requirement, User
from services.activity import log_activity
from services.llm_agent import AgentEvent, step
from services.permissions import can_view_requirement_record
from services.push_bus import bus
from services.schedule import sync_requirement_due_event

router = APIRouter(prefix="/api", tags=["chat"])
# Set of req_ids currently streaming a clarify turn. Replaces the previous
# `dict[str, asyncio.Lock]` (which had two race conditions: `lock.locked()`
# is not atomic with `await lock.acquire()` in asyncio, and popping the
# lock from the dict in `finally` opened a window where new requests could
# create a fresh lock and run concurrently). A plain set is bulletproof
# under asyncio's single-threaded model — `in` + `add` happen in the same
# scheduling tick without any await between them, so no other coroutine
# can sneak in.
_chat_running: set[str] = set()


# ---------- input models ----------

class ChatStartIn(BaseModel):
    force_summarize: bool = False


class AnswerIn(BaseModel):
    # mutually exclusive: either a selected option (with optional other_text) or open text
    selected_option_key: Optional[str] = None
    other_text: Optional[str] = None
    text: Optional[str] = None


# ---------- helpers ----------

def _sse(event: str, data) -> bytes:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    # SSE spec: every line of the payload needs its own `data:` prefix.
    # Use `splitlines()` (not `split("\n")`) so a CRLF or bare `\r` from
    # LLM output doesn't leave a trailing `\r` on each data line — the SSE
    # parser treats bare `\r` as its own line terminator and would split
    # the event mid-payload. Without this, embedded `\n` / `\r\n` in
    # LLM reasoning text breaks framing and the Clarify page sticks on
    # "AI 助理正在思考…" because `parsed` arrives as malformed JSON.
    lines = payload.splitlines() if payload else [""]
    data_block = "\n".join(f"data: {line}" for line in lines)
    return f"event: {event}\n{data_block}\n\n".encode("utf-8")


def _require_req(db: Session, req_id: str) -> Requirement:
    r = db.query(Requirement).filter(Requirement.id == req_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="requirement not found")
    return r


def _claim_chat_slot(req_id: str) -> bool:
    """Atomic try-add. Returns True if this caller now owns the slot."""
    if req_id in _chat_running:
        return False
    _chat_running.add(req_id)
    return True


def _release_chat_slot(req_id: str) -> None:
    _chat_running.discard(req_id)


# ---------- chat: SSE stream ----------

@router.post("/requirements/{req_id}/chat")
async def chat_step(
    req_id: str,
    payload: ChatStartIn = Body(default_factory=ChatStartIn),
    user: User = Depends(current_user),
):
    """Stream one LLM turn. SSE event types:
    - `thinking`   data: text chunk (assistant's reasoning)
    - `text`       data: text chunk (assistant's final JSON, raw stream)
    - `parsed`     data: full parsed action+payload JSON object (after stream ends)
    - `error`      data: error string
    - `done`       data: {"chat_message_id": "..."}
    """
    # Capture context with a synchronous session before entering the stream.
    # Claim the chat slot AFTER permission + status checks so a wrong-role
    # or wrong-state caller can't briefly hold the slot to deny clarify to
    # the real submitter between his retries.
    db_sync: Session = SessionLocal()
    try:
        req = _require_req(db_sync, req_id)
        if req.submitter_user_id != user.id:
            raise HTTPException(status_code=403, detail="only the requester can clarify this requirement")
        if req.status not in {"draft", "clarifying"}:
            raise HTTPException(status_code=400, detail=f"requirement not in clarifying state (status={req.status})")
        if not _claim_chat_slot(req_id):
            raise HTTPException(status_code=409, detail="clarification is already running for this requirement")
        attachments = list(req.attachments)
        history = list(
            db_sync.query(ChatMessage).filter(ChatMessage.requirement_id == req_id).order_by(ChatMessage.created_at).all()
        )
        if req.status == "draft":
            req.status = "clarifying"
            db_sync.commit()
            await bus.publish(f"req:{req_id}", "requirement.updated", {"status": "clarifying"})
        actor = user.nickname
        force = payload.force_summarize
    except Exception:
        _release_chat_slot(req_id)
        raise
    finally:
        db_sync.close()

    async def gen():
        try:
            text_buf: list[str] = []
            parsed: dict | None = None
            try:
                async for ev in step(req, attachments, history, force_summarize=force):
                    if ev.kind == "thinking":
                        yield _sse("thinking", ev.data)
                    elif ev.kind == "text":
                        text_buf.append(ev.data)
                        yield _sse("text", ev.data)
                    elif ev.kind == "parsed":
                        parsed = ev.data
                        yield _sse("parsed", parsed)
                    elif ev.kind == "error":
                        yield _sse("error", ev.data)
            except Exception as e:
                yield _sse("error", f"server error: {type(e).__name__}: {e}")

            chat_msg_id = None
            if parsed:
                kind = {
                    "ask_choice": "question_choice",
                    "ask_open": "question_open",
                    "summarize": "summary",
                }.get(parsed.get("action"), "text")

                db2: Session = SessionLocal()
                try:
                    msg = ChatMessage(
                        requirement_id=req_id,
                        role="assistant",
                        kind=kind,
                        content_json=json.dumps(parsed, ensure_ascii=False),
                    )
                    db2.add(msg)
                    if kind == "summary":
                        payload_d = parsed.get("payload", {}) or {}
                        req2 = db2.query(Requirement).filter(Requirement.id == req_id).first()
                        # Only transition into summary_ready if the requirement
                        # is still in an in-progress clarify state. If the user
                        # cancelled or admin-deleted the requirement during the
                        # LLM stream (which can take 30+ seconds), don't
                        # clobber that terminal status back to summary_ready.
                        if req2 and req2.status in {"draft", "clarifying"}:
                            req2.title = payload_d.get("title") or req2.title
                            req2.summary_md = payload_d.get("summary_md") or req2.summary_md
                            req2.status = "summary_ready"
                            if req2.due_at:
                                sync_requirement_due_event(db2, req2)
                        log_activity(
                            db2, requirement_id=req_id, actor_nickname=actor,
                            action="clarified", detail={"final": True},
                        )
                    db2.commit()
                    db2.refresh(msg)
                    chat_msg_id = msg.id
                    if kind == "summary":
                        await bus.publish(f"req:{req_id}", "requirement.updated", {"status": "summary_ready"})
                finally:
                    db2.close()

            yield _sse("done", {"chat_message_id": chat_msg_id})
        finally:
            _release_chat_slot(req_id)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------- answer submission ----------

@router.post("/requirements/{req_id}/chat/answer")
def chat_answer(
    req_id: str,
    payload: AnswerIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    req = _require_req(db, req_id)
    if req.submitter_user_id != user.id:
        raise HTTPException(status_code=403, detail="only the requester can answer clarification questions")
    # Refuse to append chat messages to a terminal-status requirement —
    # otherwise users can pollute a cancelled / delivered / accepted chat
    # thread (which gets reindexed into the knowledge base).
    if req.status not in {"draft", "clarifying"}:
        raise HTTPException(status_code=400, detail=f"cannot answer in status {req.status}")
    if not any([payload.selected_option_key, payload.other_text, payload.text]):
        raise HTTPException(status_code=400, detail="empty answer")

    msg = ChatMessage(
        requirement_id=req_id,
        role="user",
        kind="text",
        content_json=json.dumps(payload.model_dump(exclude_none=True), ensure_ascii=False),
        selected_option_key=payload.selected_option_key,
        user_other_text=payload.other_text,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return {"chat_message_id": msg.id, "ok": True}


@router.get("/requirements/{req_id}/chat/messages")
def list_messages(req_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[dict]:
    req = _require_req(db, req_id)
    if not can_view_requirement_record(req, user):
        raise HTTPException(status_code=403, detail="you cannot view this conversation yet")
    rows = db.query(ChatMessage).filter(ChatMessage.requirement_id == req_id).order_by(ChatMessage.created_at).all()
    out = []
    for m in rows:
        try:
            content = json.loads(m.content_json)
        except Exception:
            content = {"raw": m.content_json}
        out.append({
            "id": m.id,
            "role": m.role,
            "kind": m.kind,
            "content": content,
            "selected_option_key": m.selected_option_key,
            "user_other_text": m.user_other_text,
            "created_at": m.created_at.isoformat(),
        })
    return out
