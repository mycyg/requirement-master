from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from auth import current_user
from db import get_db
from models import Project, Requirement, User
from schemas import RequirementCreateIn, RequirementOut, StatusUpdateIn
from services.activity import log_activity

router = APIRouter(prefix="/api", tags=["requirements"])


def _to_out(r: Requirement, *, submitter_nickname: str, project_slug: str) -> RequirementOut:
    return RequirementOut(
        id=r.id, code=r.code, project_id=r.project_id, project_slug=project_slug,
        submitter_nickname=submitter_nickname,
        title=r.title, raw_description=r.raw_description, summary_md=r.summary_md,
        status=r.status, priority=r.priority,
        start_at=r.start_at, due_at=r.due_at,
        claimed_at=r.claimed_at, done_at=r.done_at,
        delivered_at=r.delivered_at, accepted_at=r.accepted_at,
        sync_state=r.sync_state,
        created_at=r.created_at, updated_at=r.updated_at,
    )


def _enrich(db: Session, r: Requirement) -> RequirementOut:
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
        status="draft",
    )
    db.add(r)
    db.flush()
    log_activity(db, requirement_id=r.id, actor_nickname=user.nickname, action="created", detail={"code": code})
    db.commit()
    db.refresh(r)
    return _enrich(db, r)


@router.get("/requirements", response_model=list[RequirementOut])
def list_requirements(
    project_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    mine: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[RequirementOut]:
    q = db.query(Requirement)
    if project_id:
        q = q.filter(Requirement.project_id == project_id)
    if status_filter:
        q = q.filter(Requirement.status == status_filter)
    if mine:
        q = q.filter(Requirement.submitter_user_id == user.id)
    rows = q.order_by(Requirement.created_at.desc()).limit(500).all()
    return [_enrich(db, r) for r in rows]


@router.get("/requirements/{req_id}", response_model=RequirementOut)
def get_requirement(req_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)) -> RequirementOut:
    r = db.query(Requirement).filter(Requirement.id == req_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="requirement not found")
    return _enrich(db, r)


@router.patch("/requirements/{req_id}/status", response_model=RequirementOut)
def update_status(
    req_id: str,
    payload: StatusUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> RequirementOut:
    r = db.query(Requirement).filter(Requirement.id == req_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="requirement not found")

    old = r.status
    new = payload.status
    if old == new:
        return _enrich(db, r)

    r.status = new
    now = datetime.utcnow()
    if new == "claimed" and not r.claimed_at:
        r.claimed_at = now
    elif new == "delivered" and not r.delivered_at:
        r.delivered_at = now
    elif new == "accepted" and not r.accepted_at:
        r.accepted_at = now
        r.done_at = now

    log_activity(
        db, requirement_id=r.id, actor_nickname=user.nickname,
        action="status_changed", detail={"from": old, "to": new},
    )
    db.commit()
    db.refresh(r)
    return _enrich(db, r)
