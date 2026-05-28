from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import current_user
from db import get_db
from models import BackgroundJob, User
from schemas import BackgroundJobOut
from services.jobs import job_out
from services.permissions import is_admin

router = APIRouter(prefix="/api", tags=["jobs"])


@router.get("/jobs/{job_id}", response_model=BackgroundJobOut)
def get_job(job_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> BackgroundJobOut:
    job = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if job.created_by_user_id != user.id and not is_admin(user):
        raise HTTPException(status_code=403, detail="only the job creator or admins can view this job")
    return job_out(job)
