from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from auth import current_user
from db import get_db
from models import Project, Requirement, ScheduleEvent, User
from schemas import ScheduleEventCreateIn, ScheduleEventOut, ScheduleEventPatchIn
from services.schedule import decode_participants, encode_participants

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


def _event_out(event: ScheduleEvent) -> ScheduleEventOut:
    return ScheduleEventOut(
        id=event.id,
        project_id=event.project_id,
        requirement_id=event.requirement_id,
        title=event.title,
        description=event.description,
        event_type=event.event_type,
        start_at=event.start_at,
        end_at=event.end_at,
        participant_user_ids=decode_participants(event.participant_user_ids_json),
        created_by_nickname=event.created_by.nickname if event.created_by else "unknown",
        created_at=event.created_at,
        updated_at=event.updated_at,
    )


def _require_event(db: Session, event_id: str) -> ScheduleEvent:
    event = db.query(ScheduleEvent).filter(ScheduleEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="calendar event not found")
    return event


def _validate_links(db: Session, project_id: str | None, requirement_id: str | None) -> None:
    if project_id and not db.query(Project.id).filter(Project.id == project_id).first():
        raise HTTPException(status_code=404, detail="project not found")
    if requirement_id and not db.query(Requirement.id).filter(Requirement.id == requirement_id).first():
        raise HTTPException(status_code=404, detail="requirement not found")


@router.get("/events", response_model=list[ScheduleEventOut])
def list_events(
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    project_id: str | None = Query(default=None),
    mine: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[ScheduleEventOut]:
    q = db.query(ScheduleEvent)
    if project_id:
        q = q.filter(ScheduleEvent.project_id == project_id)
    if start:
        q = q.filter(ScheduleEvent.end_at >= start)
    if end:
        q = q.filter(ScheduleEvent.start_at.is_(None) | (ScheduleEvent.start_at <= end))
        q = q.filter(ScheduleEvent.end_at <= end)
    rows = q.order_by(ScheduleEvent.end_at.asc()).limit(500).all()
    if mine:
        rows = [
            ev for ev in rows
            if ev.created_by_user_id == user.id or user.id in decode_participants(ev.participant_user_ids_json)
        ]
    return [_event_out(ev) for ev in rows]


@router.post("/events", response_model=ScheduleEventOut, status_code=201)
def create_event(
    payload: ScheduleEventCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ScheduleEventOut:
    _validate_links(db, payload.project_id, payload.requirement_id)
    participants = payload.participant_user_ids or [user.id]
    event = ScheduleEvent(
        project_id=payload.project_id,
        requirement_id=payload.requirement_id,
        created_by_user_id=user.id,
        title=payload.title.strip(),
        description=payload.description,
        event_type=payload.event_type,
        start_at=payload.start_at,
        end_at=payload.end_at,
        participant_user_ids_json=encode_participants(participants),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return _event_out(event)


@router.patch("/events/{event_id}", response_model=ScheduleEventOut)
def patch_event(
    event_id: str,
    payload: ScheduleEventPatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ScheduleEventOut:
    event = _require_event(db, event_id)
    if event.created_by_user_id != user.id:
        raise HTTPException(status_code=403, detail="only the creator can edit this event")
    project_id = payload.project_id if "project_id" in payload.model_fields_set else event.project_id
    requirement_id = payload.requirement_id if "requirement_id" in payload.model_fields_set else event.requirement_id
    _validate_links(db, project_id, requirement_id)
    if payload.title is not None:
        event.title = payload.title.strip()
    if "description" in payload.model_fields_set:
        event.description = payload.description
    if "project_id" in payload.model_fields_set:
        event.project_id = payload.project_id
    if "requirement_id" in payload.model_fields_set:
        event.requirement_id = payload.requirement_id
    if "start_at" in payload.model_fields_set:
        event.start_at = payload.start_at
    if payload.end_at is not None:
        event.end_at = payload.end_at
    if payload.participant_user_ids is not None:
        event.participant_user_ids_json = encode_participants(payload.participant_user_ids)
    db.commit()
    db.refresh(event)
    return _event_out(event)


@router.delete("/events/{event_id}")
def delete_event(
    event_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    event = _require_event(db, event_id)
    if event.created_by_user_id != user.id:
        raise HTTPException(status_code=403, detail="only the creator can delete this event")
    if event.event_type == "requirement_due":
        raise HTTPException(status_code=400, detail="requirement DDL events are managed by the requirement")
    db.delete(event)
    db.commit()
    return {"ok": True}
