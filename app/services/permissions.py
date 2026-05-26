"""Shared requirement access checks.

The app is still LAN/nickname based, so these helpers keep the current open
dispatch board while protecting draft assets and assigned work from casual access.
"""
from __future__ import annotations

from models import Requirement, User

PRIVATE_REQUIREMENT_STATUSES = ("draft", "clarifying", "summary_ready")


def is_submitter(req: Requirement, user: User) -> bool:
    return req.submitter_user_id == user.id


def is_assignee(req: Requirement, user: User) -> bool:
    return bool(req.claimed_by_user_id and req.claimed_by_user_id == user.id)


def can_view_requirement_record(req: Requirement, user: User) -> bool:
    if is_submitter(req, user) or is_assignee(req, user):
        return True
    return req.status not in PRIVATE_REQUIREMENT_STATUSES


def can_view_requirement_assets(req: Requirement, user: User) -> bool:
    if is_submitter(req, user) or is_assignee(req, user):
        return True
    return req.status == "ready"


def can_ack_requirement_sync(req: Requirement, user: User) -> bool:
    return is_submitter(req, user) or is_assignee(req, user)


def can_add_requirement_attachment(req: Requirement, user: User) -> bool:
    return is_submitter(req, user) and req.status in {"draft", "clarifying", "summary_ready"}
