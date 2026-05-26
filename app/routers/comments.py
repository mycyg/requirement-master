"""Per-requirement comments + per-requirement activity log readout."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import current_user
from db import get_db
from models import ActivityLog, Comment, Requirement, User
from schemas import ActivityOut, CommentCreateIn, CommentOut
from services.activity import log_activity
from services.permissions import can_view_requirement_record
from services.push_bus import bus

router = APIRouter(prefix="/api", tags=["comments"])


def _require_req(db: Session, req_id: str) -> Requirement:
    r = db.query(Requirement).filter(Requirement.id == req_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="requirement not found")
    return r


@router.get("/requirements/{req_id}/comments", response_model=list[CommentOut])
def list_comments(req_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[CommentOut]:
    req = _require_req(db, req_id)
    if not can_view_requirement_record(req, user):
        raise HTTPException(status_code=403, detail="you cannot view comments for this requirement yet")
    rows = (
        db.query(Comment)
        .filter(Comment.requirement_id == req_id)
        .order_by(Comment.created_at)
        .all()
    )
    return [
        CommentOut(id=c.id, author_nickname=c.author_nickname, body=c.body, created_at=c.created_at)
        for c in rows
    ]


@router.post("/requirements/{req_id}/comments", response_model=CommentOut)
async def create_comment(
    req_id: str,
    payload: CommentCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> CommentOut:
    req = _require_req(db, req_id)
    if not can_view_requirement_record(req, user):
        raise HTTPException(status_code=403, detail="you cannot comment on this requirement yet")
    c = Comment(requirement_id=req_id, author_nickname=user.nickname, body=payload.body.strip())
    db.add(c)
    log_activity(
        db, requirement_id=req_id, actor_nickname=user.nickname,
        action="commented", detail={"comment_id": c.id, "preview": payload.body[:80]},
    )
    db.commit()
    db.refresh(c)

    await bus.publish(f"req:{req_id}", "comment.added", {
        "id": c.id, "author": c.author_nickname, "body": c.body,
    })
    return CommentOut(id=c.id, author_nickname=c.author_nickname, body=c.body, created_at=c.created_at)


@router.get("/requirements/{req_id}/activity", response_model=list[ActivityOut])
def list_activity(req_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[ActivityOut]:
    req = _require_req(db, req_id)
    if not can_view_requirement_record(req, user):
        raise HTTPException(status_code=403, detail="you cannot view activity for this requirement yet")
    rows = (
        db.query(ActivityLog)
        .filter(ActivityLog.requirement_id == req_id)
        .order_by(ActivityLog.created_at.desc())
        .limit(200)
        .all()
    )
    return [
        ActivityOut(
            id=a.id, actor_nickname=a.actor_nickname,
            action=a.action, detail_json=a.detail_json, created_at=a.created_at,
        )
        for a in rows
    ]
