from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from auth import current_user
from db import get_db
from models import Project, User
from schemas import ProjectCreateIn, ProjectOut

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _to_out(p: Project) -> ProjectOut:
    return ProjectOut(
        id=p.id, name=p.name, slug=p.slug, description=p.description,
        owner_nickname=p.owner_nickname, archived=p.archived,
        deleted_at=p.deleted_at, deleted_by_nickname=p.deleted_by_nickname,
        created_at=p.created_at,
    )


@router.get("", response_model=list[ProjectOut])
def list_projects(
    state: str = Query(default="active", pattern=r"^(active|archived|deleted|all)$"),
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
) -> list[ProjectOut]:
    q = db.query(Project)
    if state == "active":
        q = q.filter(Project.archived == False, Project.deleted_at.is_(None))  # noqa: E712
    elif state == "archived":
        q = q.filter(Project.archived == True, Project.deleted_at.is_(None))  # noqa: E712
    elif state == "deleted":
        q = q.filter(Project.deleted_at.is_not(None))
    rows = q.order_by(Project.created_at.desc()).all()
    return [_to_out(p) for p in rows]


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ProjectOut:
    if db.query(Project).filter(Project.slug == payload.slug).first():
        raise HTTPException(status_code=409, detail=f"slug already exists: {payload.slug}")
    p = Project(
        name=payload.name, slug=payload.slug,
        description=payload.description, owner_nickname=user.nickname,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return _to_out(p)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)) -> ProjectOut:
    p = db.query(Project).filter(Project.id == project_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="project not found")
    return _to_out(p)


def _require_owner(p: Project, user: User) -> None:
    if p.owner_nickname != user.nickname:
        raise HTTPException(status_code=403, detail="only the project owner can change project state")


def _load_project(db: Session, project_id: str) -> Project:
    p = db.query(Project).filter(Project.id == project_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="project not found")
    return p


@router.post("/{project_id}/archive", response_model=ProjectOut)
def archive_project(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ProjectOut:
    p = _load_project(db, project_id)
    _require_owner(p, user)
    if p.deleted_at:
        raise HTTPException(status_code=400, detail="deleted project cannot be archived")
    p.archived = True
    db.commit()
    db.refresh(p)
    return _to_out(p)


@router.post("/{project_id}/restore", response_model=ProjectOut)
def restore_project(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ProjectOut:
    p = _load_project(db, project_id)
    _require_owner(p, user)
    p.archived = False
    p.deleted_at = None
    p.deleted_by_nickname = None
    db.commit()
    db.refresh(p)
    return _to_out(p)


@router.delete("/{project_id}", response_model=ProjectOut)
def soft_delete_project(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ProjectOut:
    p = _load_project(db, project_id)
    _require_owner(p, user)
    if not p.deleted_at:
        p.deleted_at = datetime.utcnow()
        p.deleted_by_nickname = user.nickname
    db.commit()
    db.refresh(p)
    return _to_out(p)
