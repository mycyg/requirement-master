"""Auto-process trigger + status endpoints. Spawns a background asyncio task."""
from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import update as sql_update
from sqlalchemy.orm import Session

from auth import current_user
from config import settings
from db import SessionLocal, get_db
from models import Attachment, BackgroundJob, Delivery, Project, Requirement, User
from services.activity import log_activity
from services.auto_agent import auto_process
from services.jobs import create_job, publish_job, update_job
from services.push_bus import bus

router = APIRouter(prefix="/api", tags=["auto"])


def _workdir(req_id: str) -> Path:
    return settings.data_dir / "auto" / req_id


def _looks_english(text: str) -> bool:
    letters = sum(1 for c in text if c.isascii() and c.isalpha())
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    return letters > cjk * 2


def _auto_delivery_doc(summary_md: str, notes: str, seconds: float, file_count: int, review_reason: str) -> str:
    if _looks_english(summary_md + notes + review_reason):
        return (
            f"## Delivery Overview\nThis round was completed automatically by AI ({settings.llm_model}). {notes}\n\n"
            f"## Processing Time\n{seconds:.1f} seconds, {file_count} delivered files.\n\n"
            f"## Review\n{review_reason}\n"
        )
    return (
        f"## 交付概述\n本轮由 AI ({settings.llm_model}) 自动完成。{notes}\n\n"
        f"## 处理时长\n{seconds:.1f} 秒，共 {file_count} 个交付文件\n\n"
        f"## 复审\n{review_reason}\n"
    )


@router.post("/requirements/{req_id}/auto-process")
async def trigger_auto(
    req_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
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
    if not r.summary_md:
        raise HTTPException(status_code=400, detail="no summary yet")
    if r.submitter_user_id != user.id:
        raise HTTPException(status_code=403, detail="only the requester can choose AI processing")
    if r.status not in {"summary_ready", "ready"}:
        raise HTTPException(status_code=400, detail=f"cannot auto-process from status {r.status}")

    # Atomic CAS — without this, two concurrent /auto-process clicks
    # would both pass the status check, both spawn `_run_and_finalize`,
    # both write to the same workdir, and produce duplicate Delivery
    # rows + duplicate notifications. The LLM tokens for the second run
    # are wasted.
    cas = db.execute(
        sql_update(Requirement)
        .where(Requirement.id == req_id, Requirement.status.in_({"summary_ready", "ready"}))
        .values(status="ai_processing")
    )
    if cas.rowcount == 0:
        db.rollback()
        r2 = db.query(Requirement).filter(Requirement.id == req_id).first()
        current = r2.status if r2 else "deleted"
        raise HTTPException(status_code=409, detail=f"auto-process race: requirement is now {current}")
    db.refresh(r)
    job = create_job(db, kind="auto_agent", user=user, message="AI 自动处理已排队")
    log_activity(db, requirement_id=r.id, actor_nickname=user.nickname, action="ai_started", detail={})
    db.commit()
    await publish_job(job)

    await bus.publish(f"req:{r.id}", "requirement.updated", {"status": r.status})
    await bus.publish("all", "requirement.updated", {"requirement_id": r.id, "status": r.status})

    asyncio.create_task(_run_and_finalize(r.id, r.title or r.code, r.summary_md, user.nickname, job.id))
    return {"ok": True, "status": r.status, "job_id": job.id}


async def _run_and_finalize(req_id: str, title: str, summary_md: str, actor: str, job_id: str | None = None) -> None:
    """Background task. On success → wrap as Delivery, status=delivered. On failure → status=ready."""
    workdir = _workdir(req_id)
    try:
        if job_id:
            db_job = SessionLocal()
            try:
                job = db_job.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
                if job:
                    update_job(db_job, job, status="running", progress_percent=20, message="正在准备附件和沙箱")
                    db_job.commit()
                    await publish_job(job)
            finally:
                db_job.close()
        db_inputs = SessionLocal()
        try:
            attachments = (
                db_inputs.query(Attachment)
                .filter(Attachment.requirement_id == req_id)
                .order_by(Attachment.created_at)
                .all()
            )
            input_files = [(a.filename, Path(a.storage_path)) for a in attachments]
        finally:
            db_inputs.close()
        outcome = await auto_process(
            req_id=req_id, req_title=title, summary_md=summary_md, workdir=workdir,
            input_files=input_files,
        )
        if job_id:
            db_job = SessionLocal()
            try:
                job = db_job.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
                if job:
                    update_job(db_job, job, status="running", progress_percent=85, message="AI 已完成，正在登记交付")
                    db_job.commit()
                    await publish_job(job)
            finally:
                db_job.close()
    except Exception as e:
        await _mark_auto_failed(req_id, actor, title, f"{type(e).__name__}: {e}", job_id=job_id)
        return

    db = SessionLocal()
    try:
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
            return

        if outcome.success:
            # Race check FIRST — if the requirement was cancelled while AI ran,
            # don't write a zip, don't add a Delivery row, don't clobber state.
            # Also short-circuit the job into "succeeded but skipped" so the
            # UI doesn't show a perpetual 85% spinner.
            if r.status != "ai_processing":
                if job_id:
                    job = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
                    if job:
                        update_job(
                            db, job,
                            status="succeeded",
                            progress_percent=100,
                            message=f"AI 完成但需求状态已是 {r.status}，跳过登记交付",
                            result_ref=req_id,
                        )
                        db.commit()
                        await publish_job(job)
                shutil.rmtree(workdir, ignore_errors=True)
                return

            # Package + register a Delivery
            round_num = 1 + (db.query(Delivery).filter(Delivery.requirement_id == req_id).count())
            pkg_dir = settings.data_dir / "deliveries" / req_id
            pkg_dir.mkdir(parents=True, exist_ok=True)
            pkg_path = pkg_dir / f"round-{round_num}-ai.zip"

            EXCLUDE_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv", ".pytest_cache"}
            sha = hashlib.sha256()
            file_count = 0
            with zipfile.ZipFile(pkg_path, "w", zipfile.ZIP_DEFLATED) as z:
                output_root = workdir / "outputs"
                for p in sorted(output_root.rglob("*") if output_root.exists() else []):
                    if any(part in EXCLUDE_DIRS for part in p.parts):
                        continue
                    if p.is_file():
                        z.write(p, p.relative_to(output_root))
                        sha.update(p.read_bytes())
                        file_count += 1
            size = pkg_path.stat().st_size

            doc = _auto_delivery_doc(summary_md, outcome.notes, outcome.seconds, file_count, outcome.review_reason)

            d = Delivery(
                requirement_id=req_id, round=round_num,
                package_path=str(pkg_path), package_size=size,
                package_sha256=sha.hexdigest(), file_count=file_count,
                delivery_doc_md=doc, notes=outcome.notes,
                submitted_by_nickname=f"AI ({settings.llm_model})",
            )
            db.add(d)
            r.status = "delivered"
            r.delivered_at = datetime.utcnow()
            r.delivery_doc_ready_at = r.delivered_at
            log_activity(
                db, requirement_id=req_id, actor_nickname=f"AI ({settings.llm_model})",
                action="ai_delivered",
                detail={"round": round_num, "files": file_count, "seconds": outcome.seconds},
            )
            # Synthesize a User stand-in so the lifecycle helper can format
            # the body as "AI ({model}) 提交了交付物" — the id won't match any
            # real user so the submitter is correctly included as recipient.
            from services.lifecycle import queue_status_notifications, flush_status_notifications
            ai_actor = User(id="ai-auto", nickname=f"AI ({settings.llm_model})")
            pending = queue_status_notifications(db, r, "delivered", ai_actor)
            db.commit()
            if job_id:
                job = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
                if job:
                    update_job(db, job, status="succeeded", progress_percent=100, message="AI 自动处理已交付", result_ref=req_id)
                    db.commit()
                    await publish_job(job)

            await flush_status_notifications(pending)
            await bus.publish(f"req:{req_id}", "requirement.updated", {"status": "delivered"})
            await bus.publish("all", "requirement.updated", {"requirement_id": req_id, "status": "delivered"})
        else:
            # Failure → revert to ready, leave breadcrumbs. BUT only if the
            # requirement is still in `ai_processing` — the user could have
            # cancelled mid-AI (cancelled is terminal); blindly writing
            # `ready` would resurrect a cancelled requirement.
            if r.status == "ai_processing":
                r.status = "ready"
            log_activity(
                db, requirement_id=req_id, actor_nickname=actor,
                action="ai_failed",
                detail={"reason": outcome.reason, "notes": outcome.notes, "seconds": outcome.seconds},
            )
            db.commit()
            if job_id:
                job = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
                if job:
                    update_job(db, job, status="failed", progress_percent=100, message="AI 自动处理失败，已转人工", result_ref=req_id, error=outcome.reason)
                    db.commit()
                    await publish_job(job)
            await bus.publish(f"req:{req_id}", "ai.failed", {
                "reason": outcome.reason, "notes": outcome.notes,
            })
            await bus.publish(f"req:{req_id}", "requirement.updated", {"status": "ready"})
            await bus.publish("all", "requirement.updated", {"requirement_id": req_id, "status": "ready"})
            await bus.publish("all", "requirement.ready", {
                "requirement_id": req_id, "title": title, "ai_failed": True,
                "reason": outcome.reason,
            })
            # leave workdir for inspection; don't delete on failure
            return

        # success → workdir already zipped; we can keep or remove
        shutil.rmtree(workdir, ignore_errors=True)
    finally:
        db.close()


async def _mark_auto_failed(req_id: str, actor: str, title: str, reason: str, job_id: str | None = None) -> None:
    db = SessionLocal()
    try:
        job = None
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
            return
        # Same cancel-aware guard as the inline failure path above.
        if r.status == "ai_processing":
            r.status = "ready"
        log_activity(
            db, requirement_id=req_id, actor_nickname=actor,
            action="ai_failed", detail={"reason": reason},
        )
        if job_id:
            job = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
            if job:
                update_job(db, job, status="failed", progress_percent=100, message="AI 自动处理失败，已转人工", result_ref=req_id, error=reason)
        db.commit()
        if job_id and job:
            await publish_job(job)
        await bus.publish(f"req:{req_id}", "ai.failed", {"reason": reason, "notes": ""})
        await bus.publish(f"req:{req_id}", "requirement.updated", {"status": "ready"})
        await bus.publish("all", "requirement.updated", {"requirement_id": req_id, "status": "ready"})
        await bus.publish("all", "requirement.ready", {
            "requirement_id": req_id, "title": title, "ai_failed": True,
            "reason": reason,
        })
    finally:
        db.close()
