from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, exists, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from auth import current_user
from db import get_db
from models import Project, Requirement, RequirementAssignment, User
from schemas import (
    RequirementAssigneeOut,
    RequirementAssigneesUpdateIn,
    RequirementCreateIn,
    RequirementOut,
    RequirementPlanningUpdateIn,
    RequirementScheduleUpdateIn,
    StatusUpdateIn,
)
from services.activity import log_activity
from services.assignments import ensure_public_claim_assignment, replace_assignments, sorted_assignments, sync_legacy_lead
from services.permissions import (
    PRIVATE_REQUIREMENT_STATUSES,
    can_manage_requirement_assignees,
    can_claim_requirement,
    can_view_requirement_record,
    can_work_requirement,
)
from services.push_bus import bus
from services.notifications import create_notification
from services.schedule import sync_requirement_due_event
from services.workspaces import ensure_workspaces_for_assignments, sync_workspace_to_status

router = APIRouter(prefix="/api", tags=["requirements"])


def _assignee_out(a: RequirementAssignment) -> RequirementAssigneeOut:
    return RequirementAssigneeOut(
        user_id=a.user_id,
        nickname=a.user.nickname,
        role=a.role,
        assigned_at=a.created_at,
    )


def _to_out(r: Requirement, *, submitter_nickname: str, project_slug: str) -> RequirementOut:
    return RequirementOut(
        id=r.id, code=r.code, project_id=r.project_id, project_slug=project_slug,
        submitter_nickname=submitter_nickname,
        claimed_by_user_id=r.claimed_by_user_id,
        claimed_by_nickname=r.claimed_by_nickname,
        title=r.title, raw_description=r.raw_description, summary_md=r.summary_md,
        status=r.status, priority=r.priority,
        estimate_hours=r.estimate_hours,
        estimate_confidence=r.estimate_confidence,
        planning_note=r.planning_note,
        start_at=r.start_at, due_at=r.due_at,
        source_meeting_id=r.source_meeting_id,
        source_requirement_id=r.source_requirement_id,
        claimed_at=r.claimed_at, done_at=r.done_at,
        delivered_at=r.delivered_at, accepted_at=r.accepted_at,
        delivery_doc_ready_at=r.delivery_doc_ready_at,
        sync_state=r.sync_state,
        assignees=[_assignee_out(a) for a in sorted_assignments(r)],
        created_at=r.created_at, updated_at=r.updated_at,
    )


def _enrich(db: Session, r: Requirement) -> RequirementOut:
    if "assignments" not in r.__dict__:
        r = (
            db.query(Requirement)
            .options(selectinload(Requirement.assignments).selectinload(RequirementAssignment.user))
            .filter(Requirement.id == r.id)
            .first()
        )
        if not r:
            raise HTTPException(status_code=404, detail="requirement not found")
    project = db.query(Project).filter(Project.id == r.project_id).first()
    submitter = db.query(User).filter(User.id == r.submitter_user_id).first()
    return _to_out(
        r,
        submitter_nickname=submitter.nickname if submitter else "unknown",
        project_slug=project.slug if project else "unknown",
    )


@router.post("/projects/{project_id}/requirements", response_model=RequirementOut, status_code=status.HTTP_201_CREATED)
def create_requirement(
    project_id: str,
    payload: RequirementCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> RequirementOut:
    for _ in range(5):
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="project not found")

        project.next_seq += 1
        code = f"{project.slug.upper()}-{project.next_seq:03d}"

        r = Requirement(
            code=code,
            project_id=project.id,
            submitter_user_id=user.id,
            raw_description=payload.raw_description,
            priority=payload.priority,
            estimate_hours=payload.estimate_hours,
            estimate_confidence=payload.estimate_confidence,
            planning_note=payload.planning_note,
            start_at=payload.start_at,
            due_at=payload.due_at,
            status="draft",
        )
        db.add(r)
        try:
            db.flush()
            if payload.lead_user_id or payload.collaborator_user_ids:
                replace_assignments(
                    db,
                    r,
                    lead_user_id=payload.lead_user_id,
                    collaborator_user_ids=payload.collaborator_user_ids,
                    actor=user,
                )
                ensure_workspaces_for_assignments(db, r)
                assigned_ids = {payload.lead_user_id, *payload.collaborator_user_ids} - {None}
                for assignee in db.query(User).filter(User.id.in_(assigned_ids)).all():
                    create_notification(
                        db,
                        assignee,
                        type="assigned",
                        title=f"你被指派到 {code}",
                        body=(r.raw_description or "")[:300],
                        severity="high" if r.priority in {"high", "urgent"} else "normal",
                        target_url=f"/r/{r.id}",
                        project_id=r.project_id,
                        requirement_id=r.id,
                        dedupe_key=f"assigned:{r.id}:{assignee.id}",
                    )
            log_activity(db, requirement_id=r.id, actor_nickname=user.nickname, action="created", detail={"code": code})
            if r.due_at:
                sync_requirement_due_event(db, r, user)
            db.commit()
            db.refresh(r)
            return _enrich(db, r)
        except IntegrityError:
            db.rollback()

    raise HTTPException(status_code=409, detail="could not allocate requirement code; please retry")


@router.get("/requirements", response_model=list[RequirementOut])
def list_requirements(
    project_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    mine: bool = Query(default=False),
    assigned_to_me: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[RequirementOut]:
    assigned_exists = exists().where(and_(
        RequirementAssignment.requirement_id == Requirement.id,
        RequirementAssignment.user_id == user.id,
    ))
    q = (
        db.query(Requirement, Project.slug, User.nickname)
        .join(Project, Project.id == Requirement.project_id)
        .join(User, User.id == Requirement.submitter_user_id)
        .options(selectinload(Requirement.assignments).selectinload(RequirementAssignment.user))
    )
    if project_id:
        q = q.filter(Requirement.project_id == project_id)
    if status_filter:
        q = q.filter(Requirement.status == status_filter)
    if mine:
        q = q.filter(Requirement.submitter_user_id == user.id)
    if assigned_to_me:
        q = q.filter(or_(Requirement.claimed_by_user_id == user.id, assigned_exists))
    q = q.filter(or_(
        ~Requirement.status.in_(PRIVATE_REQUIREMENT_STATUSES),
        Requirement.submitter_user_id == user.id,
        Requirement.claimed_by_user_id == user.id,
        assigned_exists,
    ))
    rows = q.order_by(Requirement.created_at.desc()).limit(500).all()
    return [
        _to_out(r, submitter_nickname=submitter_nickname, project_slug=project_slug)
        for r, project_slug, submitter_nickname in rows
    ]


@router.get("/requirements/{req_id}", response_model=RequirementOut)
def get_requirement(req_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> RequirementOut:
    r = (
        db.query(Requirement)
        .options(selectinload(Requirement.assignments).selectinload(RequirementAssignment.user))
        .filter(Requirement.id == req_id)
        .first()
    )
    if not r:
        raise HTTPException(status_code=404, detail="requirement not found")
    if not can_view_requirement_record(r, user):
        raise HTTPException(status_code=403, detail="you cannot view this requirement yet")
    return _enrich(db, r)


@router.patch("/requirements/{req_id}/status", response_model=RequirementOut)
async def update_status(
    req_id: str,
    payload: StatusUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> RequirementOut:
    r = (
        db.query(Requirement)
        .options(selectinload(Requirement.assignments).selectinload(RequirementAssignment.user))
        .filter(Requirement.id == req_id)
        .first()
    )
    if not r:
        raise HTTPException(status_code=404, detail="requirement not found")

    old = r.status
    new = payload.status
    if old == new:
        return _enrich(db, r)

    allowed = {
        "draft": {"clarifying", "cancelled"},
        "clarifying": {"summary_ready", "cancelled"},
        "summary_ready": {"clarifying", "cancelled"},
        "ready": {"claimed", "cancelled"},
        "claimed": {"doing", "cancelled"},
        "doing": {"cancelled"},
        "ai_processing": {"cancelled"},
        "delivery_doc_pending": {"cancelled"},
        "delivered": set(),
        "revision_requested": {"doing", "cancelled"},
        "accepted": set(),
        "cancelled": set(),
    }
    if new not in allowed.get(old, set()):
        raise HTTPException(status_code=400, detail=f"cannot change status from {old} to {new}")
    if old in {"draft", "clarifying", "summary_ready"} and r.submitter_user_id != user.id:
        raise HTTPException(status_code=403, detail="only the requester can change this status")
    if new == "claimed" and not can_claim_requirement(r, user):
        raise HTTPException(status_code=403, detail="only assigned users can claim this requirement")
    if new == "cancelled" and user.id != r.submitter_user_id and not can_work_requirement(r, user):
        raise HTTPException(status_code=403, detail="only the requester or assignee can cancel this requirement")
    if new != "cancelled" and old in {"claimed", "doing", "revision_requested"} and not can_work_requirement(r, user):
        raise HTTPException(status_code=403, detail="only the assignee can change this status")

    r.status = new
    now = datetime.utcnow()
    if new == "claimed":
        if not r.claimed_at:
            r.claimed_at = now
        if not r.assignments:
            ensure_public_claim_assignment(db, r, user)
        else:
            sync_legacy_lead(r)
    elif new == "doing":
        if not r.claimed_at:
            r.claimed_at = now
        if not r.assignments:
            ensure_public_claim_assignment(db, r, user)
        else:
            sync_legacy_lead(r)
    elif new == "delivered" and not r.delivered_at:
        r.delivered_at = now
    elif new == "delivery_doc_pending" and not r.delivered_at:
        r.delivered_at = now
    elif new == "accepted" and not r.accepted_at:
        r.accepted_at = now
        r.done_at = now

    log_activity(
        db, requirement_id=r.id, actor_nickname=user.nickname,
        action="status_changed", detail={"from": old, "to": new},
    )
    ensure_workspaces_for_assignments(db, r)
    sync_workspace_to_status(db, r, user)
    db.commit()
    db.refresh(r)
    await bus.publish(f"req:{r.id}", "requirement.updated", {"status": r.status})
    await bus.publish("all", "requirement.updated", {"requirement_id": r.id, "status": r.status})
    return _enrich(db, r)


@router.patch("/requirements/{req_id}/planning", response_model=RequirementOut)
async def update_requirement_planning(
    req_id: str,
    payload: RequirementPlanningUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> RequirementOut:
    r = (
        db.query(Requirement)
        .options(selectinload(Requirement.assignments).selectinload(RequirementAssignment.user))
        .filter(Requirement.id == req_id)
        .first()
    )
    if not r:
        raise HTTPException(status_code=404, detail="requirement not found")
    if r.submitter_user_id != user.id and not can_work_requirement(r, user):
        raise HTTPException(status_code=403, detail="only the requester or assignees can update planning")
    if user.id != r.submitter_user_id and payload.estimate_hours is not None:
        raise HTTPException(status_code=403, detail="only the requester can change estimate hours")
    if payload.estimate_hours is not None:
        r.estimate_hours = payload.estimate_hours
    if payload.estimate_confidence is not None:
        r.estimate_confidence = payload.estimate_confidence
    if payload.planning_note is not None:
        r.planning_note = payload.planning_note
    log_activity(
        db,
        requirement_id=r.id,
        actor_nickname=user.nickname,
        action="planning_updated",
        detail={
            "estimate_hours": r.estimate_hours,
            "estimate_confidence": r.estimate_confidence,
            "planning_note": r.planning_note,
        },
    )
    db.commit()
    db.refresh(r)
    await bus.publish(
        f"req:{r.id}",
        "requirement.updated",
        {"status": r.status, "estimate_hours": r.estimate_hours},
    )
    await bus.publish("all", "requirement.updated", {"requirement_id": r.id, "status": r.status})
    return _enrich(db, r)


@router.get("/requirements/{req_id}/assignees", response_model=list[RequirementAssigneeOut])
def list_assignees(req_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[RequirementAssigneeOut]:
    r = (
        db.query(Requirement)
        .options(selectinload(Requirement.assignments).selectinload(RequirementAssignment.user))
        .filter(Requirement.id == req_id)
        .first()
    )
    if not r:
        raise HTTPException(status_code=404, detail="requirement not found")
    if not can_view_requirement_record(r, user):
        raise HTTPException(status_code=403, detail="you cannot view this requirement yet")
    return [_assignee_out(a) for a in sorted_assignments(r)]


@router.put("/requirements/{req_id}/assignees", response_model=list[RequirementAssigneeOut])
async def update_assignees(
    req_id: str,
    payload: RequirementAssigneesUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[RequirementAssigneeOut]:
    r = (
        db.query(Requirement)
        .options(selectinload(Requirement.assignments).selectinload(RequirementAssignment.user))
        .filter(Requirement.id == req_id)
        .first()
    )
    if not r:
        raise HTTPException(status_code=404, detail="requirement not found")
    if not can_manage_requirement_assignees(r, user):
        raise HTTPException(status_code=403, detail="only the requester can manage assignees in this status")
    assignments = replace_assignments(
        db,
        r,
        lead_user_id=payload.lead_user_id,
        collaborator_user_ids=payload.collaborator_user_ids,
        actor=user,
    )
    ensure_workspaces_for_assignments(db, r)
    log_activity(
        db,
        requirement_id=r.id,
        actor_nickname=user.nickname,
        action="assignees_updated",
        detail={
            "lead_user_id": payload.lead_user_id,
            "collaborator_user_ids": payload.collaborator_user_ids,
        },
    )
    if r.due_at:
        sync_requirement_due_event(db, r, user)
    for assignment in assignments:
        if not assignment.user:
            continue
        create_notification(
            db,
            assignment.user,
            type="assigned",
            title=f"你被指派到 {r.code}",
            body=f"{user.nickname} 调整了接单人。",
            severity="normal",
            target_url=f"/r/{r.id}",
            project_id=r.project_id,
            requirement_id=r.id,
            dedupe_key=f"assigned:{r.id}:{assignment.user_id}",
        )
    db.commit()
    await bus.publish(f"req:{r.id}", "requirement.updated", {"status": r.status, "assignees": len(assignments)})
    await bus.publish("all", "requirement.updated", {"requirement_id": r.id, "status": r.status, "assignees": len(assignments)})
    return [_assignee_out(a) for a in assignments]


@router.patch("/requirements/{req_id}/schedule", response_model=RequirementOut)
async def update_requirement_schedule(
    req_id: str,
    payload: RequirementScheduleUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> RequirementOut:
    r = (
        db.query(Requirement)
        .options(selectinload(Requirement.assignments).selectinload(RequirementAssignment.user))
        .filter(Requirement.id == req_id)
        .first()
    )
    if not r:
        raise HTTPException(status_code=404, detail="requirement not found")
    if r.submitter_user_id != user.id:
        raise HTTPException(status_code=403, detail="only the requester can update DDL")
    if r.status not in {"draft", "clarifying", "summary_ready", "ready", "claimed", "doing", "revision_requested"}:
        raise HTTPException(status_code=400, detail=f"cannot update DDL from status {r.status}")
    r.start_at = payload.start_at
    r.due_at = payload.due_at
    sync_requirement_due_event(db, r, user)
    for assignment in r.assignments:
        if assignment.user:
            create_notification(
                db,
                assignment.user,
                type="due_changed",
                title=f"{r.code} 的 DDL 更新了",
                body=f"新的 DDL：{payload.due_at.isoformat() if payload.due_at else '未设置'}",
                severity="normal",
                target_url=f"/r/{r.id}",
                project_id=r.project_id,
                requirement_id=r.id,
                dedupe_key=f"due_changed:{r.id}:{assignment.user_id}:{payload.due_at.isoformat() if payload.due_at else 'none'}",
            )
    log_activity(
        db,
        requirement_id=r.id,
        actor_nickname=user.nickname,
        action="schedule_updated",
        detail={"start_at": payload.start_at.isoformat() if payload.start_at else None, "due_at": payload.due_at.isoformat() if payload.due_at else None},
    )
    db.commit()
    db.refresh(r)
    await bus.publish(f"req:{r.id}", "requirement.updated", {"status": r.status, "due_at": r.due_at.isoformat() if r.due_at else None})
    await bus.publish("all", "requirement.updated", {"requirement_id": r.id, "status": r.status})
    return _enrich(db, r)
