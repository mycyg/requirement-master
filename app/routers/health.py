from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import current_user
from db import get_db
from models import ActivityLog, Project, Requirement, RequirementAssignment, RequirementWorkspace, User
from schemas import ProjectHealthOut

router = APIRouter(prefix="/api", tags=["health"])

ACTIVE_STATUSES = {"ready", "claimed", "doing", "revision_requested", "delivery_doc_pending", "delivered"}


def _health_for_project(db: Session, project: Project) -> ProjectHealthOut:
    now = datetime.utcnow()
    soon = now + timedelta(days=3)
    reqs = db.query(Requirement).filter(Requirement.project_id == project.id).all()
    req_ids = [req.id for req in reqs]
    active = [req for req in reqs if req.status in ACTIVE_STATUSES]
    overdue = [req for req in active if req.due_at and req.due_at < now]
    due_soon = [req for req in active if req.due_at and now <= req.due_at <= soon]
    revision = [req for req in reqs if req.status == "revision_requested"]
    unclaimed = [req for req in active if req.status == "ready" and not req.claimed_by_user_id]
    load_hours = round(sum(float(req.estimate_hours or 2.0) for req in active), 1)
    blocked_count = 0
    if req_ids:
        blocked_count = (
            db.query(RequirementWorkspace)
            .filter(RequirementWorkspace.requirement_id.in_(req_ids), RequirementWorkspace.blocked_reason.isnot(None))
            .count()
        )
    accepted_30d = [req for req in reqs if req.accepted_at and req.accepted_at >= now - timedelta(days=30)]
    cycle_values = [
        (req.accepted_at - req.created_at).total_seconds() / 3600
        for req in reqs
        if req.accepted_at and req.created_at
    ]
    change_count = len([req for req in reqs if req.source_requirement_id])
    if req_ids:
        change_count += (
            db.query(ActivityLog)
            .filter(ActivityLog.requirement_id.in_(req_ids))
            .filter(ActivityLog.action.in_(["schedule_updated", "planning_updated", "assignees_updated", "revision_requested"]))
            .count()
        )

    risks: list[str] = []
    if overdue:
        risks.append(f"{len(overdue)} 个需求已逾期")
    if blocked_count:
        risks.append(f"{blocked_count} 个个人工作区存在阻塞")
    if unclaimed:
        risks.append(f"{len(unclaimed)} 个需求还在公开池等人接")
    if due_soon:
        risks.append(f"{len(due_soon)} 个需求 3 天内到期")
    if revision:
        risks.append(f"{len(revision)} 个需求处于返工")
    if load_hours > max(1, len({a.user_id for req in active for a in req.assignments}) * 18):
        risks.append("当前估算负载偏高，排期页建议看一眼")

    score = 100
    score -= len(overdue) * 10
    score -= blocked_count * 8
    score -= len(unclaimed) * 6
    score -= len(due_soon) * 4
    score -= len(revision) * 5
    score = max(0, min(100, score))
    if score >= 80:
        risk_level = "healthy"
    elif score >= 60:
        risk_level = "watch"
    else:
        risk_level = "risk"
    return ProjectHealthOut(
        project_id=project.id,
        project_name=project.name,
        project_slug=project.slug,
        score=score,
        risk_level=risk_level,
        risks=risks,
        overdue_count=len(overdue),
        blocked_count=blocked_count,
        unclaimed_count=len(unclaimed),
        due_soon_count=len(due_soon),
        revision_count=len(revision),
        change_count=change_count,
        active_count=len(active),
        accepted_count=len([req for req in reqs if req.status == "accepted"]),
        throughput_30d=len(accepted_30d),
        avg_cycle_hours=round(sum(cycle_values) / len(cycle_values), 1) if cycle_values else None,
        load_hours=load_hours,
    )


@router.get("/project-health", response_model=list[ProjectHealthOut])
def list_project_health(db: Session = Depends(get_db), _: User = Depends(current_user)) -> list[ProjectHealthOut]:
    projects = db.query(Project).filter(Project.archived == False).order_by(Project.created_at.desc()).all()  # noqa: E712
    return sorted([_health_for_project(db, project) for project in projects], key=lambda row: (row.score, -row.overdue_count))


@router.get("/projects/{project_id}/health", response_model=ProjectHealthOut)
def get_project_health(project_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)) -> ProjectHealthOut:
    project = db.query(Project).filter(Project.id == project_id, Project.archived == False).first()  # noqa: E712
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    return _health_for_project(db, project)
