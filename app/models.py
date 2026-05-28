"""SQLAlchemy 2.0 models. See plan section 3 for the schema rationale."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def uid() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    nickname: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    cookie_token: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    availability_status: Mapped[str] = mapped_column(String(16), default="free", nullable=False)
    availability_text: Mapped[Optional[str]] = mapped_column(String(128))
    availability_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    # Admin flag — when True, `permissions.can_*` checks short-circuit to True.
    # Set via `python scripts/set_admin.py <nickname>` or the YQGL_ADMIN_NICKNAMES env var.
    is_admin: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)


class ClientDevice(Base, TimestampMixin):
    __tablename__ = "client_devices"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    device_name: Mapped[str] = mapped_column(String(128), nullable=False)
    client_token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, index=True)

    user: Mapped[User] = relationship()


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    owner_nickname: Mapped[str] = mapped_column(String(64), nullable=False)
    archived: Mapped[bool] = mapped_column(default=False, nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, index=True)
    deleted_by_nickname: Mapped[Optional[str]] = mapped_column(String(64))
    next_seq: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # for PROJ-001, PROJ-002 ...

    requirements: Mapped[list[Requirement]] = relationship(back_populates="project", cascade="all, delete-orphan")
    drive_items: Mapped[list[ProjectDriveItem]] = relationship(back_populates="project", cascade="all, delete-orphan")


class BackgroundJob(Base, TimestampMixin):
    __tablename__ = "background_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False, index=True)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    message: Mapped[Optional[str]] = mapped_column(Text)
    result_ref: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    error: Mapped[Optional[str]] = mapped_column(Text)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    created_by: Mapped[User] = relationship()


class KnowledgeDocument(Base, TimestampMixin):
    __tablename__ = "knowledge_documents"
    __table_args__ = (UniqueConstraint("source_type", "source_id", name="uq_knowledge_source"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    project_id: Mapped[Optional[str]] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    requirement_id: Mapped[Optional[str]] = mapped_column(ForeignKey("requirements.id", ondelete="CASCADE"), index=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    source_url: Mapped[str] = mapped_column(String(512), nullable=False)
    corpus_path: Mapped[str] = mapped_column(String(512), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    project: Mapped[Optional[Project]] = relationship()
    requirement: Mapped[Optional[Requirement]] = relationship()


class KnowledgeAskRun(Base, TimestampMixin):
    __tablename__ = "knowledge_ask_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    project_id: Mapped[Optional[str]] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    job_id: Mapped[Optional[str]] = mapped_column(ForeignKey("background_jobs.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False, index=True)
    answer_md: Mapped[Optional[str]] = mapped_column(Text)
    citations_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    trace_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)

    project: Mapped[Optional[Project]] = relationship()
    created_by: Mapped[User] = relationship()
    job: Mapped[Optional[BackgroundJob]] = relationship()


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), default="normal", nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    body: Mapped[Optional[str]] = mapped_column(Text)
    target_url: Mapped[Optional[str]] = mapped_column(String(512))
    project_id: Mapped[Optional[str]] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    requirement_id: Mapped[Optional[str]] = mapped_column(ForeignKey("requirements.id", ondelete="SET NULL"), index=True)
    dedupe_key: Mapped[Optional[str]] = mapped_column(String(256), index=True)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime, index=True)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime, index=True)

    user: Mapped[User] = relationship(foreign_keys=[user_id])
    project: Mapped[Optional[Project]] = relationship()
    requirement: Mapped[Optional[Requirement]] = relationship()


class ProjectDriveItem(Base, TimestampMixin):
    __tablename__ = "project_drive_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[Optional[str]] = mapped_column(ForeignKey("project_drive_items.id", ondelete="CASCADE"), index=True)

    name: Mapped[str] = mapped_column(String(256), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # file | folder
    current_version_id: Mapped[Optional[str]] = mapped_column(String(32), index=True)

    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    updated_by_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, index=True)
    deleted_by_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), index=True)

    project: Mapped[Project] = relationship(back_populates="drive_items")
    parent: Mapped[Optional[ProjectDriveItem]] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list[ProjectDriveItem]] = relationship(back_populates="parent")
    versions: Mapped[list[ProjectDriveVersion]] = relationship(back_populates="item", cascade="all, delete-orphan")
    created_by: Mapped[User] = relationship(foreign_keys=[created_by_user_id])
    updated_by: Mapped[Optional[User]] = relationship(foreign_keys=[updated_by_user_id])
    deleted_by: Mapped[Optional[User]] = relationship(foreign_keys=[deleted_by_user_id])


class ProjectDriveVersion(Base, TimestampMixin):
    __tablename__ = "project_drive_versions"
    __table_args__ = (UniqueConstraint("item_id", "version_no", name="uq_project_drive_version_no"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    item_id: Mapped[str] = mapped_column(ForeignKey("project_drive_items.id", ondelete="CASCADE"), index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)

    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    mime: Mapped[Optional[str]] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[Optional[str]] = mapped_column(String(64))
    parsed_text: Mapped[Optional[str]] = mapped_column(Text)
    parsed_text_path: Mapped[Optional[str]] = mapped_column(String(512))

    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)

    item: Mapped[ProjectDriveItem] = relationship(back_populates="versions")
    created_by: Mapped[User] = relationship(foreign_keys=[created_by_user_id])


class ProjectDriveOperation(Base, TimestampMixin):
    __tablename__ = "project_drive_operations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    op_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    undone_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    project: Mapped[Project] = relationship()
    actor: Mapped[User] = relationship()


class ProjectDriveComment(Base, TimestampMixin):
    __tablename__ = "project_drive_comments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    folder_id: Mapped[Optional[str]] = mapped_column(ForeignKey("project_drive_items.id", ondelete="CASCADE"), index=True)
    author_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    author_nickname: Mapped[str] = mapped_column(String(64), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending_llm", nullable=False, index=True)
    llm_kind: Mapped[Optional[str]] = mapped_column(String(32))
    llm_reason: Mapped[Optional[str]] = mapped_column(Text)
    draft_requirement_id: Mapped[Optional[str]] = mapped_column(ForeignKey("requirements.id"), index=True)

    project: Mapped[Project] = relationship()
    folder: Mapped[Optional[ProjectDriveItem]] = relationship()
    author: Mapped[User] = relationship()
    draft_requirement: Mapped[Optional[Requirement]] = relationship()


class ScheduleEvent(Base, TimestampMixin):
    __tablename__ = "schedule_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    project_id: Mapped[Optional[str]] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    requirement_id: Mapped[Optional[str]] = mapped_column(ForeignKey("requirements.id", ondelete="CASCADE"), index=True)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(String(32), default="custom", nullable=False, index=True)
    start_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    end_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    participant_user_ids_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)

    project: Mapped[Optional[Project]] = relationship()
    requirement: Mapped[Optional[Requirement]] = relationship()
    created_by: Mapped[User] = relationship()


class MeetingRecord(Base, TimestampMixin):
    __tablename__ = "meeting_records"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    requirement_id: Mapped[Optional[str]] = mapped_column(ForeignKey("requirements.id", ondelete="SET NULL"), index=True)
    uploaded_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    audio_filename: Mapped[str] = mapped_column(String(256), nullable=False)
    audio_mime: Mapped[Optional[str]] = mapped_column(String(128))
    audio_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    audio_path: Mapped[str] = mapped_column(String(512), nullable=False)
    transcript_text: Mapped[Optional[str]] = mapped_column(Text)
    minutes_md: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="processing", nullable=False, index=True)
    job_id: Mapped[Optional[str]] = mapped_column(ForeignKey("background_jobs.id"), index=True)

    project: Mapped[Project] = relationship()
    uploaded_by: Mapped[User] = relationship()
    job: Mapped[Optional[BackgroundJob]] = relationship()


class MeetingInsight(Base, TimestampMixin):
    __tablename__ = "meeting_insights"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meeting_records.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    target_requirement_id: Mapped[Optional[str]] = mapped_column(ForeignKey("requirements.id"), index=True)
    confidence_reason: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    created_requirement_id: Mapped[Optional[str]] = mapped_column(ForeignKey("requirements.id"), index=True)
    confirmed_by_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), index=True)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    meeting: Mapped[MeetingRecord] = relationship()
    confirmed_by: Mapped[Optional[User]] = relationship()


class Requirement(Base, TimestampMixin):
    __tablename__ = "requirements"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    submitter_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    claimed_by_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), index=True)
    claimed_by_nickname: Mapped[Optional[str]] = mapped_column(String(64))

    title: Mapped[Optional[str]] = mapped_column(String(256))
    raw_description: Mapped[Optional[str]] = mapped_column(Text)
    summary_md: Mapped[Optional[str]] = mapped_column(Text)

    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False, index=True)
    # draft | clarifying | summary_ready | ready | ai_processing | claimed | doing
    # delivery_doc_pending | delivered | revision_requested | accepted | cancelled
    priority: Mapped[str] = mapped_column(String(16), default="normal", nullable=False)
    estimate_hours: Mapped[Optional[float]] = mapped_column(Float)
    estimate_confidence: Mapped[Optional[str]] = mapped_column(String(16))
    planning_note: Mapped[Optional[str]] = mapped_column(Text)

    start_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    source_meeting_id: Mapped[Optional[str]] = mapped_column(ForeignKey("meeting_records.id"), index=True)
    source_requirement_id: Mapped[Optional[str]] = mapped_column(ForeignKey("requirements.id"), index=True)
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    done_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    delivery_doc_ready_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    sync_state: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    # pending | synced | failed

    project: Mapped[Project] = relationship(back_populates="requirements")
    attachments: Mapped[list[Attachment]] = relationship(back_populates="requirement", cascade="all, delete-orphan")
    chat_messages: Mapped[list[ChatMessage]] = relationship(back_populates="requirement", cascade="all, delete-orphan")
    deliveries: Mapped[list[Delivery]] = relationship(back_populates="requirement", cascade="all, delete-orphan")
    assignments: Mapped[list[RequirementAssignment]] = relationship(back_populates="requirement", cascade="all, delete-orphan")
    workspaces: Mapped[list[RequirementWorkspace]] = relationship(back_populates="requirement", cascade="all, delete-orphan")
    task_plans: Mapped[list[RequirementTaskPlan]] = relationship(back_populates="requirement", cascade="all, delete-orphan")
    acceptance_items: Mapped[list[RequirementAcceptanceItem]] = relationship(back_populates="requirement", cascade="all, delete-orphan")


class RequirementAssignment(Base, TimestampMixin):
    __tablename__ = "requirement_assignments"
    __table_args__ = (UniqueConstraint("requirement_id", "user_id", name="uq_requirement_assignment_user"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    requirement_id: Mapped[str] = mapped_column(ForeignKey("requirements.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # lead | collaborator
    assigned_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)

    requirement: Mapped[Requirement] = relationship(back_populates="assignments")
    user: Mapped[User] = relationship(foreign_keys=[user_id])
    assigned_by: Mapped[User] = relationship(foreign_keys=[assigned_by_user_id])


class RequirementWorkspace(Base, TimestampMixin):
    __tablename__ = "requirement_workspaces"
    __table_args__ = (UniqueConstraint("requirement_id", "user_id", name="uq_requirement_workspace_user"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    requirement_id: Mapped[str] = mapped_column(ForeignKey("requirements.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    phase: Mapped[str] = mapped_column(String(64), default="未开始", nullable=False)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status_note: Mapped[Optional[str]] = mapped_column(Text)
    blocked_reason: Mapped[Optional[str]] = mapped_column(Text)

    requirement: Mapped[Requirement] = relationship(back_populates="workspaces")
    user: Mapped[User] = relationship()
    items: Mapped[list[RequirementWorkspaceItem]] = relationship(back_populates="workspace", cascade="all, delete-orphan")
    updates: Mapped[list[RequirementProgressUpdate]] = relationship(back_populates="workspace", cascade="all, delete-orphan")


class RequirementWorkspaceItem(Base, TimestampMixin):
    __tablename__ = "requirement_workspace_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("requirement_workspaces.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="todo", nullable=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    workspace: Mapped[RequirementWorkspace] = relationship(back_populates="items")


class RequirementProgressUpdate(Base, TimestampMixin):
    __tablename__ = "requirement_progress_updates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    requirement_id: Mapped[str] = mapped_column(ForeignKey("requirements.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(ForeignKey("requirement_workspaces.id", ondelete="CASCADE"), index=True)
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    actor_nickname: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    phase: Mapped[Optional[str]] = mapped_column(String(64))
    progress_percent: Mapped[Optional[int]] = mapped_column(Integer)

    workspace: Mapped[Optional[RequirementWorkspace]] = relationship(back_populates="updates")
    actor: Mapped[User] = relationship()


class RequirementTaskPlan(Base, TimestampMixin):
    __tablename__ = "requirement_task_plans"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    requirement_id: Mapped[str] = mapped_column(ForeignKey("requirements.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # dispatch | worker
    status: Mapped[str] = mapped_column(String(16), default="draft", nullable=False, index=True)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    risks: Mapped[Optional[str]] = mapped_column(Text)
    job_id: Mapped[Optional[str]] = mapped_column(ForeignKey("background_jobs.id"), index=True)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    target_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), index=True)
    confirmed_by_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), index=True)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    requirement: Mapped[Requirement] = relationship(back_populates="task_plans")
    job: Mapped[Optional[BackgroundJob]] = relationship()
    created_by: Mapped[User] = relationship(foreign_keys=[created_by_user_id])
    target_user: Mapped[Optional[User]] = relationship(foreign_keys=[target_user_id])
    confirmed_by: Mapped[Optional[User]] = relationship(foreign_keys=[confirmed_by_user_id])
    items: Mapped[list[RequirementTaskItem]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class RequirementTaskItem(Base, TimestampMixin):
    __tablename__ = "requirement_task_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    plan_id: Mapped[str] = mapped_column(ForeignKey("requirement_task_plans.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    item_type: Mapped[str] = mapped_column(String(16), default="task", nullable=False, index=True)  # task | risk | acceptance
    suggested_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), index=True)
    estimate_hours: Mapped[Optional[float]] = mapped_column(Float)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    plan: Mapped[RequirementTaskPlan] = relationship(back_populates="items")
    suggested_user: Mapped[Optional[User]] = relationship()


class RequirementAcceptanceItem(Base, TimestampMixin):
    __tablename__ = "requirement_acceptance_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    requirement_id: Mapped[str] = mapped_column(ForeignKey("requirements.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source_plan_id: Mapped[Optional[str]] = mapped_column(ForeignKey("requirement_task_plans.id"), index=True)

    requirement: Mapped[Requirement] = relationship(back_populates="acceptance_items")
    source_plan: Mapped[Optional[RequirementTaskPlan]] = relationship()


class Attachment(Base, TimestampMixin):
    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    requirement_id: Mapped[str] = mapped_column(ForeignKey("requirements.id", ondelete="CASCADE"), index=True)

    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    mime: Mapped[Optional[str]] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[Optional[str]] = mapped_column(String(64))

    parsed_text: Mapped[Optional[str]] = mapped_column(Text)  # truncated preview
    parsed_text_path: Mapped[Optional[str]] = mapped_column(String(512))  # full text on disk
    role_in_req: Mapped[Optional[str]] = mapped_column(String(64))

    requirement: Mapped[Requirement] = relationship(back_populates="attachments")


class ChatMessage(Base, TimestampMixin):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    requirement_id: Mapped[str] = mapped_column(ForeignKey("requirements.id", ondelete="CASCADE"), index=True)

    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant | system
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    # text | question_choice | question_open | summary | force_summarize | error
    content_json: Mapped[str] = mapped_column(Text, nullable=False)  # JSON-encoded payload

    selected_option_key: Mapped[Optional[str]] = mapped_column(String(64))
    user_other_text: Mapped[Optional[str]] = mapped_column(Text)

    requirement: Mapped[Requirement] = relationship(back_populates="chat_messages")


class Delivery(Base, TimestampMixin):
    __tablename__ = "deliveries"
    __table_args__ = (UniqueConstraint("requirement_id", "round", name="uq_delivery_req_round"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    requirement_id: Mapped[str] = mapped_column(ForeignKey("requirements.id", ondelete="CASCADE"), index=True)
    round: Mapped[int] = mapped_column(Integer, nullable=False)

    package_path: Mapped[str] = mapped_column(String(512), nullable=False)
    package_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    package_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False)

    delivery_doc_md: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    submitted_by_nickname: Mapped[str] = mapped_column(String(64), nullable=False)

    requirement: Mapped[Requirement] = relationship(back_populates="deliveries")


class RevisionRequest(Base, TimestampMixin):
    __tablename__ = "revision_requests"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    requirement_id: Mapped[str] = mapped_column(ForeignKey("requirements.id", ondelete="CASCADE"), index=True)
    delivery_id: Mapped[str] = mapped_column(ForeignKey("deliveries.id", ondelete="CASCADE"), index=True)
    requested_by_nickname: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_md: Mapped[str] = mapped_column(Text, nullable=False)


class Comment(Base, TimestampMixin):
    __tablename__ = "comments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    requirement_id: Mapped[str] = mapped_column(ForeignKey("requirements.id", ondelete="CASCADE"), index=True)
    author_nickname: Mapped[str] = mapped_column(String(64), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)


class ActivityLog(Base, TimestampMixin):
    __tablename__ = "activity_log"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    requirement_id: Mapped[str] = mapped_column(ForeignKey("requirements.id", ondelete="CASCADE"), index=True)
    actor_nickname: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    detail_json: Mapped[Optional[str]] = mapped_column(Text)
