from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import and_, exists, or_
from sqlalchemy.orm import Session

from auth import current_user
from db import get_db
from models import Project, Requirement, RequirementAssignment, RequirementWorkspace, User
from schemas import ReminderOut

router = APIRouter(prefix="/api/reminders", tags=["reminders"])

ACTIVE_STATUSES = {"ready", "claimed", "doing", "ai_processing", "delivery_doc_pending", "revision_requested"}


def _kind(minutes: int) -> str:
    if minutes < 0:
        return "overdue"
    if minutes <= 5:
        return "due_now"
    if minutes <= 120:
        return "due_2h"
    return "due_24h"


@router.get("/due", response_model=list[ReminderOut])
def due_reminders(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[ReminderOut]:
    now = datetime.utcnow()
    horizon = now + timedelta(hours=24)
    assigned_exists = exists().where(and_(
        RequirementAssignment.requirement_id == Requirement.id,
        RequirementAssignment.user_id == user.id,
    ))
    rows = (
        db.query(Requirement, Project.slug)
        .join(Project, Project.id == Requirement.project_id)
        .filter(
            Requirement.due_at.is_not(None),
            Requirement.status.in_(ACTIVE_STATUSES),
            Requirement.due_at <= horizon,
            # Suppress reminders for requirements in soft-deleted projects —
            # admin tombstoned/archived them, no point pinging the user about
            # a DDL they can no longer act on.
            Project.archived == False,  # noqa: E712
            Project.deleted_at.is_(None),
            or_(
                Requirement.submitter_user_id == user.id,
                Requirement.claimed_by_user_id == user.id,
                assigned_exists,
            ),
        )
        .order_by(Requirement.due_at.asc())
        .limit(200)
        .all()
    )
    out: list[ReminderOut] = []
    for req, project_slug in rows:
        minutes = int((req.due_at - now).total_seconds() // 60) if req.due_at else 0
        title = req.title or ((req.raw_description or "").strip()[:80]) or req.code
        workspace = (
            db.query(RequirementWorkspace)
            .filter(RequirementWorkspace.requirement_id == req.id, RequirementWorkspace.user_id == user.id)
            .first()
        )
        out.append(ReminderOut(
            id=f"requirement:{req.id}:{_kind(minutes)}",
            kind=_kind(minutes),
            title=title,
            project_slug=project_slug,
            requirement_id=req.id,
            requirement_code=req.code,
            due_at=req.due_at,
            status=req.status,
            minutes_until_due=minutes,
            phase=workspace.phase if workspace else None,
            progress_percent=workspace.progress_percent if workspace else None,
            blocked_reason=workspace.blocked_reason if workspace else None,
        ))
    return out
