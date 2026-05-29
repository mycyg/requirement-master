from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from models import Notification, User
from schemas import NotificationOut
from services.push_bus import bus


def notification_out(row: Notification) -> NotificationOut:
    return NotificationOut(
        id=row.id,
        type=row.type,
        severity=row.severity,
        title=row.title,
        body=row.body,
        target_url=row.target_url,
        project_id=row.project_id,
        requirement_id=row.requirement_id,
        read_at=row.read_at,
        archived_at=row.archived_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def create_notification(
    db: Session,
    user: User,
    *,
    type: str,
    title: str,
    body: str | None = None,
    severity: str = "normal",
    target_url: str | None = None,
    project_id: str | None = None,
    requirement_id: str | None = None,
    dedupe_key: str | None = None,
) -> Notification:
    if dedupe_key:
        existing = (
            db.query(Notification)
            .filter(Notification.user_id == user.id, Notification.dedupe_key == dedupe_key)
            .first()
        )
        if existing:
            # Change-detection guard. `_ensure_due_notifications` re-fires the
            # SAME dedupe_key on every polled GET with identical content; if we
            # blindly reset read_at each time, a due/overdue/blocked
            # notification can NEVER stay read — the inbox badge sticks forever
            # and "标为已读" looks broken. Only resurface (clear read/archived,
            # bump updated_at, re-push) when the content actually changed.
            new_title = title[:256]
            content_changed = (
                existing.title != new_title
                or existing.body != body
                or existing.severity != severity
                or existing.target_url != target_url
                or existing.project_id != project_id
                or existing.requirement_id != requirement_id
            )
            if not content_changed:
                return existing
            existing.title = new_title
            existing.body = body
            existing.severity = severity
            existing.target_url = target_url
            existing.project_id = project_id
            existing.requirement_id = requirement_id
            existing.read_at = None
            existing.archived_at = None
            existing.updated_at = datetime.utcnow()
            db.flush()
            return existing
    row = Notification(
        user_id=user.id,
        type=type,
        severity=severity,
        title=title[:256],
        body=body,
        target_url=target_url,
        project_id=project_id,
        requirement_id=requirement_id,
        dedupe_key=dedupe_key,
    )
    db.add(row)
    db.flush()
    return row


async def publish_notification(row: Notification) -> None:
    """Publish ONLY to the recipient user's private channel. Earlier code
    fanned out to the global `all` topic too — but every client subscribed
    to `all` then received every notification with title + body + actor
    nickname for every user in the org. Cross-user information disclosure
    over an SSE connection that's hard to spot in devtools logs.

    Clients now subscribe to `/api/push/stream/me` (cookie-scoped) to
    receive their own notifications, separately from the global
    `/api/push/stream` which carries non-PII requirement.* events."""
    payload = notification_out(row).model_dump(mode="json")
    await bus.publish(f"user:{row.user_id}", "notification.created", payload)


async def notify_users(db: Session, users: list[User], **kwargs) -> list[Notification]:
    rows: list[Notification] = []
    for user in users:
        rows.append(create_notification(db, user, **kwargs))
    db.commit()
    for row in rows:
        await publish_notification(row)
    return rows
