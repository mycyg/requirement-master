from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from auth import current_user
from db import SessionLocal, get_db
from models import BackgroundJob, KnowledgeAskRun, Project, User
from schemas import KnowledgeAskCreateOut, KnowledgeAskIn, KnowledgeAskRunOut, KnowledgeSearchHit, KnowledgeSearchOut
from services.jobs import create_job, publish_job, update_job
from services.knowledge import answer_from_hits, rebuild_knowledge_index, search_knowledge
from services.notifications import create_notification, publish_notification

router = APIRouter(prefix="/api", tags=["knowledge"])


def _run_out(row: KnowledgeAskRun) -> KnowledgeAskRunOut:
    try:
        citations = [KnowledgeSearchHit(**item) for item in json.loads(row.citations_json or "[]")]
    except Exception:
        citations = []
    try:
        trace = json.loads(row.trace_json or "[]")
    except Exception:
        trace = []
    return KnowledgeAskRunOut(
        id=row.id,
        question=row.question,
        project_id=row.project_id,
        status=row.status,
        job_id=row.job_id,
        answer_md=row.answer_md,
        citations=citations,
        trace=trace,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/knowledge/search", response_model=KnowledgeSearchOut)
def grep_knowledge(
    q: str = Query(min_length=1, max_length=500),
    project_id: str | None = Query(default=None),
    scope: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=80),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> KnowledgeSearchOut:
    if project_id and not db.query(Project.id).filter(Project.id == project_id).first():
        raise HTTPException(status_code=404, detail="project not found")
    hits = search_knowledge(db, user, query=q, project_id=project_id, scope=scope, limit=limit)
    return KnowledgeSearchOut(query=q, hits=hits)


@router.post("/knowledge/reindex")
def reindex_knowledge(
    project_id: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
) -> dict:
    if project_id and not db.query(Project.id).filter(Project.id == project_id).first():
        raise HTTPException(status_code=404, detail="project not found")
    return {"ok": True, "count": rebuild_knowledge_index(db, project_id=project_id)}


@router.post("/knowledge/ask", response_model=KnowledgeAskCreateOut)
def ask_knowledge(
    payload: KnowledgeAskIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> KnowledgeAskCreateOut:
    if payload.project_id and not db.query(Project.id).filter(Project.id == payload.project_id).first():
        raise HTTPException(status_code=404, detail="project not found")
    job = create_job(db, kind="knowledge_search", user=user, message="正在准备 grep 知识库")
    row = KnowledgeAskRun(
        question=payload.question,
        project_id=payload.project_id,
        created_by_user_id=user.id,
        job_id=job.id,
        status="running",
    )
    db.add(row)
    db.commit()
    background_tasks.add_task(_process_knowledge_ask, row.id, job.id, user.id)
    return KnowledgeAskCreateOut(id=row.id, job_id=job.id, status=row.status)


@router.get("/knowledge/runs/{run_id}", response_model=KnowledgeAskRunOut)
def get_knowledge_run(
    run_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> KnowledgeAskRunOut:
    row = db.query(KnowledgeAskRun).filter(KnowledgeAskRun.id == run_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="knowledge run not found")
    if row.created_by_user_id != user.id:
        raise HTTPException(status_code=403, detail="only the question owner can view this run")
    return _run_out(row)


async def _process_knowledge_ask(run_id: str, job_id: str, user_id: str) -> None:
    db = SessionLocal()
    try:
        row = db.query(KnowledgeAskRun).filter(KnowledgeAskRun.id == run_id).first()
        job = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
        user = db.query(User).filter(User.id == user_id).first()
        if not row or not job or not user:
            return
        update_job(db, job, status="running", progress_percent=25, message="正在用 grep 搜索项目语料")
        db.commit()
        await publish_job(job)
        hits = search_knowledge(db, user, query=row.question, project_id=row.project_id, limit=30)
        update_job(db, job, status="running", progress_percent=70, message="正在整理带证据的回答")
        db.commit()
        await publish_job(job)
        answer, citations, trace = answer_from_hits(row.question, hits)
        row.answer_md = answer
        row.citations_json = json.dumps(citations, ensure_ascii=False)
        row.trace_json = json.dumps(trace, ensure_ascii=False)
        row.status = "succeeded"
        update_job(db, job, status="succeeded", progress_percent=100, message="知识库问答已完成", result_ref=row.id)
        note = create_notification(
            db,
            user,
            type="knowledge_answer",
            title="知识库回答好了",
            body=row.question[:200],
            severity="normal",
            target_url=f"/knowledge?run_id={row.id}",
            project_id=row.project_id,
            dedupe_key=f"knowledge:{row.id}",
        )
        db.commit()
        await publish_job(job)
        await publish_notification(note)
    except Exception as exc:
        row = db.query(KnowledgeAskRun).filter(KnowledgeAskRun.id == run_id).first()
        job = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
        if row:
            row.status = "failed"
        if job:
            update_job(db, job, status="failed", progress_percent=100, message="知识库问答失败", error=f"{type(exc).__name__}: {exc}")
        db.commit()
        if job:
            await publish_job(job)
    finally:
        db.close()
