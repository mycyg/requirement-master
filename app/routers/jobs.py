from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import current_user
from db import get_db
from models import BackgroundJob, User
from schemas import BackgroundJobOut
from services.jobs import job_out

router = APIRouter(prefix="/api", tags=["jobs"])


@router.get("/jobs/{job_id}", response_model=BackgroundJobOut)
def get_job(job_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)) -> BackgroundJobOut:
    job = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job_out(job)
