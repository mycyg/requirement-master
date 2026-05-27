from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import current_user, require_local_client
from db import get_db
from models import RequirementWorkspace, RequirementWorkspaceItem, User
from schemas import (
    ProgressUpdateCreateIn,
    ProgressUpdateOut,
    RequirementWorkspaceOut,
    WorkspaceItemCreateIn,
    WorkspaceItemOut,
    WorkspaceItemPatchIn,
    WorkspacePatchIn,
)
from services.permissions import can_work_requirement, is_assignee, is_submitter
from services.push_bus import bus
from services.workspaces import (
    add_progress_update,
    ensure_workspace,
    ensure_workspaces_for_assignments,
    load_requirement_with_workspaces,
    progress_update_out,
    workspace_item_out,
    workspace_out,
)

router = APIRouter(prefix="/api", tags=["workspaces"])


def _require_req(db: Session, req_id: str, user: User):
    req = load_requirement_with_workspaces(db, req_id)
    if not req:
        raise HTTPException(status_code=404, detail="requirement not found")
    if not (is_submitter(req, user) or is_assignee(req, user)):
        raise HTTPException(status_code=403, detail="only the requester and assignees can view workspaces")
    return req


def _my_workspace(db: Session, req_id: str, user: User) -> RequirementWorkspace:
    req = _require_req(db, req_id, user)
    if not can_work_requirement(req, user):
        raise HTTPException(status_code=403, detail="only assignees can edit their personal workspace")
    return ensure_workspace(db, req, user)


@router.get("/requirements/{req_id}/workspaces", response_model=list[RequirementWorkspaceOut])
def list_requirement_workspaces(
    req_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[RequirementWorkspaceOut]:
    req = _require_req(db, req_id, user)
    ensure_workspaces_for_assignments(db, req)
    db.commit()
    req = _require_req(db, req_id, user)
    return [workspace_out(ws) for ws in sorted(req.workspaces, key=lambda w: w.user.nickname.lower())]


@router.patch("/requirements/{req_id}/workspaces/me", response_model=RequirementWorkspaceOut)
async def update_my_workspace(
    req_id: str,
    payload: WorkspacePatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_local_client),
) -> RequirementWorkspaceOut:
    req = _require_req(db, req_id, user)
    if not can_work_requirement(req, user):
        raise HTTPException(status_code=403, detail="only assignees can edit their personal workspace")
    workspace = ensure_workspace(db, req, user)
    changed: list[str] = []
    if payload.phase is not None and payload.phase != workspace.phase:
        workspace.phase = payload.phase.strip()
        changed.append("阶段")
    if payload.progress_percent is not None and payload.progress_percent != workspace.progress_percent:
        workspace.progress_percent = payload.progress_percent
        changed.append("进度")
    if "status_note" in payload.model_fields_set:
        workspace.status_note = (payload.status_note or "").strip() or None
        changed.append("状态说明")
    if "blocked_reason" in payload.model_fields_set:
        workspace.blocked_reason = (payload.blocked_reason or "").strip() or None
        changed.append("阻塞")
    if changed:
        add_progress_update(db, req, user, workspace=workspace, kind="manual", body=f"更新了{', '.join(changed)}。")
    db.commit()
    db.refresh(workspace)
    await bus.publish(f"req:{req.id}", "workspace.updated", {"requirement_id": req.id, "workspace_id": workspace.id})
    return workspace_out(_my_workspace(db, req_id, user))


@router.post("/requirements/{req_id}/workspaces/me/items", response_model=WorkspaceItemOut, status_code=201)
async def create_workspace_item(
    req_id: str,
    payload: WorkspaceItemCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_local_client),
) -> WorkspaceItemOut:
    req = _require_req(db, req_id, user)
    if not can_work_requirement(req, user):
        raise HTTPException(status_code=403, detail="only assignees can edit their personal workspace")
    workspace = ensure_workspace(db, req, user)
    item = RequirementWorkspaceItem(
        workspace_id=workspace.id,
        title=payload.title.strip(),
        status=payload.status,
        sort_order=payload.sort_order,
    )
    db.add(item)
    db.flush()
    add_progress_update(db, req, user, workspace=workspace, kind="item", body=f"新增清单：{item.title}")
    db.commit()
    db.refresh(item)
    await bus.publish(f"req:{req.id}", "workspace.updated", {"requirement_id": req.id, "workspace_id": workspace.id})
    return workspace_item_out(item)


def _require_item(db: Session, item_id: str, user: User) -> RequirementWorkspaceItem:
    item = db.query(RequirementWorkspaceItem).filter(RequirementWorkspaceItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="workspace item not found")
    if item.workspace.user_id != user.id:
        raise HTTPException(status_code=403, detail="only the workspace owner can edit this item")
    return item


@router.patch("/workspace-items/{item_id}", response_model=WorkspaceItemOut)
async def patch_workspace_item(
    item_id: str,
    payload: WorkspaceItemPatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_local_client),
) -> WorkspaceItemOut:
    item = _require_item(db, item_id, user)
    req = item.workspace.requirement
    old_status = item.status
    if payload.title is not None:
        item.title = payload.title.strip()
    if payload.status is not None:
        item.status = payload.status
    if payload.sort_order is not None:
        item.sort_order = payload.sort_order
    if payload.status and payload.status != old_status:
        add_progress_update(db, req, user, workspace=item.workspace, kind="item", body=f"清单“{item.title}”变为 {payload.status}。")
    db.commit()
    db.refresh(item)
    await bus.publish(f"req:{req.id}", "workspace.updated", {"requirement_id": req.id, "workspace_id": item.workspace_id})
    return workspace_item_out(item)


@router.delete("/workspace-items/{item_id}")
async def delete_workspace_item(
    item_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_local_client),
) -> dict:
    item = _require_item(db, item_id, user)
    req = item.workspace.requirement
    workspace_id = item.workspace_id
    add_progress_update(db, req, user, workspace=item.workspace, kind="item", body=f"删除清单：{item.title}")
    db.delete(item)
    db.commit()
    await bus.publish(f"req:{req.id}", "workspace.updated", {"requirement_id": req.id, "workspace_id": workspace_id})
    return {"ok": True}


@router.post("/requirements/{req_id}/workspaces/me/updates", response_model=ProgressUpdateOut, status_code=201)
async def add_my_progress_update(
    req_id: str,
    payload: ProgressUpdateCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_local_client),
) -> ProgressUpdateOut:
    req = _require_req(db, req_id, user)
    if not can_work_requirement(req, user):
        raise HTTPException(status_code=403, detail="only assignees can edit their personal workspace")
    workspace = ensure_workspace(db, req, user)
    update = add_progress_update(db, req, user, workspace=workspace, kind=payload.kind, body=payload.body.strip())
    db.commit()
    db.refresh(update)
    await bus.publish(f"req:{req.id}", "workspace.updated", {"requirement_id": req.id, "workspace_id": workspace.id})
    return progress_update_out(update)
