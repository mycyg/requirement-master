"""SQLAlchemy 2.0 models. See plan section 3 for the schema rationale."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
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


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    owner_nickname: Mapped[str] = mapped_column(String(64), nullable=False)
    archived: Mapped[bool] = mapped_column(default=False, nullable=False)
    next_seq: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # for PROJ-001, PROJ-002 ...

    requirements: Mapped[list[Requirement]] = relationship(back_populates="project", cascade="all, delete-orphan")


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

    start_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
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
