import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import settings
from db import engine
from models import Base
from routers import attachments as attachments_router
from routers import auth as auth_router
from routers import auto as auto_router
from routers import calendar as calendar_router
from routers import chat as chat_router
from routers import client_devices as client_devices_router
from routers import comments as comments_router
from routers import decompositions as decompositions_router
from routers import deliveries as deliveries_router
from routers import delivery_upload as delivery_upload_router
from routers import health as health_router
from routers import knowledge as knowledge_router
from routers import jobs as jobs_router
from routers import meetings as meetings_router
from routers import notifications as notifications_router
from routers import planning as planning_router
from routers import projects as projects_router
from routers import project_drive as project_drive_router
from routers import push as push_router
from routers import reminders as reminders_router
from routers import requirements as requirements_router
from routers import sync as sync_router
from routers import users as users_router
from routers import voice as voice_router
from routers import workspaces as workspaces_router
from db import SessionLocal
from services.partial_uploads import cleanup_stale_partials
from services.schema_migrations import ensure_runtime_schema

_logger = logging.getLogger(__name__)


async def _periodic_knowledge_reindex() -> None:
    """Background task: rebuild the knowledge corpus every 5 minutes.

    Previously the index was rebuilt on every /api/knowledge/search call
    (services/knowledge.py:350), which under any concurrent load became a
    self-DoS — every search walked every requirement / chat / comment etc.
    Moving the rebuild here means searches are fast and the index lags by
    at most 5 minutes. Admins can force-rebuild via POST /api/knowledge/reindex.
    """
    # Allow the app to fully boot before the first big scan.
    await asyncio.sleep(60)
    while True:
        try:
            from services.knowledge import rebuild_knowledge_index
            db = SessionLocal()
            try:
                rebuild_knowledge_index(db)
            finally:
                db.close()
        except Exception:
            _logger.exception("periodic knowledge reindex failed (will retry)")
        await asyncio.sleep(300)


async def _periodic_partial_cleanup() -> None:
    """Garbage-collect abandoned chunked uploads every 6 hours.

    Previously only ran once at boot — a server with multi-week uptime
    accumulated stale uploads (especially big drive / meeting files
    where users frequently cancel). Each abandoned upload can be GB-sized.
    """
    await asyncio.sleep(600)  # first sweep 10 minutes after boot
    while True:
        try:
            cleanup_stale_partials(settings.data_dir)
        except Exception:
            _logger.exception("periodic partial-upload cleanup failed")
        await asyncio.sleep(6 * 60 * 60)


async def _resume_stuck_jobs() -> None:
    """One-shot startup sweep: fail any background jobs that were left
    `running` by a previous process crash. Without this, requirements
    stuck in `ai_processing` / `delivery_doc_pending` (from auto.py /
    delivery_upload), meetings in `processing` (from meetings.py), and
    knowledge ASK runs in `running` (from knowledge.py) all stay stuck
    forever — no in-process worker owns them anymore.
    """
    from datetime import datetime, timedelta
    from models import BackgroundJob, KnowledgeAskRun, MeetingRecord, Requirement
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(minutes=15)
        stale_jobs = (
            db.query(BackgroundJob)
            .filter(BackgroundJob.status == "running", BackgroundJob.updated_at < cutoff)
            .all()
        )
        for j in stale_jobs:
            j.status = "failed"
            j.message = "process restarted while running"
            # If this job was driving a requirement transition, unfreeze
            # the requirement so the user can retry.
            if j.result_ref:
                req = db.query(Requirement).filter(Requirement.id == j.result_ref).first()
                if req and req.status in {"ai_processing", "delivery_doc_pending"}:
                    # ai_processing came from /auto-process; revert to ready
                    # (user can re-trigger). delivery_doc_pending came from
                    # delivery_upload finalize; revert to delivered (skip the
                    # AI doc — manual review still works).
                    req.status = "ready" if req.status == "ai_processing" else "delivered"

        # Meetings whose analyze-task was killed mid-stream.
        stale_meetings = (
            db.query(MeetingRecord)
            .filter(MeetingRecord.status == "processing", MeetingRecord.updated_at < cutoff)
            .all()
        )
        for m in stale_meetings:
            m.status = "failed"

        # Knowledge ASK runs that were polling LLM when process died.
        stale_asks = (
            db.query(KnowledgeAskRun)
            .filter(KnowledgeAskRun.status == "running", KnowledgeAskRun.updated_at < cutoff)
            .all()
        )
        for a in stale_asks:
            a.status = "failed"
            a.answer_md = (a.answer_md or "") + "\n\n（服务在生成回答时重启了，可以重新提问）"

        total = len(stale_jobs) + len(stale_meetings) + len(stale_asks)
        if total:
            db.commit()
            _logger.info(
                "resumed %d stuck record(s): %d jobs, %d meetings, %d asks",
                total, len(stale_jobs), len(stale_meetings), len(stale_asks),
            )
    except Exception:
        _logger.exception("startup stuck-job sweep failed")
    finally:
        db.close()


def _validate_runtime_config() -> None:
    if settings.app_env.lower() != "production":
        return
    if settings.cookie_secret in {"", "dev-change-me", "change-me-to-a-long-random-string"}:
        raise RuntimeError("COOKIE_SECRET must be set to a strong non-default value in production")
    if "*" in settings.cors_allow_origins:
        raise RuntimeError("CORS_ALLOW_ORIGINS must be explicit in production")


@asynccontextmanager
async def lifespan(_: FastAPI):
    _validate_runtime_config()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "uploads").mkdir(exist_ok=True)
    (settings.data_dir / "uploads" / "_partial").mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "voice").mkdir(exist_ok=True)
    (settings.data_dir / "outputs").mkdir(exist_ok=True)
    (settings.data_dir / "outputs" / "project_drive").mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "knowledge_corpus").mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "project_drive").mkdir(exist_ok=True)
    (settings.data_dir / "project_drive" / "_partial").mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "deliveries").mkdir(exist_ok=True)
    (settings.data_dir / "deliveries" / "_partial").mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "auto").mkdir(exist_ok=True)
    Base.metadata.create_all(engine)
    ensure_runtime_schema(engine)
    cleanup_stale_partials(settings.data_dir)
    # Recover from any crash that left background jobs stuck in `running`.
    await _resume_stuck_jobs()
    # Periodic background tasks.
    reindex_task = asyncio.create_task(_periodic_knowledge_reindex())
    cleanup_task = asyncio.create_task(_periodic_partial_cleanup())
    try:
        yield
    finally:
        for t in (reindex_task, cleanup_task):
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass


app = FastAPI(title="需求管理大师", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(projects_router.router)
app.include_router(client_devices_router.router)
app.include_router(project_drive_router.router)
app.include_router(requirements_router.router)
app.include_router(attachments_router.router)
app.include_router(chat_router.router)
app.include_router(voice_router.router)
app.include_router(sync_router.router)
app.include_router(push_router.router)
app.include_router(auto_router.router)
app.include_router(comments_router.router)
app.include_router(deliveries_router.router)
app.include_router(delivery_upload_router.router)
app.include_router(users_router.router)
app.include_router(calendar_router.router)
app.include_router(reminders_router.router)
app.include_router(jobs_router.router)
app.include_router(workspaces_router.router)
app.include_router(meetings_router.router)
app.include_router(decompositions_router.router)
app.include_router(knowledge_router.router)
app.include_router(planning_router.router)
app.include_router(notifications_router.router)
app.include_router(health_router.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": "yqgl", "version": app.version}


CLIENT_ROOT = Path(__file__).resolve().parents[1] / "client"
CLIENT_FILES = {
    "install.ps1": "install-client.ps1",
    "install.sh": "install-client.sh",
    "launch.ps1": "launch.ps1",
    "launch.sh": "launch.sh",
    "yqgl_tray.py": "yqgl_tray.py",
    "yqgl_dashboard.py": "yqgl_dashboard.py",
    "requirements.txt": "requirements.txt",
}


@app.get("/client/{name}")
def client_file(name: str):
    filename = CLIENT_FILES.get(name)
    if not filename:
        raise HTTPException(status_code=404)
    path = CLIENT_ROOT / filename
    if not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(path)


# ───── Desktop client installer downloads ─────────────────────────────
# Looks for installers in /srv/yqgl/downloads/ (mirrored from local CI), plus
# an optional GitHub Release URL for the macOS universal client.
DOWNLOADS_ROOT = Path("/srv/yqgl/downloads")
if DOWNLOADS_ROOT.is_dir():
    app.mount("/downloads", StaticFiles(directory=DOWNLOADS_ROOT), name="downloads")


def _download_entry(
    *,
    id: str,
    label: str,
    filename: str | None = None,
    fallback_url: str = "",
    fallback_size: int = 0,
    note: str = "",
) -> dict | None:
    if filename:
        target = DOWNLOADS_ROOT / filename
        if target.exists():
            stat = target.stat()
            return {
                "id": id,
                "label": label,
                "url": f"/downloads/{filename}",
                "size_bytes": stat.st_size,
                "mtime": stat.st_mtime,
                "external": False,
                "note": note,
            }
    if fallback_url:
        return {
            "id": id,
            "label": label,
            "url": fallback_url,
            "size_bytes": fallback_size,
            "mtime": 0,
            "external": True,
            "note": note,
        }
    return None


@app.get("/api/downloads/manifest")
def downloads_manifest() -> dict:
    """Installer manifest for the web banner.

    The legacy top-level fields still point to the first available installer so
    older clients remain harmless while the new web UI renders platform cards.
    """
    platforms = [
        entry for entry in [
            _download_entry(
                id="windows",
                label="Windows",
                filename="yqgl-client-setup.exe",
                note="本地工作台 + 托盘常驻",
            ),
            _download_entry(
                id="macos",
                label="macOS",
                filename="yqgl-client-macos-universal-unsigned.dmg",
                fallback_url=settings.macos_client_download_url,
                fallback_size=settings.macos_client_size_bytes,
                note="Universal 未签名测试包",
            ),
        ]
        if entry
    ]
    if not platforms:
        return {"available": False, "platforms": []}
    primary = platforms[0]
    version_key = "|".join(f"{p['id']}:{p.get('mtime') or p['url']}" for p in platforms)
    return {
        "available": True,
        "url": primary["url"],
        "size_bytes": primary.get("size_bytes", 0),
        "mtime": primary.get("mtime", 0),
        "version_key": version_key,
        "platforms": platforms,
    }


# ───── static frontend (vite build deployed to /srv/yqgl/web/dist) ─────
WEB_ROOT = Path("/srv/yqgl/web/dist")
if WEB_ROOT.is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_ROOT / "assets"), name="assets")

    @app.get("/")
    @app.get("/{full_path:path}")
    async def spa_fallback(request: Request, full_path: str = ""):
        # Don't swallow unknown API / asset / download / client paths into
        # the SPA — a missing /downloads/foo.exe should 404, not return
        # index.html (which the browser then tries to execute, presenting
        # a nonsense error to the user).
        if (
            full_path.startswith("api/")
            or full_path.startswith("assets/")
            or full_path.startswith("downloads/")
            or full_path.startswith("client/")
        ):
            raise HTTPException(status_code=404)
        idx = WEB_ROOT / "index.html"
        if idx.exists():
            return FileResponse(idx, media_type="text/html")
        raise HTTPException(status_code=404)
else:
    @app.get("/")
    def root() -> dict:
        return {
            "name": "需求管理大师",
            "api": "/api/health",
            "note": "web/dist 未部署；前端走开发服务器 (cd web && npm run dev)",
        }
