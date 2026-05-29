"""Receive a delivery zip via chunked upload from the tray client, then
asynchronously have the LLM write a delivery doc and notify everyone."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from auth import require_local_client
from config import settings
from db import SessionLocal, get_db
from models import Delivery, Project, Requirement, RequirementAssignment, User
from services.activity import log_activity
from services.assignments import ensure_public_claim_assignment, sync_legacy_lead
from services.delivery_doc import generate_doc, inspect_zip_entries, list_zip_files
from services.permissions import can_work_requirement
from services.push_bus import bus
from services.workspaces import ensure_workspaces_for_assignments, sync_workspace_to_status

router = APIRouter(prefix="/api", tags=["delivery-upload"])
logger = logging.getLogger(__name__)

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
        .join(Project, Project.id == Requirement.project_id)
        .options(selectinload(Requirement.assignments).selectinload(RequirementAssignment.user))
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
    out_dir = settings.data_dir / "deliveries" / req_id
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = out_dir / f".{upload_id}.zip.tmp"

    # 1 GB merges synchronously freeze every other request handler. The
    # handler is `async def` so the chunk-loop blocks the event loop —
    # health checks time out, SSE streams stall, other uploads stall.
    # Push the bytes work to a worker thread; also fold in the per-chunk
    # `.stat().st_size` validation (1000× os calls on a 1GB upload) so
    # we don't bounce in and out of the loop.
    def _validate_and_merge_sync() -> tuple[int, str]:
        for idx, c in enumerate(chunks):
            expected_size = _expected_chunk_size(meta, idx)
            actual_size = c.stat().st_size
            if actual_size != expected_size:
                raise ValueError(f"chunk {idx} size mismatch: got {actual_size}, expected {expected_size}")
        h = hashlib.sha256()
        total = 0
        with open(tmp_path, "wb") as out:
            for c in chunks:
                with open(c, "rb") as src:
                    while True:
                        buf = src.read(1024 * 1024)
                        if not buf: break
                        out.write(buf)
                        h.update(buf)
                        total += len(buf)
        return total, h.hexdigest()
    try:
        total, digest_hex = await asyncio.to_thread(_validate_and_merge_sync)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if total != meta["total_size"]:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"size mismatch: got {total}, expected {meta['total_size']}")

    try:
        # Central-dir scan on a 1 GB zip can take a few hundred ms — keep
        # it off the event loop.
        file_count = len(await asyncio.to_thread(inspect_zip_entries, tmp_path))
    except Exception as e:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"invalid delivery zip: {e}")

    # Capture the prior status so we can revert atomically if the post-CAS
    # work fails (notably `os.replace` on Windows under live AV scans).
    prior_status = r.status

    # Atomic CAS — without this, a submitter who cancelled the requirement
    # mid-upload would have the cancelled status blindly overwritten by
    # delivery_doc_pending. Also prevents two concurrent finalizes from
    # both passing the status check and racing on Delivery insert.
    from sqlalchemy import update as sql_update
    cas = db.execute(
        sql_update(Requirement)
        .where(
            Requirement.id == req_id,
            Requirement.status.in_({"claimed", "doing", "revision_requested"}),
        )
        .values(status="delivery_doc_pending", delivered_at=datetime.utcnow())
    )
    if cas.rowcount == 0:
        tmp_path.unlink(missing_ok=True)
        db.rollback()
        r2 = db.query(Requirement).filter(Requirement.id == req_id).first()
        current = r2.status if r2 else "deleted"
        raise HTTPException(status_code=409, detail=f"deliver race: requirement is now {current}")
    db.refresh(r)
    round_num = 1 + db.query(Delivery).filter(Delivery.requirement_id == req_id).count()
    out_path = out_dir / f"round-{round_num}.zip"

    # Everything after CAS must be exception-protected: `os.replace`,
    # `Delivery` insert, lifecycle helpers all can raise. On any failure
    # we revert the CAS so the requirement doesn't stick in
    # delivery_doc_pending without an actual delivery row.
    def _rollback_status() -> None:
        try:
            db.rollback()
            db.execute(
                sql_update(Requirement)
                .where(
                    Requirement.id == req_id,
                    Requirement.status == "delivery_doc_pending",
                )
                .values(status=prior_status, delivered_at=None)
            )
            db.commit()
        except Exception:
            logger.exception("delivery_upload: failed to roll back status for req %s", req_id)

    try:
        os.replace(tmp_path, out_path)
    except OSError as e:
        tmp_path.unlink(missing_ok=True)
        out_path.unlink(missing_ok=True)
        _rollback_status()
        raise HTTPException(status_code=500, detail=f"could not save delivery package: {e}") from e

    d = Delivery(
        requirement_id=req_id, round=round_num,
        package_path=str(out_path), package_size=total,
        package_sha256=digest_hex, file_count=file_count,
        delivery_doc_md="（AI 正在撰写交付文档…）",
        submitted_by_nickname=user.nickname,
    )
    try:
        db.add(d)
        ensure_workspaces_for_assignments(db, r)
        sync_workspace_to_status(db, r, user)
        log_activity(
            db, requirement_id=req_id, actor_nickname=user.nickname,
            action="status_changed", detail={"to": "delivery_doc_pending", "round": round_num, "files": file_count},
        )
        # Submitter notification — they need to know delivery just happened, even
        # though the AI doc isn't ready yet. The "delivered" notification fires
        # later from _finalize_doc when status flips to delivered.
        from services.lifecycle import queue_status_notifications, flush_status_notifications
        pending = queue_status_notifications(db, r, "delivery_doc_pending", user)
        db.commit()
        db.refresh(d)
    except IntegrityError:
        out_path.unlink(missing_ok=True)
        _rollback_status()
        raise HTTPException(status_code=409, detail="delivery round already exists; refresh and retry")
    except Exception:
        out_path.unlink(missing_ok=True)
        _rollback_status()
        raise

    # rmtree of a partial dir holding ~1000 chunks can be ~100ms+ on slow
    # disks — offload so we don't block the event loop on hot-path success.
    await asyncio.to_thread(shutil.rmtree, pdir, True)

    await flush_status_notifications(pending)
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
            pending = []
            if r and r.status == "delivery_doc_pending":
                r.status = "delivered"
                r.delivery_doc_ready_at = datetime.utcnow()
                # Notify submitter — this is THE critical "等你验收" moment.
                # Actor here is the delivery's submitter (the worker), looked
                # up from the submitted_by_nickname or the most recent worker.
                from services.lifecycle import queue_status_notifications, flush_status_notifications
                # Best-effort actor — we don't carry a User context here, so
                # synthesize one from the worker nickname stored on the row.
                worker = User(id="ai-finalize", nickname=d.submitted_by_nickname or "AI 助理")
                pending = queue_status_notifications(db, r, "delivered", worker)
            db.commit()
            if r:
                from services.lifecycle import flush_status_notifications
                await flush_status_notifications(pending)
            # delivery.doc_ready is published to BOTH `req:{id}` (web's
            # per-requirement stream) AND `all` (the only stream the Tauri
            # client opens). Without the `all` copy the desktop DeliveryWizard
            # waits for an event it never receives and hangs on "等 AI 写交付
            # 文档" forever. The payload carries only ids (PII-free), so it's
            # safe on the global topic. It fires once per delivery, so the
            # extra web-Dashboard refresh is negligible.
            doc_ready_payload = {"delivery_id": d.id, "round": d.round, "requirement_id": d.requirement_id}
            await bus.publish(f"req:{d.requirement_id}", "delivery.doc_ready", doc_ready_payload)
            await bus.publish("all", "delivery.doc_ready", doc_ready_payload)
            await bus.publish(f"req:{d.requirement_id}", "requirement.updated", {"status": "delivered"})
            await bus.publish("all", "requirement.updated", {
                "requirement_id": d.requirement_id, "status": "delivered",
            })
    except Exception:
        # The doc-write / status-flip / commit failed (disk-full, or a commit
        # OperationalError under writer contention). The deliverable zip + the
        # Delivery row are ALREADY committed by the finalize endpoint; this task
        # only generates the doc, flips delivery_doc_pending→delivered, and
        # fires the "等你验收" notification. This task carries NO job_id, so the
        # restart sweep's job-driven recovery can't reach it — without this
        # handler the requirement would be stranded `delivery_doc_pending`
        # forever. Retry the critical transition in a fresh session.
        logger.exception("delivery doc finalize failed for %s", delivery_id)
        try:
            db.rollback()
        except Exception:
            pass
        await _recover_stranded_delivery(delivery_id, doc)
    finally:
        db.close()


async def _recover_stranded_delivery(delivery_id: str, fallback_doc: str) -> None:
    """Best-effort second attempt at the delivery_doc_pending→delivered
    transition after `_finalize_doc`'s main block raised. Uses a fresh session
    so a poisoned transaction can't block it. Idempotent: if the requirement
    already moved on, it's a no-op."""
    db = SessionLocal()
    try:
        d = db.query(Delivery).filter(Delivery.id == delivery_id).first()
        if not d:
            return
        if not d.delivery_doc_md:
            d.delivery_doc_md = fallback_doc
        r = db.query(Requirement).filter(Requirement.id == d.requirement_id).first()
        pending = []
        if r and r.status == "delivery_doc_pending":
            r.status = "delivered"
            r.delivery_doc_ready_at = datetime.utcnow()
            from services.lifecycle import queue_status_notifications
            worker = User(id="ai-finalize", nickname=d.submitted_by_nickname or "AI 助理")
            pending = queue_status_notifications(db, r, "delivered", worker)
        db.commit()
        if r:
            from services.lifecycle import flush_status_notifications
            await flush_status_notifications(pending)
            doc_ready_payload = {"delivery_id": d.id, "round": d.round, "requirement_id": d.requirement_id}
            await bus.publish(f"req:{d.requirement_id}", "delivery.doc_ready", doc_ready_payload)
            await bus.publish("all", "delivery.doc_ready", doc_ready_payload)
            await bus.publish(f"req:{d.requirement_id}", "requirement.updated", {"status": "delivered"})
            await bus.publish("all", "requirement.updated", {
                "requirement_id": d.requirement_id, "status": "delivered",
            })
    except Exception:
        # Second failure (e.g. persistent disk-full). The requirement-status
        # backstop sweep at startup (main._resume_stuck_jobs) will catch it.
        logger.exception("delivery doc recovery also failed for %s", delivery_id)
    finally:
        db.close()
