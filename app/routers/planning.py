from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from auth import current_user
from db import get_db
from models import Project, Requirement, RequirementAssignment, RequirementWorkspace, User
from schemas import UserWorkloadOut, WorkloadRequirementOut
from services.presence import get_presence_map

router = APIRouter(prefix="/api", tags=["planning"])

ACTIVE_STATUSES = {"ready", "claimed", "doing", "revision_requested", "delivery_doc_pending", "delivered"}


@router.get("/planning/workload", response_model=list[UserWorkloadOut])
def get_workload(
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    project_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
) -> list[UserWorkloadOut]:
    if project_id and not db.query(Project.id).filter(
        Project.id == project_id,
        Project.archived == False,  # noqa: E712
        Project.deleted_at.is_(None),
    ).first():
        raise HTTPException(status_code=404, detail="project not found")
    now = datetime.utcnow()
    start_dt = start or now
    end_dt = end or (now + timedelta(days=14))
    if end_dt < start_dt:
        raise HTTPException(status_code=400, detail="end must be after start")

    req_q = (
        db.query(Requirement)
        .join(Project, Project.id == Requirement.project_id)
        .options(
            selectinload(Requirement.project),
            selectinload(Requirement.assignments).selectinload(RequirementAssignment.user),
            selectinload(Requirement.workspaces).selectinload(RequirementWorkspace.user),
        )
        .filter(Project.archived == False, Project.deleted_at.is_(None))  # noqa: E712
        .filter(Requirement.status.in_(ACTIVE_STATUSES))
        .filter(or_(Requirement.due_at.is_(None), Requirement.due_at.between(start_dt, end_dt)))
    )
    if project_id:
        req_q = req_q.filter(Requirement.project_id == project_id)
    reqs = req_q.order_by(Requirement.due_at.asc().nullslast(), Requirement.created_at.desc()).limit(1000).all()

    users = {u.id: u for u in db.query(User).all()}
    presence = get_presence_map(list(users))
    task_map: dict[str, list[WorkloadRequirementOut]] = defaultdict(list)
    hours_map: dict[str, float] = defaultdict(float)
    overdue_map: dict[str, int] = defaultdict(int)
    blocked_map: dict[str, int] = defaultdict(int)
    due_week_map: dict[str, int] = defaultdict(int)
    week_end = now + timedelta(days=7)

    for req in reqs:
        assignees = [a for a in req.assignments if a.user_id in users]
        if not assignees:
            continue
        share = float(req.estimate_hours or 2.0) / max(1, len(assignees))
        for assignment in assignees:
            workspace = next((w for w in req.workspaces if w.user_id == assignment.user_id), None)
            blocked = workspace.blocked_reason if workspace else None
            task_map[assignment.user_id].append(WorkloadRequirementOut(
                id=req.id,
                code=req.code,
                title=req.title,
                project_id=req.project_id,
                project_slug=req.project.slug if req.project else "unknown",
                status=req.status,
                due_at=req.due_at,
                estimate_hours=req.estimate_hours,
                progress_percent=workspace.progress_percent if workspace else None,
                blocked_reason=blocked,
            ))
            hours_map[assignment.user_id] += share
            if req.due_at and req.due_at < now and req.status not in {"accepted", "cancelled"}:
                overdue_map[assignment.user_id] += 1
            if blocked:
                blocked_map[assignment.user_id] += 1
            if req.due_at and now <= req.due_at <= week_end:
                due_week_map[assignment.user_id] += 1

    span_days = max(1, ceil((end_dt - start_dt).total_seconds() / 86400))
    rows: list[UserWorkloadOut] = []
    for user_id, user in users.items():
        status = user.availability_status or "free"
        capacity = span_days * 6.0
        if status == "busy":
            capacity *= 0.5
        hours = round(hours_map[user_id], 1)
        load = int(round((hours / capacity) * 100)) if capacity > 0 else 0
        rows.append(UserWorkloadOut(
            user_id=user.id,
            nickname=user.nickname,
            is_online=presence[user.id].is_online,
            availability_status=status,
            availability_text=user.availability_text,
            task_count=len(task_map[user_id]),
            estimate_hours=hours,
            capacity_hours=round(capacity, 1),
            load_percent=load,
            overdue_count=overdue_map[user_id],
            blocked_count=blocked_map[user_id],
            due_this_week_count=due_week_map[user_id],
            requirements=sorted(task_map[user_id], key=lambda item: (item.due_at or datetime.max, item.code))[:30],
        ))
    return sorted(rows, key=lambda row: (-row.load_percent, -row.overdue_count, row.nickname.casefold()))
