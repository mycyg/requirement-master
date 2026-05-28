from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from auth import current_user
from db import get_db
from models import Notification, Project, Requirement, RequirementAssignment, RequirementWorkspace, User
from schemas import NotificationOut
from services.notifications import create_notification, notification_out

router = APIRouter(prefix="/api", tags=["notifications"])

ACTIVE_STATUSES = {"ready", "claimed", "doing", "revision_requested", "delivery_doc_pending", "delivered"}


def _ensure_due_notifications(db: Session, user: User) -> None:
    now = datetime.utcnow()
    soon = now + timedelta(hours=24)
    assigned = (
        db.query(Requirement)
        .join(Project, Project.id == Requirement.project_id)
        .join(RequirementAssignment, RequirementAssignment.requirement_id == Requirement.id)
        .filter(Project.archived == False, Project.deleted_at.is_(None))  # noqa: E712
        .filter(RequirementAssignment.user_id == user.id)
        .filter(Requirement.status.in_(ACTIVE_STATUSES))
        .filter(Requirement.due_at.isnot(None))
        .filter(Requirement.due_at <= soon)
        .limit(200)
        .all()
    )
    for req in assigned:
        if req.due_at and req.due_at < now:
            day = now.date().isoformat()
            create_notification(
                db,
                user,
                type="due_overdue",
                title=f"{req.code} 已逾期",
                body=f"DDL 是 {req.due_at.strftime('%Y-%m-%d %H:%M')}，该去把它从火里捞出来了。",
                severity="high",
                target_url=f"/r/{req.id}",
                project_id=req.project_id,
                requirement_id=req.id,
                dedupe_key=f"due:{req.id}:overdue:{day}",
            )
        elif req.due_at:
            create_notification(
                db,
                user,
                type="due_soon",
                title=f"{req.code} 即将到期",
                body=f"DDL 是 {req.due_at.strftime('%Y-%m-%d %H:%M')}，建议看一眼进度。",
                severity="normal",
                target_url=f"/r/{req.id}",
                project_id=req.project_id,
                requirement_id=req.id,
                dedupe_key=f"due:{req.id}:soon:{req.due_at.date().isoformat()}",
            )
    blocked = (
        db.query(RequirementWorkspace)
        .join(Requirement, Requirement.id == RequirementWorkspace.requirement_id)
        .join(Project, Project.id == Requirement.project_id)
        .filter(RequirementWorkspace.user_id == user.id)
        .filter(RequirementWorkspace.blocked_reason.isnot(None))
        .filter(Project.archived == False, Project.deleted_at.is_(None))  # noqa: E712
        .filter(Requirement.status.in_(ACTIVE_STATUSES))
        .limit(100)
        .all()
    )
    for ws in blocked:
        create_notification(
            db,
            user,
            type="workspace_blocked",
            title="你的工作区标了阻塞",
            body=ws.blocked_reason[:300] if ws.blocked_reason else None,
            severity="high",
            target_url=f"/r/{ws.requirement_id}?tab=workspace",
            project_id=ws.requirement.project_id if ws.requirement else None,
            requirement_id=ws.requirement_id,
            dedupe_key=f"blocked:{ws.requirement_id}:{user.id}",
        )


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(
    status: str = Query(default="unread", pattern=r"^(unread|all)$"),
    limit: int = Query(default=80, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[NotificationOut]:
    _ensure_due_notifications(db, user)
    db.commit()
    q = (
        db.query(Notification)
        .outerjoin(Project, Project.id == Notification.project_id)
        .filter(Notification.user_id == user.id, Notification.archived_at.is_(None))
        .filter(or_(Notification.project_id.is_(None), and_(
            Project.archived == False,  # noqa: E712
            Project.deleted_at.is_(None),
        )))
    )
    if status == "unread":
        q = q.filter(Notification.read_at.is_(None))
    rows = q.order_by(Notification.created_at.desc()).limit(limit).all()
    return [notification_out(row) for row in rows]


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
def mark_notification_read(
    notification_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> NotificationOut:
    row = db.query(Notification).filter(Notification.id == notification_id, Notification.user_id == user.id).first()
    if not row:
        raise HTTPException(status_code=404, detail="notification not found")
    if not row.read_at:
        row.read_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return notification_out(row)


@router.post("/notifications/read-all")
def mark_all_notifications_read(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    now = datetime.utcnow()
    count = (
        db.query(Notification)
        .filter(and_(Notification.user_id == user.id, Notification.read_at.is_(None), Notification.archived_at.is_(None)))
        .update({Notification.read_at: now}, synchronize_session=False)
    )
    db.commit()
    return {"ok": True, "count": count}
