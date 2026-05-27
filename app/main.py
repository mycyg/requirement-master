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
from routers import chat as chat_router
from routers import comments as comments_router
from routers import deliveries as deliveries_router
from routers import delivery_upload as delivery_upload_router
from routers import projects as projects_router
from routers import project_drive as project_drive_router
from routers import push as push_router
from routers import requirements as requirements_router
from routers import sync as sync_router
from routers import users as users_router
from routers import voice as voice_router
from services.partial_uploads import cleanup_stale_partials
from services.schema_migrations import ensure_runtime_schema


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
    (settings.data_dir / "project_drive").mkdir(exist_ok=True)
    (settings.data_dir / "project_drive" / "_partial").mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "deliveries").mkdir(exist_ok=True)
    (settings.data_dir / "deliveries" / "_partial").mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "auto").mkdir(exist_ok=True)
    Base.metadata.create_all(engine)
    ensure_runtime_schema(engine)
    cleanup_stale_partials(settings.data_dir)
    yield


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


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": "yqgl", "version": app.version}


# ───── static frontend (vite build deployed to /srv/yqgl/web/dist) ─────
WEB_ROOT = Path("/srv/yqgl/web/dist")
if WEB_ROOT.is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_ROOT / "assets"), name="assets")

    @app.get("/")
    @app.get("/{full_path:path}")
    async def spa_fallback(request: Request, full_path: str = ""):
        if full_path.startswith("api/") or full_path.startswith("assets/"):
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
