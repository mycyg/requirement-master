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
from sqlalchemy.orm import Session, selectinload

from auth import require_local_client
from config import settings
from db import SessionLocal, get_db
from models import Delivery, Requirement, RequirementAssignment, User
from services.activity import log_activity
from services.assignments import ensure_public_claim_assignment, sync_legacy_lead
from services.delivery_doc import generate_doc, inspect_zip_entries, list_zip_files
from services.permissions import can_work_requirement
from services.push_bus import bus
from services.workspaces import ensure_workspaces_for_assignments, sync_workspace_to_status

router = APIRouter(prefix="/api", tags=["delivery-upload"])

MAX_BYTES = 1024 * 1024 * 1024  # 1 GB
CHUNK_SIZE = 5 * 1024 * 1024  # 5 MB


class DeliveryInitIn(BaseModel):
    filename: str = Field(min_length=1, max_length=256)
    total_size: int = Field(ge=1, le=MAX_BYTES)
    total_chunks: int = Field(ge=1)


def _partial_dir(upload_id: str) -> Path:
    return settings.data_dir / "deliveries" / "_partial" / upload_id


def _meta_path(upload_id: str) -> Path:
    return _partial_dir(upload_id) / "_meta.json"


def _expected_chunks(total_size: int) -> int:
    return max(1, (total_size + CHUNK_SIZE - 1) // CHUNK_SIZE)


def _expected_chunk_size(meta: dict, idx: int) -> int:
    if idx < meta["total_chunks"] - 1:
        return CHUNK_SIZE
    return meta["total_size"] - (CHUNK_SIZE * (meta["total_chunks"] - 1))


def _require_req(db: Session, req_id: str) -> Requirement:
    r = (
        db.query(Requirement)
        .options(selectinload(Requirement.assignments).selectinload(RequirementAssignment.user))
        .filter(Requirement.id == req_id)
        .first()
    )
    if not r:
        raise HTTPException(status_code=404, detail="requirement not found")
    return r


def _ensure_assignee(db: Session, r: Requirement, user: User) -> None:
    if r.assignments and not can_work_requirement(r, user):
        raise HTTPException(status_code=403, detail="only the assignee can deliver this requirement")
    if r.claimed_by_user_id and r.claimed_by_user_id != user.id and not can_work_requirement(r, user):
        raise HTTPException(status_code=403, detail="only the assignee can deliver this requirement")
    if not r.assignments:
        ensure_public_claim_assignment(db, r, user)
        log_activity(
            db, requirement_id=r.id, actor_nickname=user.nickname,
            action="claimed", detail={"source": "delivery_upload_backfill"},
        )
    else:
        sync_legacy_lead(r)
        if not r.claimed_at:
            r.claimed_at = datetime.utcnow()


@router.post("/requirements/{req_id}/delivery/init")
def init(
    req_id: str,
    payload: DeliveryInitIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_local_client),
) -> dict:
    r = _require_req(db, req_id)
    if r.status not in {"claimed", "doing", "revision_requested"}:
        raise HTTPException(status_code=400, detail=f"requirement is {r.status}; cannot deliver")
    if payload.total_chunks != _expected_chunks(payload.total_size):
        raise HTTPException(status_code=400, detail="total_chunks does not match configured chunk size")
    _ensure_assignee(db, r, user)

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
            "user_id": user.id,
        }),
        encoding="utf-8",
    )
    db.commit()
    return {"upload_id": upload_id, "chunk_size": CHUNK_SIZE}


@router.put("/requirements/{req_id}/delivery/{upload_id}/chunk/{idx}")
async def chunk(
    req_id: str, upload_id: str, idx: int, request: Request,
    user: User = Depends(require_local_client),
) -> dict:
    pdir = _partial_dir(upload_id)
    if not pdir.exists():
        raise HTTPException(status_code=404, detail="unknown upload_id")
    meta = json.loads(_meta_path(upload_id).read_text(encoding="utf-8"))
    if meta["req_id"] != req_id:
        raise HTTPException(status_code=400, detail="upload_id mismatch")
    if meta.get("user_id") != user.id:
        raise HTTPException(status_code=403, detail="only the upload owner can send chunks")
    if idx < 0 or idx >= meta["total_chunks"]:
        raise HTTPException(status_code=400, detail="chunk index out of range")

    target = pdir / f"{idx:06d}.bin"
    if target.exists():
        raise HTTPException(status_code=409, detail="chunk already uploaded")

    expected_size = _expected_chunk_size(meta, idx)
    written = 0
    h = hashlib.sha256()
    try:
        with open(target, "wb") as f:
            async for piece in request.stream():
                if written + len(piece) > expected_size:
                    raise HTTPException(status_code=413, detail="chunk too large")
                f.write(piece)
                h.update(piece)
                written += len(piece)
    except HTTPException:
        try:
            target.unlink(missing_ok=True)
        except Exception:
            pass
        raise
    if written != expected_size:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"chunk size mismatch: got {written}, expected {expected_size}")
    return {"idx": idx, "bytes": written, "sha256": h.hexdigest()}


@router.post("/requirements/{req_id}/delivery/{upload_id}/finalize")
async def finalize(
    req_id: str, upload_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_local_client),
) -> dict:
    pdir = _partial_dir(upload_id)
    if not pdir.exists():
        raise HTTPException(status_code=404, detail="unknown upload_id")
    meta = json.loads(_meta_path(upload_id).read_text(encoding="utf-8"))
    if meta["req_id"] != req_id:
        raise HTTPException(status_code=400, detail="upload_id mismatch")
    if meta.get("user_id") != user.id:
        raise HTTPException(status_code=403, detail="only the upload owner can finalize this upload")
    r = _require_req(db, req_id)
    if r.status not in {"claimed", "doing", "revision_requested"}:
        raise HTTPException(status_code=400, detail=f"requirement is {r.status}; cannot deliver")
    _ensure_assignee(db, r, user)

    chunks = sorted(p for p in pdir.iterdir() if p.suffix == ".bin")
    if len(chunks) != meta["total_chunks"]:
        raise HTTPException(status_code=400, detail=f"missing chunks: have {len(chunks)}, expected {meta['total_chunks']}")
    expected_names = {f"{i:06d}.bin" for i in range(meta["total_chunks"])}
    actual_names = {p.name for p in chunks}
    if actual_names != expected_names:
        raise HTTPException(status_code=400, detail="chunk set is incomplete or invalid")
    for idx, c in enumerate(chunks):
        expected_size = _expected_chunk_size(meta, idx)
        if c.stat().st_size != expected_size:
            raise HTTPException(
                status_code=400,
                detail=f"chunk {idx} size mismatch: got {c.stat().st_size}, expected {expected_size}",
            )

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

    try:
        file_count = len(inspect_zip_entries(out_path))
    except Exception as e:
        os.unlink(out_path)
        raise HTTPException(status_code=400, detail=f"invalid delivery zip: {e}")

    d = Delivery(
        requirement_id=req_id, round=round_num,
        package_path=str(out_path), package_size=total,
        package_sha256=h.hexdigest(), file_count=file_count,
        delivery_doc_md="（AI 正在撰写交付文档…）",
        submitted_by_nickname=user.nickname,
    )
    db.add(d)
    r.status = "delivery_doc_pending"
    r.delivered_at = datetime.utcnow()
    ensure_workspaces_for_assignments(db, r)
    sync_workspace_to_status(db, r, user)
    log_activity(
        db, requirement_id=req_id, actor_nickname=user.nickname,
        action="status_changed", detail={"to": "delivery_doc_pending", "round": round_num, "files": file_count},
    )
    db.commit()
    db.refresh(d)

    shutil.rmtree(pdir, ignore_errors=True)

    await bus.publish(f"req:{req_id}", "requirement.updated", {"status": "delivery_doc_pending"})
    await bus.publish("all", "requirement.updated", {"requirement_id": req_id, "status": "delivery_doc_pending"})

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
            r = db.query(Requirement).filter(Requirement.id == d.requirement_id).first()
            if r and r.status == "delivery_doc_pending":
                r.status = "delivered"
                r.delivery_doc_ready_at = datetime.utcnow()
            db.commit()
            await bus.publish(f"req:{d.requirement_id}", "delivery.doc_ready", {
                "delivery_id": d.id, "round": d.round,
            })
            await bus.publish(f"req:{d.requirement_id}", "requirement.updated", {"status": "delivered"})
            await bus.publish("all", "requirement.updated", {
                "requirement_id": d.requirement_id, "status": "delivered",
            })
    finally:
        db.close()
