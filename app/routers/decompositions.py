from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from auth import current_user, optional_local_client
from db import SessionLocal, get_db
from models import (
    BackgroundJob,
    Requirement,
    RequirementAcceptanceItem,
    RequirementAssignment,
    RequirementTaskItem,
    RequirementTaskPlan,
    User,
)
from schemas import (
    RequirementAcceptanceItemOut,
    TaskDecompositionCreateIn,
    TaskPlanConfirmOut,
    TaskPlanOut,
)
from services.activity import log_activity
from services.jobs import create_job, publish_job, update_job
from services.notifications import create_notification, publish_notification
from services.permissions import can_view_requirement_record, can_work_requirement, requirement_project_is_active
from services.push_bus import bus
from services.task_decomposition import acceptance_item_out, analyze_requirement, apply_confirmed_plan, task_plan_out
from services.workspaces import workspace_item_out

router = APIRouter(prefix="/api", tags=["decompositions"])


def _parse_estimate(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _load_requirement(db: Session, req_id: str) -> Requirement:
    req = (
        db.query(Requirement)
        .options(
            selectinload(Requirement.assignments).selectinload(RequirementAssignment.user),
            selectinload(Requirement.workspaces),
        )
        .filter(Requirement.id == req_id)
        .first()
    )
    if not req:
        raise HTTPException(status_code=404, detail="requirement not found")
    return req


def _load_plan(db: Session, plan_id: str) -> RequirementTaskPlan:
    plan = (
        db.query(RequirementTaskPlan)
        .options(
            selectinload(RequirementTaskPlan.requirement).selectinload(Requirement.assignments).selectinload(RequirementAssignment.user),
            selectinload(RequirementTaskPlan.items).selectinload(RequirementTaskItem.suggested_user),
            selectinload(RequirementTaskPlan.created_by),
            selectinload(RequirementTaskPlan.target_user),
        )
        .filter(RequirementTaskPlan.id == plan_id)
        .first()
    )
    if not plan:
        raise HTTPException(status_code=404, detail="decomposition not found")
    return plan


@router.post("/requirements/{req_id}/decompositions", response_model=TaskPlanOut)
def create_decomposition(
    req_id: str,
    payload: TaskDecompositionCreateIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    local_user: User | None = Depends(optional_local_client),
) -> TaskPlanOut:
    req = _load_requirement(db, req_id)
    if not can_view_requirement_record(req, user):
        raise HTTPException(status_code=403, detail="you cannot view this requirement yet")
    if payload.stage == "dispatch" and req.submitter_user_id != user.id:
        raise HTTPException(status_code=403, detail="only the requester can create dispatch decompositions")
    if payload.stage == "worker" and not can_work_requirement(req, user):
        raise HTTPException(status_code=403, detail="only assignees can create worker decompositions")
    if payload.stage == "worker" and local_user is None:
        raise HTTPException(status_code=403, detail="local client required")
    job = create_job(db, kind="task_decomposition", user=user, message="正在拆任务")
    plan = RequirementTaskPlan(
        requirement_id=req.id,
        stage=payload.stage,
        status="draft",
        job_id=job.id,
        created_by_user_id=user.id,
        target_user_id=user.id if payload.stage == "worker" else None,
    )
    db.add(plan)
    log_activity(
        db,
        requirement_id=req.id,
        actor_nickname=user.nickname,
        action="decomposition_started",
        detail={"stage": payload.stage, "job_id": job.id},
    )
    db.commit()
    db.refresh(plan)
    background_tasks.add_task(_process_decomposition, plan.id, job.id, user.id)
    return task_plan_out(_load_plan(db, plan.id))


@router.get("/requirements/{req_id}/decompositions", response_model=list[TaskPlanOut])
def list_decompositions(req_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[TaskPlanOut]:
    req = _load_requirement(db, req_id)
    if not can_view_requirement_record(req, user):
        raise HTTPException(status_code=403, detail="you cannot view this requirement yet")
    plans = (
        db.query(RequirementTaskPlan)
        .options(
            selectinload(RequirementTaskPlan.items).selectinload(RequirementTaskItem.suggested_user),
            selectinload(RequirementTaskPlan.created_by),
            selectinload(RequirementTaskPlan.target_user),
        )
        .filter(RequirementTaskPlan.requirement_id == req.id)
        .order_by(RequirementTaskPlan.created_at.desc())
        .all()
    )
    return [task_plan_out(plan) for plan in plans]


@router.get("/requirements/{req_id}/acceptance", response_model=list[RequirementAcceptanceItemOut])
def list_acceptance_items(
    req_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[RequirementAcceptanceItemOut]:
    req = _load_requirement(db, req_id)
    if not can_view_requirement_record(req, user):
        raise HTTPException(status_code=403, detail="you cannot view this requirement yet")
    rows = (
        db.query(RequirementAcceptanceItem)
        .filter(RequirementAcceptanceItem.requirement_id == req.id)
        .order_by(RequirementAcceptanceItem.sort_order.asc(), RequirementAcceptanceItem.created_at.asc())
        .all()
    )
    return [acceptance_item_out(row) for row in rows]


@router.post("/decompositions/{plan_id}/confirm", response_model=TaskPlanConfirmOut)
async def confirm_decomposition(
    plan_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    local_user: User | None = Depends(optional_local_client),
) -> TaskPlanConfirmOut:
    plan = _load_plan(db, plan_id)
    req = plan.requirement
    if not requirement_project_is_active(req):
        raise HTTPException(status_code=404, detail="requirement not found")
    if plan.status != "draft":
        raise HTTPException(status_code=400, detail=f"cannot confirm decomposition in status {plan.status}")
    if plan.stage == "dispatch" and req.submitter_user_id != user.id:
        raise HTTPException(status_code=403, detail="only the requester can confirm dispatch decompositions")
    if plan.stage == "worker" and plan.target_user_id != user.id:
        raise HTTPException(status_code=403, detail="only the target assignee can confirm this worker decomposition")
    if plan.stage == "worker" and local_user is None:
        raise HTTPException(status_code=403, detail="local client required")
    # Atomic CAS — without this, two tabs both pass the `!= "draft"`
    # check, both run apply_confirmed_plan, inserting duplicate acceptance
    # items and duplicate workspace items.
    from sqlalchemy import update as sql_update
    cas = db.execute(
        sql_update(RequirementTaskPlan)
        .where(RequirementTaskPlan.id == plan_id, RequirementTaskPlan.status == "draft")
        .values(status="confirmed")
    )
    if cas.rowcount == 0:
        db.rollback()
        raise HTTPException(status_code=409, detail="another tab already confirmed/dismissed this plan")
    db.refresh(plan)
    acceptance_rows, workspace_rows = apply_confirmed_plan(db, plan, user)
    log_activity(
        db,
        requirement_id=req.id,
        actor_nickname=user.nickname,
        action="decomposition_confirmed",
        detail={"stage": plan.stage, "plan_id": plan.id},
    )
    db.commit()
    await bus.publish(f"req:{req.id}", "requirement.updated", {"status": req.status, "decomposition": plan.stage})
    await bus.publish("all", "requirement.updated", {"requirement_id": req.id, "status": req.status})
    return TaskPlanConfirmOut(
        plan=task_plan_out(_load_plan(db, plan.id)),
        acceptance_items=[acceptance_item_out(row) for row in acceptance_rows],
        workspace_items=[workspace_item_out(row) for row in workspace_rows],
    )


@router.post("/decompositions/{plan_id}/dismiss", response_model=TaskPlanOut)
async def dismiss_decomposition(
    plan_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    local_user: User | None = Depends(optional_local_client),
) -> TaskPlanOut:
    plan = _load_plan(db, plan_id)
    req = plan.requirement
    if not requirement_project_is_active(req):
        raise HTTPException(status_code=404, detail="requirement not found")
    if plan.stage == "dispatch" and req.submitter_user_id != user.id:
        raise HTTPException(status_code=403, detail="only the requester can dismiss dispatch decompositions")
    if plan.stage == "worker" and plan.target_user_id != user.id:
        raise HTTPException(status_code=403, detail="only the target assignee can dismiss this worker decomposition")
    if plan.stage == "worker" and local_user is None:
        raise HTTPException(status_code=403, detail="local client required")
    # Only transition from draft — without this, a curl call can dismiss
    # an already-confirmed plan and leave its derived acceptance/workspace
    # items orphaned.
    from sqlalchemy import update as sql_update
    cas = db.execute(
        sql_update(RequirementTaskPlan)
        .where(RequirementTaskPlan.id == plan_id, RequirementTaskPlan.status == "draft")
        .values(status="dismissed")
    )
    if cas.rowcount == 0:
        db.rollback()
        return task_plan_out(_load_plan(db, plan.id))
    db.refresh(plan)
    log_activity(
        db,
        requirement_id=req.id,
        actor_nickname=user.nickname,
        action="decomposition_dismissed",
        detail={"stage": plan.stage, "plan_id": plan.id},
    )
    db.commit()
    await bus.publish(f"req:{req.id}", "requirement.updated", {"status": req.status, "decomposition": plan.stage})
    return task_plan_out(_load_plan(db, plan.id))


async def _process_decomposition(plan_id: str, job_id: str, user_id: str) -> None:
    db = SessionLocal()
    try:
        plan = (
            db.query(RequirementTaskPlan)
            .options(selectinload(RequirementTaskPlan.requirement), selectinload(RequirementTaskPlan.items))
            .filter(RequirementTaskPlan.id == plan_id)
            .first()
        )
        job = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
        user = db.query(User).filter(User.id == user_id).first()
        if not plan or not job or not user:
            return
        if not requirement_project_is_active(plan.requirement):
            update_job(db, job, status="failed", progress_percent=100, message="项目已归档或删除，已取消任务拆解")
            plan.status = "dismissed"
            db.commit()
            await publish_job(job)
            return
        update_job(db, job, status="running", progress_percent=25, message="正在分析需求、风险和验收口径")
        db.commit()
        await publish_job(job)
        result = await analyze_requirement(plan.requirement, stage=plan.stage, actor=user)
        db.refresh(plan.requirement)
        if not requirement_project_is_active(plan.requirement):
            update_job(db, job, status="failed", progress_percent=100, message="项目已归档或删除，已取消任务拆解")
            plan.status = "dismissed"
            db.commit()
            await publish_job(job)
            return
        plan.summary = result.summary
        plan.risks = result.risks
        for item in list(plan.items):
            db.delete(item)
        db.flush()
        for idx, item in enumerate(result.items, start=1):
            item_type = str(item.get("type") or "task")
            if item_type not in {"task", "risk", "acceptance"}:
                item_type = "task"
            db.add(RequirementTaskItem(
                plan_id=plan.id,
                title=str(item.get("title") or f"任务 {idx}")[:256],
                description=str(item.get("description") or "")[:5000] or None,
                item_type=item_type,
                estimate_hours=_parse_estimate(item.get("estimate_hours")),
                sort_order=idx,
            ))
        update_job(db, job, status="succeeded", progress_percent=100, message="任务拆解已完成", result_ref=plan.id)
        note = create_notification(
            db,
            user,
            type="decomposition_ready",
            title="任务拆解草稿已生成",
            body=f"{plan.requirement.code} 可以确认或忽略。",
            severity="normal",
            target_url=f"/r/{plan.requirement_id}?tab=decomposition",
            project_id=plan.requirement.project_id,
            requirement_id=plan.requirement_id,
            dedupe_key=f"decomposition:{plan.id}",
        )
        db.commit()
        await publish_job(job)
        await publish_notification(note)
        await bus.publish(f"req:{plan.requirement_id}", "requirement.updated", {"decomposition": plan.stage})
    except Exception as exc:
        plan = db.query(RequirementTaskPlan).filter(RequirementTaskPlan.id == plan_id).first()
        job = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
        # Only flip to dismissed if still in draft — if user already
        # confirmed (and apply_confirmed_plan ran), don't resurrect a
        # confirmed plan as dismissed (would orphan acceptance + workspace
        # items that were already inserted).
        if plan and plan.status == "draft":
            plan.status = "dismissed"
        if job:
            update_job(db, job, status="failed", progress_percent=100, message="任务拆解失败", error=f"{type(exc).__name__}: {exc}")
        db.commit()
        if job:
            await publish_job(job)
    finally:
        db.close()
