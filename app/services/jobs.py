from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from models import BackgroundJob, User
from schemas import BackgroundJobOut
from services.push_bus import bus


def job_out(job: BackgroundJob) -> BackgroundJobOut:
    return BackgroundJobOut(
        id=job.id,
        kind=job.kind,
        status=job.status,
        progress_percent=job.progress_percent,
        message=job.message,
        result_ref=job.result_ref,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


def create_job(db: Session, *, kind: str, user: User, message: str = "排队中") -> BackgroundJob:
    job = BackgroundJob(
        kind=kind,
        status="queued",
        progress_percent=0,
        message=message,
        created_by_user_id=user.id,
    )
    db.add(job)
    db.flush()
    return job


def update_job(
    db: Session,
    job: BackgroundJob,
    *,
    status: str | None = None,
    progress_percent: int | None = None,
    message: str | None = None,
    result_ref: str | None = None,
    error: str | None = None,
) -> BackgroundJob:
    now = datetime.utcnow()
    if status is not None:
        job.status = status
        if status == "running" and not job.started_at:
            job.started_at = now
        if status in {"succeeded", "failed"}:
            job.finished_at = now
    if progress_percent is not None:
        job.progress_percent = max(0, min(100, int(progress_percent)))
    if message is not None:
        job.message = message
    if result_ref is not None:
        job.result_ref = result_ref
    if error is not None:
        job.error = error
    job.updated_at = now
    db.flush()
    return job


async def publish_job(job: BackgroundJob) -> None:
    """Publish job updates ONLY to (a) the per-job topic for callers
    polling a specific job, and (b) the owner's user channel so their
    desktop client can react. We deliberately do NOT publish to the
    global `all` topic — that would leak `result_ref` (= requirement_id),
    progress, and message text to every connected user, same class of
    cross-user info disclosure as the notification leak fixed earlier."""
    data = job_out(job).model_dump(mode="json")
    await bus.publish(f"job:{job.id}", "job.updated", data)
    if job.created_by_user_id:
        await bus.publish(f"user:{job.created_by_user_id}", "job.updated", data)
