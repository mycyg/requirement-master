"""Chunked file upload for attachments. Up to 1 GB.

Flow:
  1. POST /api/requirements/{req_id}/upload/init    → {upload_id, chunk_size}
  2. PUT  /api/requirements/{req_id}/upload/{upload_id}/chunk/{idx}   binary body
  3. POST /api/requirements/{req_id}/upload/{upload_id}/finalize      → AttachmentOut

Partial chunks live at: <data>/uploads/_partial/<upload_id>/<idx>.bin
On finalize, chunks are concatenated → <data>/uploads/<req_id>/<filename>, parsed, and a row created.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session

from auth import current_user
from config import settings
from db import get_db
from models import Attachment, Project, Requirement, User
from schemas import AttachmentOut, ChunkInitIn, ChunkInitOut
from services.activity import log_activity
from services.file_parser import is_parseable, parse_file
from services.permissions import can_add_requirement_attachment, can_view_requirement_assets

router = APIRouter(prefix="/api", tags=["attachments"])

CHUNK_SIZE = 5 * 1024 * 1024  # 5 MB
MAX_BYTES = 1024 * 1024 * 1024  # 1 GB


def _partial_dir(upload_id: str) -> Path:
    return settings.data_dir / "uploads" / "_partial" / upload_id


def _meta_path(upload_id: str) -> Path:
    return _partial_dir(upload_id) / "_meta.json"


def _expected_chunks(total_size: int) -> int:
    return max(1, (total_size + CHUNK_SIZE - 1) // CHUNK_SIZE)


def _expected_chunk_size(meta: dict, idx: int) -> int:
    if idx < meta["total_chunks"] - 1:
        return CHUNK_SIZE
    return meta["total_size"] - (CHUNK_SIZE * (meta["total_chunks"] - 1))


def _req_dir(req_id: str) -> Path:
    d = settings.data_dir / "uploads" / req_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _full_text_path(req_id: str, att_id: str) -> Path:
    d = settings.data_dir / "outputs" / req_id
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{att_id}.txt"


def _require_req(db: Session, req_id: str) -> Requirement:
    r = (
        db.query(Requirement)
        .join(Project, Project.id == Requirement.project_id)
        .filter(
            Requirement.id == req_id,
            Project.archived == False,  # noqa: E712
            Project.deleted_at.is_(None),
        )
        .first()
    )
    if not r:
        raise HTTPException(status_code=404, detail="requirement not found")
    return r


def _require_can_add_attachment(req: Requirement, user: User) -> None:
    if not can_add_requirement_attachment(req, user):
        raise HTTPException(status_code=403, detail="only the requester can add attachments before dispatch")


def _require_can_view_assets(req: Requirement, user: User) -> None:
    if not can_view_requirement_assets(req, user):
        raise HTTPException(status_code=403, detail="you cannot access files for this requirement")


@router.post("/requirements/{req_id}/upload/init", response_model=ChunkInitOut)
def init_upload(
    req_id: str,
    payload: ChunkInitIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ChunkInitOut:
    req = _require_req(db, req_id)
    _require_can_add_attachment(req, user)
    if payload.total_size > MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"file too large (>{MAX_BYTES} bytes)")
    if payload.total_chunks != _expected_chunks(payload.total_size):
        raise HTTPException(status_code=400, detail="total_chunks does not match configured chunk size")

    upload_id = uuid.uuid4().hex
    pdir = _partial_dir(upload_id)
    pdir.mkdir(parents=True, exist_ok=True)
    _meta_path(upload_id).write_text(
        json.dumps({
            "req_id": req_id,
            "filename": payload.filename,
            "total_size": payload.total_size,
            "total_chunks": payload.total_chunks,
            "mime": payload.mime,
            "user_id": user.id,
        }),
        encoding="utf-8",
    )
    return ChunkInitOut(upload_id=upload_id, chunk_size=CHUNK_SIZE)


@router.put("/requirements/{req_id}/upload/{upload_id}/chunk/{idx}")
async def upload_chunk(req_id: str, upload_id: str, idx: int, request: Request,
                       user: User = Depends(current_user)) -> dict:
    pdir = _partial_dir(upload_id)
    if not pdir.exists():
        raise HTTPException(status_code=404, detail="unknown upload_id")
    meta = json.loads(_meta_path(upload_id).read_text(encoding="utf-8"))
    if meta["req_id"] != req_id:
        raise HTTPException(status_code=400, detail="upload_id does not match requirement")
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


@router.post("/requirements/{req_id}/upload/{upload_id}/finalize", response_model=AttachmentOut)
def finalize_upload(
    req_id: str, upload_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> AttachmentOut:
    pdir = _partial_dir(upload_id)
    if not pdir.exists():
        raise HTTPException(status_code=404, detail="unknown upload_id")
    meta = json.loads(_meta_path(upload_id).read_text(encoding="utf-8"))
    if meta["req_id"] != req_id:
        raise HTTPException(status_code=400, detail="upload_id does not match requirement")
    if meta.get("user_id") != user.id:
        raise HTTPException(status_code=403, detail="only the upload owner can finalize this upload")

    r = _require_req(db, req_id)
    _require_can_add_attachment(r, user)
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

    safe_filename = Path(meta["filename"]).name
    final_path = _req_dir(req_id) / safe_filename
    if final_path.exists():
        # name conflict — suffix with upload_id prefix
        final_path = _req_dir(req_id) / f"{upload_id[:8]}-{safe_filename}"

    h = hashlib.sha256()
    total = 0
    with open(final_path, "wb") as out:
        for c in chunks:
            with open(c, "rb") as src:
                while True:
                    buf = src.read(1024 * 1024)
                    if not buf:
                        break
                    out.write(buf)
                    h.update(buf)
                    total += len(buf)

    if total != meta["total_size"]:
        os.unlink(final_path)
        raise HTTPException(status_code=400, detail=f"size mismatch: got {total}, expected {meta['total_size']}")

    sha = h.hexdigest()
    att = Attachment(
        requirement_id=r.id,
        filename=safe_filename,
        mime=meta.get("mime"),
        size_bytes=total,
        storage_path=str(final_path),
        sha256=sha,
    )

    full = ""
    if is_parseable(safe_filename, att.mime):
        preview, full = parse_file(final_path)
        att.parsed_text = preview or None

    db.add(att)
    db.flush()

    if full:
        full_path = _full_text_path(req_id, att.id)
        full_path.write_text(full, encoding="utf-8")
        att.parsed_text_path = str(full_path)

    log_activity(
        db, requirement_id=r.id, actor_nickname=user.nickname,
        action="file_added", detail={"attachment_id": att.id, "filename": safe_filename, "size": total},
    )
    db.commit()
    db.refresh(att)

    shutil.rmtree(pdir, ignore_errors=True)

    return AttachmentOut(
        id=att.id, filename=att.filename, mime=att.mime, size_bytes=att.size_bytes,
        sha256=att.sha256, role_in_req=att.role_in_req,
        has_parsed_text=bool(att.parsed_text), created_at=att.created_at,
    )


@router.post("/requirements/{req_id}/attachments", response_model=AttachmentOut)
async def upload_simple(
    req_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> AttachmentOut:
    """Convenience path for small files (no chunking). Streams to disk, max 1 GB."""
    r = _require_req(db, req_id)
    _require_can_add_attachment(r, user)
    safe_filename = Path(file.filename or "upload.bin").name
    final_path = _req_dir(req_id) / safe_filename
    if final_path.exists():
        final_path = _req_dir(req_id) / f"{uuid.uuid4().hex[:8]}-{safe_filename}"

    h = hashlib.sha256()
    total = 0
    with open(final_path, "wb") as out:
        while True:
            buf = await file.read(1024 * 1024)
            if not buf:
                break
            if total + len(buf) > MAX_BYTES:
                out.close()
                os.unlink(final_path)
                raise HTTPException(status_code=413, detail="file too large")
            out.write(buf)
            h.update(buf)
            total += len(buf)

    att = Attachment(
        requirement_id=r.id,
        filename=safe_filename,
        mime=file.content_type,
        size_bytes=total,
        storage_path=str(final_path),
        sha256=h.hexdigest(),
    )

    full = ""
    if is_parseable(safe_filename, att.mime):
        preview, full = parse_file(final_path)
        att.parsed_text = preview or None

    db.add(att)
    db.flush()

    if full:
        full_path = _full_text_path(r.id, att.id)
        full_path.write_text(full, encoding="utf-8")
        att.parsed_text_path = str(full_path)

    log_activity(
        db, requirement_id=r.id, actor_nickname=user.nickname,
        action="file_added", detail={"attachment_id": att.id, "filename": safe_filename, "size": total},
    )
    db.commit()
    db.refresh(att)

    return AttachmentOut(
        id=att.id, filename=att.filename, mime=att.mime, size_bytes=att.size_bytes,
        sha256=att.sha256, role_in_req=att.role_in_req,
        has_parsed_text=bool(att.parsed_text), created_at=att.created_at,
    )


@router.get("/requirements/{req_id}/attachments", response_model=list[AttachmentOut])
def list_attachments(req_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[AttachmentOut]:
    req = _require_req(db, req_id)
    _require_can_view_assets(req, user)
    rows = db.query(Attachment).filter(Attachment.requirement_id == req_id).order_by(Attachment.created_at).all()
    return [
        AttachmentOut(
            id=a.id, filename=a.filename, mime=a.mime, size_bytes=a.size_bytes,
            sha256=a.sha256, role_in_req=a.role_in_req,
            has_parsed_text=bool(a.parsed_text), created_at=a.created_at,
        )
        for a in rows
    ]


@router.get("/files/{att_id}")
def download_attachment(att_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    from fastapi.responses import FileResponse
    a = db.query(Attachment).filter(Attachment.id == att_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="attachment not found")
    req = _require_req(db, a.requirement_id)
    _require_can_view_assets(req, user)
    p = Path(a.storage_path)
    if not p.exists():
        raise HTTPException(status_code=410, detail="file missing on disk")
    return FileResponse(p, filename=a.filename, media_type=a.mime or "application/octet-stream")
