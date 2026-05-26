"""Voice I/O proxies. ASR (8001) for transcribe, CosyVoice (8002) for TTS."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from auth import current_user
from config import settings
from models import User

router = APIRouter(prefix="/api/voice", tags=["voice"])


# ---------- ASR ----------

@router.post("/transcribe")
async def transcribe(audio: UploadFile = File(...), _: User = Depends(current_user)) -> dict:
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="empty audio")
    files = {"audio": (audio.filename or "voice.webm", audio_bytes, audio.content_type or "audio/webm")}
    try:
        async with httpx.AsyncClient(timeout=60.0) as c:
            r = await c.post(f"{settings.asr_base_url}/transcribe", files=files)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=503, detail=f"ASR upstream error: {e}") from e
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"ASR returned {r.status_code}: {r.text[:300]}")
    data = r.json()
    return {"text": data.get("text", ""), "language": data.get("language"), "ms": data.get("ms")}


@router.get("/asr-health")
async def asr_health() -> dict:
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{settings.asr_base_url}/health")
        return r.json()
    except Exception as e:
        return {"ready": False, "error": str(e)}


# ---------- TTS ----------

class TTSIn(BaseModel):
    text: str = Field(min_length=1, max_length=3000)
    voice: str | None = None


@router.post("/tts")
async def tts(payload: TTSIn, _: User = Depends(current_user)) -> Response:
    try:
        async with httpx.AsyncClient(timeout=60.0) as c:
            r = await c.post(f"{settings.tts_base_url}/tts", json=payload.model_dump(exclude_none=True))
    except httpx.HTTPError as e:
        raise HTTPException(status_code=503, detail=f"TTS upstream error: {e}") from e
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"TTS returned {r.status_code}: {r.text[:300]}")
    return Response(
        content=r.content,
        media_type="audio/wav",
        headers={
            "X-Voice": r.headers.get("x-voice", ""),
            "X-Elapsed-Ms": r.headers.get("x-elapsed-ms", ""),
            "Cache-Control": "no-cache",
        },
    )


@router.get("/voices")
async def list_voices() -> dict:
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{settings.tts_base_url}/health")
        if r.status_code != 200:
            return {
                "ready": False,
                "voices": [],
                "default": None,
                "error": f"TTS returned {r.status_code}: {r.text[:200]}",
            }
        try:
            h = r.json()
        except ValueError:
            return {
                "ready": False,
                "voices": [],
                "default": None,
                "error": "TTS health returned non-JSON or empty response",
            }
        return {
            "ready": bool(h.get("ready")),
            "voices": h.get("voices", []),
            "default": h.get("default_voice"),
        }
    except Exception as e:
        return {"ready": False, "voices": [], "default": None, "error": str(e)}
