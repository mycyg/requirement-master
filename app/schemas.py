"""Pydantic IO schemas. Mirrors the SQLAlchemy models but only the fields exposed via API."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------- Project ----------

class ProjectCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9\-_]*$")
    description: Optional[str] = None


class ProjectOut(BaseModel):
    id: str
    name: str
    slug: str
    description: Optional[str]
    owner_nickname: str
    archived: bool
    created_at: datetime


# ---------- Project Drive ----------

class DriveFolderCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    parent_id: Optional[str] = None


class DriveChunkInitIn(BaseModel):
    filename: str = Field(min_length=1, max_length=256)
    total_size: int = Field(ge=1, le=1024 * 1024 * 1024)
    total_chunks: int = Field(ge=1)
    mime: Optional[str] = None
    parent_id: Optional[str] = None
    conflict: str = Field(default="cancel", pattern=r"^(cancel|replace|rename)$")
    existing_item_id: Optional[str] = None


class DriveChunkInitOut(BaseModel):
    upload_id: Optional[str] = None
    chunk_size: int
    conflict: Optional[str] = None
    existing_item: Optional["DriveItemOut"] = None


class DriveItemPatchIn(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=256)
    parent_id: Optional[str] = None


class DriveBulkIn(BaseModel):
    item_ids: list[str] = Field(min_length=1)


class DrivePasteIn(BaseModel):
    item_ids: list[str] = Field(min_length=1)
    target_parent_id: Optional[str] = None
    mode: str = Field(pattern=r"^(copy|cut)$")


class DriveItemOut(BaseModel):
    id: str
    project_id: str
    parent_id: Optional[str]
    name: str
    kind: str
    size_bytes: Optional[int] = None
    mime: Optional[str] = None
    sha256: Optional[str] = None
    version_no: Optional[int] = None
    has_preview: bool = False
    created_by_nickname: Optional[str] = None
    updated_by_nickname: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None


class DriveTreeNodeOut(BaseModel):
    id: str
    name: str
    parent_id: Optional[str]
    children: list["DriveTreeNodeOut"] = Field(default_factory=list)


class DriveBreadcrumbOut(BaseModel):
    id: Optional[str]
    name: str


class DriveListOut(BaseModel):
    project_id: str
    parent_id: Optional[str]
    breadcrumbs: list[DriveBreadcrumbOut]
    items: list[DriveItemOut]


class DrivePreviewOut(BaseModel):
    item_id: str
    name: str
    preview_type: str
    mime: Optional[str] = None
    content: Optional[str] = None
    download_url: str
    render_url: Optional[str] = None
    version_no: Optional[int] = None


class DriveOperationOut(BaseModel):
    ok: bool = True
    operation_id: Optional[str] = None
    items: list[DriveItemOut] = Field(default_factory=list)


# ---------- User ----------

class UserOut(BaseModel):
    id: str
    nickname: str
    is_online: bool = False
    last_seen_at: Optional[datetime] = None


# ---------- Requirement ----------

class RequirementCreateIn(BaseModel):
    raw_description: str = Field(min_length=1)
    priority: str = Field(default="normal", pattern=r"^(low|normal|high|urgent)$")
    lead_user_id: Optional[str] = None
    collaborator_user_ids: list[str] = Field(default_factory=list)


class RequirementAssigneeOut(BaseModel):
    user_id: str
    nickname: str
    role: str
    assigned_at: datetime


class RequirementAssigneesUpdateIn(BaseModel):
    lead_user_id: Optional[str] = None
    collaborator_user_ids: list[str] = Field(default_factory=list)


class RequirementOut(BaseModel):
    id: str
    code: str
    project_id: str
    project_slug: str
    submitter_nickname: str
    claimed_by_user_id: Optional[str]
    claimed_by_nickname: Optional[str]
    title: Optional[str]
    raw_description: Optional[str]
    summary_md: Optional[str]
    status: str
    priority: str
    start_at: Optional[datetime]
    due_at: Optional[datetime]
    claimed_at: Optional[datetime]
    done_at: Optional[datetime]
    delivered_at: Optional[datetime]
    delivery_doc_ready_at: Optional[datetime]
    accepted_at: Optional[datetime]
    sync_state: str
    assignees: list[RequirementAssigneeOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class StatusUpdateIn(BaseModel):
    status: str = Field(pattern=r"^(draft|clarifying|summary_ready|ready|claimed|doing|ai_processing|delivery_doc_pending|delivered|revision_requested|accepted|cancelled)$")


# ---------- Attachment ----------

class AttachmentOut(BaseModel):
    id: str
    filename: str
    mime: Optional[str]
    size_bytes: int
    sha256: Optional[str]
    role_in_req: Optional[str]
    has_parsed_text: bool
    created_at: datetime


class ChunkInitIn(BaseModel):
    filename: str = Field(min_length=1, max_length=256)
    total_size: int = Field(ge=1, le=1024 * 1024 * 1024)  # 1 GB cap
    total_chunks: int = Field(ge=1)
    mime: Optional[str] = None


class ChunkInitOut(BaseModel):
    upload_id: str
    chunk_size: int


# ---------- Comment ----------

class CommentCreateIn(BaseModel):
    body: str = Field(min_length=1)


class CommentOut(BaseModel):
    id: str
    author_nickname: str
    body: str
    created_at: datetime


# ---------- Activity ----------

class ActivityOut(BaseModel):
    id: str
    actor_nickname: str
    action: str
    detail_json: Optional[str]
    created_at: datetime
