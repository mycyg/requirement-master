from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import current_user
from db import get_db
from models import BackgroundJob, MeetingRecord, Project, Requirement, User
from schemas import BackgroundJobOut
from services.jobs import job_out
from services.permissions import can_view_requirement_record, is_admin

router = APIRouter(prefix="/api", tags=["jobs"])


def _can_view_job(db: Session, job: BackgroundJob, user: User) -> bool:
    """Job visibility goes beyond the creator: anyone with access to the
    underlying resource (requirement / meeting / project) should be able to
    poll progress. Otherwise the lead assignee waiting on a decomposition
    plan or a meeting collaborator watching the analysis job get 403 and
    the UI shows a perpetual spinner.
    """
    if is_admin(user):
        return True
    if job.created_by_user_id == user.id:
        return True
    if not job.result_ref:
        return False
    # Decomposition / auto-process jobs: result_ref is the requirement id.
    req = db.query(Requirement).filter(Requirement.id == job.result_ref).first()
    if req is not None:
        return can_view_requirement_record(req, user)
    # Meeting jobs: result_ref is the meeting id; visibility = any auth user
    # who can see the project (we don't have a stricter membership model).
    meeting = db.query(MeetingRecord).filter(MeetingRecord.id == job.result_ref).first()
    if meeting is not None:
        project = db.query(Project).filter(
            Project.id == meeting.project_id,
            Project.deleted_at.is_(None),
        ).first()
        return project is not None
    return False


@router.get("/jobs/{job_id}", response_model=BackgroundJobOut)
def get_job(job_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> BackgroundJobOut:
    job = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if not _can_view_job(db, job, user):
        raise HTTPException(status_code=403, detail="you cannot view this job")
    return job_out(job)
