from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.orm import Session, selectinload

from auth import current_user
from config import settings
from db import SessionLocal, get_db
from models import BackgroundJob, MeetingInsight, MeetingRecord, Project, Requirement, User
from schemas import (
    MeetingChunkInitIn,
    MeetingChunkInitOut,
    MeetingInsightOut,
    MeetingOut,
    MeetingPatchIn,
)
from services.jobs import create_job, publish_job, update_job
from services.meeting_agent import analyze_meeting
from services.permissions import can_view_requirement_record
from services.push_bus import bus

router = APIRouter(prefix="/api", tags=["meetings"])

CHUNK_SIZE = 5 * 1024 * 1024
MAX_BYTES = 1024 * 1024 * 1024


def _partial_dir(upload_id: str) -> Path:
    return settings.data_dir / "meetings" / "_partial" / upload_id


def _meta_path(upload_id: str) -> Path:
    return _partial_dir(upload_id) / "_meta.json"


def _meeting_dir(project_id: str, meeting_id: str) -> Path:
    d = settings.data_dir / "meetings" / project_id / meeting_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _expected_chunks(total_size: int) -> int:
    return max(1, (total_size + CHUNK_SIZE - 1) // CHUNK_SIZE)


def _expected_chunk_size(meta: dict[str, Any], idx: int) -> int:
    if idx < meta["total_chunks"] - 1:
        return CHUNK_SIZE
    return meta["total_size"] - (CHUNK_SIZE * (meta["total_chunks"] - 1))


def _require_project(db: Session, project_id: str) -> Project:
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.archived == False,  # noqa: E712
        Project.deleted_at.is_(None),
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    return project


def _require_meeting(db: Session, meeting_id: str) -> MeetingRecord:
    meeting = (
        db.query(MeetingRecord)
        .options(selectinload(MeetingRecord.uploaded_by))
        .filter(MeetingRecord.id == meeting_id)
        .first()
    )
    if not meeting:
        raise HTTPException(status_code=404, detail="meeting not found")
    _require_project(db, meeting.project_id)
    return meeting


def _insight_out(insight: MeetingInsight) -> MeetingInsightOut:
    return MeetingInsightOut(
        id=insight.id,
        meeting_id=insight.meeting_id,
        kind=insight.kind,
        title=insight.title,
        description=insight.description,
        target_requirement_id=insight.target_requirement_id,
        confidence_reason=insight.confidence_reason,
        status=insight.status,
        created_requirement_id=insight.created_requirement_id,
        created_at=insight.created_at,
        updated_at=insight.updated_at,
    )


def _meeting_out(db: Session, meeting: MeetingRecord) -> MeetingOut:
    insights = (
        db.query(MeetingInsight)
        .filter(MeetingInsight.meeting_id == meeting.id)
        .order_by(MeetingInsight.created_at.asc())
        .all()
    )
    return MeetingOut(
        id=meeting.id,
        project_id=meeting.project_id,
        requirement_id=meeting.requirement_id,
        title=meeting.title,
        audio_filename=meeting.audio_filename,
        audio_mime=meeting.audio_mime,
        audio_size_bytes=meeting.audio_size_bytes,
        transcript_text=meeting.transcript_text,
        minutes_md=meeting.minutes_md,
        status=meeting.status,
        job_id=meeting.job_id,
        uploaded_by_nickname=meeting.uploaded_by.nickname if meeting.uploaded_by else "unknown",
        insights=[_insight_out(row) for row in insights],
        created_at=meeting.created_at,
        updated_at=meeting.updated_at,
    )


@router.get("/projects/{project_id}/meetings", response_model=list[MeetingOut])
def list_meetings(project_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)) -> list[MeetingOut]:
    _require_project(db, project_id)
    rows = (
        db.query(MeetingRecord)
        .options(selectinload(MeetingRecord.uploaded_by))
        .filter(MeetingRecord.project_id == project_id)
        .order_by(MeetingRecord.created_at.desc())
        .limit(100)
        .all()
    )
    return [_meeting_out(db, row) for row in rows]


@router.post("/projects/{project_id}/meetings/upload/init", response_model=MeetingChunkInitOut)
def init_meeting_upload(
    project_id: str,
    payload: MeetingChunkInitIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> MeetingChunkInitOut:
    _require_project(db, project_id)
    if payload.total_size > MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"file too large (>{MAX_BYTES} bytes)")
    if payload.total_chunks != _expected_chunks(payload.total_size):
        raise HTTPException(status_code=400, detail="total_chunks does not match configured chunk size")
    if payload.requirement_id:
        req = db.query(Requirement).filter(Requirement.id == payload.requirement_id, Requirement.project_id == project_id).first()
        if not req or not can_view_requirement_record(req, user):
            raise HTTPException(status_code=400, detail="requirement_id must belong to this project")
    upload_id = uuid.uuid4().hex
    pdir = _partial_dir(upload_id)
    pdir.mkdir(parents=True, exist_ok=True)
    _meta_path(upload_id).write_text(
        json.dumps({
            "project_id": project_id,
            "filename": Path(payload.filename).name or "meeting.webm",
            "total_size": payload.total_size,
            "total_chunks": payload.total_chunks,
            "mime": payload.mime,
            "title": payload.title,
            "requirement_id": payload.requirement_id,
            "user_id": user.id,
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    return MeetingChunkInitOut(upload_id=upload_id, chunk_size=CHUNK_SIZE)


@router.put("/projects/{project_id}/meetings/upload/{upload_id}/chunk/{idx}")
async def upload_meeting_chunk(
    project_id: str,
    upload_id: str,
    idx: int,
    request: Request,
    user: User = Depends(current_user),
) -> dict:
    pdir = _partial_dir(upload_id)
    if not pdir.exists():
        raise HTTPException(status_code=404, detail="unknown upload_id")
    meta = json.loads(_meta_path(upload_id).read_text(encoding="utf-8"))
    if meta["project_id"] != project_id:
        raise HTTPException(status_code=400, detail="upload_id does not match project")
    if meta.get("user_id") != user.id:
        raise HTTPException(status_code=403, detail="only the upload owner can send chunks")
    if idx < 0 or idx >= meta["total_chunks"]:
        raise HTTPException(status_code=400, detail="chunk index out of range")
    target = pdir / f"{idx:06d}.bin"
    if target.exists():
        raise HTTPException(status_code=409, detail="chunk already uploaded")
    expected_size = _expected_chunk_size(meta, idx)
    written = 0
    h = hashlib.sha256()
    try:
        with open(target, "wb") as f:
            async for piece in request.stream():
                if written + len(piece) > expected_size:
                    raise HTTPException(status_code=413, detail="chunk too large")
                f.write(piece)
                h.update(piece)
                written += len(piece)
    except HTTPException:
        target.unlink(missing_ok=True)
        raise
    if written != expected_size:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"chunk size mismatch: got {written}, expected {expected_size}")
    return {"idx": idx, "bytes": written, "sha256": h.hexdigest()}


@router.post("/projects/{project_id}/meetings/upload/{upload_id}/finalize", response_model=MeetingOut)
def finalize_meeting_upload(
    project_id: str,
    upload_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> MeetingOut:
    project = _require_project(db, project_id)
    pdir = _partial_dir(upload_id)
    if not pdir.exists():
        raise HTTPException(status_code=404, detail="unknown upload_id")
    meta = json.loads(_meta_path(upload_id).read_text(encoding="utf-8"))
    if meta["project_id"] != project_id:
        raise HTTPException(status_code=400, detail="upload_id does not match project")
    if meta.get("user_id") != user.id:
        raise HTTPException(status_code=403, detail="only the upload owner can finalize this upload")
    chunks = sorted(p for p in pdir.iterdir() if p.suffix == ".bin")
    if len(chunks) != meta["total_chunks"]:
        raise HTTPException(status_code=400, detail=f"missing chunks: have {len(chunks)}, expected {meta['total_chunks']}")

    job = create_job(db, kind="meeting_minutes", user=user, message="会议录音已上传，等待转写")
    meeting = MeetingRecord(
        project_id=project_id,
        requirement_id=meta.get("requirement_id"),
        uploaded_by_user_id=user.id,
        title=(meta.get("title") or Path(meta["filename"]).stem or "会议纪要")[:256],
        audio_filename=meta["filename"],
        audio_mime=meta.get("mime"),
        audio_size_bytes=meta["total_size"],
        audio_path="",
        status="processing",
        job_id=job.id,
    )
    db.add(meeting)
    db.flush()
    out_path = _meeting_dir(project_id, meeting.id) / meta["filename"]
    total = 0
    with open(out_path, "wb") as out:
        for idx, chunk in enumerate(chunks):
            expected_size = _expected_chunk_size(meta, idx)
            if chunk.stat().st_size != expected_size:
                raise HTTPException(status_code=400, detail=f"chunk {idx} size mismatch")
            with open(chunk, "rb") as src:
                while True:
                    buf = src.read(1024 * 1024)
                    if not buf:
                        break
                    out.write(buf)
                    total += len(buf)
    if total != meta["total_size"]:
        out_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"size mismatch: got {total}, expected {meta['total_size']}")
    meeting.audio_path = str(out_path)
    update_job(db, job, status="running", progress_percent=10, message="准备转写会议录音", result_ref=meeting.id)
    db.commit()
    db.refresh(meeting)
    shutil.rmtree(pdir, ignore_errors=True)
    background_tasks.add_task(_process_meeting_background, meeting.id, job.id)
    return _meeting_out(db, meeting)


async def _process_meeting_background(meeting_id: str, job_id: str) -> None:
    # Must be `async def` (NOT sync wrapping `asyncio.run`). The previous
    # sync version was scheduled by FastAPI into a worker thread, and
    # `asyncio.run` inside it built a SECOND event loop. Any `await
    # bus.publish(...)` from `_process_meeting` then tried to put events
    # into asyncio.Queue / asyncio.Lock objects that belonged to the MAIN
    # loop → cross-loop RuntimeError, silently swallowed. UI never saw
    # `meeting.ready` etc. Async background tasks run on the request's
    # original loop, so bus operations target the right queues.
    await _process_meeting(meeting_id, job_id)


async def _process_meeting(meeting_id: str, job_id: str) -> None:
    db = SessionLocal()
    try:
        meeting = db.query(MeetingRecord).filter(MeetingRecord.id == meeting_id).first()
        job = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
        if not meeting or not job:
            return
        update_job(db, job, status="running", progress_percent=25, message="正在转写会议录音")
        db.commit()
        await publish_job(job)

        transcript = await _transcribe_or_decode(meeting)
        meeting.transcript_text = transcript
        update_job(db, job, status="running", progress_percent=60, message="正在整理会议纪要")
        db.commit()
        await publish_job(job)

        project = db.query(Project).filter(Project.id == meeting.project_id).first()
        req = db.query(Requirement).filter(Requirement.id == meeting.requirement_id).first() if meeting.requirement_id else None
        analysis = await analyze_meeting(
            project_name=project.name if project else "unknown",
            transcript=transcript,
            linked_requirement_title=req.title if req else None,
        )
        meeting.minutes_md = analysis.minutes_md
        meeting.status = "ready"
        db.query(MeetingInsight).filter(MeetingInsight.meeting_id == meeting.id).delete()
        for decision in analysis.insights:
            db.add(MeetingInsight(
                meeting_id=meeting.id,
                kind=decision.kind,
                title=decision.title[:256] or "会议后续",
                description=decision.description or decision.title,
                target_requirement_id=meeting.requirement_id if decision.kind == "requirement_change" else None,
                confidence_reason=decision.confidence_reason,
                status="pending",
            ))
        update_job(db, job, status="succeeded", progress_percent=100, message="会议纪要已生成", result_ref=meeting.id)
        db.commit()
        await publish_job(job)
        await bus.publish("all", "meeting.ready", {"meeting_id": meeting.id, "project_id": meeting.project_id})
    except Exception as exc:
        meeting = db.query(MeetingRecord).filter(MeetingRecord.id == meeting_id).first()
        job = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
        if meeting:
            meeting.status = "failed"
        if job:
            update_job(db, job, status="failed", progress_percent=100, message="会议处理失败", error=f"{type(exc).__name__}: {exc}")
        db.commit()
        if job:
            await publish_job(job)
    finally:
        db.close()


async def _transcribe_or_decode(meeting: MeetingRecord) -> str:
    """Send the meeting audio to ASR. Streams from disk so a 1 GB recording
    doesn't get fully buffered into RAM (which would OOM the worker)."""
    path = Path(meeting.audio_path)
    try:
        # httpx supports passing an open file handle in `files`; it streams
        # the multipart body without buffering the whole file.
        async with httpx.AsyncClient(timeout=90.0) as client:
            with open(path, "rb") as fh:
                files = {"audio": (meeting.audio_filename, fh, meeting.audio_mime or "audio/webm")}
                resp = await client.post(f"{settings.asr_base_url}/transcribe", files=files)
        if resp.status_code == 200:
            payload = resp.json()
            text = str(payload.get("text") or "").strip()
            if text:
                return text
    except Exception:
        pass
    # Plain-text fallback — read up to 1 MB only; if the file is actually
    # binary audio we don't try to decode the whole thing.
    try:
        with open(path, "rb") as fh:
            sample = fh.read(1024 * 1024)
        decoded = sample.decode("utf-8", errors="ignore").strip()
        if decoded:
            return decoded
    except Exception:
        pass
    return "ASR 服务暂时不可用，且录音无法直接解码。请人工补充会议转写文本后重新确认纪要。"


@router.get("/meetings/{meeting_id}", response_model=MeetingOut)
def get_meeting(meeting_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)) -> MeetingOut:
    return _meeting_out(db, _require_meeting(db, meeting_id))


@router.patch("/meetings/{meeting_id}", response_model=MeetingOut)
def patch_meeting(
    meeting_id: str,
    payload: MeetingPatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> MeetingOut:
    meeting = _require_meeting(db, meeting_id)
    if meeting.uploaded_by_user_id != user.id:
        raise HTTPException(status_code=403, detail="only the uploader can edit this meeting")
    if payload.title is not None:
        meeting.title = payload.title.strip()
    if "transcript_text" in payload.model_fields_set:
        meeting.transcript_text = payload.transcript_text
    if "minutes_md" in payload.model_fields_set:
        meeting.minutes_md = payload.minutes_md
    db.commit()
    db.refresh(meeting)
    return _meeting_out(db, meeting)


@router.post("/meeting-insights/{insight_id}/confirm", response_model=MeetingInsightOut)
async def confirm_meeting_insight(
    insight_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> MeetingInsightOut:
    insight = db.query(MeetingInsight).filter(MeetingInsight.id == insight_id).first()
    if not insight:
        raise HTTPException(status_code=404, detail="meeting insight not found")
    meeting = insight.meeting
    if meeting.uploaded_by_user_id != user.id:
        raise HTTPException(status_code=403, detail="only the meeting uploader can confirm this insight")
    if insight.status != "pending":
        return _insight_out(insight)
    _require_project(db, meeting.project_id)
    # Atomic CAS — double-click on "confirm" would otherwise pass the
    # `!= "pending"` check twice, both bump project.next_seq, both
    # insert duplicate Requirement rows (one 500s on uq constraint, but
    # the user-visible effect is unpredictable).
    from sqlalchemy import update as sql_update
    cas = db.execute(
        sql_update(MeetingInsight)
        .where(MeetingInsight.id == insight_id, MeetingInsight.status == "pending")
        .values(status="confirmed", confirmed_by_user_id=user.id, confirmed_at=datetime.utcnow())
    )
    if cas.rowcount == 0:
        db.rollback()
        # Someone else won the race — return the latest state.
        db.refresh(insight)
        return _insight_out(insight)
    # Persist the state transition before creating the draft requirement.
    # If the later requirement-code allocation hits an IntegrityError and
    # rolls back, the insight must not become pending again.
    db.commit()
    insight = db.query(MeetingInsight).filter(MeetingInsight.id == insight_id).first()
    if not insight:
        raise HTTPException(status_code=404, detail="meeting insight not found")
    if insight.kind in {"new_requirement", "requirement_change"}:
        # Retry on next_seq race with another insight-confirm / requirement-
        # create / drive-comment running in parallel. Without this, concurrent
        # confirms can both compute the same `SLUG-NNN` and one 500s on the
        # `code` UNIQUE constraint — user clicks "确认" and sees a generic
        # error, never knowing the request actually completed for someone else.
        from sqlalchemy.exc import IntegrityError
        last_err: Exception | None = None
        for _ in range(5):
            project = _require_project(db, meeting.project_id)
            project.next_seq += 1
            code = f"{project.slug.upper()}-{project.next_seq:03d}"
            req = Requirement(
                code=code,
                project_id=project.id,
                submitter_user_id=user.id,
                title=insight.title,
                raw_description=(
                    f"来源会议：{meeting.title}\n"
                    f"会议 ID：{meeting.id}\n\n"
                    f"{insight.description}\n\n"
                    "请进入需求评估和澄清流程，确认这是否应该成为明确需求。"
                ),
                priority="normal",
                status="draft",
                source_meeting_id=meeting.id,
                source_requirement_id=insight.target_requirement_id,
            )
            db.add(req)
            try:
                db.flush()
                insight.created_requirement_id = req.id
                break
            except IntegrityError as e:
                db.rollback()
                last_err = e
                # Re-load insight after rollback since rollback wipes ORM state.
                insight = db.query(MeetingInsight).filter(MeetingInsight.id == insight_id).first()
                if not insight:
                    raise HTTPException(status_code=404, detail="meeting insight not found")
        else:
            raise HTTPException(status_code=500, detail=f"could not allocate requirement code: {last_err}")
    # status/confirmed_by/confirmed_at were already set atomically by the
    # CAS above; just commit any insight.created_requirement_id update.
    db.commit()
    db.refresh(insight)
    await bus.publish("all", "meeting.insight_confirmed", {
        "meeting_id": meeting.id,
        "insight_id": insight.id,
        "created_requirement_id": insight.created_requirement_id,
    })
    return _insight_out(insight)


@router.post("/meeting-insights/{insight_id}/dismiss", response_model=MeetingInsightOut)
def dismiss_meeting_insight(
    insight_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> MeetingInsightOut:
    insight = db.query(MeetingInsight).filter(MeetingInsight.id == insight_id).first()
    if not insight:
        raise HTTPException(status_code=404, detail="meeting insight not found")
    if insight.meeting.uploaded_by_user_id != user.id:
        raise HTTPException(status_code=403, detail="only the meeting uploader can dismiss this insight")
    if insight.status == "pending":
        insight.status = "dismissed"
        insight.confirmed_by_user_id = user.id
        insight.confirmed_at = datetime.utcnow()
        db.commit()
        db.refresh(insight)
    return _insight_out(insight)
