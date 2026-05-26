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

router = APIRouter(prefix="/api", tags=["chat"])
_chat_locks: dict[str, asyncio.Lock] = {}


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
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


def _require_req(db: Session, req_id: str) -> Requirement:
    r = db.query(Requirement).filter(Requirement.id == req_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="requirement not found")
    return r


def _lock_for(req_id: str) -> asyncio.Lock:
    lock = _chat_locks.get(req_id)
    if lock is None:
        lock = asyncio.Lock()
        _chat_locks[req_id] = lock
    return lock


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
    lock = _lock_for(req_id)
    if lock.locked():
        raise HTTPException(status_code=409, detail="clarification is already running for this requirement")
    await lock.acquire()

    # Capture context with a synchronous session before entering the stream
    db_sync: Session = SessionLocal()
    try:
        req = _require_req(db_sync, req_id)
        if req.submitter_user_id != user.id:
            raise HTTPException(status_code=403, detail="only the requester can clarify this requirement")
        if req.status not in {"draft", "clarifying"}:
            raise HTTPException(status_code=400, detail=f"requirement not in clarifying state (status={req.status})")
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
        lock.release()
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
                        if req2:
                            req2.title = payload_d.get("title") or req2.title
                            req2.summary_md = payload_d.get("summary_md") or req2.summary_md
                            req2.status = "summary_ready"
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
            if lock.locked():
                lock.release()
            _chat_locks.pop(req_id, None)

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
