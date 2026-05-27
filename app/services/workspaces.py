from __future__ import annotations

from sqlalchemy.orm import Session, selectinload

from models import (
    Requirement,
    RequirementAssignment,
    RequirementProgressUpdate,
    RequirementWorkspace,
    RequirementWorkspaceItem,
    User,
)
from schemas import ProgressUpdateOut, RequirementWorkspaceOut, WorkspaceItemOut


STATUS_PROGRESS = {
    "ready": ("待接单", 5),
    "claimed": ("已接单", 15),
    "doing": ("处理中", 45),
    "revision_requested": ("返工中", 60),
    "delivery_doc_pending": ("整理交付", 85),
    "delivered": ("待验收", 90),
    "accepted": ("已完成", 100),
    "cancelled": ("已取消", 0),
}


def ensure_workspace(db: Session, req: Requirement, user: User) -> RequirementWorkspace:
    workspace = (
        db.query(RequirementWorkspace)
        .filter(RequirementWorkspace.requirement_id == req.id, RequirementWorkspace.user_id == user.id)
        .first()
    )
    if workspace:
        return workspace
    phase, progress = STATUS_PROGRESS.get(req.status, ("未开始", 0))
    workspace = RequirementWorkspace(
        requirement_id=req.id,
        user_id=user.id,
        phase=phase,
        progress_percent=progress,
    )
    db.add(workspace)
    db.flush()
    add_progress_update(
        db,
        req,
        user,
        workspace=workspace,
        kind="system",
        body=f"已创建 {user.nickname} 的个人工作区。",
    )
    return workspace


def ensure_workspaces_for_assignments(db: Session, req: Requirement) -> None:
    for assignment in req.assignments:
        if assignment.user:
            ensure_workspace(db, req, assignment.user)


def add_progress_update(
    db: Session,
    req: Requirement,
    actor: User,
    *,
    workspace: RequirementWorkspace | None,
    kind: str,
    body: str,
) -> RequirementProgressUpdate:
    update = RequirementProgressUpdate(
        requirement_id=req.id,
        workspace_id=workspace.id if workspace else None,
        actor_user_id=actor.id,
        actor_nickname=actor.nickname,
        kind=kind,
        body=body,
        phase=workspace.phase if workspace else None,
        progress_percent=workspace.progress_percent if workspace else None,
    )
    db.add(update)
    db.flush()
    return update


def sync_workspace_to_status(db: Session, req: Requirement, actor: User) -> None:
    phase_progress = STATUS_PROGRESS.get(req.status)
    if not phase_progress:
        return
    phase, progress = phase_progress
    ensure_workspaces_for_assignments(db, req)
    for workspace in list(req.workspaces):
        if req.status != "cancelled" and workspace.progress_percent > progress:
            continue
        workspace.phase = phase
        workspace.progress_percent = progress
        add_progress_update(
            db,
            req,
            actor,
            workspace=workspace,
            kind="status",
            body=f"需求状态进入“{phase}”。",
        )


def workspace_item_out(item: RequirementWorkspaceItem) -> WorkspaceItemOut:
    return WorkspaceItemOut(
        id=item.id,
        workspace_id=item.workspace_id,
        title=item.title,
        status=item.status,
        sort_order=item.sort_order,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def progress_update_out(update: RequirementProgressUpdate) -> ProgressUpdateOut:
    return ProgressUpdateOut(
        id=update.id,
        requirement_id=update.requirement_id,
        workspace_id=update.workspace_id,
        actor_nickname=update.actor_nickname,
        kind=update.kind,
        body=update.body,
        phase=update.phase,
        progress_percent=update.progress_percent,
        created_at=update.created_at,
    )


def workspace_out(workspace: RequirementWorkspace) -> RequirementWorkspaceOut:
    return RequirementWorkspaceOut(
        id=workspace.id,
        requirement_id=workspace.requirement_id,
        user_id=workspace.user_id,
        nickname=workspace.user.nickname if workspace.user else workspace.user_id[:8],
        phase=workspace.phase,
        progress_percent=workspace.progress_percent,
        status_note=workspace.status_note,
        blocked_reason=workspace.blocked_reason,
        items=[
            workspace_item_out(item)
            for item in sorted(workspace.items, key=lambda x: (x.sort_order, x.created_at))
        ],
        updates=[
            progress_update_out(update)
            for update in sorted(workspace.updates, key=lambda x: x.created_at, reverse=True)[:20]
        ],
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
    )


def load_requirement_with_workspaces(db: Session, req_id: str) -> Requirement | None:
    return (
        db.query(Requirement)
        .options(
            selectinload(Requirement.assignments).selectinload(RequirementAssignment.user),
            selectinload(Requirement.workspaces).selectinload(RequirementWorkspace.user),
            selectinload(Requirement.workspaces).selectinload(RequirementWorkspace.items),
            selectinload(Requirement.workspaces).selectinload(RequirementWorkspace.updates),
        )
        .filter(Requirement.id == req_id)
        .first()
    )
