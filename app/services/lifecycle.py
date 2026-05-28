"""Centralised submitter/assignee notifications for requirement lifecycle events.

The state machine has at least four sites that mutate `Requirement.status`:
  - app/routers/requirements.py  PATCH /status   (generic transitions)
  - app/routers/sync.py          POST /claim      (claimant takes work)
  - app/routers/delivery_upload.py finalize       (manual delivery)
  - app/routers/auto.py          background       (AI auto-process)

Each one used to do its own notification logic (or none at all). The latter
was a real outage — submitters never got a "你的需求被接走了" or "等你验收"
because PATCH /status was never on the actual claim/deliver code path.

This module owns ALL milestone notifications so adding a new transition
hook only requires one call site.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from models import Notification, Requirement, User
from services.notifications import create_notification, publish_notification

logger = logging.getLogger(__name__)


# (old_status?, new_status) → (recipient_role, type, title_template, body_template, severity)
# recipient_role: "submitter" | "assignees" | "other_side"
# Templates accept {code, title, label, actor}.
_MILESTONES: dict[str, dict] = {
    "claimed": {
        "recipients": "submitter",
        "type": "requirement.claimed",
        "title": "{code} 被接走了",
        "body": "{actor} 接走了「{label}」",
        "severity": "normal",
    },
    "delivered": {
        "recipients": "submitter",
        "type": "requirement.delivered",
        "title": "{code} 交付了，等你验收",
        "body": "{actor} 提交了交付物 — 进去查验后通过或打回",
        "severity": "high",
    },
    "delivery_doc_pending": {
        "recipients": "submitter",
        "type": "requirement.delivered",
        "title": "{code} 已交付，AI 正在写交付文档",
        "body": "{actor} 上传了交付物，AI 助理正在生成交付摘要 — 完成后会再通知你验收",
        "severity": "normal",
    },
    "accepted": {
        "recipients": "assignees",
        "type": "requirement.accepted",
        "title": "{code} 通过验收 🎉",
        "body": "{actor} 通过了你的交付",
        "severity": "normal",
    },
    "revision_requested": {
        "recipients": "assignees",
        "type": "requirement.revision",
        "title": "{code} 需要返工",
        "body": "{actor} 打回了你的交付，请到工单看返工说明",
        "severity": "high",
    },
    "cancelled": {
        "recipients": "other_side",
        "type": "requirement.cancelled",
        "title": "{code} 被取消了",
        "body": "{actor} 取消了「{label}」",
        "severity": "normal",
    },
}


def _resolve_recipients(db: Session, req: Requirement, recipient_role: str, actor: User) -> list[User]:
    """Return the list of users who should be notified, excluding the actor."""
    user_ids: set[str] = set()
    if recipient_role == "submitter":
        if req.submitter_user_id:
            user_ids.add(req.submitter_user_id)
    elif recipient_role == "assignees":
        for a in (req.assignments or []):
            user_ids.add(a.user_id)
    elif recipient_role == "other_side":
        # Notify everyone *not* the actor — cancellation affects both sides.
        if req.submitter_user_id:
            user_ids.add(req.submitter_user_id)
        for a in (req.assignments or []):
            user_ids.add(a.user_id)

    user_ids.discard(actor.id)
    if not user_ids:
        return []
    # Skip soft-deleted users — they can't log in to see the notification,
    # so creating one just clutters the DB and the unread badge for a
    # ghost account no one will see.
    return db.query(User).filter(
        User.id.in_(user_ids), User.deleted_at.is_(None),
    ).all()


def queue_status_notifications(
    db: Session,
    req: Requirement,
    new_status: str,
    actor: User,
) -> list[Notification]:
    """Create + return Notification rows for this status transition.

    Does NOT commit and does NOT publish — the caller controls those
    so the notification share a transaction with the status change.
    Call `flush_status_notifications(rows)` AFTER `db.commit()` to fire SSE.
    """
    spec = _MILESTONES.get(new_status)
    if not spec:
        return []

    recipients = _resolve_recipients(db, req, spec["recipients"], actor)
    if not recipients:
        return []

    # Substitute via str.replace, NOT str.format — a nickname or title
    # containing "{" (e.g. an attacker tries to claim the nickname
    # "{actor.__class__}") would otherwise crash with KeyError or worse
    # leak attribute access. .replace is dumb and safe.
    label = req.title or req.code
    subs = [
        ("{code}", req.code),
        ("{title}", req.title or ""),
        ("{label}", label),
        ("{actor}", actor.nickname),
    ]
    def render(tpl: str) -> str:
        out = tpl
        for needle, value in subs:
            out = out.replace(needle, value)
        return out
    title = render(spec["title"])
    body = render(spec["body"])

    rows: list[Notification] = []
    for target in recipients:
        rows.append(create_notification(
            db, target,
            type=spec["type"],
            title=title,
            body=body,
            severity=spec["severity"],
            target_url=f"/r/{req.id}",
            project_id=req.project_id,
            requirement_id=req.id,
            # Dedupe across same-event retries (e.g. PATCH /status replay
            # firing twice). Include actor id so a cycle like
            # revision_requested → doing → revision_requested doesn't have
            # worker A's notification silently overwritten with worker B's
            # body — they're genuinely two different events.
            dedupe_key=f"{new_status}:{req.id}:{actor.id}",
        ))
    return rows


async def flush_status_notifications(rows: list[Notification]) -> None:
    """Publish notifications to the SSE bus AFTER the DB transaction
    committed. Swallows bus errors so a transient publish failure can't
    500 a successful state change — the row is in the DB, the user will
    see it next page load."""
    for row in rows:
        try:
            await publish_notification(row)
        except Exception:
            logger.exception("publish_notification failed for %s (will be picked up via polling)", row.id)
