"""Tray-client sync APIs:
  - submit:        提需求方点"确认投递" → status ready + push
  - sync-manifest: client pulls per-requirement file list + metadata
  - sync-ack:      client confirms it has all files locally
  - claim:         eligible assignee takes the work; public pool creates a lead
"""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import update as sql_update
from sqlalchemy.orm import Session

from auth import current_user, require_local_client
from db import get_db
from models import Project, Requirement, RequirementAssignment, User
from services.activity import log_activity
from services.assignments import ensure_public_claim_assignment, sync_legacy_lead
from services.permissions import can_ack_requirement_sync, can_claim_requirement, can_view_requirement_assets
from services.schedule import sync_requirement_due_event
from services.push_bus import bus
from services.sync_manifest import build as build_manifest
from services.workspaces import ensure_workspaces_for_assignments, sync_workspace_to_status
from sqlalchemy.orm import selectinload

router = APIRouter(prefix="/api", tags=["sync"])


def _active_requirement_query(db: Session):
    return (
        db.query(Requirement)
        .join(Project, Project.id == Requirement.project_id)
        .filter(Project.archived == False, Project.deleted_at.is_(None))  # noqa: E712
    )


@router.post("/requirements/{req_id}/submit")
async def submit(req_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    r = _active_requirement_query(db).filter(Requirement.id == req_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="requirement not found")
    if not r.summary_md:
        raise HTTPException(status_code=400, detail="no summary yet; complete clarification first")
    if r.submitter_user_id != user.id:
        raise HTTPException(status_code=403, detail="only the requester can submit this requirement")

    if r.status not in {"summary_ready", "ready"}:
        raise HTTPException(status_code=400, detail=f"cannot submit from status {r.status}")
    if not r.due_at:
        raise HTTPException(status_code=400, detail="DDL is required before dispatch")

    # Atomic CAS — without this, a submitter double-clicking "投递"
    # would emit two `requirement.ready` SSE events, causing every
    # tray client to fire two "new requirement" toasts AND set off a
    # claim race storm. Idempotent destination (ready→ready) is fine
    # for the requirement row but bad for downstream side-effects.
    cas = db.execute(
        sql_update(Requirement)
        .where(Requirement.id == req_id, Requirement.status.in_({"summary_ready", "ready"}))
        .values(status="ready", sync_state="pending")
    )
    if cas.rowcount == 0:
        db.rollback()
        r2 = db.query(Requirement).filter(Requirement.id == req_id).first()
        current = r2.status if r2 else "deleted"
        raise HTTPException(status_code=409, detail=f"submit race: requirement is now {current}")
    db.refresh(r)
    sync_requirement_due_event(db, r, user)
    log_activity(db, requirement_id=r.id, actor_nickname=user.nickname, action="submitted", detail={})
    db.commit()
    db.refresh(r)

    payload = {
        "requirement_id": r.id,
        "code": r.code,
        "title": r.title,
        "project_id": r.project_id,
    }
    await bus.publish("all", "requirement.ready", payload)
    await bus.publish(f"req:{r.id}", "requirement.updated", {"status": r.status})
    await bus.publish("all", "requirement.updated", {"requirement_id": r.id, "status": r.status})

    return {"ok": True, "status": r.status}


@router.get("/requirements/{req_id}/sync-manifest")
def sync_manifest(req_id: str, db: Session = Depends(get_db), user: User = Depends(require_local_client)) -> dict:
    r = _active_requirement_query(db).filter(Requirement.id == req_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="requirement not found")
    if not can_view_requirement_assets(r, user):
        raise HTTPException(status_code=403, detail="you cannot sync files for this requirement")
    return build_manifest(db, r)


@router.post("/requirements/{req_id}/sync-ack")
async def sync_ack(req_id: str, db: Session = Depends(get_db), user: User = Depends(require_local_client)) -> dict:
    r = _active_requirement_query(db).filter(Requirement.id == req_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="requirement not found")
    if not can_ack_requirement_sync(r, user):
        raise HTTPException(status_code=403, detail="you cannot acknowledge sync for this requirement")
    r.sync_state = "synced"
    log_activity(db, requirement_id=r.id, actor_nickname=user.nickname, action="synced", detail={})
    db.commit()
    return {"ok": True}


@router.post("/requirements/{req_id}/claim")
async def claim(req_id: str, db: Session = Depends(get_db), user: User = Depends(require_local_client)) -> dict:
    # Fast permission + existence pre-check (read-only).
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
    if r.status != "ready":
        raise HTTPException(status_code=400, detail=f"cannot claim from status {r.status}")
    if not can_claim_requirement(r, user):
        raise HTTPException(status_code=403, detail="only assigned users can claim this requirement")

    # Atomic compare-and-swap: only the request that flips ready → claimed
    # "wins". Two concurrent claims previously both passed the in-memory
    # status check, then both blind-wrote status=claimed and the loser
    # silently overwrote claimed_by with their own nickname while leaving
    # the winner's assignment row in place — ambiguous lead.
    now = datetime.utcnow()
    result = db.execute(
        sql_update(Requirement)
        .where(Requirement.id == req_id, Requirement.status == "ready")
        .values(status="claimed", claimed_at=now)
    )
    if result.rowcount == 0:
        # Lost the race or status changed underneath us.
        db.rollback()
        # Re-read to give the caller a useful error.
        r2 = db.query(Requirement).filter(Requirement.id == req_id).first()
        current = r2.status if r2 else "deleted"
        raise HTTPException(status_code=409, detail=f"claim race: requirement is now {current}")
    # Refresh the ORM object so subsequent assignment/notification work
    # uses the post-CAS state.
    db.refresh(r)

    if not r.assignments:
        ensure_public_claim_assignment(db, r, user)
    else:
        sync_legacy_lead(r)
    ensure_workspaces_for_assignments(db, r)
    sync_workspace_to_status(db, r, user)
    log_activity(db, requirement_id=r.id, actor_nickname=user.nickname, action="claimed", detail={})
    # Queue submitter notification while still in the same transaction.
    from services.lifecycle import queue_status_notifications, flush_status_notifications
    pending = queue_status_notifications(db, r, "claimed", user)
    db.commit()
    db.refresh(r)
    await flush_status_notifications(pending)
    await bus.publish(f"req:{r.id}", "requirement.updated", {"status": r.status, "claimed_by": user.nickname})
    await bus.publish("all", "requirement.updated", {
        "requirement_id": r.id, "status": r.status, "claimed_by": user.nickname,
    })
    return {"ok": True, "status": r.status}
