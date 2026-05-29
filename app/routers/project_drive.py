"""Project-level drive: folders, versioned files, preview, and soft-delete."""
from __future__ import annotations

import hashlib
import asyncio
import json
import logging
import os
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from auth import current_user
from config import settings
from db import SessionLocal, get_db
from models import Project, ProjectDriveComment, ProjectDriveItem, ProjectDriveOperation, ProjectDriveVersion, Requirement, User
from schemas import (
    DriveBreadcrumbOut,
    DriveBulkIn,
    DriveChunkInitIn,
    DriveChunkInitOut,
    DriveCommentCreateIn,
    DriveCommentOut,
    DriveFolderCreateIn,
    DriveItemOut,
    DriveItemPatchIn,
    DriveListOut,
    DriveManifestItemOut,
    DriveManifestOut,
    DriveOperationOut,
    DrivePasteIn,
    DrivePreviewOut,
    DriveTreeNodeOut,
)
from services.drive_comment_agent import classify_drive_comment
from services.file_parser import is_parseable, parse_file
from services.knowledge import rebuild_knowledge_index
from services.permissions import is_admin
from services.push_bus import bus

router = APIRouter(prefix="/api", tags=["project-drive"])
logger = logging.getLogger(__name__)

CHUNK_SIZE = 5 * 1024 * 1024
MAX_BYTES = 1024 * 1024 * 1024
TEXT_PREVIEW_LIMIT = 500_000
CODE_EXTS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".css", ".scss", ".html", ".htm",
    ".json", ".md", ".txt", ".csv", ".xml", ".yaml", ".yml", ".toml",
    ".ini", ".sql", ".sh", ".ps1", ".bat", ".dockerfile", ".go", ".rs",
    ".java", ".c", ".cpp", ".h", ".hpp", ".cs", ".php", ".rb", ".swift",
}
OFFICE_EXTS = {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx"}


def _require_project(db: Session, project_id: str) -> Project:
    # Soft-deleted projects should not accept reads or writes — otherwise
    # admins can "delete" a project and the drive keeps mutating because
    # the file APIs ignored the tombstone.
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.archived == False,  # noqa: E712
        Project.deleted_at.is_(None),
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    return project


def _require_item(db: Session, item_id: str, *, include_deleted: bool = False) -> ProjectDriveItem:
    q = db.query(ProjectDriveItem).filter(ProjectDriveItem.id == item_id)
    if not include_deleted:
        q = q.filter(ProjectDriveItem.deleted_at.is_(None))
    item = q.first()
    if not item:
        raise HTTPException(status_code=404, detail="drive item not found")
    _require_project(db, item.project_id)
    return item


def _can_manage_project(project: Project, user: User) -> bool:
    # Identity-based ownership — mirrors projects.py::_require_owner.
    # A NULL owner_user_id (orphaned project whose owner was deleted) is
    # admin-only: falling back to a raw nickname compare would let a
    # re-registered nickname inherit drive management rights over a
    # tombstoned user's project. The boot migration already backfilled
    # owner_user_id for every still-active owner.
    if is_admin(user):
        return True
    return project.owner_user_id is not None and project.owner_user_id == user.id


def _require_manage_item(db: Session, item: ProjectDriveItem, user: User) -> None:
    project = _require_project(db, item.project_id)
    if _can_manage_project(project, user) or item.created_by_user_id == user.id or item.deleted_by_user_id == user.id:
        return
    raise HTTPException(status_code=403, detail="only the project owner, admins, or the file owner can change this drive item")


def _require_folder(db: Session, project_id: str, folder_id: str | None) -> ProjectDriveItem | None:
    if not folder_id:
        return None
    folder = _require_item(db, folder_id)
    if folder.project_id != project_id or folder.kind != "folder":
        raise HTTPException(status_code=400, detail="parent_id must be a folder in this project")
    return folder


def _current_version(db: Session, item: ProjectDriveItem) -> ProjectDriveVersion | None:
    if item.kind != "file" or not item.current_version_id:
        return None
    return db.query(ProjectDriveVersion).filter(ProjectDriveVersion.id == item.current_version_id).first()


def _has_preview(item: ProjectDriveItem, version: ProjectDriveVersion | None) -> bool:
    if item.kind != "file" or not version:
        return False
    ext = Path(item.name).suffix.lower()
    if ext == ".pdf" or ext in CODE_EXTS or ext in OFFICE_EXTS:
        return True
    return bool(version.mime and version.mime.startswith("text/"))


def _item_out(db: Session, item: ProjectDriveItem) -> DriveItemOut:
    version = _current_version(db, item)
    return DriveItemOut(
        id=item.id,
        project_id=item.project_id,
        parent_id=item.parent_id,
        name=item.name,
        kind=item.kind,
        size_bytes=version.size_bytes if version else None,
        mime=version.mime if version else None,
        sha256=version.sha256 if version else None,
        version_no=version.version_no if version else None,
        has_preview=_has_preview(item, version),
        created_by_nickname=item.created_by.nickname if item.created_by else None,
        updated_by_nickname=item.updated_by.nickname if item.updated_by else None,
        created_at=item.created_at,
        updated_at=item.updated_at,
        deleted_at=item.deleted_at,
    )


def _comment_out(comment: ProjectDriveComment) -> DriveCommentOut:
    return DriveCommentOut(
        id=comment.id,
        project_id=comment.project_id,
        folder_id=comment.folder_id,
        author_nickname=comment.author_nickname,
        body=comment.body,
        status=comment.status,
        llm_kind=comment.llm_kind,
        llm_reason=comment.llm_reason,
        draft_requirement_id=comment.draft_requirement_id,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
    )


def _folder_path(db: Session, project_id: str, folder_id: str | None) -> str:
    if not folder_id:
        return "项目网盘根目录"
    names: list[str] = []
    cursor = _require_folder(db, project_id, folder_id)
    while cursor:
        names.append(cursor.name)
        cursor = _require_item(db, cursor.parent_id) if cursor.parent_id else None
    return "/".join(reversed(names))


def _item_path(db: Session, item: ProjectDriveItem) -> str:
    names = [item.name]
    cursor = _require_item(db, item.parent_id, include_deleted=True) if item.parent_id else None
    while cursor:
        names.append(cursor.name)
        cursor = _require_item(db, cursor.parent_id, include_deleted=True) if cursor.parent_id else None
    return "/".join(reversed(names))


def _item_path_from_map(item: ProjectDriveItem, item_map: dict[str, ProjectDriveItem]) -> str:
    """Same as _item_path but walks an in-memory {id: item} map instead of
    issuing one query per ancestor. Used by the manifest/changes endpoints
    which the desktop client polls every 45s per project — the per-hop DB
    walk was the dominant cost (≈D queries × N items). Guards against a
    cyclic parent chain (shouldn't happen, but a corrupted row must not
    spin forever)."""
    names = [item.name]
    seen = {item.id}
    parent_id = item.parent_id
    while parent_id and parent_id in item_map and parent_id not in seen:
        seen.add(parent_id)
        parent = item_map[parent_id]
        names.append(parent.name)
        parent_id = parent.parent_id
    return "/".join(reversed(names))


def _drive_manifest_item(
    db: Session,
    item: ProjectDriveItem,
    *,
    item_map: dict[str, ProjectDriveItem] | None = None,
    version_map: dict[str, ProjectDriveVersion] | None = None,
) -> DriveManifestItemOut:
    # Fast path: callers that pre-build the maps (manifest/changes) avoid the
    # per-item version query and the per-ancestor path query. Fall back to the
    # query-per-call path only when maps aren't supplied.
    if version_map is not None:
        version = version_map.get(item.current_version_id) if item.current_version_id else None
    else:
        version = _current_version(db, item)
    path = _item_path_from_map(item, item_map) if item_map is not None else _item_path(db, item)
    return DriveManifestItemOut(
        id=item.id,
        parent_id=item.parent_id,
        path=path,
        name=item.name,
        kind=item.kind,
        size_bytes=version.size_bytes if version else None,
        mime=version.mime if version else None,
        sha256=version.sha256 if version else None,
        version_no=version.version_no if version else None,
        updated_at=item.updated_at,
        deleted_at=item.deleted_at,
        download_url=f"/api/drive/files/{item.id}/download" if item.kind == "file" and not item.deleted_at else None,
    )


# Generous safety ceiling for a single project's drive. Not a silent LIMIT —
# we log if a project ever exceeds it (which would mean the manifest is
# incomplete and sync would miss files), so it surfaces rather than rotting.
_MANIFEST_MAX_ITEMS = 50000


def _build_manifest_maps(
    db: Session, project_id: str, rows: list[ProjectDriveItem]
) -> tuple[dict[str, ProjectDriveItem], dict[str, ProjectDriveVersion]]:
    """Build {id: item} (for path-walking, ALL project items incl. ancestors of
    changed rows) + {version_id: version} (only the versions the rows reference)
    in two queries total, replacing the old ≈(D+1)×N per-row queries."""
    item_map = {
        i.id: i
        for i in db.query(ProjectDriveItem).filter(ProjectDriveItem.project_id == project_id).all()
    }
    version_ids = [r.current_version_id for r in rows if r.current_version_id]
    version_map: dict[str, ProjectDriveVersion] = {}
    if version_ids:
        version_map = {
            v.id: v
            for v in db.query(ProjectDriveVersion).filter(ProjectDriveVersion.id.in_(version_ids)).all()
        }
    return item_map, version_map


def _publish_drive_changed(project_id: str, item_ids: list[str] | None = None) -> None:
    data = {"project_id": project_id, "item_ids": item_ids or [], "changed_at": datetime.utcnow().isoformat()}
    try:
        from anyio import from_thread
        from_thread.run(bus.publish, "all", "drive.changed", data)
    except Exception:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(bus.publish("all", "drive.changed", data))
        except Exception:
            pass


import threading as _threading

# Per-project debounce — bulk operations (paste 50 items, delete 50 items,
# bulk drive ops) call schedule_project_reindex once per item, but only ONE
# reindex per project per burst is useful. The first one to land sets the
# in_progress flag; subsequent schedules within the same window become
# no-ops. After the reindex completes, if any schedule came in during it
# the worker re-runs once more and clears the flag.
_reindex_lock = _threading.Lock()
_reindex_state: dict[str, dict[str, bool]] = {}  # project_id -> {"running": bool, "dirty": bool}


def _reindex_project_in_background(project_id: str) -> None:
    """Owns its own DB session (request session already closed by the time
    BackgroundTasks runs). Coalesces with concurrent schedules via
    `_reindex_state` so a burst of writes triggers at most 2 reindexes
    (one immediate, one trailing if more dirties arrived mid-run).

    The worker itself owns the `running` flag — schedule_project_reindex
    only sets `dirty`. This way a request that crashes between scheduling
    and response (BackgroundTasks gets cancelled) doesn't leak a sticky
    `running=True` that blocks all future schedules.
    """
    # Acquire run-slot. If another worker is already in flight we mark
    # ourselves dirty and exit; the in-flight worker will re-loop.
    with _reindex_lock:
        state = _reindex_state.setdefault(project_id, {"running": False, "dirty": False})
        if state["running"]:
            state["dirty"] = True
            return
        state["running"] = True
    try:
        while True:
            db = SessionLocal()
            try:
                rebuild_knowledge_index(db, project_id=project_id)
            except Exception:
                logger.exception("background project reindex failed for %s", project_id)
            finally:
                db.close()
            with _reindex_lock:
                state = _reindex_state.get(project_id)
                if state is None or not state.get("dirty"):
                    return
                state["dirty"] = False  # consume and re-loop
    finally:
        with _reindex_lock:
            state = _reindex_state.get(project_id)
            if state is not None:
                state["running"] = False


def schedule_project_reindex(background: BackgroundTasks, project_id: str) -> None:
    """Async reindex after the response is sent. Doesn't block the user's
    request (the old `_refresh_project_knowledge` sync call stalled drive
    renames for 10s on large projects), but freshens the search index
    within seconds instead of waiting 5 minutes for the periodic task.

    Bulk-safe: 50 calls in a row from one request (e.g. paste-copy 50
    items) translate to at most 2 reindex runs via `_reindex_state`."""
    background.add_task(_reindex_project_in_background, project_id)


def _active_sibling(
    db: Session,
    project_id: str,
    parent_id: str | None,
    name: str,
    *,
    exclude_id: str | None = None,
) -> ProjectDriveItem | None:
    q = db.query(ProjectDriveItem).filter(
        ProjectDriveItem.project_id == project_id,
        ProjectDriveItem.parent_id.is_(parent_id) if parent_id is None else ProjectDriveItem.parent_id == parent_id,
        ProjectDriveItem.name == name,
        ProjectDriveItem.deleted_at.is_(None),
    )
    if exclude_id:
        q = q.filter(ProjectDriveItem.id != exclude_id)
    return q.first()


def _unique_name(db: Session, project_id: str, parent_id: str | None, desired: str, *, exclude_id: str | None = None) -> str:
    base = Path(desired).stem if Path(desired).suffix else desired
    suffix = Path(desired).suffix
    candidate = desired
    n = 2
    while _active_sibling(db, project_id, parent_id, candidate, exclude_id=exclude_id):
        candidate = f"{base} ({n}){suffix}"
        n += 1
    return candidate


def _safe_filename(name: str) -> str:
    clean = Path(name or "upload.bin").name.strip()
    return clean or "upload.bin"


def _partial_dir(upload_id: str) -> Path:
    return settings.data_dir / "project_drive" / "_partial" / upload_id


def _meta_path(upload_id: str) -> Path:
    return _partial_dir(upload_id) / "_meta.json"


def _expected_chunks(total_size: int) -> int:
    return max(1, (total_size + CHUNK_SIZE - 1) // CHUNK_SIZE)


def _expected_chunk_size(meta: dict[str, Any], idx: int) -> int:
    if idx < meta["total_chunks"] - 1:
        return CHUNK_SIZE
    return meta["total_size"] - (CHUNK_SIZE * (meta["total_chunks"] - 1))


def _drive_file_path(project_id: str, item_id: str, version_id: str, filename: str) -> Path:
    folder = settings.data_dir / "project_drive" / project_id / item_id
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{version_id}-{_safe_filename(filename)}"


def _full_text_path(project_id: str, item_id: str, version_id: str) -> Path:
    folder = settings.data_dir / "outputs" / "project_drive" / project_id / item_id
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{version_id}.txt"


def _record_op(db: Session, project_id: str, actor: User, op_type: str, payload: dict[str, Any]) -> ProjectDriveOperation:
    op = ProjectDriveOperation(
        project_id=project_id,
        actor_user_id=actor.id,
        op_type=op_type,
        payload_json=json.dumps(payload, ensure_ascii=False),
    )
    db.add(op)
    db.flush()
    return op


def _children(db: Session, item_id: str, *, include_deleted: bool = False) -> list[ProjectDriveItem]:
    q = db.query(ProjectDriveItem).filter(ProjectDriveItem.parent_id == item_id)
    if not include_deleted:
        q = q.filter(ProjectDriveItem.deleted_at.is_(None))
    return q.all()


def _descendants(db: Session, roots: list[ProjectDriveItem], *, include_deleted: bool = False) -> list[ProjectDriveItem]:
    out: list[ProjectDriveItem] = []
    stack = list(roots)
    while stack:
        item = stack.pop()
        out.append(item)
        stack.extend(_children(db, item.id, include_deleted=include_deleted))
    return out


def _ensure_no_cycle(db: Session, item: ProjectDriveItem, target_parent_id: str | None) -> None:
    if not target_parent_id:
        return
    if item.id == target_parent_id:
        raise HTTPException(status_code=400, detail="cannot move a folder into itself")
    cursor = _require_folder(db, item.project_id, target_parent_id)
    # Include soft-deleted ancestors so a target whose chain runs through
    # a tombstoned folder can't form a cycle that becomes real after
    # restore. Also cap depth at 100 — if data is corrupt and parent_id
    # forms a cycle (no DB constraint prevents it for legacy rows), we
    # bail rather than loop forever.
    for _ in range(100):
        if cursor is None:
            return
        if cursor.id == item.id:
            raise HTTPException(status_code=400, detail="cannot move a folder into its descendant")
        cursor = _require_item(db, cursor.parent_id, include_deleted=True) if cursor.parent_id else None
    raise HTTPException(status_code=400, detail="folder chain too deep (>100); refusing to move")


def _breadcrumbs(db: Session, project_id: str, parent_id: str | None) -> list[DriveBreadcrumbOut]:
    path: list[DriveBreadcrumbOut] = [DriveBreadcrumbOut(id=None, name="项目网盘")]
    chain: list[ProjectDriveItem] = []
    cursor = _require_folder(db, project_id, parent_id) if parent_id else None
    while cursor:
        chain.append(cursor)
        cursor = _require_item(db, cursor.parent_id) if cursor.parent_id else None
    for item in reversed(chain):
        path.append(DriveBreadcrumbOut(id=item.id, name=item.name))
    return path


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")[:TEXT_PREVIEW_LIMIT]


def _restore_items(db: Session, items: list[ProjectDriveItem], actor: User) -> None:
    now = datetime.utcnow()
    for item in _descendants(db, items, include_deleted=True):
        item.deleted_at = None
        item.deleted_by_user_id = None
        item.updated_by_user_id = actor.id
        item.updated_at = now


def _soft_delete_items(db: Session, items: list[ProjectDriveItem], actor: User) -> None:
    now = datetime.utcnow()
    for item in _descendants(db, items, include_deleted=True):
        item.deleted_at = now
        item.deleted_by_user_id = actor.id
        item.updated_by_user_id = actor.id
        item.updated_at = now


_COPY_MAX_DESCENDANTS = 2000
_COPY_MAX_DEPTH = 32


def _copy_item(
    db: Session,
    source: ProjectDriveItem,
    target_parent_id: str | None,
    actor: User,
    *,
    _depth: int = 0,
    _counter: list[int] | None = None,
) -> ProjectDriveItem:
    """Recursively copy a drive item. Caps depth + descendant count to
    prevent a user from triggering an O(N) blocking sync I/O storm on
    the request thread by copying a deeply-nested or large folder.
    """
    if _depth >= _COPY_MAX_DEPTH:
        raise HTTPException(status_code=400, detail=f"folder nesting exceeds {_COPY_MAX_DEPTH}; copy refused")
    if _counter is None:
        _counter = [0]
    _counter[0] += 1
    if _counter[0] > _COPY_MAX_DESCENDANTS:
        raise HTTPException(
            status_code=413,
            detail=f"copy exceeds {_COPY_MAX_DESCENDANTS} descendants; split into smaller batches",
        )
    _require_folder(db, source.project_id, target_parent_id)
    copied = ProjectDriveItem(
        project_id=source.project_id,
        parent_id=target_parent_id,
        name=_unique_name(db, source.project_id, target_parent_id, source.name),
        kind=source.kind,
        created_by_user_id=actor.id,
        updated_by_user_id=actor.id,
    )
    db.add(copied)
    db.flush()
    if source.kind == "file":
        source_version = _current_version(db, source)
        if source_version:
            version = ProjectDriveVersion(
                item_id=copied.id,
                version_no=1,
                filename=copied.name,
                mime=source_version.mime,
                size_bytes=source_version.size_bytes,
                storage_path="",
                sha256=source_version.sha256,
                parsed_text=source_version.parsed_text,
                created_by_user_id=actor.id,
            )
            db.add(version)
            db.flush()
            src = Path(source_version.storage_path)
            dest = _drive_file_path(copied.project_id, copied.id, version.id, copied.name)
            if src.exists():
                shutil.copy2(src, dest)
            version.storage_path = str(dest)
            if source_version.parsed_text_path and Path(source_version.parsed_text_path).exists():
                text_dest = _full_text_path(copied.project_id, copied.id, version.id)
                shutil.copy2(source_version.parsed_text_path, text_dest)
                version.parsed_text_path = str(text_dest)
            copied.current_version_id = version.id
    else:
        for child in _children(db, source.id):
            _copy_item(db, child, copied.id, actor, _depth=_depth + 1, _counter=_counter)
    return copied


@router.get("/projects/{project_id}/drive", response_model=DriveListOut)
def list_drive(
    project_id: str,
    parent_id: str | None = Query(default=None),
    search: str = Query(default="", max_length=128),
    trash: bool = Query(default=False),
    sort: str = Query(default="name", pattern=r"^(name|updated_at|size|kind)$"),
    direction: str = Query(default="asc", pattern=r"^(asc|desc)$"),
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
) -> DriveListOut:
    _require_project(db, project_id)
    if not trash:
        _require_folder(db, project_id, parent_id)
    q = db.query(ProjectDriveItem).filter(ProjectDriveItem.project_id == project_id)
    if trash:
        q = q.filter(ProjectDriveItem.deleted_at.is_not(None))
    else:
        q = q.filter(
            ProjectDriveItem.deleted_at.is_(None),
            ProjectDriveItem.parent_id.is_(parent_id) if parent_id is None else ProjectDriveItem.parent_id == parent_id,
        )
    term = search.strip()
    if term:
        q = q.filter(ProjectDriveItem.name.ilike(f"%{term}%"))
    rows = q.all()
    rows.sort(key=lambda i: (i.kind != "folder", i.name.casefold()))
    if sort == "updated_at":
        rows.sort(key=lambda i: i.updated_at, reverse=direction == "desc")
    elif sort == "kind":
        rows.sort(key=lambda i: (i.kind, i.name.casefold()), reverse=direction == "desc")
    elif sort == "size":
        rows.sort(key=lambda i: (_current_version(db, i).size_bytes if _current_version(db, i) else -1), reverse=direction == "desc")
    elif direction == "desc":
        rows.reverse()
    return DriveListOut(
        project_id=project_id,
        parent_id=parent_id,
        breadcrumbs=[] if trash else _breadcrumbs(db, project_id, parent_id),
        items=[_item_out(db, item) for item in rows],
    )


@router.get("/projects/{project_id}/drive/tree", response_model=list[DriveTreeNodeOut])
def drive_tree(project_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)) -> list[DriveTreeNodeOut]:
    _require_project(db, project_id)
    folders = (
        db.query(ProjectDriveItem)
        .filter(
            ProjectDriveItem.project_id == project_id,
            ProjectDriveItem.kind == "folder",
            ProjectDriveItem.deleted_at.is_(None),
        )
        .order_by(ProjectDriveItem.name)
        .all()
    )
    nodes = {f.id: DriveTreeNodeOut(id=f.id, name=f.name, parent_id=f.parent_id, children=[]) for f in folders}
    roots: list[DriveTreeNodeOut] = []
    for folder in folders:
        node = nodes[folder.id]
        if folder.parent_id and folder.parent_id in nodes:
            nodes[folder.parent_id].children.append(node)
        else:
            roots.append(node)
    return roots


@router.get("/projects/{project_id}/drive/manifest", response_model=DriveManifestOut)
def drive_manifest(project_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)) -> DriveManifestOut:
    project = _require_project(db, project_id)
    rows = (
        db.query(ProjectDriveItem)
        .filter(ProjectDriveItem.project_id == project_id)
        .order_by(ProjectDriveItem.parent_id, ProjectDriveItem.name)
        .all()
    )
    if len(rows) > _MANIFEST_MAX_ITEMS:
        logger.warning(
            "drive manifest for project %s has %d items (> %d cap); "
            "sync clients poll this every 45s — consider the incremental /changes endpoint",
            project_id, len(rows), _MANIFEST_MAX_ITEMS,
        )
    # Two queries (all items + referenced versions), then render in-memory.
    # Previously this was ≈(depth+1)×N queries — the dominant cost of the
    # client's 45s drive-sync poll on large/aged drives.
    item_map, version_map = _build_manifest_maps(db, project_id, rows)
    return DriveManifestOut(
        project_id=project_id,
        project_slug=project.slug,
        cursor=datetime.utcnow(),
        items=[_drive_manifest_item(db, item, item_map=item_map, version_map=version_map) for item in rows],
    )


@router.get("/projects/{project_id}/drive/changes", response_model=DriveManifestOut)
def drive_changes(
    project_id: str,
    since: datetime = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
) -> DriveManifestOut:
    project = _require_project(db, project_id)
    since_naive = since.replace(tzinfo=None) if since.tzinfo else since
    rows = (
        db.query(ProjectDriveItem)
        .filter(
            ProjectDriveItem.project_id == project_id,
            or_(ProjectDriveItem.updated_at > since_naive, ProjectDriveItem.deleted_at > since_naive),
        )
        .order_by(ProjectDriveItem.updated_at.asc())
        .all()
    )
    # Path-walking needs the FULL item tree (a changed row's ancestors may be
    # unchanged and absent from `rows`), so build the maps over all items.
    item_map, version_map = _build_manifest_maps(db, project_id, rows)
    return DriveManifestOut(
        project_id=project_id,
        project_slug=project.slug,
        cursor=datetime.utcnow(),
        items=[_drive_manifest_item(db, item, item_map=item_map, version_map=version_map) for item in rows],
    )


@router.post("/projects/{project_id}/drive/folders", response_model=DriveItemOut)
def create_folder(
    project_id: str,
    payload: DriveFolderCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> DriveItemOut:
    _require_project(db, project_id)
    _require_folder(db, project_id, payload.parent_id)
    name = _safe_filename(payload.name)
    if _active_sibling(db, project_id, payload.parent_id, name):
        raise HTTPException(status_code=409, detail="name already exists in this folder")
    item = ProjectDriveItem(
        project_id=project_id,
        parent_id=payload.parent_id,
        name=name,
        kind="folder",
        created_by_user_id=user.id,
        updated_by_user_id=user.id,
    )
    db.add(item)
    db.flush()
    _record_op(db, project_id, user, "create", {"item_ids": [item.id]})
    db.commit()
    db.refresh(item)
    _publish_drive_changed(project_id, [item.id])
    return _item_out(db, item)


@router.post("/projects/{project_id}/drive/upload/init", response_model=DriveChunkInitOut)
def init_drive_upload(
    project_id: str,
    payload: DriveChunkInitIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> DriveChunkInitOut:
    _require_project(db, project_id)
    _require_folder(db, project_id, payload.parent_id)
    if payload.total_size > MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"file too large (>{MAX_BYTES} bytes)")
    if payload.total_chunks != _expected_chunks(payload.total_size):
        raise HTTPException(status_code=400, detail="total_chunks does not match configured chunk size")

    filename = _safe_filename(payload.filename)
    existing = _active_sibling(db, project_id, payload.parent_id, filename)
    if existing and payload.conflict == "cancel":
        return DriveChunkInitOut(
            upload_id=None,
            chunk_size=CHUNK_SIZE,
            conflict="name_exists",
            existing_item=_item_out(db, existing),
        )
    if existing and payload.conflict == "replace" and existing.kind != "file":
        raise HTTPException(status_code=409, detail="a folder with this name already exists")
    if payload.existing_item_id and existing and payload.existing_item_id != existing.id:
        raise HTTPException(status_code=409, detail="existing_item_id does not match current conflict")

    upload_id = uuid.uuid4().hex
    pdir = _partial_dir(upload_id)
    pdir.mkdir(parents=True, exist_ok=True)
    _meta_path(upload_id).write_text(
        json.dumps({
            "project_id": project_id,
            "parent_id": payload.parent_id,
            "filename": filename,
            "total_size": payload.total_size,
            "total_chunks": payload.total_chunks,
            "mime": payload.mime,
            "user_id": user.id,
            "conflict": payload.conflict,
            "existing_item_id": existing.id if existing else None,
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    return DriveChunkInitOut(upload_id=upload_id, chunk_size=CHUNK_SIZE)


@router.put("/projects/{project_id}/drive/upload/{upload_id}/chunk/{idx}")
async def upload_drive_chunk(project_id: str, upload_id: str, idx: int, request: Request, user: User = Depends(current_user)) -> dict:
    pdir = _partial_dir(upload_id)
    if not pdir.exists():
        raise HTTPException(status_code=404, detail="unknown upload_id")
    meta = json.loads(_meta_path(upload_id).read_text(encoding="utf-8"))
    if meta["project_id"] != project_id:
        raise HTTPException(status_code=400, detail="upload_id does not match project")
    if meta.get("user_id") != user.id:
        raise HTTPException(status_code=403, detail="only the upload owner can send chunks")
    if idx < 0 or idx >= meta["total_chunks"]:
        raise HTTPException(status_code=400, detail="chunk index out of range")

    target = pdir / f"{idx:06d}.bin"
    if target.exists():
        raise HTTPException(status_code=409, detail="chunk already uploaded")

    expected_size = _expected_chunk_size(meta, idx)
    written = 0
    h = hashlib.sha256()
    try:
        with open(target, "wb") as f:
            async for piece in request.stream():
                if written + len(piece) > expected_size:
                    raise HTTPException(status_code=413, detail="chunk too large")
                f.write(piece)
                h.update(piece)
                written += len(piece)
    except HTTPException:
        target.unlink(missing_ok=True)
        raise
    if written != expected_size:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"chunk size mismatch: got {written}, expected {expected_size}")
    return {"idx": idx, "bytes": written, "sha256": h.hexdigest()}


@router.post("/projects/{project_id}/drive/upload/{upload_id}/finalize", response_model=DriveItemOut)
def finalize_drive_upload(
    project_id: str,
    upload_id: str,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> DriveItemOut:
    pdir = _partial_dir(upload_id)
    if not pdir.exists():
        raise HTTPException(status_code=404, detail="unknown upload_id")
    meta = json.loads(_meta_path(upload_id).read_text(encoding="utf-8"))
    if meta["project_id"] != project_id:
        raise HTTPException(status_code=400, detail="upload_id does not match project")
    if meta.get("user_id") != user.id:
        raise HTTPException(status_code=403, detail="only the upload owner can finalize this upload")
    _require_project(db, project_id)
    _require_folder(db, project_id, meta.get("parent_id"))

    chunks = sorted(p for p in pdir.iterdir() if p.suffix == ".bin")
    if len(chunks) != meta["total_chunks"]:
        raise HTTPException(status_code=400, detail=f"missing chunks: have {len(chunks)}, expected {meta['total_chunks']}")
    for idx, chunk in enumerate(chunks):
        if chunk.name != f"{idx:06d}.bin" or chunk.stat().st_size != _expected_chunk_size(meta, idx):
            raise HTTPException(status_code=400, detail="chunk set is incomplete or invalid")

    filename = _safe_filename(meta["filename"])
    parent_id = meta.get("parent_id")
    existing = _active_sibling(db, project_id, parent_id, filename)
    previous_version_id: str | None = None
    op_type = "upload_new"
    if existing and meta["conflict"] == "replace":
        _require_manage_item(db, existing, user)
        item = existing
        previous_version_id = item.current_version_id
        op_type = "replace"
    else:
        item = ProjectDriveItem(
            project_id=project_id,
            parent_id=parent_id,
            name=_unique_name(db, project_id, parent_id, filename) if existing else filename,
            kind="file",
            created_by_user_id=user.id,
            updated_by_user_id=user.id,
        )
        db.add(item)
        db.flush()

    version_no = (db.query(ProjectDriveVersion).filter(ProjectDriveVersion.item_id == item.id).count() or 0) + 1
    version = ProjectDriveVersion(
        item_id=item.id,
        version_no=version_no,
        filename=item.name,
        mime=meta.get("mime"),
        size_bytes=meta["total_size"],
        storage_path="",
        sha256="",
        created_by_user_id=user.id,
    )
    db.add(version)
    db.flush()
    final_path = _drive_file_path(project_id, item.id, version.id, item.name)

    h = hashlib.sha256()
    total = 0
    with open(final_path, "wb") as out:
        for chunk in chunks:
            with open(chunk, "rb") as src:
                while True:
                    buf = src.read(1024 * 1024)
                    if not buf:
                        break
                    out.write(buf)
                    h.update(buf)
                    total += len(buf)
    if total != meta["total_size"]:
        os.unlink(final_path)
        raise HTTPException(status_code=400, detail=f"size mismatch: got {total}, expected {meta['total_size']}")

    version.storage_path = str(final_path)
    version.sha256 = h.hexdigest()
    full = ""
    if is_parseable(item.name, version.mime):
        preview, full = parse_file(final_path)
        version.parsed_text = preview or None
    if full:
        full_path = _full_text_path(project_id, item.id, version.id)
        full_path.write_text(full, encoding="utf-8")
        version.parsed_text_path = str(full_path)

    item.current_version_id = version.id
    item.updated_by_user_id = user.id
    item.updated_at = datetime.utcnow()
    if op_type == "replace":
        _record_op(db, project_id, user, op_type, {
            "item_id": item.id,
            "previous_version_id": previous_version_id,
            "new_version_id": version.id,
        })
    else:
        _record_op(db, project_id, user, op_type, {"item_ids": [item.id]})
    db.commit()
    db.refresh(item)
    shutil.rmtree(pdir, ignore_errors=True)
    _publish_drive_changed(project_id, [item.id])
    schedule_project_reindex(background, project_id)
    return _item_out(db, item)


# Mime types we trust to inline-render without becoming an XSS pivot. Notably
# excludes svg/html/xml: those CAN carry <script> AND the browser will execute
# it in the API origin's security context (same origin as the SPA), giving the
# uploader full takeover of the viewer's session.
_INLINE_SAFE_MIME_PREFIXES = ("image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp",
                              "image/x-icon", "image/vnd.microsoft.icon", "audio/", "video/",
                              "application/pdf", "text/plain")


@router.get("/drive/files/{item_id}/download")
def download_drive_file(
    item_id: str,
    inline: bool = Query(default=False),
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    item = _require_item(db, item_id, include_deleted=False)
    if item.kind != "file":
        raise HTTPException(status_code=400, detail="folders cannot be downloaded directly")
    version = _current_version(db, item)
    if not version:
        raise HTTPException(status_code=404, detail="file has no version")
    path = Path(version.storage_path)
    if not path.exists():
        raise HTTPException(status_code=410, detail="file missing on disk")
    raw_mime = (version.mime or "application/octet-stream").lower()
    # Always send filename so Starlette emits Content-Disposition. Without
    # an explicit Disposition, an SVG/HTML upload would render in-origin
    # and execute its <script> with the viewer's auth cookies. nosniff
    # blocks the browser from "helpfully" reinterpreting a quoted-mime
    # text/plain as text/html.
    disposition = "inline" if inline else "attachment"
    safe_mime = raw_mime if (
        inline and any(raw_mime.startswith(p) for p in _INLINE_SAFE_MIME_PREFIXES)
    ) else (raw_mime if not inline else "application/octet-stream")
    return FileResponse(
        path,
        filename=item.name,
        media_type=safe_mime,
        content_disposition_type=disposition,
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.post("/drive/bulk-download")
def bulk_download_drive(
    payload: DriveBulkIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    items = [_require_item(db, item_id) for item_id in payload.item_ids]
    # Verify the caller actually has access to each item's project. Without
    # this, any authenticated user could craft an item-id list spanning
    # arbitrary projects and zip-download files from projects they were
    # never added to. _require_project (with deleted_at filter) raises 404
    # for projects the caller can't see.
    seen_projects: set[str] = set()
    for it in items:
        if it.project_id in seen_projects:
            continue
        _require_project(db, it.project_id)
        seen_projects.add(it.project_id)
    tmp = tempfile.NamedTemporaryFile(prefix="project-drive-", suffix=".zip", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()
    try:
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as z:
            for root in items:
                base = root.name
                for item in _descendants(db, [root]):
                    rel_parts: list[str] = []
                    cursor: ProjectDriveItem | None = item
                    while cursor and cursor.id != root.parent_id:
                        rel_parts.append(cursor.name)
                        cursor = _require_item(db, cursor.parent_id) if cursor.parent_id else None
                    rel = Path(*reversed(rel_parts)) if rel_parts else Path(base)
                    if item.kind == "folder":
                        z.writestr(str(rel).replace("\\", "/").rstrip("/") + "/", "")
                    else:
                        version = _current_version(db, item)
                        if version and Path(version.storage_path).exists():
                            z.write(version.storage_path, str(rel).replace("\\", "/"))
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    background_tasks.add_task(lambda p: Path(p).unlink(missing_ok=True), str(tmp_path))
    return FileResponse(tmp_path, filename="project-drive.zip", media_type="application/zip")


@router.get("/drive/files/{item_id}/preview", response_model=DrivePreviewOut)
def preview_drive_file(item_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)) -> DrivePreviewOut:
    item = _require_item(db, item_id)
    if item.kind != "file":
        raise HTTPException(status_code=400, detail="folders cannot be previewed")
    version = _current_version(db, item)
    if not version:
        raise HTTPException(status_code=404, detail="file has no version")
    path = Path(version.storage_path)
    ext = Path(item.name).suffix.lower()
    download_url = f"/api/drive/files/{item.id}/download"
    if ext == ".pdf":
        return DrivePreviewOut(
            item_id=item.id, name=item.name, preview_type="pdf", mime=version.mime,
            render_url=f"{download_url}?inline=1", download_url=download_url, version_no=version.version_no,
        )
    if ext in {".html", ".htm"}:
        content = _read_text(path) if path.exists() else version.parsed_text
        return DrivePreviewOut(
            item_id=item.id, name=item.name, preview_type="html", mime=version.mime,
            content=content, render_url=f"{download_url}?inline=1", download_url=download_url, version_no=version.version_no,
        )
    if ext in OFFICE_EXTS:
        content = ""
        if version.parsed_text_path and Path(version.parsed_text_path).exists():
            content = _read_text(Path(version.parsed_text_path))
        else:
            content = version.parsed_text or ""
        return DrivePreviewOut(
            item_id=item.id, name=item.name, preview_type="markdown", mime=version.mime,
            content=content or "这个 Office 文件暂时没有解析出文本，但原文件还活着。",
            download_url=download_url, version_no=version.version_no,
        )
    if ext in CODE_EXTS or (version.mime and version.mime.startswith("text/")):
        content = _read_text(path) if path.exists() else (version.parsed_text or "")
        preview_type = "markdown" if ext == ".md" else "code"
        return DrivePreviewOut(
            item_id=item.id, name=item.name, preview_type=preview_type, mime=version.mime,
            content=content, download_url=download_url, version_no=version.version_no,
        )
    return DrivePreviewOut(
        item_id=item.id, name=item.name, preview_type="unsupported", mime=version.mime,
        content="暂时看不了，但文件还活着。先下载它，别跟它硬刚。",
        download_url=download_url, version_no=version.version_no,
    )


@router.patch("/drive/items/{item_id}", response_model=DriveItemOut)
def patch_drive_item(
    item_id: str,
    payload: DriveItemPatchIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> DriveItemOut:
    item = _require_item(db, item_id)
    _require_manage_item(db, item, user)
    old_name = item.name
    old_parent_id = item.parent_id
    changed: dict[str, Any] = {}
    if payload.name is not None:
        new_name = _safe_filename(payload.name)
        if _active_sibling(db, item.project_id, item.parent_id, new_name, exclude_id=item.id):
            raise HTTPException(status_code=409, detail="name already exists in this folder")
        item.name = new_name
        changed["old_name"] = old_name
    if "parent_id" in payload.model_fields_set:
        target_parent_id = payload.parent_id
        _require_folder(db, item.project_id, target_parent_id)
        if item.kind == "folder":
            _ensure_no_cycle(db, item, target_parent_id)
        if _active_sibling(db, item.project_id, target_parent_id, item.name, exclude_id=item.id):
            raise HTTPException(status_code=409, detail="name already exists in target folder")
        item.parent_id = target_parent_id
        changed["old_parent_id"] = old_parent_id
    if not changed:
        return _item_out(db, item)
    item.updated_by_user_id = user.id
    item.updated_at = datetime.utcnow()
    changed["item_id"] = item.id
    _record_op(db, item.project_id, user, "patch", changed)
    db.commit()
    db.refresh(item)
    _publish_drive_changed(item.project_id, [item.id])
    schedule_project_reindex(background, item.project_id)
    return _item_out(db, item)


@router.post("/projects/{project_id}/drive/paste", response_model=DriveOperationOut)
def paste_drive_items(
    project_id: str,
    payload: DrivePasteIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> DriveOperationOut:
    _require_project(db, project_id)
    _require_folder(db, project_id, payload.target_parent_id)
    items = [_require_item(db, item_id) for item_id in payload.item_ids]
    if any(item.project_id != project_id for item in items):
        raise HTTPException(status_code=400, detail="all items must belong to this project")
    if payload.mode == "copy":
        # Copy still needs the same ownership check as move/delete — without
        # it any LAN user could duplicate any file they didn't author, which
        # is inconsistent with the rest of the drive surface and would let
        # private drafts leak via a second-hand copy.
        for item in items:
            _require_manage_item(db, item, user)
        copied = [_copy_item(db, item, payload.target_parent_id, user) for item in items]
        op = _record_op(db, project_id, user, "paste_copy", {"item_ids": [i.id for i in copied]})
        db.commit()
        _publish_drive_changed(project_id, [i.id for i in copied])
        schedule_project_reindex(background, project_id)
        return DriveOperationOut(operation_id=op.id, items=[_item_out(db, i) for i in copied])

    # Record BOTH old parent AND old name so undo can restore the
    # _unique_name suffix we may have appended. Previously undo only
    # restored parent_id, leaving the user's "report.pdf" stuck as
    # "report.pdf (2)" forever.
    old_state: dict[str, dict[str, str | None]] = {}
    for item in items:
        _require_manage_item(db, item, user)
        if item.kind == "folder":
            _ensure_no_cycle(db, item, payload.target_parent_id)
        old_state[item.id] = {"parent_id": item.parent_id, "name": item.name}
        item.name = _unique_name(db, project_id, payload.target_parent_id, item.name, exclude_id=item.id)
        item.parent_id = payload.target_parent_id
        item.updated_by_user_id = user.id
        item.updated_at = datetime.utcnow()
    # Keep `old_parents` key for backward compat with already-recorded
    # operations in the DB; new ops also carry `old_state` with the
    # name.
    op = _record_op(db, project_id, user, "paste_cut", {
        "old_parents": {k: v["parent_id"] for k, v in old_state.items()},
        "old_state": old_state,
    })
    db.commit()
    _publish_drive_changed(project_id, [i.id for i in items])
    schedule_project_reindex(background, project_id)
    return DriveOperationOut(operation_id=op.id, items=[_item_out(db, i) for i in items])


@router.post("/drive/items/{item_id}/copy", response_model=DriveOperationOut)
def copy_one_drive_item(
    item_id: str,
    background: BackgroundTasks,
    target_parent_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> DriveOperationOut:
    item = _require_item(db, item_id)
    _require_manage_item(db, item, user)
    _require_folder(db, item.project_id, target_parent_id)
    copied = _copy_item(db, item, target_parent_id, user)
    op = _record_op(db, item.project_id, user, "paste_copy", {"item_ids": [copied.id]})
    db.commit()
    _publish_drive_changed(item.project_id, [copied.id])
    schedule_project_reindex(background, item.project_id)
    return DriveOperationOut(operation_id=op.id, items=[_item_out(db, copied)])


@router.post("/drive/items/{item_id}/cut", response_model=DriveItemOut)
def cut_one_drive_item(
    item_id: str,
    background: BackgroundTasks,
    target_parent_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> DriveItemOut:
    item = _require_item(db, item_id)
    _require_manage_item(db, item, user)
    old_parent_id = item.parent_id
    _require_folder(db, item.project_id, target_parent_id)
    if item.kind == "folder":
        _ensure_no_cycle(db, item, target_parent_id)
    item.name = _unique_name(db, item.project_id, target_parent_id, item.name, exclude_id=item.id)
    item.parent_id = target_parent_id
    item.updated_by_user_id = user.id
    item.updated_at = datetime.utcnow()
    _record_op(db, item.project_id, user, "paste_cut", {"old_parents": {item.id: old_parent_id}})
    db.commit()
    db.refresh(item)
    _publish_drive_changed(item.project_id, [item.id])
    schedule_project_reindex(background, item.project_id)
    return _item_out(db, item)


@router.delete("/drive/items/{item_id}", response_model=DriveOperationOut)
def delete_drive_item(item_id: str, background: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(current_user)) -> DriveOperationOut:
    item = _require_item(db, item_id)
    _require_manage_item(db, item, user)
    _soft_delete_items(db, [item], user)
    op = _record_op(db, item.project_id, user, "delete", {"item_ids": [item.id]})
    db.commit()
    _publish_drive_changed(item.project_id, [item.id])
    schedule_project_reindex(background, item.project_id)
    return DriveOperationOut(operation_id=op.id)


@router.post("/drive/bulk-delete", response_model=DriveOperationOut)
def bulk_delete_drive_items(payload: DriveBulkIn, background: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(current_user)) -> DriveOperationOut:
    items = [_require_item(db, item_id) for item_id in payload.item_ids]
    if not items:
        return DriveOperationOut()
    project_id = items[0].project_id
    if any(item.project_id != project_id for item in items):
        raise HTTPException(status_code=400, detail="all items must belong to the same project")
    for item in items:
        _require_manage_item(db, item, user)
    _soft_delete_items(db, items, user)
    op = _record_op(db, project_id, user, "delete", {"item_ids": [item.id for item in items]})
    db.commit()
    _publish_drive_changed(project_id, [item.id for item in items])
    schedule_project_reindex(background, project_id)
    return DriveOperationOut(operation_id=op.id)


@router.post("/drive/items/{item_id}/restore", response_model=DriveItemOut)
def restore_drive_item(item_id: str, background: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(current_user)) -> DriveItemOut:
    item = _require_item(db, item_id, include_deleted=True)
    _require_manage_item(db, item, user)
    if _active_sibling(db, item.project_id, item.parent_id, item.name, exclude_id=item.id):
        item.name = _unique_name(db, item.project_id, item.parent_id, item.name, exclude_id=item.id)
    _restore_items(db, [item], user)
    _record_op(db, item.project_id, user, "restore", {"item_ids": [item.id]})
    db.commit()
    db.refresh(item)
    _publish_drive_changed(item.project_id, [item.id])
    schedule_project_reindex(background, item.project_id)
    return _item_out(db, item)


@router.post("/projects/{project_id}/drive/undo", response_model=DriveOperationOut)
def undo_drive_operation(project_id: str, background: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(current_user)) -> DriveOperationOut:
    op = (
        db.query(ProjectDriveOperation)
        .filter(
            ProjectDriveOperation.project_id == project_id,
            ProjectDriveOperation.actor_user_id == user.id,
            ProjectDriveOperation.undone_at.is_(None),
        )
        .order_by(ProjectDriveOperation.created_at.desc())
        .first()
    )
    if not op:
        raise HTTPException(status_code=404, detail="no operation to undo")
    payload = json.loads(op.payload_json)
    if op.op_type in {"create", "upload_new", "paste_copy"}:
        items = [_require_item(db, item_id, include_deleted=True) for item_id in payload.get("item_ids", [])]
        _soft_delete_items(db, items, user)
    elif op.op_type == "replace":
        item = _require_item(db, payload["item_id"], include_deleted=True)
        item.current_version_id = payload.get("previous_version_id")
        item.updated_by_user_id = user.id
    elif op.op_type == "delete":
        items = [_require_item(db, item_id, include_deleted=True) for item_id in payload.get("item_ids", [])]
        _restore_items(db, items, user)
    elif op.op_type == "restore":
        items = [_require_item(db, item_id, include_deleted=True) for item_id in payload.get("item_ids", [])]
        _soft_delete_items(db, items, user)
    elif op.op_type == "patch":
        item = _require_item(db, payload["item_id"], include_deleted=True)
        if "old_name" in payload:
            item.name = payload["old_name"]
        if "old_parent_id" in payload:
            item.parent_id = payload["old_parent_id"]
        item.updated_by_user_id = user.id
    elif op.op_type == "paste_cut":
        # Newer ops carry `old_state` (parent_id + name) so we can restore
        # any rename that `_unique_name` applied during the cut. Older ops
        # (pre-fix) only have `old_parents` — best-effort restore of
        # parent only.
        old_state = payload.get("old_state") or {}
        for item_id, old_parent_id in payload.get("old_parents", {}).items():
            item = _require_item(db, item_id, include_deleted=True)
            item.parent_id = old_parent_id
            saved = old_state.get(item_id) or {}
            if isinstance(saved, dict) and saved.get("name"):
                item.name = saved["name"]
            item.updated_by_user_id = user.id
    else:
        raise HTTPException(status_code=400, detail=f"operation cannot be undone: {op.op_type}")
    op.undone_at = datetime.utcnow()
    db.commit()
    _publish_drive_changed(project_id, [])
    schedule_project_reindex(background, project_id)
    return DriveOperationOut(operation_id=op.id)


@router.get("/projects/{project_id}/drive/folders/{folder_id}/comments", response_model=list[DriveCommentOut])
def list_drive_comments(
    project_id: str,
    folder_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
) -> list[DriveCommentOut]:
    _require_project(db, project_id)
    folder_db_id = None if folder_id == "root" else folder_id
    _require_folder(db, project_id, folder_db_id)
    q = db.query(ProjectDriveComment).filter(ProjectDriveComment.project_id == project_id)
    q = q.filter(ProjectDriveComment.folder_id.is_(None) if folder_db_id is None else ProjectDriveComment.folder_id == folder_db_id)
    rows = q.order_by(ProjectDriveComment.created_at.desc()).limit(100).all()
    return [_comment_out(row) for row in rows]


@router.post("/projects/{project_id}/drive/folders/{folder_id}/comments", response_model=DriveCommentOut, status_code=201)
async def create_drive_comment(
    project_id: str,
    folder_id: str,
    payload: DriveCommentCreateIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> DriveCommentOut:
    project = _require_project(db, project_id)
    folder_db_id = None if folder_id == "root" else folder_id
    _require_folder(db, project_id, folder_db_id)
    body = payload.body.strip()
    comment = ProjectDriveComment(
        project_id=project_id,
        folder_id=folder_db_id,
        author_user_id=user.id,
        author_nickname=user.nickname,
        body=body,
        status="pending_llm",
    )
    db.add(comment)
    db.flush()
    folder_path = _folder_path(db, project_id, folder_db_id)
    try:
        decision = await classify_drive_comment(project.name, folder_path, body)
    except Exception as exc:
        comment.status = "review_failed"
        comment.llm_kind = "review_failed"
        comment.llm_reason = str(exc)[:1000]
        db.commit()
        db.refresh(comment)
        return _comment_out(comment)

    comment.llm_kind = decision.kind
    comment.llm_reason = decision.reason
    comment_id = comment.id
    if decision.kind == "requirement_change":
        # Phase 1: persist the comment as "posted" NOW, before allocating the
        # draft requirement. The code-allocation below can hit the `code`
        # UNIQUE constraint under concurrency; if that rolled back an
        # un-committed comment, the user's text would be silently lost.
        comment.status = "posted"
        db.commit()
        # Phase 2: allocate the draft requirement with the same 5-try
        # IntegrityError retry the other two next_seq writers use
        # (create_requirement, confirm_meeting_insight). Two concurrent
        # requirement_change comments on one project would otherwise compute
        # the same SLUG-NNN and the loser would 500 (and lose its comment).
        from sqlalchemy.exc import IntegrityError
        last_err: Exception | None = None
        draft_id: str | None = None
        for _ in range(5):
            proj = _require_project(db, project_id)
            proj.next_seq += 1
            code = f"{proj.slug.upper()}-{proj.next_seq:03d}"
            draft = Requirement(
                code=code,
                project_id=proj.id,
                submitter_user_id=user.id,
                title=decision.title,
                raw_description=decision.draft_description or body,
                priority="normal",
                status="draft",
            )
            db.add(draft)
            try:
                db.flush()
                draft_id = draft.id
                break
            except IntegrityError as e:
                db.rollback()
                last_err = e
        # Re-load the comment (rollback in the loop expires ORM state); it was
        # committed in phase 1 so it always exists.
        comment = db.query(ProjectDriveComment).filter(ProjectDriveComment.id == comment_id).first()
        if draft_id is not None:
            comment.status = "draft_created"
            comment.draft_requirement_id = draft_id
            db.commit()
        else:
            # Couldn't allocate a code after retries — leave the comment safely
            # "posted" (never lost) rather than 500-ing. Surfaces in logs.
            logger.warning(
                "create_drive_comment: could not allocate requirement code for project %s: %s",
                project_id, last_err,
            )
    else:
        comment.status = "posted"
        db.commit()
    db.refresh(comment)
    schedule_project_reindex(background, project_id)
    await bus.publish("all", "drive.comment", {
        "project_id": project_id,
        "folder_id": folder_db_id,
        "status": comment.status,
        "draft_requirement_id": comment.draft_requirement_id,
    })
    return _comment_out(comment)
