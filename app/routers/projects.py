from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from auth import current_user
from db import SessionLocal, get_db
from models import Project, User
from schemas import ProjectCreateIn, ProjectOut
from services.knowledge import rebuild_knowledge_index

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _reindex_project_in_background(project_id: str) -> None:
    """Mirrors the helper in project_drive.py — owns its own DB session
    because BackgroundTasks runs after the request session is closed."""
    import logging
    db = SessionLocal()
    try:
        rebuild_knowledge_index(db, project_id=project_id)
    except Exception:
        logging.getLogger(__name__).exception("background project reindex failed for %s", project_id)
    finally:
        db.close()


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
    if state in ("archived", "deleted", "all") and not is_admin(user):
        q = q.filter(Project.owner_nickname == user.nickname)
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
    # Identity-based ownership check. Fallback to nickname match ONLY for
    # legacy rows that predate the `owner_user_id` column AND where the
    # nickname still uniquely identifies that user (no soft-deletion has
    # claimed it yet). Otherwise reject — a recycled nickname must not
    # inherit ownership of someone else's project.
    if p.owner_user_id is not None:
        if p.owner_user_id != user.id:
            raise HTTPException(status_code=403, detail="only the project owner can change project state")
        return
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
    background.add_task(_reindex_project_in_background, project_id)
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
    background.add_task(_reindex_project_in_background, project_id)
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
    background.add_task(_reindex_project_in_background, project_id)
    return _to_out(p)
