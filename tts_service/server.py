"""Standalone CosyVoice TTS FastAPI server (port 8002, localhost only).

Loads CosyVoice3 + Fun-CosyVoice3-0.5B at startup. Exposes:
  POST /tts          body {text, voice} → audio/wav binary
  GET  /health       readiness + available voices
"""
from __future__ import annotations

import io
import os
import sys
import time
from contextlib import asynccontextmanager

# Make sibling CosyVoice repo importable (its modules are not in site-packages)
COSY_ROOT = os.environ.get("COSY_ROOT", "/home/mycyg/CosyVoice")
sys.path.insert(0, os.path.join(COSY_ROOT, "third_party/Matcha-TTS"))
sys.path.insert(0, COSY_ROOT)

# Strip outbound proxy env (model files are local)
for _k in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import Response  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

MODEL_DIR = os.environ.get(
    "COSY_MODEL_DIR",
    os.path.join(COSY_ROOT, "pretrained_models/Fun-CosyVoice3-0.5B"),
)
DEFAULT_VOICE = os.environ.get("COSY_DEFAULT_VOICE", "male")
SAMPLE_RATE = 22050  # CosyVoice3 output sample rate

_state: dict = {"model": None, "voices": [], "ready": False, "error": None}


def _load():
    import soundfile  # noqa: F401  ensure available before use
    from cosyvoice.cli.cosyvoice import CosyVoice3
    print(f"[tts] loading {MODEL_DIR}", flush=True)
    t0 = time.time()
    m = CosyVoice3(MODEL_DIR)
    print(f"[tts] loaded in {time.time() - t0:.1f}s, voices={m.list_available_spks()}", flush=True)
    return m


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        _state["model"] = _load()
        _state["voices"] = _state["model"].list_available_spks()
        _state["ready"] = True
    except Exception as e:
        _state["error"] = repr(e)
        print(f"[tts] FATAL load error: {e}", flush=True)
        raise
    yield


app = FastAPI(title="yqgl-tts", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {
        "ready": _state["ready"],
        "model_dir": MODEL_DIR,
        "voices": _state["voices"],
        "default_voice": DEFAULT_VOICE,
        "sample_rate": SAMPLE_RATE,
        "error": _state["error"],
    }


class TTSIn(BaseModel):
    text: str = Field(min_length=1, max_length=3000)
    voice: str | None = None


@app.post("/tts")
def tts(payload: TTSIn) -> Response:
    if not _state["ready"]:
        raise HTTPException(status_code=503, detail="model not ready")

    voice = payload.voice or DEFAULT_VOICE
    if voice not in _state["voices"]:
        raise HTTPException(
            status_code=400,
            detail=f"voice '{voice}' not available; available: {_state['voices']}",
        )

    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="empty text")

    import soundfile as sf

    chunks: list = []
    t0 = time.time()
    try:
        for res in _state["model"].inference_zero_shot(
            text, "", "", zero_shot_spk_id=voice, stream=False,
        ):
            arr = res["tts_speech"].cpu().numpy().squeeze()
            chunks.append(arr)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"inference failed: {type(e).__name__}: {e}")

    if not chunks:
        raise HTTPException(status_code=500, detail="no audio generated")

    import numpy as np
    audio = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
    buf = io.BytesIO()
    sf.write(buf, audio, SAMPLE_RATE, format="WAV")
    elapsed_ms = int((time.time() - t0) * 1000)

    return Response(
        content=buf.getvalue(),
        media_type="audio/wav",
        headers={
            "X-Voice": voice,
            "X-Elapsed-Ms": str(elapsed_ms),
            "X-Sample-Rate": str(SAMPLE_RATE),
        },
    )
