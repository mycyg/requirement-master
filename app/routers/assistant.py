"""Free-form AI assistant: system/usage help, project Q&A grounded in the
grep knowledge base, and conversational requirement drafting.

SSE streaming reuses the same event contract as the clarify chat
(`thinking` / `text` / `parsed` / `error` / `done`) so the frontend's
streaming reader works unchanged. The conversation is stateless — the
client holds the history and sends it each turn (no DB persistence)."""
from __future__ import annotations

import json
import logging
from typing import Optional

from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from auth import current_user
from config import settings
from db import SessionLocal
from models import User
from prompts import load as load_prompt
from services.knowledge import search_knowledge

router = APIRouter(prefix="/api", tags=["assistant"])
logger = logging.getLogger("yqgl.assistant")

_client = AsyncAnthropic(base_url=settings.llm_base_url, api_key=settings.llm_api_key)

HISTORY_BUDGET = 16
KNOWLEDGE_HITS = 6


class AssistantMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class AssistantChatIn(BaseModel):
    messages: list[AssistantMessage]
    project_id: Optional[str] = None


def _sse(event: str, data) -> bytes:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    # Per SSE spec each line of the payload needs its own `data:`; use
    # splitlines so embedded \n / \r in LLM text can't break framing.
    lines = payload.splitlines() if payload else [""]
    block = "\n".join(f"data: {line}" for line in lines)
    return f"event: {event}\n{block}\n\n".encode("utf-8")


def _safe_parse(raw: str) -> dict | None:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        nl = raw.find("\n")
        if nl != -1:
            raw = raw[nl + 1:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        i, j = raw.find("{"), raw.rfind("}")
        if i == -1 or j == -1 or j <= i:
            return None
        try:
            d = json.loads(raw[i:j + 1])
        except json.JSONDecodeError:
            return None
    if not isinstance(d, dict) or d.get("action") not in {"answer", "draft_requirement"}:
        return None
    return d


def _evidence_block(user: User, project_id: str | None, query: str) -> str:
    """Grep the knowledge base for the latest user question and format the top
    hits as an evidence block. Runs synchronously with its own short-lived
    session before streaming begins, so no DB session is held across the SSE."""
    if not project_id or not query.strip():
        return ""
    db = SessionLocal()
    try:
        hits = search_knowledge(db, user, query=query, project_id=project_id, limit=KNOWLEDGE_HITS)
    except Exception:
        logger.exception("assistant knowledge search failed")
        hits = []
    finally:
        db.close()
    if not hits:
        return ""
    lines = ["# Project evidence (from the knowledge base — cite the items you use)"]
    for h in hits:
        lines.append(f"- [{h.title}] ({h.source_url}) :: {h.snippet[:240]}")
    return "\n".join(lines)


@router.post("/assistant/chat")
async def assistant_chat(payload: AssistantChatIn, user: User = Depends(current_user)):
    system_prompt = load_prompt("assistant_system")

    msgs: list[dict] = []
    for m in payload.messages[-HISTORY_BUDGET:]:
        content = (m.content or "").strip()
        if not content:
            continue
        msgs.append({"role": "assistant" if m.role == "assistant" else "user", "content": content})
    if not msgs or msgs[0]["role"] != "user":
        msgs.insert(0, {"role": "user", "content": "(开始对话)"})

    last_user = next((m["content"] for m in reversed(msgs) if m["role"] == "user"), "")
    evidence = _evidence_block(user, payload.project_id, last_user)

    ctx = f"Context — current user: {user.nickname}."
    if payload.project_id:
        ctx += f" Active project id: {payload.project_id}."
    if evidence:
        ctx += "\n\n" + evidence
    msgs[0]["content"] = f"{ctx}\n\n---\n\n{msgs[0]['content']}"

    async def gen():
        text_accum: list[str] = []
        try:
            async with _client.messages.stream(
                model=settings.llm_model,
                max_tokens=4000,
                system=system_prompt,
                messages=msgs,
            ) as stream:
                async for event in stream:
                    if getattr(event, "type", None) != "content_block_delta":
                        continue
                    delta = event.delta
                    dtype = getattr(delta, "type", None)
                    if dtype == "thinking_delta":
                        yield _sse("thinking", delta.thinking)
                    elif dtype == "text_delta":
                        text_accum.append(delta.text)
                        yield _sse("text", delta.text)
            parsed = _safe_parse("".join(text_accum))
            if parsed is None:
                # Never strand the user on a parse miss — surface the raw text.
                parsed = {"action": "answer", "payload": {"answer_md": "".join(text_accum).strip() or "（暂时没有内容）"}}
            yield _sse("parsed", parsed)
        except Exception as e:
            logger.exception("assistant stream failed")
            yield _sse("error", f"server error: {type(e).__name__}: {e}")
        yield _sse("done", {})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
