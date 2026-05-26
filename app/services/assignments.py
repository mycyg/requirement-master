"""Requirement assignment helpers.

Assignments are explicit workers for a requirement: one lead and zero or more
collaborators. The old ``claimed_by_*`` fields remain as a compatibility
snapshot of the current lead.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import Requirement, RequirementAssignment, User

ASSIGNMENT_ROLES = {"lead", "collaborator"}
ACTIVE_ASSIGNMENT_STATUSES = {"claimed", "doing", "revision_requested"}


def assignment_user_ids(req: Requirement) -> set[str]:
    return {a.user_id for a in req.assignments}


def has_explicit_assignees(req: Requirement) -> bool:
    return bool(req.assignments)


def is_assigned_user(req: Requirement, user: User) -> bool:
    if any(a.user_id == user.id for a in req.assignments):
        return True
    return bool(req.claimed_by_user_id and req.claimed_by_user_id == user.id)


def lead_assignment(req: Requirement) -> RequirementAssignment | None:
    for a in req.assignments:
        if a.role == "lead":
            return a
    return None


def sorted_assignments(req: Requirement) -> list[RequirementAssignment]:
    return sorted(req.assignments, key=lambda a: (0 if a.role == "lead" else 1, a.user.nickname.lower()))


def normalize_assignment_input(
    lead_user_id: str | None,
    collaborator_user_ids: list[str] | None,
    *,
    active_status: str | None = None,
) -> tuple[str | None, list[str]]:
    collaborator_user_ids = collaborator_user_ids or []
    lead = (lead_user_id or "").strip() or None
    collabs: list[str] = []
    seen: set[str] = set()
    for uid in collaborator_user_ids:
        uid = (uid or "").strip()
        if not uid or uid == lead or uid in seen:
            continue
        seen.add(uid)
        collabs.append(uid)
    if collabs and not lead:
        raise HTTPException(status_code=400, detail="lead_user_id is required when collaborators are assigned")
    if active_status in ACTIVE_ASSIGNMENT_STATUSES and not lead:
        raise HTTPException(status_code=400, detail="active work must keep a lead assignee")
    return lead, collabs


def _users_by_id(db: Session, ids: set[str]) -> dict[str, User]:
    if not ids:
        return {}
    users = db.query(User).filter(User.id.in_(ids)).all()
    found = {u.id: u for u in users}
    missing = sorted(ids - set(found))
    if missing:
        raise HTTPException(status_code=400, detail=f"unknown user id(s): {', '.join(missing)}")
    return found


def sync_legacy_lead(req: Requirement) -> None:
    lead = lead_assignment(req)
    if lead:
        req.claimed_by_user_id = lead.user_id
        req.claimed_by_nickname = lead.user.nickname
    elif not req.assignments:
        req.claimed_by_user_id = None
        req.claimed_by_nickname = None


def replace_assignments(
    db: Session,
    req: Requirement,
    *,
    lead_user_id: str | None,
    collaborator_user_ids: list[str] | None,
    actor: User,
) -> list[RequirementAssignment]:
    lead_user_id, collaborator_user_ids = normalize_assignment_input(
        lead_user_id,
        collaborator_user_ids,
        active_status=req.status,
    )
    ids = {lead_user_id, *collaborator_user_ids} if lead_user_id else set()
    users = _users_by_id(db, {uid for uid in ids if uid})

    for assignment in list(req.assignments):
        db.delete(assignment)
    req.assignments.clear()
    db.flush()

    if lead_user_id:
        req.assignments.append(RequirementAssignment(
            requirement_id=req.id,
            user_id=lead_user_id,
            role="lead",
            assigned_by_user_id=actor.id,
        ))
    for uid in collaborator_user_ids:
        req.assignments.append(RequirementAssignment(
            requirement_id=req.id,
            user_id=uid,
            role="collaborator",
            assigned_by_user_id=actor.id,
        ))

    db.flush()
    if lead_user_id:
        lead = users[lead_user_id]
        req.claimed_by_user_id = lead.id
        req.claimed_by_nickname = lead.nickname
    else:
        req.claimed_by_user_id = None
        req.claimed_by_nickname = None
        if req.status in {"draft", "clarifying", "summary_ready", "ready"}:
            req.claimed_at = None
    return sorted_assignments(req)


def ensure_public_claim_assignment(db: Session, req: Requirement, user: User) -> None:
    if req.assignments:
        return
    req.assignments.append(RequirementAssignment(
        requirement_id=req.id,
        user_id=user.id,
        role="lead",
        assigned_by_user_id=user.id,
    ))
    req.claimed_by_user_id = user.id
    req.claimed_by_nickname = user.nickname
    if not req.claimed_at:
        req.claimed_at = datetime.utcnow()
    db.flush()
