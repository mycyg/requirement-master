"""Delivery listing, single-file download from package, accept/revision actions."""
from __future__ import annotations

import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import update as sql_update
from sqlalchemy.orm import Session

from auth import current_user
from db import get_db
from models import Delivery, Requirement, RevisionRequest, User
from services.activity import log_activity
from services.delivery_doc import inspect_zip_entries
from services.lifecycle import flush_status_notifications, queue_status_notifications
from services.permissions import can_view_requirement_assets
from services.push_bus import bus
from services.workspaces import ensure_workspaces_for_assignments, sync_workspace_to_status

router = APIRouter(prefix="/api", tags=["deliveries"])


class DeliveryOut(BaseModel):
    id: str
    round: int
    package_size: int
    package_sha256: str
    file_count: int
    delivery_doc_md: str | None
    notes: str | None
    submitted_by_nickname: str
    created_at: datetime
    files: list[dict]  # [{name, size}]


class RevisionIn(BaseModel):
    reason_md: str = Field(min_length=1)


def _require_req(db: Session, req_id: str) -> Requirement:
    r = db.query(Requirement).filter(Requirement.id == req_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="requirement not found")
    return r


def _require_can_view_assets(req: Requirement, user: User) -> None:
    if not can_view_requirement_assets(req, user):
        raise HTTPException(status_code=403, detail="you cannot access deliveries for this requirement")


def _zip_filelist(path: str) -> list[dict]:
    try:
        return [
            {"name": e["safe_name"], "size": e["size"]}
            for e in inspect_zip_entries(Path(path))
        ]
    except Exception:
        return []


@router.get("/requirements/{req_id}/deliveries", response_model=list[DeliveryOut])
def list_deliveries(req_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[DeliveryOut]:
    req = _require_req(db, req_id)
    _require_can_view_assets(req, user)
    rows = (
        db.query(Delivery)
        .filter(Delivery.requirement_id == req_id)
        .order_by(Delivery.round.desc())
        .all()
    )
    return [
        DeliveryOut(
            id=d.id, round=d.round,
            package_size=d.package_size, package_sha256=d.package_sha256,
            file_count=d.file_count, delivery_doc_md=d.delivery_doc_md,
            notes=d.notes, submitted_by_nickname=d.submitted_by_nickname,
            created_at=d.created_at, files=_zip_filelist(d.package_path),
        )
        for d in rows
    ]


@router.get("/deliveries/{delivery_id}/package")
def download_package(delivery_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    d = db.query(Delivery).filter(Delivery.id == delivery_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="delivery not found")
    _require_can_view_assets(d.requirement, user)
    p = Path(d.package_path)
    if not p.exists():
        raise HTTPException(status_code=410, detail="package missing on disk")
    return FileResponse(
        p,
        filename=f"{d.requirement_id}-round-{d.round}.zip",
        media_type="application/zip",
    )


@router.get("/deliveries/{delivery_id}/files/{filename:path}")
def download_file_from_package(delivery_id: str, filename: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    d = db.query(Delivery).filter(Delivery.id == delivery_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="delivery not found")
    _require_can_view_assets(d.requirement, user)
    p = Path(d.package_path)
    if not p.exists():
        raise HTTPException(status_code=410, detail="package missing on disk")
    try:
        entries = inspect_zip_entries(p)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid zip package: {e}")
    entry = next((e for e in entries if e["safe_name"] == filename), None)
    if not entry:
        raise HTTPException(status_code=404, detail=f"file not in package: {filename}")

    return StreamingResponse(
        _iter_zip_member(p, str(entry["name"])),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{Path(filename).name}"'},
    )


def _iter_zip_member(path: Path, member_name: str):
    with zipfile.ZipFile(path) as z:
        with z.open(member_name) as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                yield chunk


@router.post("/requirements/{req_id}/accept")
async def accept_delivery(req_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    r = _require_req(db, req_id)
    if r.status != "delivered":
        raise HTTPException(status_code=400, detail=f"cannot accept from status {r.status}")
    if r.submitter_user_id != user.id:
        raise HTTPException(status_code=403, detail="only the requester can accept this delivery")
    # Atomic CAS — submitter double-clicking "通过" would otherwise produce
    # two `requirement.updated` events and two "通过验收" notifications to
    # assignees. Worse, a concurrent request_revision would race accept
    # and could land us in an inconsistent state (revision row + accepted
    # status). Restrict the transition to the exact prior status.
    now = datetime.utcnow()
    cas = db.execute(
        sql_update(Requirement)
        .where(Requirement.id == req_id, Requirement.status == "delivered")
        .values(status="accepted", accepted_at=now, done_at=now)
    )
    if cas.rowcount == 0:
        db.rollback()
        r2 = db.query(Requirement).filter(Requirement.id == req_id).first()
        current = r2.status if r2 else "deleted"
        raise HTTPException(status_code=409, detail=f"accept race: requirement is now {current}")
    db.refresh(r)
    ensure_workspaces_for_assignments(db, r)
    sync_workspace_to_status(db, r, user)
    log_activity(db, requirement_id=r.id, actor_nickname=user.nickname, action="accepted", detail={})
    # Queue assignees' inbox notification ("{code} 通过验收 🎉") in the same
    # transaction as the status change, then flush AFTER commit. Without
    # this, sync.py's claim handler is the only place that uses lifecycle;
    # accept/revision were silently skipping the assignee notification.
    pending = queue_status_notifications(db, r, "accepted", user)
    db.commit()

    await flush_status_notifications(pending)
    await bus.publish(f"req:{r.id}", "requirement.updated", {"status": r.status})
    await bus.publish("all", "requirement.updated", {"requirement_id": r.id, "status": r.status})
    return {"ok": True, "status": r.status}


@router.post("/requirements/{req_id}/revisions")
async def request_revision(
    req_id: str,
    payload: RevisionIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    r = _require_req(db, req_id)
    if r.status != "delivered":
        raise HTTPException(status_code=400, detail=f"cannot request revision from status {r.status}")
    if r.submitter_user_id != user.id:
        raise HTTPException(status_code=403, detail="only the requester can request a revision")

    latest = (
        db.query(Delivery)
        .filter(Delivery.requirement_id == req_id)
        .order_by(Delivery.round.desc())
        .first()
    )
    if not latest:
        raise HTTPException(status_code=400, detail="no delivery to revise")

    # Atomic CAS — symmetric with accept_delivery above. Prevents the
    # double-revision-row + double-notification storm if submitter
    # double-clicks; also prevents racing with accept (which we now
    # CAS too — first one wins).
    cas = db.execute(
        sql_update(Requirement)
        .where(Requirement.id == req_id, Requirement.status == "delivered")
        .values(status="revision_requested")
    )
    if cas.rowcount == 0:
        db.rollback()
        r2 = db.query(Requirement).filter(Requirement.id == req_id).first()
        current = r2.status if r2 else "deleted"
        raise HTTPException(status_code=409, detail=f"revision race: requirement is now {current}")
    db.refresh(r)
    rr = RevisionRequest(
        requirement_id=req_id, delivery_id=latest.id,
        requested_by_nickname=user.nickname, reason_md=payload.reason_md.strip(),
    )
    db.add(rr)
    ensure_workspaces_for_assignments(db, r)
    sync_workspace_to_status(db, r, user)
    log_activity(
        db, requirement_id=r.id, actor_nickname=user.nickname,
        action="revision_requested",
        detail={"reason_preview": payload.reason_md[:120], "round": latest.round},
    )
    pending = queue_status_notifications(db, r, "revision_requested", user)
    db.commit()

    await flush_status_notifications(pending)
    await bus.publish("all", "revision.requested", {
        "requirement_id": r.id, "round": latest.round,
        "reason_preview": payload.reason_md[:160],
        "requested_by": user.nickname,
    })
    await bus.publish(f"req:{r.id}", "requirement.updated", {"status": r.status})
    await bus.publish("all", "requirement.updated", {"requirement_id": r.id, "status": r.status})
    return {"ok": True, "status": r.status}
