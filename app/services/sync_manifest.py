"""Build the sync manifest that the tray client downloads to mirror a requirement locally."""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from models import (
    Attachment,
    ChatMessage,
    Project,
    Requirement,
    RequirementAcceptanceItem,
    RequirementAssignment,
    RequirementTaskItem,
    RequirementTaskPlan,
    RequirementWorkspace,
    User,
)


def build(db: Session, req: Requirement) -> dict:
    project = db.query(Project).filter(Project.id == req.project_id).first()
    submitter = db.query(User).filter(User.id == req.submitter_user_id).first()
    attachments = (
        db.query(Attachment)
        .filter(Attachment.requirement_id == req.id)
        .order_by(Attachment.created_at)
        .all()
    )
    chats = (
        db.query(ChatMessage)
        .filter(ChatMessage.requirement_id == req.id)
        .order_by(ChatMessage.created_at)
        .all()
    )
    assignments = (
        db.query(RequirementAssignment)
        .filter(RequirementAssignment.requirement_id == req.id)
        .all()
    )
    workspaces = (
        db.query(RequirementWorkspace)
        .filter(RequirementWorkspace.requirement_id == req.id)
        .all()
    )
    acceptance_items = (
        db.query(RequirementAcceptanceItem)
        .filter(RequirementAcceptanceItem.requirement_id == req.id)
        .order_by(RequirementAcceptanceItem.sort_order.asc(), RequirementAcceptanceItem.created_at.asc())
        .all()
    )
    confirmed_plans = (
        db.query(RequirementTaskPlan)
        .filter(RequirementTaskPlan.requirement_id == req.id, RequirementTaskPlan.status == "confirmed")
        .order_by(RequirementTaskPlan.created_at.asc())
        .all()
    )
    assignments.sort(key=lambda a: (0 if a.role == "lead" else 1, a.user.nickname.lower()))
    return {
        "code": req.code,
        "project_slug": project.slug if project else "unknown",
        "project_name": project.name if project else "unknown",
        "submitter_nickname": submitter.nickname if submitter else "unknown",
        "title": req.title,
        "status": req.status,
        "priority": req.priority,
        "estimate_hours": req.estimate_hours,
        "estimate_confidence": req.estimate_confidence,
        "planning_note": req.planning_note,
        "claimed_by_nickname": req.claimed_by_nickname,
        "assignees": [
            {"user_id": a.user_id, "nickname": a.user.nickname, "role": a.role}
            for a in assignments
        ],
        "workspaces": [
            {
                "user_id": w.user_id,
                "nickname": w.user.nickname,
                "phase": w.phase,
                "progress_percent": w.progress_percent,
                "status_note": w.status_note,
                "blocked_reason": w.blocked_reason,
                "items": [
                    {"title": i.title, "status": i.status, "sort_order": i.sort_order}
                    for i in sorted(w.items, key=lambda x: (x.sort_order, x.created_at))
                ],
            }
            for w in sorted(workspaces, key=lambda x: x.user.nickname.lower())
        ],
        "created_at": req.created_at.isoformat(),
        "summary_md": req.summary_md or "",
        "raw_description": req.raw_description or "",
        "acceptance_items": [
            {
                "title": item.title,
                "description": item.description,
                "status": item.status,
                "sort_order": item.sort_order,
            }
            for item in acceptance_items
        ],
        "task_plans": [
            {
                "id": plan.id,
                "stage": plan.stage,
                "summary": plan.summary,
                "risks": plan.risks,
                "target_user_id": plan.target_user_id,
                "items": [
                    {
                        "title": item.title,
                        "description": item.description,
                        "type": item.item_type,
                        "estimate_hours": item.estimate_hours,
                        "sort_order": item.sort_order,
                    }
                    for item in sorted(plan.items, key=lambda x: (x.sort_order, x.created_at))
                ],
            }
            for plan in confirmed_plans
        ],
        "files": [
            {
                "id": a.id,
                "name": a.filename,
                "sha256": a.sha256,
                "size": a.size_bytes,
                "mime": a.mime,
                "download_url": f"/api/files/{a.id}",
                "role": a.role_in_req,
            }
            for a in attachments
        ],
        "chat": [
            {
                "role": m.role,
                "kind": m.kind,
                "content": _safe_json(m.content_json),
                "selected_option_key": m.selected_option_key,
                "user_other_text": m.user_other_text,
                "created_at": m.created_at.isoformat(),
            }
            for m in chats
        ],
    }


def _safe_json(s: str):
    try:
        return json.loads(s)
    except Exception:
        return {"raw": s}
