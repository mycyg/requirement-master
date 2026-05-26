"""Receive a delivery zip via chunked upload from the tray client, then
asynchronously have the LLM write a delivery doc and notify everyone."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import current_user
from config import settings
from db import SessionLocal, get_db
from models import Delivery, Requirement, User
from services.activity import log_activity
from services.delivery_doc import generate_doc, list_zip_files
from services.push_bus import bus

router = APIRouter(prefix="/api", tags=["delivery-upload"])

MAX_BYTES = 1024 * 1024 * 1024  # 1 GB


class DeliveryInitIn(BaseModel):
    filename: str = Field(min_length=1, max_length=256)
    total_size: int = Field(ge=1, le=MAX_BYTES)
    total_chunks: int = Field(ge=1)


def _partial_dir(upload_id: str) -> Path:
    return settings.data_dir / "deliveries" / "_partial" / upload_id


def _meta_path(upload_id: str) -> Path:
    return _partial_dir(upload_id) / "_meta.json"


def _require_req(db: Session, req_id: str) -> Requirement:
    r = db.query(Requirement).filter(Requirement.id == req_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="requirement not found")
    return r


@router.post("/requirements/{req_id}/delivery/init")
def init(
    req_id: str,
    payload: DeliveryInitIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    r = _require_req(db, req_id)
    if r.status in {"accepted", "cancelled"}:
        raise HTTPException(status_code=400, detail=f"requirement is {r.status}; cannot deliver")

    upload_id = uuid.uuid4().hex
    pdir = _partial_dir(upload_id)
    pdir.mkdir(parents=True, exist_ok=True)
    _meta_path(upload_id).write_text(
        json.dumps({
            "req_id": req_id,
            "filename": payload.filename,
            "total_size": payload.total_size,
            "total_chunks": payload.total_chunks,
            "nickname": user.nickname,
        }),
        encoding="utf-8",
    )
    return {"upload_id": upload_id, "chunk_size": 5 * 1024 * 1024}


@router.put("/requirements/{req_id}/delivery/{upload_id}/chunk/{idx}")
async def chunk(
    req_id: str, upload_id: str, idx: int, request: Request,
    _: User = Depends(current_user),
) -> dict:
    pdir = _partial_dir(upload_id)
    if not pdir.exists():
        raise HTTPException(status_code=404, detail="unknown upload_id")
    meta = json.loads(_meta_path(upload_id).read_text(encoding="utf-8"))
    if meta["req_id"] != req_id:
        raise HTTPException(status_code=400, detail="upload_id mismatch")
    if idx < 0 or idx >= meta["total_chunks"]:
        raise HTTPException(status_code=400, detail="chunk index out of range")

    target = pdir / f"{idx:06d}.bin"
    written = 0
    h = hashlib.sha256()
    with open(target, "wb") as f:
        async for piece in request.stream():
            f.write(piece)
            h.update(piece)
            written += len(piece)
    return {"idx": idx, "bytes": written, "sha256": h.hexdigest()}


@router.post("/requirements/{req_id}/delivery/{upload_id}/finalize")
async def finalize(
    req_id: str, upload_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    pdir = _partial_dir(upload_id)
    if not pdir.exists():
        raise HTTPException(status_code=404, detail="unknown upload_id")
    meta = json.loads(_meta_path(upload_id).read_text(encoding="utf-8"))
    if meta["req_id"] != req_id:
        raise HTTPException(status_code=400, detail="upload_id mismatch")
    r = _require_req(db, req_id)

    chunks = sorted(p for p in pdir.iterdir() if p.suffix == ".bin")
    if len(chunks) != meta["total_chunks"]:
        raise HTTPException(status_code=400, detail=f"missing chunks: have {len(chunks)}, expected {meta['total_chunks']}")

    round_num = 1 + db.query(Delivery).filter(Delivery.requirement_id == req_id).count()
    out_dir = settings.data_dir / "deliveries" / req_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"round-{round_num}.zip"

    h = hashlib.sha256()
    total = 0
    with open(out_path, "wb") as out:
        for c in chunks:
            with open(c, "rb") as src:
                while True:
                    buf = src.read(1024 * 1024)
                    if not buf: break
                    out.write(buf)
                    h.update(buf)
                    total += len(buf)
    if total != meta["total_size"]:
        os.unlink(out_path)
        raise HTTPException(status_code=400, detail=f"size mismatch: got {total}, expected {meta['total_size']}")

    file_count = len(list_zip_files(out_path))

    d = Delivery(
        requirement_id=req_id, round=round_num,
        package_path=str(out_path), package_size=total,
        package_sha256=h.hexdigest(), file_count=file_count,
        delivery_doc_md="（AI 正在撰写交付文档…）",
        submitted_by_nickname=user.nickname,
    )
    db.add(d)
    r.status = "delivered"
    r.delivered_at = datetime.utcnow()
    log_activity(
        db, requirement_id=req_id, actor_nickname=user.nickname,
        action="status_changed", detail={"to": "delivered", "round": round_num, "files": file_count},
    )
    db.commit()
    db.refresh(d)

    shutil.rmtree(pdir, ignore_errors=True)

    await bus.publish(f"req:{req_id}", "requirement.updated", {"status": "delivered"})
    await bus.publish("all", "requirement.updated", {"requirement_id": req_id, "status": "delivered"})

    # Kick off async LLM doc generation
    prior_files: list[str] = []
    if round_num > 1:
        prev = db.query(Delivery).filter(
            Delivery.requirement_id == req_id, Delivery.round == round_num - 1,
        ).first()
        if prev:
            prior_files = list_zip_files(Path(prev.package_path))

    asyncio.create_task(_finalize_doc(d.id, r.title or r.code, r.summary_md or "", out_path, prior_files))

    return {
        "id": d.id, "round": d.round, "package_size": d.package_size,
        "file_count": d.file_count, "sha256": d.package_sha256,
    }


async def _finalize_doc(delivery_id: str, title: str, summary_md: str, zip_path: Path, prior_files: list[str]) -> None:
    try:
        doc = await generate_doc(title, summary_md, zip_path, prior_round_files=prior_files)
    except Exception as e:
        doc = f"## 交付文档生成失败\n\n{type(e).__name__}: {e}"

    db = SessionLocal()
    try:
        d = db.query(Delivery).filter(Delivery.id == delivery_id).first()
        if d:
            d.delivery_doc_md = doc
            db.commit()
            await bus.publish(f"req:{d.requirement_id}", "delivery.doc_ready", {
                "delivery_id": d.id, "round": d.round,
            })
    finally:
        db.close()
