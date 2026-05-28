"""Shared requirement access checks.

The app is still LAN/nickname based, so these helpers keep the current open
dispatch board while protecting draft assets and assigned work from casual access.

Admin scope:
* For READ paths (view requirement, view assets, ack sync): admin
  short-circuits every relationship-based filter AND the project-active
  filter. Admin must always be able to audit any historical project
  state, including archived/deleted ones — that's the whole point of the
  admin flag.
* For WRITE paths (add attachment, manage assignees, claim, work):
  admin bypasses relationship filters but still respects the
  project-active filter. Mutating an archived project would silently
  undo the archive intent and break the "read-only review state"
  contract. To act, admin restores the project first via
  ``POST /api/projects/{id}/restore``.

Admins still need a registered client device to perform actions guarded by
``require_local_client`` (claim, sync, delivery) — admin doesn't mean "bypass
device safety", it means "bypass relationship-based filters".
"""
from __future__ import annotations

from models import Requirement, User
from services.assignments import has_explicit_assignees, is_assigned_user, lead_assignment

PRIVATE_REQUIREMENT_STATUSES = ("draft", "clarifying", "summary_ready")
ASSIGNMENT_EDITABLE_STATUSES = {"draft", "clarifying", "summary_ready", "ready", "claimed", "doing", "revision_requested"}


def is_admin(user: User) -> bool:
    """True if the user has been granted the admin flag."""
    return bool(getattr(user, "is_admin", False))


def is_submitter(req: Requirement, user: User) -> bool:
    return req.submitter_user_id == user.id


def is_assignee(req: Requirement, user: User) -> bool:
    return is_assigned_user(req, user)


def requirement_project_is_active(req: Requirement) -> bool:
    project = getattr(req, "project", None)
    return bool(project and not project.archived and project.deleted_at is None)


def can_view_requirement_record(req: Requirement, user: User) -> bool:
    # Admin view bypass MUST come before the project-active filter — see
    # module docstring. Without this, admins lose audit visibility into
    # archived/deleted projects.
    if is_admin(user):
        return True
    if not requirement_project_is_active(req):
        return False
    if is_submitter(req, user) or is_assignee(req, user):
        return True
    return req.status not in PRIVATE_REQUIREMENT_STATUSES


def can_view_requirement_assets(req: Requirement, user: User) -> bool:
    if is_admin(user):
        return True
    if not requirement_project_is_active(req):
        return False
    if is_submitter(req, user) or is_assignee(req, user):
        return True
    return req.status not in PRIVATE_REQUIREMENT_STATUSES


def can_ack_requirement_sync(req: Requirement, user: User) -> bool:
    # Sync-ack is a read-style metadata fetch (records that the local client
    # has the latest manifest). Treat as a read for admin override purposes.
    if is_admin(user):
        return True
    if not requirement_project_is_active(req):
        return False
    return can_view_requirement_assets(req, user)


def can_add_requirement_attachment(req: Requirement, user: User) -> bool:
    if not requirement_project_is_active(req):
        return False
    if is_admin(user):
        return True
    return is_submitter(req, user) and req.status in {"draft", "clarifying", "summary_ready"}


def can_manage_requirement_assignees(req: Requirement, user: User) -> bool:
    if not requirement_project_is_active(req):
        return False
    if is_admin(user):
        return req.status in ASSIGNMENT_EDITABLE_STATUSES
    # Submitter can always re-dispatch their own requirement; the current lead may
    # also re-assign to keep work flowing when the original submitter is offline.
    if req.status not in ASSIGNMENT_EDITABLE_STATUSES:
        return False
    if is_submitter(req, user):
        return True
    lead = lead_assignment(req)
    return lead is not None and lead.user_id == user.id


def can_claim_requirement(req: Requirement, user: User) -> bool:
    if not requirement_project_is_active(req):
        return False
    if is_admin(user):
        return req.status == "ready"
    return req.status == "ready" and (not has_explicit_assignees(req) or is_assignee(req, user))


def can_work_requirement(req: Requirement, user: User) -> bool:
    if not requirement_project_is_active(req):
        return False
    if is_admin(user):
        return True
    return is_assignee(req, user)
