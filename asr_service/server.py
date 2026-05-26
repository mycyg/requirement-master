"""Standalone Qwen3-ASR FastAPI server (port 8001, localhost only).

Loads the model on startup (resident in VRAM). Exposes:
  POST /transcribe   multipart audio file → {"language": str, "text": str, "ms": int}
  GET  /health       readiness probe
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

# Strip outbound proxy env vars (we're calling local files only; mirrors the user's transcribe.py)
for _k in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

from fastapi import FastAPI, HTTPException, UploadFile, File  # noqa: E402

MODEL_PATH = os.environ.get(
    "QWEN_ASR_MODEL_PATH",
    "/home/mycyg/.cache/modelscope/hub/models/Qwen/Qwen3-ASR-1___7B",
)
DEVICE = os.environ.get("QWEN_ASR_DEVICE", "cuda:0")
DTYPE = os.environ.get("QWEN_ASR_DTYPE", "bfloat16")

_state: dict = {"model": None, "ready": False, "error": None}


def _load_model():
    import torch
    from qwen_asr import Qwen3ASRModel

    dtype_map = {"bfloat16": torch.bfloat16, "float16": torch.float16, "float32": torch.float32}
    dtype = dtype_map.get(DTYPE, torch.bfloat16)

    print(f"[asr] loading model from {MODEL_PATH} on {DEVICE} ({DTYPE})", flush=True)
    t0 = time.time()
    model = Qwen3ASRModel.from_pretrained(
        MODEL_PATH,
        dtype=dtype,
        device_map=DEVICE,
        max_inference_batch_size=4,
        max_new_tokens=4096,
    )
    print(f"[asr] model loaded in {time.time() - t0:.1f}s", flush=True)
    return model


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        _state["model"] = _load_model()
        _state["ready"] = True
    except Exception as e:
        _state["error"] = repr(e)
        print(f"[asr] FATAL load error: {e}", flush=True)
        raise
    yield


app = FastAPI(title="yqgl-asr", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {
        "ready": _state["ready"],
        "model_path": MODEL_PATH,
        "device": DEVICE,
        "dtype": DTYPE,
        "error": _state["error"],
    }


def _to_wav_16k_mono(src: Path) -> Path:
    out = src.with_suffix(".wav")
    r = subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out)],
        capture_output=True,
    )
    if r.returncode != 0:
        raise HTTPException(status_code=400, detail=f"ffmpeg failed: {r.stderr.decode('utf-8', errors='replace')[-500:]}")
    return out


@app.post("/transcribe")
async def transcribe(audio: UploadFile = File(...)) -> dict:
    if not _state["ready"]:
        raise HTTPException(status_code=503, detail="model not ready")

    suffix = Path(audio.filename or "audio").suffix or ".bin"
    with tempfile.TemporaryDirectory(prefix="yqgl-asr-") as td:
        src = Path(td) / f"input{suffix}"
        with open(src, "wb") as f:
            f.write(await audio.read())

        wav = src if suffix.lower() == ".wav" else _to_wav_16k_mono(src)

        t0 = time.time()
        results = _state["model"].transcribe(audio=str(wav), language=None)
        elapsed_ms = int((time.time() - t0) * 1000)

    if not results:
        return {"language": None, "text": "", "ms": elapsed_ms}

    r0 = results[0]
    return {
        "language": getattr(r0, "language", None),
        "text": (getattr(r0, "text", "") or "").strip(),
        "ms": elapsed_ms,
    }
