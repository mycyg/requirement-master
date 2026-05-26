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
from sqlalchemy.orm import Session

from auth import current_user
from config import settings
from db import SessionLocal, get_db
from models import Delivery, Requirement, User
from services.activity import log_activity
from services.auto_agent import auto_process
from services.push_bus import bus

router = APIRouter(prefix="/api", tags=["auto"])


def _workdir(req_id: str) -> Path:
    return settings.data_dir / "auto" / req_id


@router.post("/requirements/{req_id}/auto-process")
async def trigger_auto(
    req_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    r = db.query(Requirement).filter(Requirement.id == req_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="requirement not found")
    if not r.summary_md:
        raise HTTPException(status_code=400, detail="no summary yet")
    if r.submitter_user_id != user.id:
        raise HTTPException(status_code=403, detail="only the requester can choose AI processing")
    if r.status not in {"summary_ready", "ready"}:
        raise HTTPException(status_code=400, detail=f"cannot auto-process from status {r.status}")

    r.status = "ai_processing"
    log_activity(db, requirement_id=r.id, actor_nickname=user.nickname, action="ai_started", detail={})
    db.commit()

    await bus.publish(f"req:{r.id}", "requirement.updated", {"status": r.status})
    await bus.publish("all", "requirement.updated", {"requirement_id": r.id, "status": r.status})

    asyncio.create_task(_run_and_finalize(r.id, r.title or r.code, r.summary_md, user.nickname))
    return {"ok": True, "status": r.status}


async def _run_and_finalize(req_id: str, title: str, summary_md: str, actor: str) -> None:
    """Background task. On success → wrap as Delivery, status=delivered. On failure → status=ready."""
    workdir = _workdir(req_id)
    try:
        outcome = await auto_process(
            req_id=req_id, req_title=title, summary_md=summary_md, workdir=workdir,
        )
    except Exception as e:
        await _mark_auto_failed(req_id, actor, title, f"{type(e).__name__}: {e}")
        return

    db = SessionLocal()
    try:
        r = db.query(Requirement).filter(Requirement.id == req_id).first()
        if not r:
            return

        if outcome.success:
            # Package + register a Delivery
            round_num = 1 + (db.query(Delivery).filter(Delivery.requirement_id == req_id).count())
            pkg_dir = settings.data_dir / "deliveries" / req_id
            pkg_dir.mkdir(parents=True, exist_ok=True)
            pkg_path = pkg_dir / f"round-{round_num}-ai.zip"

            EXCLUDE_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv", ".pytest_cache"}
            sha = hashlib.sha256()
            file_count = 0
            with zipfile.ZipFile(pkg_path, "w", zipfile.ZIP_DEFLATED) as z:
                for p in sorted(workdir.rglob("*")):
                    if any(part in EXCLUDE_DIRS for part in p.parts):
                        continue
                    if p.is_file():
                        z.write(p, p.relative_to(workdir))
                        sha.update(p.read_bytes())
                        file_count += 1
            size = pkg_path.stat().st_size

            doc = (
                f"## 交付概述\n本轮由 AI ({settings.llm_model}) 自动完成。{outcome.notes}\n\n"
                f"## 处理时长\n{outcome.seconds:.1f} 秒，共 {file_count} 个交付文件\n\n"
                f"## 复审\n{outcome.review_reason}\n"
            )

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
            db.commit()

            await bus.publish(f"req:{req_id}", "requirement.updated", {"status": "delivered"})
            await bus.publish("all", "requirement.updated", {"requirement_id": req_id, "status": "delivered"})
        else:
            # Failure → revert to ready, leave breadcrumbs
            r.status = "ready"
            log_activity(
                db, requirement_id=req_id, actor_nickname=actor,
                action="ai_failed",
                detail={"reason": outcome.reason, "notes": outcome.notes, "seconds": outcome.seconds},
            )
            db.commit()
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


async def _mark_auto_failed(req_id: str, actor: str, title: str, reason: str) -> None:
    db = SessionLocal()
    try:
        r = db.query(Requirement).filter(Requirement.id == req_id).first()
        if not r:
            return
        r.status = "ready"
        log_activity(
            db, requirement_id=req_id, actor_nickname=actor,
            action="ai_failed", detail={"reason": reason},
        )
        db.commit()
        await bus.publish(f"req:{req_id}", "ai.failed", {"reason": reason, "notes": ""})
        await bus.publish(f"req:{req_id}", "requirement.updated", {"status": "ready"})
        await bus.publish("all", "requirement.updated", {"requirement_id": req_id, "status": "ready"})
        await bus.publish("all", "requirement.ready", {
            "requirement_id": req_id, "title": title, "ai_failed": True,
            "reason": reason,
        })
    finally:
        db.close()
