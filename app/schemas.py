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
    deleted_at: Optional[datetime] = None
    deleted_by_nickname: Optional[str] = None
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


class DriveManifestItemOut(BaseModel):
    id: str
    parent_id: Optional[str]
    path: str
    name: str
    kind: str
    size_bytes: Optional[int] = None
    mime: Optional[str] = None
    sha256: Optional[str] = None
    version_no: Optional[int] = None
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    download_url: Optional[str] = None


class DriveManifestOut(BaseModel):
    project_id: str
    project_slug: str
    cursor: datetime
    items: list[DriveManifestItemOut]


class DriveCommentCreateIn(BaseModel):
    body: str = Field(min_length=1, max_length=10000)


class DriveCommentOut(BaseModel):
    id: str
    project_id: str
    folder_id: Optional[str]
    author_nickname: str
    body: str
    status: str
    llm_kind: Optional[str] = None
    llm_reason: Optional[str] = None
    draft_requirement_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ---------- Background jobs ----------

class BackgroundJobOut(BaseModel):
    id: str
    kind: str
    status: str
    progress_percent: int
    message: Optional[str] = None
    result_ref: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


# ---------- User ----------

class UserOut(BaseModel):
    id: str
    nickname: str
    is_online: bool = False
    last_seen_at: Optional[datetime] = None
    availability_status: str = "free"
    availability_text: Optional[str] = None
    availability_updated_at: Optional[datetime] = None
    is_admin: bool = False


class UserStatusUpdateIn(BaseModel):
    availability_status: str = Field(pattern=r"^(free|busy|custom)$")
    availability_text: Optional[str] = Field(default=None, max_length=128)


class ClientDeviceRegisterIn(BaseModel):
    device_name: str = Field(min_length=1, max_length=128)
    platform: str = Field(default="unknown", max_length=64)


class ClientDeviceOut(BaseModel):
    id: str
    device_name: str
    platform: str
    last_seen_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    created_at: datetime


class ClientDeviceRegisterOut(BaseModel):
    device: ClientDeviceOut
    client_token: str


# ---------- Requirement ----------

class RequirementCreateIn(BaseModel):
    raw_description: str = Field(min_length=1)
    priority: str = Field(default="normal", pattern=r"^(low|normal|high|urgent)$")
    lead_user_id: Optional[str] = None
    collaborator_user_ids: list[str] = Field(default_factory=list)
    start_at: Optional[datetime] = None
    due_at: Optional[datetime] = None
    estimate_hours: Optional[float] = Field(default=None, ge=0, le=10000)
    estimate_confidence: Optional[str] = Field(default=None, pattern=r"^(low|medium|high)$")
    planning_note: Optional[str] = Field(default=None, max_length=5000)


class RequirementAssigneeOut(BaseModel):
    user_id: str
    nickname: str
    role: str
    assigned_at: datetime


class RequirementAssigneesUpdateIn(BaseModel):
    lead_user_id: Optional[str] = None
    collaborator_user_ids: list[str] = Field(default_factory=list)


class RequirementScheduleUpdateIn(BaseModel):
    start_at: Optional[datetime] = None
    due_at: Optional[datetime] = None


class RequirementPlanningUpdateIn(BaseModel):
    estimate_hours: Optional[float] = Field(default=None, ge=0, le=10000)
    estimate_confidence: Optional[str] = Field(default=None, pattern=r"^(low|medium|high)$")
    planning_note: Optional[str] = Field(default=None, max_length=5000)


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
    estimate_hours: Optional[float] = None
    estimate_confidence: Optional[str] = None
    planning_note: Optional[str] = None
    start_at: Optional[datetime]
    due_at: Optional[datetime]
    source_meeting_id: Optional[str] = None
    source_requirement_id: Optional[str] = None
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


# ---------- Requirement workspaces ----------

class WorkspaceItemCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    status: str = Field(default="todo", pattern=r"^(todo|doing|done)$")
    sort_order: int = 0


class WorkspaceItemPatchIn(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=256)
    status: Optional[str] = Field(default=None, pattern=r"^(todo|doing|done)$")
    sort_order: Optional[int] = None


class WorkspaceItemOut(BaseModel):
    id: str
    workspace_id: str
    title: str
    status: str
    sort_order: int
    created_at: datetime
    updated_at: datetime


class ProgressUpdateCreateIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)
    kind: str = Field(default="manual", pattern=r"^(manual|status|item|system)$")


class ProgressUpdateOut(BaseModel):
    id: str
    requirement_id: str
    workspace_id: Optional[str]
    actor_nickname: str
    kind: str
    body: str
    phase: Optional[str]
    progress_percent: Optional[int]
    created_at: datetime


class WorkspacePatchIn(BaseModel):
    phase: Optional[str] = Field(default=None, min_length=1, max_length=64)
    progress_percent: Optional[int] = Field(default=None, ge=0, le=100)
    status_note: Optional[str] = Field(default=None, max_length=5000)
    blocked_reason: Optional[str] = Field(default=None, max_length=5000)


class RequirementWorkspaceOut(BaseModel):
    id: str
    requirement_id: str
    user_id: str
    nickname: str
    phase: str
    progress_percent: int
    status_note: Optional[str]
    blocked_reason: Optional[str]
    items: list[WorkspaceItemOut] = Field(default_factory=list)
    updates: list[ProgressUpdateOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# ---------- Task decomposition / acceptance ----------

class RequirementAcceptanceItemOut(BaseModel):
    id: str
    requirement_id: str
    title: str
    description: Optional[str] = None
    status: str
    sort_order: int
    source_plan_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class TaskDecompositionCreateIn(BaseModel):
    stage: str = Field(default="worker", pattern=r"^(dispatch|worker)$")


class TaskPlanItemOut(BaseModel):
    id: str
    plan_id: str
    title: str
    description: Optional[str] = None
    item_type: str
    suggested_user_id: Optional[str] = None
    suggested_nickname: Optional[str] = None
    estimate_hours: Optional[float] = None
    sort_order: int
    created_at: datetime
    updated_at: datetime


class TaskPlanOut(BaseModel):
    id: str
    requirement_id: str
    stage: str
    status: str
    summary: Optional[str] = None
    risks: Optional[str] = None
    job_id: Optional[str] = None
    created_by_nickname: str
    target_user_id: Optional[str] = None
    target_nickname: Optional[str] = None
    confirmed_at: Optional[datetime] = None
    items: list[TaskPlanItemOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class TaskPlanConfirmOut(BaseModel):
    plan: TaskPlanOut
    acceptance_items: list[RequirementAcceptanceItemOut] = Field(default_factory=list)
    workspace_items: list[WorkspaceItemOut] = Field(default_factory=list)


# ---------- Knowledge search ----------

class KnowledgeSearchHit(BaseModel):
    document_id: str
    project_id: Optional[str] = None
    requirement_id: Optional[str] = None
    source_type: str
    source_id: str
    title: str
    source_url: str
    line_no: int
    snippet: str


class KnowledgeSearchOut(BaseModel):
    query: str
    hits: list[KnowledgeSearchHit] = Field(default_factory=list)


class KnowledgeAskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    project_id: Optional[str] = None


class KnowledgeAskCreateOut(BaseModel):
    id: str
    job_id: str
    status: str


class KnowledgeAskRunOut(BaseModel):
    id: str
    question: str
    project_id: Optional[str]
    status: str
    job_id: Optional[str]
    answer_md: Optional[str]
    citations: list[KnowledgeSearchHit] = Field(default_factory=list)
    trace: list[dict] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# ---------- Planning / notifications / health ----------

class WorkloadRequirementOut(BaseModel):
    id: str
    code: str
    title: Optional[str]
    project_id: str
    project_slug: str
    status: str
    due_at: Optional[datetime]
    estimate_hours: Optional[float]
    progress_percent: Optional[int] = None
    blocked_reason: Optional[str] = None


class UserWorkloadOut(BaseModel):
    user_id: str
    nickname: str
    is_online: bool = False
    availability_status: str = "free"
    availability_text: Optional[str] = None
    task_count: int
    estimate_hours: float
    capacity_hours: float
    load_percent: int
    overdue_count: int
    blocked_count: int
    due_this_week_count: int
    requirements: list[WorkloadRequirementOut] = Field(default_factory=list)


class NotificationOut(BaseModel):
    id: str
    type: str
    severity: str
    title: str
    body: Optional[str]
    target_url: Optional[str]
    project_id: Optional[str]
    requirement_id: Optional[str]
    read_at: Optional[datetime]
    archived_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class ProjectHealthOut(BaseModel):
    project_id: str
    project_name: str
    project_slug: str
    score: int
    risk_level: str
    risks: list[str] = Field(default_factory=list)
    overdue_count: int
    blocked_count: int
    unclaimed_count: int
    due_soon_count: int
    revision_count: int
    change_count: int
    active_count: int
    accepted_count: int
    throughput_30d: int
    avg_cycle_hours: Optional[float] = None
    load_hours: float


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


# ---------- Calendar ----------

class ScheduleEventCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    description: Optional[str] = None
    project_id: Optional[str] = None
    requirement_id: Optional[str] = None
    event_type: str = Field(default="custom", pattern=r"^(custom|requirement_due)$")
    start_at: Optional[datetime] = None
    end_at: datetime
    participant_user_ids: list[str] = Field(default_factory=list)


class ScheduleEventPatchIn(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=256)
    description: Optional[str] = None
    project_id: Optional[str] = None
    requirement_id: Optional[str] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    participant_user_ids: Optional[list[str]] = None


class ScheduleEventOut(BaseModel):
    id: str
    project_id: Optional[str]
    requirement_id: Optional[str]
    title: str
    description: Optional[str]
    event_type: str
    start_at: Optional[datetime]
    end_at: datetime
    participant_user_ids: list[str] = Field(default_factory=list)
    created_by_nickname: str
    created_at: datetime
    updated_at: datetime


class ReminderOut(BaseModel):
    id: str
    kind: str
    title: str
    project_slug: Optional[str] = None
    requirement_id: Optional[str] = None
    requirement_code: Optional[str] = None
    due_at: datetime
    status: str
    minutes_until_due: int
    phase: Optional[str] = None
    progress_percent: Optional[int] = None
    blocked_reason: Optional[str] = None


# ---------- Meetings ----------

class MeetingChunkInitIn(BaseModel):
    filename: str = Field(min_length=1, max_length=256)
    total_size: int = Field(ge=1, le=1024 * 1024 * 1024)
    total_chunks: int = Field(ge=1)
    mime: Optional[str] = None
    title: Optional[str] = Field(default=None, max_length=256)
    requirement_id: Optional[str] = None


class MeetingChunkInitOut(BaseModel):
    upload_id: str
    chunk_size: int


class MeetingPatchIn(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=256)
    transcript_text: Optional[str] = None
    minutes_md: Optional[str] = None


class MeetingInsightOut(BaseModel):
    id: str
    meeting_id: str
    kind: str
    title: str
    description: str
    target_requirement_id: Optional[str]
    confidence_reason: Optional[str]
    status: str
    created_requirement_id: Optional[str]
    created_at: datetime
    updated_at: datetime


class MeetingOut(BaseModel):
    id: str
    project_id: str
    requirement_id: Optional[str]
    title: str
    audio_filename: str
    audio_mime: Optional[str]
    audio_size_bytes: int
    transcript_text: Optional[str]
    minutes_md: Optional[str]
    status: str
    job_id: Optional[str]
    uploaded_by_nickname: str
    insights: list[MeetingInsightOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# ---------- Activity ----------

class ActivityOut(BaseModel):
    id: str
    actor_nickname: str
    action: str
    detail_json: Optional[str]
    created_at: datetime
