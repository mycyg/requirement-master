from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime

from anthropic import AsyncAnthropic
from sqlalchemy.orm import Session

from config import settings
from models import (
    Requirement,
    RequirementAcceptanceItem,
    RequirementTaskItem,
    RequirementTaskPlan,
    RequirementWorkspaceItem,
    User,
)
from schemas import (
    RequirementAcceptanceItemOut,
    TaskPlanItemOut,
    TaskPlanOut,
    WorkspaceItemOut,
)
from services.workspaces import ensure_workspace, workspace_item_out

logger = logging.getLogger("yqgl.task_decomposition")
_client = AsyncAnthropic(base_url=settings.llm_base_url, api_key=settings.llm_api_key)

SYSTEM = """You decompose requirements into executable work.

You must:
- Write all user-facing output in the user's language.
- Produce concrete tasks, risks, acceptance criteria, and lightweight hour estimates.
- Never claim work is done.
- Output exactly one JSON object and no extra text.

Schema:
{
  "summary": "...",
  "risks": "...",
  "estimate_hours": 4,
  "estimate_confidence": "low" | "medium" | "high",
  "items": [
    {
      "type": "task" | "risk" | "acceptance",
      "title": "...",
      "description": "...",
      "estimate_hours": 1.5
    }
  ]
}"""


@dataclass
class Decomposition:
    summary: str
    risks: str
    estimate_hours: float | None
    estimate_confidence: str | None
    items: list[dict]


def _fallback(req: Requirement, stage: str) -> Decomposition:
    title = req.title or req.code
    raw = (req.summary_md or req.raw_description or "").strip()
    if stage == "dispatch":
        items = [
            {"type": "task", "title": "确认需求范围", "description": "核对目标、边界和交付格式。", "estimate_hours": 0.5},
            {"type": "task", "title": "完成核心交付", "description": "按需求摘要制作主要交付物。", "estimate_hours": 2.0},
            {"type": "acceptance", "title": "交付物符合需求摘要", "description": "提交人可按摘要逐项验收。", "estimate_hours": None},
            {"type": "acceptance", "title": "说明文档清楚可读", "description": "交付包包含使用说明、限制和后续建议。", "estimate_hours": None},
            {"type": "risk", "title": "需求信息可能仍有缺口", "description": "如附件或上下文不足，需要在开工前补问。", "estimate_hours": None},
        ]
    else:
        items = [
            {"type": "task", "title": "拉取上下文和附件", "description": "阅读需求摘要、附件、会议/留言补充。", "estimate_hours": 0.5},
            {"type": "task", "title": "拆成可提交的小步", "description": "先完成核心功能，再补齐说明和自检。", "estimate_hours": 1.5},
            {"type": "task", "title": "自检并准备交付", "description": "确认文件、截图、说明和验收标准都对齐。", "estimate_hours": 1.0},
            {"type": "risk", "title": "DDL 或依赖阻塞", "description": "如缺测试账号、素材或权限，需要立即在工作区标阻塞。", "estimate_hours": None},
        ]
    return Decomposition(
        summary=f"{title} 的{'投递前' if stage == 'dispatch' else '接单后'}拆解草稿。",
        risks="本地 fallback 生成，建议人工确认后再写入工作区。",
        estimate_hours=req.estimate_hours or 4.0 if raw else req.estimate_hours or 2.0,
        estimate_confidence=req.estimate_confidence or "medium",
        items=items,
    )


def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1:]
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


async def analyze_requirement(req: Requirement, *, stage: str, actor: User) -> Decomposition:
    if not settings.llm_api_key:
        return _fallback(req, stage)
    try:
        resp = await _client.messages.create(
            model=settings.llm_model,
            max_tokens=2500,
            system=SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    f"# Stage\n{stage}\n\n"
                    f"# Actor\n{actor.nickname}\n\n"
                    f"# Requirement\n{req.code} {req.title or ''}\n\n"
                    f"# Raw\n{req.raw_description or ''}\n\n"
                    f"# Summary\n{req.summary_md or ''}\n\n"
                    f"# Current planning\nestimate={req.estimate_hours}, confidence={req.estimate_confidence}, note={req.planning_note or ''}"
                ),
            }],
        )
        raw = "".join(block.text for block in resp.content if block.type == "text")
        data = json.loads(_strip_fence(raw))
        items = [item for item in data.get("items") or [] if item.get("title")]
        return Decomposition(
            summary=str(data.get("summary") or ""),
            risks=str(data.get("risks") or ""),
            estimate_hours=float(data["estimate_hours"]) if data.get("estimate_hours") is not None else None,
            estimate_confidence=data.get("estimate_confidence") if data.get("estimate_confidence") in {"low", "medium", "high"} else None,
            items=items or _fallback(req, stage).items,
        )
    except Exception:
        logger.exception("task decomposition failed")
        return _fallback(req, stage)


def task_item_out(item: RequirementTaskItem) -> TaskPlanItemOut:
    return TaskPlanItemOut(
        id=item.id,
        plan_id=item.plan_id,
        title=item.title,
        description=item.description,
        item_type=item.item_type,
        suggested_user_id=item.suggested_user_id,
        suggested_nickname=item.suggested_user.nickname if item.suggested_user else None,
        estimate_hours=item.estimate_hours,
        sort_order=item.sort_order,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def task_plan_out(plan: RequirementTaskPlan) -> TaskPlanOut:
    return TaskPlanOut(
        id=plan.id,
        requirement_id=plan.requirement_id,
        stage=plan.stage,
        status=plan.status,
        summary=plan.summary,
        risks=plan.risks,
        job_id=plan.job_id,
        created_by_nickname=plan.created_by.nickname if plan.created_by else "unknown",
        target_user_id=plan.target_user_id,
        target_nickname=plan.target_user.nickname if plan.target_user else None,
        confirmed_at=plan.confirmed_at,
        items=[task_item_out(item) for item in sorted(plan.items, key=lambda x: (x.sort_order, x.created_at))],
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


def acceptance_item_out(item: RequirementAcceptanceItem) -> RequirementAcceptanceItemOut:
    return RequirementAcceptanceItemOut(
        id=item.id,
        requirement_id=item.requirement_id,
        title=item.title,
        description=item.description,
        status=item.status,
        sort_order=item.sort_order,
        source_plan_id=item.source_plan_id,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def apply_confirmed_plan(
    db: Session,
    plan: RequirementTaskPlan,
    actor: User,
) -> tuple[list[RequirementAcceptanceItem], list[RequirementWorkspaceItem]]:
    req = plan.requirement
    acceptance_rows: list[RequirementAcceptanceItem] = []
    workspace_rows: list[RequirementWorkspaceItem] = []
    if plan.stage == "dispatch":
        estimate_hours = sum((item.estimate_hours or 0) for item in plan.items if item.item_type == "task")
        if estimate_hours > 0:
            req.estimate_hours = estimate_hours
        if not req.estimate_confidence:
            req.estimate_confidence = "medium"
        if not req.planning_note:
            req.planning_note = plan.summary
        for idx, item in enumerate([i for i in plan.items if i.item_type == "acceptance"], start=1):
            row = RequirementAcceptanceItem(
                requirement_id=req.id,
                title=item.title,
                description=item.description,
                sort_order=idx,
                source_plan_id=plan.id,
            )
            db.add(row)
            acceptance_rows.append(row)
    else:
        workspace = ensure_workspace(db, req, actor)
        base = len(workspace.items)
        for idx, item in enumerate([i for i in plan.items if i.item_type == "task"], start=1):
            row = RequirementWorkspaceItem(
                workspace_id=workspace.id,
                title=item.title,
                status="todo",
                sort_order=base + idx,
            )
            db.add(row)
            workspace_rows.append(row)
    plan.status = "confirmed"
    plan.confirmed_by_user_id = actor.id
    plan.confirmed_at = datetime.utcnow()
    db.flush()
    return acceptance_rows, workspace_rows
