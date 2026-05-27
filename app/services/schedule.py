from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from models import Requirement, RequirementAssignment, ScheduleEvent, User


def participant_ids_for_requirement(req: Requirement) -> list[str]:
    ids = [req.submitter_user_id]
    ids.extend(a.user_id for a in (req.assignments or []))
    if req.claimed_by_user_id:
        ids.append(req.claimed_by_user_id)
    seen: set[str] = set()
    out: list[str] = []
    for user_id in ids:
        if user_id and user_id not in seen:
            seen.add(user_id)
            out.append(user_id)
    return out


def decode_participants(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    return [str(x) for x in data if x]


def encode_participants(user_ids: list[str]) -> str:
    seen: set[str] = set()
    out: list[str] = []
    for user_id in user_ids:
        if user_id and user_id not in seen:
            seen.add(user_id)
            out.append(user_id)
    return json.dumps(out, ensure_ascii=False)


def sync_requirement_due_event(db: Session, req: Requirement, actor: User | None = None) -> ScheduleEvent | None:
    existing = (
        db.query(ScheduleEvent)
        .filter(ScheduleEvent.requirement_id == req.id, ScheduleEvent.event_type == "requirement_due")
        .first()
    )
    if not req.due_at:
        if existing:
            db.delete(existing)
        return None

    assignments = (
        db.query(RequirementAssignment)
        .filter(RequirementAssignment.requirement_id == req.id)
        .all()
    )
    req.assignments = assignments
    title = f"DDL: {req.title or req.code}"
    creator_id = actor.id if actor else req.submitter_user_id
    if existing:
        existing.title = title
        existing.project_id = req.project_id
        existing.start_at = req.start_at
        existing.end_at = req.due_at
        existing.participant_user_ids_json = encode_participants(participant_ids_for_requirement(req))
        existing.updated_at = datetime.utcnow()
        return existing

    event = ScheduleEvent(
        project_id=req.project_id,
        requirement_id=req.id,
        created_by_user_id=creator_id,
        title=title,
        description=req.summary_md or req.raw_description,
        event_type="requirement_due",
        start_at=req.start_at,
        end_at=req.due_at,
        participant_user_ids_json=encode_participants(participant_ids_for_requirement(req)),
    )
    db.add(event)
    return event
