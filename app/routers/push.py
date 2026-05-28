"""SSE push channel for the tray client (and the web UI, where useful).

Topics published elsewhere via services.push_bus:
  - "all"          requirement.ready / requirement.updated (tray client subscribes)
  - "req:<id>"     per-requirement updates (web UI when viewing detail)
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from auth import StreamUser, require_stream_user
from services.presence import mark_stream_closed, mark_stream_open
from services.push_bus import stream

router = APIRouter(prefix="/api/push", tags=["push"])


def _sse(event: str, data) -> bytes:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    # Per SSE spec — each payload line needs its own `data:` prefix or any
    # embedded `\n` breaks event framing. Use `splitlines()` (not split)
    # so CRLF / bare \r don't leave trailing \r that the parser treats as
    # a record terminator. See chat.py for the symptom.
    lines = payload.splitlines() if payload else [""]
    data_block = "\n".join(f"data: {line}" for line in lines)
    return f"event: {event}\n{data_block}\n\n".encode("utf-8")


async def _gen(request: Request, topic: str, user: StreamUser):
    mark_stream_open(user.id)
    try:
        # initial ack
        yield _sse("connected", {"topic": topic})
        async for ev in stream(topic):
            if await request.is_disconnected():
                return
            if ev.type == "heartbeat":
                yield b": ping\n\n"
            else:
                yield _sse(ev.type, ev.data)
    finally:
        mark_stream_closed(user.id)


@router.get("/stream")
async def stream_all(request: Request, user: StreamUser = Depends(require_stream_user)) -> StreamingResponse:
    """Global stream — receives all requirement.* events."""
    return StreamingResponse(
        _gen(request, "all", user),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/stream/req/{req_id}")
async def stream_one(req_id: str, request: Request, user: StreamUser = Depends(require_stream_user)) -> StreamingResponse:
    """Per-requirement stream — for web UI watching a single requirement detail."""
    return StreamingResponse(
        _gen(request, f"req:{req_id}", user),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/stream/me")
async def stream_me(request: Request, user: StreamUser = Depends(require_stream_user)) -> StreamingResponse:
    """Cookie-scoped per-user stream — receives `notification.created` events
    addressed to the requesting user only. Topic is `user:{auth_user_id}`
    (NOT a path param), so a client can't request another user's stream."""
    return StreamingResponse(
        _gen(request, f"user:{user.id}", user),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
