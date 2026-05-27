"""Project-level drive: folders, versioned files, preview, and soft-delete."""
from __future__ import annotations

import hashlib
import json
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
from db import get_db
from models import Project, ProjectDriveItem, ProjectDriveOperation, ProjectDriveVersion, User
from schemas import (
    DriveBreadcrumbOut,
    DriveBulkIn,
    DriveChunkInitIn,
    DriveChunkInitOut,
    DriveFolderCreateIn,
    DriveItemOut,
    DriveItemPatchIn,
    DriveListOut,
    DriveOperationOut,
    DrivePasteIn,
    DrivePreviewOut,
    DriveTreeNodeOut,
)
from services.file_parser import is_parseable, parse_file

router = APIRouter(prefix="/api", tags=["project-drive"])

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
    project = db.query(Project).filter(Project.id == project_id, Project.archived == False).first()  # noqa: E712
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
    return item


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
    while cursor:
        if cursor.id == item.id:
            raise HTTPException(status_code=400, detail="cannot move a folder into its descendant")
        cursor = _require_item(db, cursor.parent_id) if cursor.parent_id else None


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


def _copy_item(db: Session, source: ProjectDriveItem, target_parent_id: str | None, actor: User) -> ProjectDriveItem:
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
            _copy_item(db, child, copied.id, actor)
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
    return _item_out(db, item)


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
    if inline:
        return FileResponse(path, media_type=version.mime or "application/octet-stream")
    return FileResponse(path, filename=item.name, media_type=version.mime or "application/octet-stream")


@router.post("/drive/bulk-download")
def bulk_download_drive(
    payload: DriveBulkIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    items = [_require_item(db, item_id) for item_id in payload.item_ids]
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
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> DriveItemOut:
    item = _require_item(db, item_id)
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
    return _item_out(db, item)


@router.post("/projects/{project_id}/drive/paste", response_model=DriveOperationOut)
def paste_drive_items(
    project_id: str,
    payload: DrivePasteIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> DriveOperationOut:
    _require_project(db, project_id)
    _require_folder(db, project_id, payload.target_parent_id)
    items = [_require_item(db, item_id) for item_id in payload.item_ids]
    if any(item.project_id != project_id for item in items):
        raise HTTPException(status_code=400, detail="all items must belong to this project")
    if payload.mode == "copy":
        copied = [_copy_item(db, item, payload.target_parent_id, user) for item in items]
        op = _record_op(db, project_id, user, "paste_copy", {"item_ids": [i.id for i in copied]})
        db.commit()
        return DriveOperationOut(operation_id=op.id, items=[_item_out(db, i) for i in copied])

    old_parents: dict[str, str | None] = {}
    for item in items:
        if item.kind == "folder":
            _ensure_no_cycle(db, item, payload.target_parent_id)
        item.name = _unique_name(db, project_id, payload.target_parent_id, item.name, exclude_id=item.id)
        old_parents[item.id] = item.parent_id
        item.parent_id = payload.target_parent_id
        item.updated_by_user_id = user.id
        item.updated_at = datetime.utcnow()
    op = _record_op(db, project_id, user, "paste_cut", {"old_parents": old_parents})
    db.commit()
    return DriveOperationOut(operation_id=op.id, items=[_item_out(db, i) for i in items])


@router.post("/drive/items/{item_id}/copy", response_model=DriveOperationOut)
def copy_one_drive_item(
    item_id: str,
    target_parent_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> DriveOperationOut:
    item = _require_item(db, item_id)
    copied = _copy_item(db, item, target_parent_id, user)
    op = _record_op(db, item.project_id, user, "paste_copy", {"item_ids": [copied.id]})
    db.commit()
    return DriveOperationOut(operation_id=op.id, items=[_item_out(db, copied)])


@router.post("/drive/items/{item_id}/cut", response_model=DriveItemOut)
def cut_one_drive_item(
    item_id: str,
    target_parent_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> DriveItemOut:
    item = _require_item(db, item_id)
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
    return _item_out(db, item)


@router.delete("/drive/items/{item_id}", response_model=DriveOperationOut)
def delete_drive_item(item_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> DriveOperationOut:
    item = _require_item(db, item_id)
    _soft_delete_items(db, [item], user)
    op = _record_op(db, item.project_id, user, "delete", {"item_ids": [item.id]})
    db.commit()
    return DriveOperationOut(operation_id=op.id)


@router.post("/drive/bulk-delete", response_model=DriveOperationOut)
def bulk_delete_drive_items(payload: DriveBulkIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> DriveOperationOut:
    items = [_require_item(db, item_id) for item_id in payload.item_ids]
    if not items:
        return DriveOperationOut()
    project_id = items[0].project_id
    if any(item.project_id != project_id for item in items):
        raise HTTPException(status_code=400, detail="all items must belong to the same project")
    _soft_delete_items(db, items, user)
    op = _record_op(db, project_id, user, "delete", {"item_ids": [item.id for item in items]})
    db.commit()
    return DriveOperationOut(operation_id=op.id)


@router.post("/drive/items/{item_id}/restore", response_model=DriveItemOut)
def restore_drive_item(item_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> DriveItemOut:
    item = _require_item(db, item_id, include_deleted=True)
    if _active_sibling(db, item.project_id, item.parent_id, item.name, exclude_id=item.id):
        item.name = _unique_name(db, item.project_id, item.parent_id, item.name, exclude_id=item.id)
    _restore_items(db, [item], user)
    _record_op(db, item.project_id, user, "restore", {"item_ids": [item.id]})
    db.commit()
    db.refresh(item)
    return _item_out(db, item)


@router.post("/projects/{project_id}/drive/undo", response_model=DriveOperationOut)
def undo_drive_operation(project_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> DriveOperationOut:
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
        for item_id, old_parent_id in payload.get("old_parents", {}).items():
            item = _require_item(db, item_id, include_deleted=True)
            item.parent_id = old_parent_id
            item.updated_by_user_id = user.id
    else:
        raise HTTPException(status_code=400, detail=f"operation cannot be undone: {op.op_type}")
    op.undone_at = datetime.utcnow()
    db.commit()
    return DriveOperationOut(operation_id=op.id)
