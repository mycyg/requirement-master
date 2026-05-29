from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, exists, or_, update as sql_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from auth import current_user, optional_local_client
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
    is_admin,
    requirement_project_is_active,
)
from services.push_bus import bus
from services.notifications import create_notification, publish_notification, publish_notification_threadsafe
from services.lifecycle import queue_status_notifications, flush_status_notifications
from services.schedule import sync_requirement_due_event
from services.workspaces import ensure_workspaces_for_assignments, sync_workspace_to_status

router = APIRouter(prefix="/api", tags=["requirements"])


def _assignee_out(a: RequirementAssignment) -> RequirementAssigneeOut:
    # Same masking — tombstoned assignee should display as "已删除用户"
    # rather than the raw `_deleted_<id8>_originalname` tombstone string.
    nick = "已删除用户" if a.user and a.user.deleted_at is not None else (a.user.nickname if a.user else "unknown")
    return RequirementAssigneeOut(
        user_id=a.user_id,
        nickname=nick,
        role=a.role,
        assigned_at=a.created_at,
    )


def _to_out(r: Requirement, *, submitter_nickname: str, project_slug: str) -> RequirementOut:
    return RequirementOut(
        id=r.id, code=r.code, project_id=r.project_id, project_slug=project_slug,
        submitter_user_id=r.submitter_user_id,
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


def _display_nickname(u: User | None) -> str:
    """Mask the raw tombstoned nickname (`_deleted_<id8>_originalname`)
    so the original nickname never bleeds back into the UI after admin
    soft-deletes a user."""
    if not u:
        return "unknown"
    if u.deleted_at is not None:
        return "已删除用户"
    return u.nickname


def _ensure_requirement_project_active(req: Requirement) -> None:
    if not requirement_project_is_active(req):
        raise HTTPException(status_code=404, detail="requirement not found")


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
        submitter_nickname=_display_nickname(submitter),
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
        if project.deleted_at:
            raise HTTPException(status_code=400, detail="deleted project cannot accept new requirements")
        if project.archived:
            raise HTTPException(status_code=400, detail="archived project cannot accept new requirements")

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
        # Reset per attempt — a rollback below discards these rows, so a retry
        # must not carry stale notification objects forward.
        notes_to_publish: list = []
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
                    note = create_notification(
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
                    notes_to_publish.append(note)
            log_activity(db, requirement_id=r.id, actor_nickname=user.nickname, action="created", detail={"code": code})
            if r.due_at:
                sync_requirement_due_event(db, r, user)
            db.commit()
            db.refresh(r)
            # Live-push the assignment notifications now that they're committed.
            # This is a SYNC endpoint (threadpool, retry loop) so it can't await
            # publish_notification — the threadsafe bridge schedules it onto the
            # event loop. Without this the assignee's /stream/me never got the
            # live "你被指派到 …" event (it only showed on the next poll).
            for note in notes_to_publish:
                publish_notification_threadsafe(note)
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
        .filter(Project.archived == False, Project.deleted_at.is_(None))  # noqa: E712
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
    _ensure_requirement_project_active(r)
    if not can_view_requirement_record(r, user):
        raise HTTPException(status_code=403, detail="you cannot view this requirement yet")
    return _enrich(db, r)


@router.patch("/requirements/{req_id}/status", response_model=RequirementOut)
async def update_status(
    req_id: str,
    payload: StatusUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    local_user: User | None = Depends(optional_local_client),
) -> RequirementOut:
    r = (
        db.query(Requirement)
        .options(selectinload(Requirement.assignments).selectinload(RequirementAssignment.user))
        .filter(Requirement.id == req_id)
        .first()
    )
    if not r:
        raise HTTPException(status_code=404, detail="requirement not found")
    _ensure_requirement_project_active(r)

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
    worker_transition = (
        new == "claimed"
        or (new != "cancelled" and old in {"claimed", "doing", "revision_requested"})
        or (new == "cancelled" and user.id != r.submitter_user_id)
    )
    if worker_transition and local_user is None:
        raise HTTPException(status_code=403, detail="local client required")

    # Atomic compare-and-swap on status — without this, two concurrent
    # PATCH /status calls both pass the allowed-transitions check and
    # both blind-write the destination, so lifecycle notifications +
    # audit log claim BOTH transitions happened. The same race pattern
    # we fixed in /claim (sync.py).
    now = datetime.utcnow()
    cas = db.execute(
        sql_update(Requirement)
        .where(Requirement.id == req_id, Requirement.status == old)
        .values(status=new)
    )
    if cas.rowcount == 0:
        db.rollback()
        r2 = db.query(Requirement).filter(Requirement.id == req_id).first()
        current = r2.status if r2 else "deleted"
        raise HTTPException(status_code=409, detail=f"status race: requirement is now {current}")
    db.refresh(r)
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

    # Notify the submitter on key milestones — claimed (someone picked it up),
    # delivered (please verify), cancelled-by-someone-else (worker abandoned).
    # Skipped when the submitter themselves is making the transition (they
    # already know). Each notification gets a unique dedupe_key per (req, event)
    # so a duplicate transition doesn't double-toast.
    pending_notifications = queue_status_notifications(db, r, new, user)

    db.commit()
    db.refresh(r)
    await flush_status_notifications(pending_notifications)
    await bus.publish(f"req:{r.id}", "requirement.updated", {"status": r.status})
    await bus.publish("all", "requirement.updated", {"requirement_id": r.id, "status": r.status})
    return _enrich(db, r)


@router.patch("/requirements/{req_id}/planning", response_model=RequirementOut)
async def update_requirement_planning(
    req_id: str,
    payload: RequirementPlanningUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    local_user: User | None = Depends(optional_local_client),
) -> RequirementOut:
    r = (
        db.query(Requirement)
        .options(selectinload(Requirement.assignments).selectinload(RequirementAssignment.user))
        .filter(Requirement.id == req_id)
        .first()
    )
    if not r:
        raise HTTPException(status_code=404, detail="requirement not found")
    _ensure_requirement_project_active(r)
    if r.submitter_user_id != user.id and not can_work_requirement(r, user):
        raise HTTPException(status_code=403, detail="only the requester or assignees can update planning")
    if r.submitter_user_id != user.id and local_user is None:
        raise HTTPException(status_code=403, detail="local client required")
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
    _ensure_requirement_project_active(r)
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
    _ensure_requirement_project_active(r)
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
    notes_to_publish = []
    for assignment in assignments:
        if not assignment.user:
            continue
        notes_to_publish.append(create_notification(
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
        ))
    db.commit()
    # Live-push the (re)assignment notifications — async endpoint, so await
    # directly. content-change guard in create_notification means a no-op
    # re-assign produces an unchanged row whose publish is harmless.
    for note in notes_to_publish:
        await publish_notification(note)
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
    _ensure_requirement_project_active(r)
    if r.submitter_user_id != user.id:
        raise HTTPException(status_code=403, detail="only the requester can update DDL")
    if r.status not in {"draft", "clarifying", "summary_ready", "ready", "claimed", "doing", "revision_requested"}:
        raise HTTPException(status_code=400, detail=f"cannot update DDL from status {r.status}")
    r.start_at = payload.start_at
    r.due_at = payload.due_at
    sync_requirement_due_event(db, r, user)
    notes_to_publish = []
    for assignment in r.assignments:
        if assignment.user:
            notes_to_publish.append(create_notification(
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
            ))
    log_activity(
        db,
        requirement_id=r.id,
        actor_nickname=user.nickname,
        action="schedule_updated",
        detail={"start_at": payload.start_at.isoformat() if payload.start_at else None, "due_at": payload.due_at.isoformat() if payload.due_at else None},
    )
    db.commit()
    db.refresh(r)
    for note in notes_to_publish:
        await publish_notification(note)
    await bus.publish(f"req:{r.id}", "requirement.updated", {"status": r.status, "due_at": r.due_at.isoformat() if r.due_at else None})
    await bus.publish("all", "requirement.updated", {"requirement_id": r.id, "status": r.status})
    return _enrich(db, r)


# --- Tauri client adjuncts (skip AI clarification, admin delete) ---------------

class _FinalizeSummaryIn(__import__("pydantic").BaseModel):
    """If summary_md / title are omitted, we derive sensible defaults from
    raw_description so the desktop client can ship a draft straight to
    summary_ready without round-tripping the AI clarification flow."""
    summary_md: str | None = None
    title: str | None = None


@router.post("/requirements/{req_id}/finalize-summary", response_model=RequirementOut)
async def finalize_summary(
    req_id: str,
    payload: _FinalizeSummaryIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> RequirementOut:
    """Admin-only emergency bypass that marks a draft as `summary_ready`
    without going through the AI clarification chat. Normal flow MUST be
    draft → AI chat (auto sets summary_ready) → submit → ready. This
    bypass exists only for cases where the LLM is down or a hot-fix
    requirement is too trivial to clarify."""
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="finalize-summary 是应急旁路，正常请走 AI 澄清")
    r = (
        db.query(Requirement)
        .options(selectinload(Requirement.assignments).selectinload(RequirementAssignment.user))
        .filter(Requirement.id == req_id)
        .first()
    )
    if not r:
        raise HTTPException(status_code=404, detail="requirement not found")
    _ensure_requirement_project_active(r)
    if r.status not in {"draft", "clarifying", "summary_ready"}:
        raise HTTPException(status_code=400, detail=f"cannot finalize from status {r.status}")

    # Guard against silently clobbering a valid summary_ready record. If
    # caller didn't override and we already have a summary, return unchanged.
    if r.status == "summary_ready" and not payload.summary_md and not payload.title:
        return _enrich(db, r)

    summary_md = (payload.summary_md or "").strip() or (r.summary_md or "").strip() or (r.raw_description or "").strip()
    if not summary_md:
        raise HTTPException(status_code=400, detail="no description to summarise")

    title = (payload.title or "").strip() or (r.title or "").strip()
    if not title:
        # First line, capped at 40 chars — good enough as a card label.
        first_line = next((ln.strip() for ln in (r.raw_description or "").splitlines() if ln.strip()), "")
        title = (first_line[:40] or "未命名需求")

    r.summary_md = summary_md
    r.title = title
    r.status = "summary_ready"
    log_activity(
        db, requirement_id=r.id, actor_nickname=user.nickname,
        action="summary_finalized", detail={"skipped_clarification": True},
    )
    db.commit()
    db.refresh(r)
    await bus.publish(f"req:{r.id}", "requirement.updated", {"status": r.status})
    await bus.publish("all", "requirement.updated", {"requirement_id": r.id, "status": r.status})
    return _enrich(db, r)


@router.delete("/requirements/{req_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_requirement(
    req_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> None:
    """Hard delete. Admin always allowed. Submitter allowed only while
    the requirement is still private (draft / clarifying / summary_ready)
    — once it's been dispatched, traces in workspaces / deliveries / audit
    log have value to other people.

    Archives related notifications first so users don't end up clicking
    dead `/r/<deleted-id>` deep links from their inbox (the FK column is
    `ondelete=SET NULL`, so without this they'd remain visible with stale
    titles and broken targets).
    """
    from datetime import datetime
    from sqlalchemy import update as sql_update
    from models import MeetingInsight, Notification, ProjectDriveComment
    r = db.query(Requirement).filter(Requirement.id == req_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="requirement not found")
    _ensure_requirement_project_active(r)
    if not is_admin(user):
        if r.submitter_user_id != user.id:
            raise HTTPException(status_code=403, detail="only the requester or an admin can delete")
        if r.status not in {"draft", "clarifying", "summary_ready", "cancelled"}:
            raise HTTPException(status_code=400, detail=f"cannot delete from status {r.status} — ask an admin")
    db.query(Notification).filter(
        Notification.requirement_id == req_id, Notification.archived_at.is_(None),
    ).update({"archived_at": datetime.utcnow()})
    # Explicitly NULL out cross-references before delete. The model FKs use
    # `ondelete=SET NULL`, but SQLite tables created BEFORE that schema
    # change kept the old NO ACTION constraint (ALTER TABLE can't change
    # FK on_delete), so on older deployments the delete would fail with
    # FOREIGN KEY constraint violation under `PRAGMA foreign_keys=ON`.
    # Doing it in application code is portable + works on both schemas.
    db.execute(sql_update(ProjectDriveComment).where(ProjectDriveComment.draft_requirement_id == req_id).values(draft_requirement_id=None))
    db.execute(sql_update(MeetingInsight).where(MeetingInsight.target_requirement_id == req_id).values(target_requirement_id=None))
    db.execute(sql_update(MeetingInsight).where(MeetingInsight.created_requirement_id == req_id).values(created_requirement_id=None))
    db.execute(sql_update(Requirement).where(Requirement.source_requirement_id == req_id).values(source_requirement_id=None))
    db.delete(r)
    db.commit()
