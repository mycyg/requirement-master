from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from auth import current_user
from db import get_db
from models import Project, User
from schemas import ProjectCreateIn, ProjectOut

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _to_out(p: Project) -> ProjectOut:
    return ProjectOut(
        id=p.id, name=p.name, slug=p.slug, description=p.description,
        owner_nickname=p.owner_nickname, archived=p.archived, created_at=p.created_at,
    )


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db), _: User = Depends(current_user)) -> list[ProjectOut]:
    rows = db.query(Project).filter(Project.archived == False).order_by(Project.created_at.desc()).all()  # noqa: E712
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
