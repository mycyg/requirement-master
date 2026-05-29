"""Delivery listing, single-file download from package, accept/revision actions."""
from __future__ import annotations

import zipfile
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import update as sql_update
from sqlalchemy.orm import Session

from auth import current_user
from db import get_db
from models import Delivery, Project, Requirement, RevisionRequest, User
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
    reason_md: str = Field(min_length=1, max_length=200_000)


def _require_req(db: Session, req_id: str) -> Requirement:
    r = db.query(Requirement).filter(Requirement.id == req_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="requirement not found")
    return r


def _ensure_writable_project(req: Requirement, user: User) -> None:
    """Reject mutations on requirements whose project is archived / soft-deleted.

    Read paths (list/download) use can_view_requirement_assets which already
    enforces this (with admin-read-override per services/permissions.py). The
    write paths here (accept / request_revision) need a parallel guard so
    archive doesn't get silently bypassed by the submitter. Admin must
    explicitly restore the project before mutating.
    """
    from services.permissions import is_admin, requirement_project_is_active
    if requirement_project_is_active(req):
        return
    if is_admin(user):
        raise HTTPException(
            status_code=409,
            detail="project is archived or deleted; restore it before mutating its requirements",
        )
    raise HTTPException(status_code=404, detail="requirement not found")


def _require_can_view_assets(req: Requirement, user: User) -> None:
    if not can_view_requirement_assets(req, user):
        raise HTTPException(status_code=403, detail="you cannot access deliveries for this requirement")


@lru_cache(maxsize=512)
def _zip_filelist_cached(path: str, _sha256: str) -> tuple[tuple[str, int], ...]:
    """Walk the package's central directory once and memoize. A delivered
    package is immutable (content-addressed by sha256 + unique package_path),
    so repeated GETs of the same delivery — and every historical round on a
    requirement-detail load — need not re-open the zip and re-run
    inspect_zip_entries' validation each time. Keyed on (path, sha256) so a
    re-uploaded package at a reused path can never collide."""
    try:
        return tuple((e["safe_name"], e["size"]) for e in inspect_zip_entries(Path(path)))
    except Exception:
        return ()


def _zip_filelist(path: str, sha256: str = "") -> list[dict]:
    return [{"name": n, "size": s} for (n, s) in _zip_filelist_cached(path, sha256)]


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
            created_at=d.created_at, files=_zip_filelist(d.package_path, d.package_sha256),
        )
        for d in rows
    ]


class ProjectDeliveryOut(BaseModel):
    delivery_id: str
    requirement_id: str
    requirement_code: str
    requirement_title: str | None
    requirement_status: str
    round: int
    package_size: int
    file_count: int
    submitted_by_nickname: str
    created_at: datetime
    # NOTE: no per-file `files` list here. The project-drive deliverables view
    # (the only consumer) renders code/title/status/round/file_count/size only,
    # so opening every requirement's package zip on each call was pure wasted
    # IO. Per-file names are fetched on demand via the per-delivery endpoints.


@router.get("/projects/{project_id}/deliveries", response_model=list[ProjectDeliveryOut])
def list_project_deliveries(
    project_id: str, db: Session = Depends(get_db), user: User = Depends(current_user),
) -> list[ProjectDeliveryOut]:
    """Read-only deliverables view for the project drive: the latest delivery
    of every requirement in this project that has produced one. Team-visible,
    mirroring the project drive's own visibility (active project + any
    identified user) — deliverables are shared project output, not per-user
    private assets."""
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.archived == False,  # noqa: E712
        Project.deleted_at.is_(None),
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="project not found")

    rows = (
        db.query(Delivery, Requirement)
        .join(Requirement, Requirement.id == Delivery.requirement_id)
        .filter(Requirement.project_id == project_id)
        .order_by(Delivery.requirement_id, Delivery.round.desc())
        .all()
    )
    out: list[ProjectDeliveryOut] = []
    seen: set[str] = set()
    for d, r in rows:
        if d.requirement_id in seen:
            continue  # keep only the latest round per requirement
        seen.add(d.requirement_id)
        out.append(ProjectDeliveryOut(
            delivery_id=d.id, requirement_id=d.requirement_id,
            requirement_code=r.code, requirement_title=r.title,
            requirement_status=r.status, round=d.round,
            package_size=d.package_size, file_count=d.file_count,
            submitted_by_nickname=d.submitted_by_nickname,
            created_at=d.created_at,
        ))
    out.sort(key=lambda x: x.created_at, reverse=True)
    return out


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
    _ensure_writable_project(r, user)
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
    _ensure_writable_project(r, user)
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
