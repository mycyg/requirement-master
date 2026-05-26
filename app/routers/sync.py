"""Tray-client sync APIs:
  - submit:        提需求方点"确认投递" → status ready + push
  - sync-manifest: client pulls per-requirement file list + metadata
  - sync-ack:      client confirms it has all files locally
  - claim:         接单人 (the only one) takes the work
"""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import current_user
from db import get_db
from models import Requirement, User
from services.activity import log_activity
from services.push_bus import bus
from services.sync_manifest import build as build_manifest

router = APIRouter(prefix="/api", tags=["sync"])


@router.post("/requirements/{req_id}/submit")
async def submit(req_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    r = db.query(Requirement).filter(Requirement.id == req_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="requirement not found")
    if not r.summary_md:
        raise HTTPException(status_code=400, detail="no summary yet; complete clarification first")

    if r.status not in {"clarifying", "ready"}:
        raise HTTPException(status_code=400, detail=f"cannot submit from status {r.status}")

    r.status = "ready"
    r.sync_state = "pending"
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

    return {"ok": True, "status": r.status}


@router.get("/requirements/{req_id}/sync-manifest")
def sync_manifest(req_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    r = db.query(Requirement).filter(Requirement.id == req_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="requirement not found")
    return build_manifest(db, r)


@router.post("/requirements/{req_id}/sync-ack")
async def sync_ack(req_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    r = db.query(Requirement).filter(Requirement.id == req_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="requirement not found")
    r.sync_state = "synced"
    log_activity(db, requirement_id=r.id, actor_nickname=user.nickname, action="synced", detail={})
    db.commit()
    return {"ok": True}


@router.post("/requirements/{req_id}/claim")
async def claim(req_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    r = db.query(Requirement).filter(Requirement.id == req_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="requirement not found")
    if r.status not in {"ready"}:
        raise HTTPException(status_code=400, detail=f"cannot claim from status {r.status}")
    r.status = "claimed"
    r.claimed_at = datetime.utcnow()
    log_activity(db, requirement_id=r.id, actor_nickname=user.nickname, action="claimed", detail={})
    db.commit()
    db.refresh(r)
    await bus.publish(f"req:{r.id}", "requirement.updated", {"status": r.status, "claimed_by": user.nickname})
    return {"ok": True, "status": r.status}
