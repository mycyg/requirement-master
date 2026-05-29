from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from auth import current_user
from db import get_db
from models import Project, User
from schemas import ProjectCreateIn, ProjectOut
# Single source of truth for the background reindex helper. Was duplicated
# across two routers; consolidated so a future change (debounce policy,
# logging, etc.) lands once.
from routers.project_drive import schedule_project_reindex

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
    user: User = Depends(current_user),
) -> list[ProjectOut]:
    from services.permissions import is_admin
    q = db.query(Project)
    if state == "active":
        q = q.filter(Project.archived == False, Project.deleted_at.is_(None))  # noqa: E712
    elif state == "archived":
        q = q.filter(Project.archived == True, Project.deleted_at.is_(None))  # noqa: E712
    elif state == "deleted":
        q = q.filter(Project.deleted_at.is_not(None))
    # Non-admins must not enumerate OTHER people's archived/deleted projects
    # — that leaks ownership records of work someone deliberately removed.
    # They can still see THEIR OWN archived/deleted projects (restore UX).
    # Identity-based filter mirrors `_require_owner`: owner_user_id only.
    # NULL-owner (orphaned) projects are invisible to non-admins — a recycled
    # nickname must not see the previous owner's archived/deleted projects.
    if state in ("archived", "deleted", "all") and not is_admin(user):
        q = q.filter(Project.owner_user_id == user.id)
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
        owner_user_id=user.id,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return _to_out(p)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ProjectOut:
    # Non-admins shouldn't be able to GET soft-deleted projects' metadata
    # by guessing IDs — leaks the existence of deleted projects.
    from services.permissions import is_admin
    q = db.query(Project).filter(Project.id == project_id)
    if not is_admin(user):
        q = q.filter(Project.deleted_at.is_(None))
    p = q.first()
    if not p:
        raise HTTPException(status_code=404, detail="project not found")
    return _to_out(p)


def _require_owner(p: Project, user: User) -> None:
    # Admin override — global admins manage any project so a single person
    # can clean up after teammates who left or mis-named slugs.
    from services.permissions import is_admin  # local import to avoid cycle
    if is_admin(user):
        return
    # Identity-based ownership ONLY. The boot-time migration backfills
    # owner_user_id for every project whose owner is still an active user
    # (matched by nickname). So after startup, a NULL owner_user_id means
    # the original owner is gone (deleted → nickname tombstoned to
    # `_deleted_…`, no longer matchable). We must NOT fall back to a raw
    # nickname compare in that case: a re-registered nickname would
    # silently inherit a stranger's project. Orphaned (NULL-owner) projects
    # are admin-only to manage.
    if p.owner_user_id is None or p.owner_user_id != user.id:
        raise HTTPException(status_code=403, detail="only the project owner can change project state")


def _load_project(db: Session, project_id: str) -> Project:
    p = db.query(Project).filter(Project.id == project_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="project not found")
    return p


@router.post("/{project_id}/archive", response_model=ProjectOut)
def archive_project(
    project_id: str,
    background: BackgroundTasks,
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
    # Reindex in background so archived project's rows drop from knowledge
    # search within seconds rather than waiting for the periodic 5-min cycle.
    schedule_project_reindex(background, project_id)
    return _to_out(p)


@router.post("/{project_id}/restore", response_model=ProjectOut)
def restore_project(
    project_id: str,
    background: BackgroundTasks,
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
    # Reindex to restore the project's rows back into knowledge search.
    schedule_project_reindex(background, project_id)
    return _to_out(p)


@router.delete("/{project_id}", response_model=ProjectOut)
def soft_delete_project(
    project_id: str,
    background: BackgroundTasks,
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
    schedule_project_reindex(background, project_id)
    return _to_out(p)
