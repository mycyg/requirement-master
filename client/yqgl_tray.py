r"""需求管理大师 · 托盘客户端 (Windows)

后台职责：
  1. 维持 SSE 长连接 (/api/push/stream)
  2. 收到 requirement.ready / revision.requested 时：
     - 拉 sync-manifest
     - 下载文件到 <sync_root>\<project_slug>\<code>\
     - Windows 通知
  3. 托盘菜单 "完成任务" → 选 req → zip 整目录 → 分片上传 → 服务端 LLM 写交付文档
  4. 托盘菜单 "打开主界面" → 在浏览器开主 web app

配置：%APPDATA%\yqgl\config.json
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import platform
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any, Callable
from urllib.parse import urlparse, urlunparse

import httpx
from PIL import Image, ImageDraw
import pystray

# ───────────────────────── config ─────────────────────────

APP_NAME = "yqgl"
APP_DIR = Path(os.environ.get("APPDATA", str(Path.home() / ".config"))) / APP_NAME
CONFIG_PATH = APP_DIR / "config.json"
DEFAULT_SYNC_ROOT = Path("D:/工作需求")
DEFAULT_SERVER_SCHEME = "http"
DEFAULT_SERVER_IP = "192.168.5.53"
DEFAULT_SERVER_PORT = 8080
DEFAULT_SERVER_URL = f"{DEFAULT_SERVER_SCHEME}://{DEFAULT_SERVER_IP}:{DEFAULT_SERVER_PORT}"
LEGACY_LAN_PREFIX = "192.168.0."
TARGET_LAN_PREFIX = "192.168.5."


@dataclass
class Config:
    server_url: str = DEFAULT_SERVER_URL
    server_ip: str = DEFAULT_SERVER_IP
    server_port: int = DEFAULT_SERVER_PORT
    server_scheme: str = DEFAULT_SERVER_SCHEME
    nickname: str = ""
    cookie_token: str = ""           # signed cookie (yqgl_id) value
    client_token: str = ""
    client_device_id: str = ""
    client_device_name: str = field(default_factory=lambda: platform.node() or "本地工作台")
    sync_root: str = str(DEFAULT_SYNC_ROOT)
    project_save_root: str = str(DEFAULT_SYNC_ROOT)
    drive_sync_enabled: bool = False
    drive_sync_mode: str = "download"  # download | two_way
    drive_sync_root: str = str(DEFAULT_SYNC_ROOT / "项目网盘")
    drive_sync_cursor_by_project: dict[str, str] = field(default_factory=dict)
    propagate_local_deletes: bool = False
    availability_status: str = "free"  # free | busy | custom
    availability_text: str = ""
    reminder_offsets_minutes: list[int] = field(default_factory=lambda: [1440, 120, 0])
    known_reminders: dict[str, str] = field(default_factory=dict)
    known_notifications: dict[str, str] = field(default_factory=dict)
    tray_started_notice_shown: bool = False
    paused: bool = False
    known_reqs: dict[str, str] = field(default_factory=dict)  # req_id -> code (avoid duplicate downloads)
    known_revision_requests: dict[str, str] = field(default_factory=dict)  # req_id -> updated_at marker


def normalize_server_url(url: str) -> str:
    raw = (url or "").strip() or DEFAULT_SERVER_URL
    if "://" not in raw:
        raw = f"{DEFAULT_SERVER_SCHEME}://{raw}"
    parsed = urlparse(raw)
    if not parsed.hostname:
        raise ValueError("服务端地址缺少 IP 或主机名")
    host = parsed.hostname or ""
    if host.startswith(LEGACY_LAN_PREFIX):
        new_host = TARGET_LAN_PREFIX + host.rsplit(".", 1)[-1]
        netloc = parsed.netloc.replace(host, new_host, 1)
        parsed = parsed._replace(netloc=netloc)
    return urlunparse(parsed._replace(path=parsed.path.rstrip("/"), params="", query="", fragment="")).rstrip("/")


def _coerce_port(value: int | str | None) -> int:
    try:
        port = int(value if value not in (None, "") else DEFAULT_SERVER_PORT)
    except (TypeError, ValueError) as exc:
        raise ValueError("服务端端口必须是数字") from exc
    if port < 1 or port > 65535:
        raise ValueError("服务端端口必须在 1-65535 之间")
    return port


def server_parts_from_url(url: str) -> tuple[str, str, int]:
    normalized = normalize_server_url(url)
    parsed = urlparse(normalized)
    scheme = parsed.scheme or DEFAULT_SERVER_SCHEME
    host = parsed.hostname or DEFAULT_SERVER_IP
    port = parsed.port or (443 if scheme == "https" else DEFAULT_SERVER_PORT)
    return scheme, host, port


def build_server_url(server_ip: str, server_port: int | str, server_scheme: str = DEFAULT_SERVER_SCHEME) -> str:
    raw_ip = (server_ip or "").strip()
    if raw_ip.startswith(("http://", "https://")):
        return normalize_server_url(raw_ip)
    host = raw_ip or DEFAULT_SERVER_IP
    port = _coerce_port(server_port)
    scheme = (server_scheme or DEFAULT_SERVER_SCHEME).strip().lower()
    if scheme not in {"http", "https"}:
        scheme = DEFAULT_SERVER_SCHEME
    return normalize_server_url(urlunparse((scheme, f"{host}:{port}", "", "", "", "")))


def sync_server_fields(cfg: Config, *, prefer_parts: bool) -> Config:
    if prefer_parts:
        cfg.server_url = build_server_url(cfg.server_ip, cfg.server_port, cfg.server_scheme)
    else:
        cfg.server_url = normalize_server_url(cfg.server_url)
    cfg.server_scheme, cfg.server_ip, cfg.server_port = server_parts_from_url(cfg.server_url)
    return cfg


def sync_storage_fields(cfg: Config, source: str = "sync_root") -> Config:
    if source == "project_save_root" and cfg.project_save_root:
        cfg.sync_root = cfg.project_save_root
    else:
        cfg.project_save_root = cfg.sync_root
    if not cfg.drive_sync_root:
        cfg.drive_sync_root = str(Path(cfg.project_save_root) / "项目网盘")
    if cfg.drive_sync_mode not in {"download", "two_way"}:
        cfg.drive_sync_mode = "download"
    if cfg.availability_status not in {"free", "busy", "custom"}:
        cfg.availability_status = "free"
    return cfg


def load_config() -> Config:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.exists():
        try:
            d = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
            cfg = Config(**{**Config().__dict__, **d})
            sync_server_fields(cfg, prefer_parts=("server_ip" in d or "server_port" in d))
            sync_storage_fields(cfg, source="project_save_root" if "project_save_root" in d else "sync_root")
            return cfg
        except Exception:
            pass
    return Config()


def save_config(cfg: Config) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    sync_server_fields(cfg, prefer_parts=True)
    sync_storage_fields(cfg, source="sync_root")
    CONFIG_PATH.write_text(
        json.dumps(cfg.__dict__, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ───────────────────────── logging ─────────────────────────

LOG_PATH = APP_DIR / "client.log"


def log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ───────────────────────── notifications ─────────────────────────

def notify(title: str, message: str, on_click: Callable[[], None] | None = None) -> None:
    """Best-effort Windows toast. Falls back to console log on any failure."""
    try:
        from plyer import notification
        notification.notify(
            title=title, message=message[:200],
            app_name="需求管理大师", timeout=10,
        )
        log(f"notify: {title} — {message[:80]}")
        # plyer doesn't support click handlers; on Windows we lose it. The tray
        # menu still gives the user a way to access whatever changed.
        return
    except Exception as e:
        log(f"[warn] plyer notify failed: {e}")
    # last resort: tkinter dialog (blocks but visible)
    try:
        from tkinter import messagebox
        messagebox.showinfo(title, message)
    except Exception:
        pass


# ───────────────────────── HTTP / SSE client ─────────────────────────

class ServerClient:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        cookies = {"yqgl_id": cfg.cookie_token} if cfg.cookie_token else {}
        headers = {"X-YQGL-Client-Token": cfg.client_token} if cfg.client_token else {}
        self._client = httpx.Client(
            base_url=cfg.server_url, cookies=cookies, headers=headers, timeout=httpx.Timeout(60, read=None),
        )

    def close(self) -> None:
        try: self._client.close()
        except Exception: pass

    def identify(self, nickname: str) -> str:
        r = self._client.post("/api/auth/identify", json={"nickname": nickname})
        r.raise_for_status()
        cookie = r.cookies.get("yqgl_id", "")
        return cookie

    def register_client_device(self, device_name: str, platform_name: str | None = None) -> tuple[str, str]:
        r = self._client.post(
            "/api/client-devices/register",
            json={
                "device_name": (device_name or platform.node() or "本地工作台")[:128],
                "platform": (platform_name or platform.platform() or "unknown")[:64],
            },
        )
        r.raise_for_status()
        data = r.json()
        return data["device"]["id"], data["client_token"]

    def me(self) -> dict | None:
        try:
            r = self._client.get("/api/auth/me")
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

    def list_my_pending(self) -> list[dict]:
        try:
            r = self._client.get("/api/requirements", params={"status": "ready"})
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log(f"list_my_pending failed: {e}")
            return []

    def list_projects(self) -> list[dict]:
        r = self._client.get("/api/projects")
        r.raise_for_status()
        return r.json()

    def update_availability(self, status: str, text: str = "") -> None:
        r = self._client.put("/api/users/me/status", json={
            "availability_status": status,
            "availability_text": text or None,
        })
        r.raise_for_status()

    def due_reminders(self) -> list[dict]:
        r = self._client.get("/api/reminders/due")
        r.raise_for_status()
        return r.json()

    def unread_notifications(self) -> list[dict]:
        r = self._client.get("/api/notifications", params={"status": "unread"})
        r.raise_for_status()
        return r.json()

    def list_all_with_statuses(self, statuses: list[str], *, assigned_to_me: bool = False) -> list[dict]:
        out: list[dict] = []
        for s in statuses:
            try:
                params: dict[str, Any] = {"status": s}
                if assigned_to_me:
                    params["assigned_to_me"] = "true"
                r = self._client.get("/api/requirements", params=params)
                r.raise_for_status()
                out.extend(r.json())
            except Exception:
                pass
        return out

    def get_manifest(self, req_id: str) -> dict:
        r = self._client.get(f"/api/requirements/{req_id}/sync-manifest")
        r.raise_for_status()
        return r.json()

    def download_file(self, att_id: str, dest: Path) -> str:
        dest.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256()
        with self._client.stream("GET", f"/api/files/{att_id}") as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_bytes(chunk_size=128 * 1024):
                    f.write(chunk)
                    h.update(chunk)
        return h.hexdigest()

    def drive_manifest(self, project_id: str) -> dict:
        r = self._client.get(f"/api/projects/{project_id}/drive/manifest")
        r.raise_for_status()
        return r.json()

    def drive_download_file(self, item_id: str, dest: Path) -> str:
        dest.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256()
        with self._client.stream("GET", f"/api/drive/files/{item_id}/download") as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_bytes(chunk_size=128 * 1024):
                    f.write(chunk)
                    h.update(chunk)
        return h.hexdigest()

    def create_drive_folder(self, project_id: str, name: str, parent_id: str | None) -> dict:
        r = self._client.post(
            f"/api/projects/{project_id}/drive/folders",
            json={"name": name, "parent_id": parent_id},
        )
        if r.status_code == 409:
            listing = self._client.get(f"/api/projects/{project_id}/drive", params={"parent_id": parent_id})
            listing.raise_for_status()
            for item in listing.json().get("items", []):
                if item.get("name") == name and item.get("kind") == "folder":
                    return item
        r.raise_for_status()
        return r.json()

    def upload_drive_file(self, project_id: str, path: Path, parent_id: str | None, *, conflict: str = "rename", existing_item_id: str | None = None) -> dict:
        size = path.stat().st_size
        chunk_size = 5 * 1024 * 1024
        total_chunks = max(1, (size + chunk_size - 1) // chunk_size)
        mime, _ = mimetypes.guess_type(str(path))
        r = self._client.post(
            f"/api/projects/{project_id}/drive/upload/init",
            json={
                "filename": path.name,
                "total_size": size,
                "total_chunks": total_chunks,
                "mime": mime,
                "parent_id": parent_id,
                "conflict": conflict,
                "existing_item_id": existing_item_id,
            },
        )
        r.raise_for_status()
        init = r.json()
        upload_id = init.get("upload_id")
        if not upload_id and init.get("conflict") == "name_exists":
            return self.upload_drive_file(
                project_id,
                path,
                parent_id,
                conflict="rename",
                existing_item_id=init.get("existing_item", {}).get("id"),
            )
        if not upload_id:
            raise RuntimeError(f"drive upload init did not return upload_id: {init}")
        chunk_size = int(init.get("chunk_size") or chunk_size)
        with open(path, "rb") as f:
            for idx in range(total_chunks):
                buf = f.read(chunk_size)
                cr = self._client.put(
                    f"/api/projects/{project_id}/drive/upload/{upload_id}/chunk/{idx}",
                    content=buf,
                    headers={"Content-Type": "application/octet-stream"},
                )
                cr.raise_for_status()
        r = self._client.post(f"/api/projects/{project_id}/drive/upload/{upload_id}/finalize")
        r.raise_for_status()
        return r.json()

    def ack_sync(self, req_id: str) -> None:
        try:
            self._client.post(f"/api/requirements/{req_id}/sync-ack")
        except Exception as e:
            log(f"sync-ack failed for {req_id}: {e}")

    def upload_delivery(self, req_id: str, zip_path: Path,
                        progress: Callable[[int, int], None] | None = None) -> dict:
        """Init → chunk PUTs → finalize. Returns delivery dict."""
        size = zip_path.stat().st_size
        CHUNK = 5 * 1024 * 1024
        total_chunks = max(1, (size + CHUNK - 1) // CHUNK)

        r = self._client.post(
            f"/api/requirements/{req_id}/delivery/init",
            json={"filename": zip_path.name, "total_size": size, "total_chunks": total_chunks},
        )
        r.raise_for_status()
        upload_id = r.json()["upload_id"]

        sent = 0
        with open(zip_path, "rb") as f:
            for idx in range(total_chunks):
                buf = f.read(CHUNK)
                cr = self._client.put(
                    f"/api/requirements/{req_id}/delivery/{upload_id}/chunk/{idx}",
                    content=buf,
                    headers={"Content-Type": "application/octet-stream"},
                )
                cr.raise_for_status()
                sent += len(buf)
                if progress:
                    progress(sent, size)

        r = self._client.post(f"/api/requirements/{req_id}/delivery/{upload_id}/finalize")
        r.raise_for_status()
        return r.json()

    def stream_events(
        self,
        on_event: Callable[[str, Any], None],
        stop: threading.Event,
        on_state: Callable[[str], None] | None = None,
    ) -> None:
        """Long-poll SSE. Auto-reconnect with exponential backoff."""
        backoff = 1.0
        while not stop.is_set():
            try:
                if on_state:
                    on_state("connecting")
                with self._client.stream("GET", "/api/push/stream", timeout=None) as r:
                    r.raise_for_status()
                    backoff = 1.0
                    if on_state:
                        on_state("connected")
                    event = ""
                    data_lines: list[str] = []
                    for line in r.iter_lines():
                        if stop.is_set():
                            return
                        if line.startswith("event:"):
                            event = line[6:].strip()
                        elif line.startswith("data:"):
                            data_lines.append(line[5:].strip())
                        elif line == "":
                            if event:
                                raw = "\n".join(data_lines)
                                try: data = json.loads(raw)
                                except Exception: data = raw
                                try: on_event(event, data)
                                except Exception as e: log(f"on_event err: {e}")
                            event = ""
                            data_lines = []
            except Exception as e:
                if on_state:
                    on_state("offline")
                log(f"SSE disconnected: {e}; retry in {backoff:.0f}s")
                stop.wait(backoff)
                backoff = min(30.0, backoff * 2)


# ───────────────────────── sync logic ─────────────────────────

def sanitize(name: str) -> str:
    bad = '<>:"/\\|?*'
    return "".join("_" if c in bad else c for c in name).strip() or "untitled"


def sync_requirement(client: ServerClient, cfg: Config, req_id: str) -> Path:
    """Download all files for a requirement. Returns the dir path."""
    m = client.get_manifest(req_id)
    project_slug = sanitize(m.get("project_slug") or "unknown")
    code = sanitize(m.get("code") or req_id[:8])
    target = Path(cfg.sync_root) / project_slug / code
    target.mkdir(parents=True, exist_ok=True)

    # requirement.md
    (target / "requirement.md").write_text(
        f"# {m.get('title') or code}\n\n{m.get('summary_md') or ''}\n",
        encoding="utf-8",
    )
    # metadata.json
    meta_keep = {k: m.get(k) for k in (
        "code", "title", "submitter_nickname", "priority", "created_at",
        "raw_description", "chat", "assignees", "estimate_hours",
        "estimate_confidence", "planning_note", "acceptance_items", "task_plans",
    )}
    (target / "metadata.json").write_text(
        json.dumps(meta_keep, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    my_workspace = next(
        (w for w in m.get("workspaces", []) if (w.get("nickname") or "").lower() == (cfg.nickname or "").lower()),
        None,
    )
    if my_workspace:
        acceptance_md = "\n".join(
            f"- [ ] {item.get('title')}{f': {item.get('description')}' if item.get('description') else ''}"
            for item in m.get("acceptance_items", [])
        ) or "- 暂无验收标准"
        my_user_id = my_workspace.get("user_id")
        plan_lines: list[str] = []
        for plan in m.get("task_plans", []):
            if plan.get("stage") == "dispatch" or plan.get("target_user_id") == my_user_id:
                plan_lines.append(f"### {plan.get('stage')} · {plan.get('summary') or '已确认拆解'}")
                if plan.get("risks"):
                    plan_lines.append(f"\n风险：{plan.get('risks')}")
                for item in plan.get("items", []):
                    if item.get("type") == "task":
                        hours = f" · {item.get('estimate_hours')}h" if item.get("estimate_hours") is not None else ""
                        plan_lines.append(f"- [ ] {item.get('title')}{hours}")
                plan_lines.append("")
        plans_md = "\n".join(plan_lines).strip() or "- 暂无已确认拆解"
        items_md = "\n".join(
            f"- [{'x' if item.get('status') == 'done' else ' '}] {item.get('title')} ({item.get('status')})"
            for item in my_workspace.get("items", [])
        ) or "- 暂无清单"
        (target / "workspace.md").write_text(
            f"# 我的工作区\n\n"
            f"## 排期\n\n"
            f"- 估算工时：{m.get('estimate_hours') if m.get('estimate_hours') is not None else '未估'}\n"
            f"- 估算信心：{m.get('estimate_confidence') or '未知'}\n"
            f"- 计划备注：{m.get('planning_note') or '无'}\n\n"
            f"- 阶段：{my_workspace.get('phase') or '未开始'}\n"
            f"- 进度：{my_workspace.get('progress_percent') or 0}%\n"
            f"- 状态说明：{my_workspace.get('status_note') or '无'}\n"
            f"- 阻塞原因：{my_workspace.get('blocked_reason') or '无'}\n\n"
            f"## 验收标准\n\n{acceptance_md}\n\n"
            f"## 已确认拆解\n\n{plans_md}\n\n"
            f"## 清单\n\n{items_md}\n",
            encoding="utf-8",
        )
    # attachments/
    att_dir = target / "attachments"
    att_dir.mkdir(exist_ok=True)
    for f in m.get("files", []):
        dest = att_dir / sanitize(f["name"])
        actual_sha = client.download_file(f["id"], dest)
        if f.get("sha256") and actual_sha != f["sha256"]:
            log(f"[warn] sha256 mismatch for {dest}: {actual_sha} vs {f['sha256']}")

    client.ack_sync(req_id)
    log(f"synced {code} → {target}")
    cfg.known_reqs[req_id] = code
    save_config(cfg)
    return target


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            buf = f.read(1024 * 1024)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def drive_state_path(project_root: Path) -> Path:
    return project_root / ".yqgl-drive-state.json"


def load_drive_state(project_root: Path) -> dict:
    p = drive_state_path(project_root)
    if not p.exists():
        return {"items": {}, "paths": {}}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        d.setdefault("items", {})
        d.setdefault("paths", {})
        return d
    except Exception:
        return {"items": {}, "paths": {}}


def save_drive_state(project_root: Path, state: dict) -> None:
    project_root.mkdir(parents=True, exist_ok=True)
    drive_state_path(project_root).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_rel_path(path: str) -> Path:
    parts = [sanitize(part) for part in path.replace("\\", "/").split("/") if part and part != "."]
    return Path(*parts) if parts else Path()


def move_to_trash(project_root: Path, rel: Path) -> None:
    src = project_root / rel
    if not src.exists():
        return
    trash = project_root / ".yqgl-trash" / f"{int(time.time())}" / rel
    trash.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(trash))


def ensure_remote_folder(client: ServerClient, project_id: str, folder_parts: list[str], state: dict) -> str | None:
    parent_id: str | None = None
    current_path: list[str] = []
    for part in folder_parts:
        current_path.append(part)
        key = "/".join(current_path)
        known_id = state.get("paths", {}).get(key)
        item = state.get("items", {}).get(known_id or "")
        if known_id and item and item.get("kind") == "folder":
            parent_id = known_id
            continue
        created = client.create_drive_folder(project_id, part, parent_id)
        parent_id = created["id"]
        state.setdefault("paths", {})[key] = parent_id
        state.setdefault("items", {})[parent_id] = {
            "path": key,
            "kind": "folder",
            "sha256": None,
            "version_no": None,
            "updated_at": created.get("updated_at"),
        }
    return parent_id


def sync_project_drive_once(client: ServerClient, cfg: Config, project: dict) -> None:
    if not cfg.drive_sync_enabled:
        return
    manifest = client.drive_manifest(project["id"])
    project_slug = sanitize(manifest.get("project_slug") or project.get("slug") or project["id"][:8])
    project_root = Path(cfg.drive_sync_root) / project_slug
    state = load_drive_state(project_root)
    remote_by_path: dict[str, dict] = {}

    for item in manifest.get("items", []):
        rel = safe_rel_path(item.get("path") or item.get("name") or item["id"])
        rel_key = rel.as_posix()
        remote_by_path[rel_key] = item
        state.setdefault("paths", {})[rel_key] = item["id"]
        previous = state.setdefault("items", {}).get(item["id"], {})
        local = project_root / rel
        if item.get("deleted_at"):
            move_to_trash(project_root, rel)
            state["items"][item["id"]] = {**previous, **item}
            continue
        if item.get("kind") == "folder":
            local.mkdir(parents=True, exist_ok=True)
            state["items"][item["id"]] = {**previous, **item}
            continue
        local.parent.mkdir(parents=True, exist_ok=True)
        remote_sha = item.get("sha256")
        previous_sha = previous.get("sha256")
        local_changed = local.exists() and previous_sha and file_sha256(local) != previous_sha
        remote_changed = remote_sha and previous_sha and remote_sha != previous_sha
        if local_changed and remote_changed:
            conflict = local.with_name(f"{local.stem}.conflict-{int(time.time())}{local.suffix}")
            shutil.copy2(local, conflict)
        if (not local.exists()) or (remote_sha and file_sha256(local) != remote_sha):
            got = client.drive_download_file(item["id"], local)
            if remote_sha and got != remote_sha:
                log(f"[warn] drive sha mismatch {local}: {got} vs {remote_sha}")
        state["items"][item["id"]] = {**previous, **item}

    if cfg.drive_sync_mode == "two_way":
        for local in sorted(project_root.rglob("*")):
            if not local.is_file():
                continue
            rel = local.relative_to(project_root)
            rel_key = rel.as_posix()
            if rel.parts and rel.parts[0] in {".yqgl-trash"}:
                continue
            if local.name == ".yqgl-drive-state.json":
                continue
            if local.stat().st_size <= 0:
                continue
            remote = remote_by_path.get(rel_key)
            local_sha = file_sha256(local)
            if remote and remote.get("sha256") == local_sha:
                continue
            parent_id = ensure_remote_folder(client, project["id"], [sanitize(p) for p in rel.parts[:-1]], state)
            if remote and remote.get("id") in state.get("items", {}):
                previous_sha = state["items"][remote["id"]].get("sha256")
                if previous_sha and previous_sha == remote.get("sha256"):
                    uploaded = client.upload_drive_file(project["id"], local, parent_id, conflict="replace", existing_item_id=remote["id"])
                else:
                    uploaded = client.upload_drive_file(project["id"], local, parent_id, conflict="rename")
            elif not remote:
                uploaded = client.upload_drive_file(project["id"], local, parent_id, conflict="rename")
            else:
                uploaded = remote
            state.setdefault("paths", {})[rel_key] = uploaded["id"]
            state.setdefault("items", {})[uploaded["id"]] = {
                "path": rel_key,
                "kind": "file",
                "sha256": uploaded.get("sha256") or local_sha,
                "version_no": uploaded.get("version_no"),
                "updated_at": uploaded.get("updated_at"),
            }

    cfg.drive_sync_cursor_by_project[project["id"]] = manifest.get("cursor") or time.strftime("%Y-%m-%dT%H:%M:%S")
    save_drive_state(project_root, state)
    save_config(cfg)
    log(f"drive synced {project_slug} ({cfg.drive_sync_mode})")


def sync_all_project_drives(client: ServerClient, cfg: Config) -> None:
    if not cfg.drive_sync_enabled:
        return
    for project in client.list_projects():
        try:
            sync_project_drive_once(client, cfg, project)
        except Exception as e:
            log(f"drive sync failed for {project.get('slug') or project.get('id')}: {e}")


# ───────────────────────── deliver (zip + upload) ─────────────────────────

EXCLUDE_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".DS_Store"}


def zip_directory(src: Path, dest_zip: Path,
                  progress: Callable[[str], None] | None = None) -> tuple[int, str]:
    """Zip src recursively into dest_zip. Returns (file_count, sha256_of_zip)."""
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    count = 0
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(src.rglob("*")):
            if any(part in EXCLUDE_DIRS for part in p.parts):
                continue
            if not p.is_file():
                continue
            rel = p.relative_to(src)
            z.write(p, rel)
            count += 1
            if progress and count % 5 == 0:
                progress(f"zipped {count} files…")
    with open(dest_zip, "rb") as f:
        while True:
            buf = f.read(1024 * 1024)
            if not buf: break
            h.update(buf)
    return count, h.hexdigest()


# ───────────────────────── tk dialogs ─────────────────────────

def show_first_run_dialog(cfg: Config) -> bool:
    """Modal config dialog. Returns True if user saved, False if cancelled."""
    root = tk.Tk()
    root.title("需求管理大师 · 设置")
    root.geometry("640x680")
    root.attributes("-topmost", True)

    frm = ttk.Frame(root, padding=20)
    frm.pack(fill="both", expand=True)

    server_ip_var = tk.StringVar(value=cfg.server_ip)
    server_port_var = tk.StringVar(value=str(cfg.server_port))
    server_preview_var = tk.StringVar(value=cfg.server_url)
    drive_enabled_var = tk.BooleanVar(value=cfg.drive_sync_enabled)
    drive_mode_var = tk.StringVar(value=cfg.drive_sync_mode)
    drive_root_var = tk.StringVar(value=cfg.drive_sync_root)
    availability_var = tk.StringVar(value=cfg.availability_status)
    availability_text_var = tk.StringVar(value=cfg.availability_text)
    reminder_offsets_var = tk.StringVar(value=",".join(str(x) for x in cfg.reminder_offsets_minutes))
    device_name_var = tk.StringVar(value=cfg.client_device_name or platform.node() or "本地工作台")

    def update_server_preview(*_: Any) -> None:
        try:
            server_preview_var.set(build_server_url(server_ip_var.get(), server_port_var.get(), cfg.server_scheme))
        except ValueError as exc:
            server_preview_var.set(str(exc))

    server_ip_var.trace_add("write", update_server_preview)
    server_port_var.trace_add("write", update_server_preview)

    ttk.Label(frm, text="服务端 IP").grid(row=0, column=0, sticky="w", pady=4)
    e_ip = ttk.Entry(frm, width=32, textvariable=server_ip_var)
    e_ip.grid(row=0, column=1, sticky="we", pady=4)

    ttk.Label(frm, text="端口").grid(row=1, column=0, sticky="w", pady=4)
    e_port = ttk.Entry(frm, width=10, textvariable=server_port_var)
    e_port.grid(row=1, column=1, sticky="w", pady=4)

    ttk.Label(frm, text="请求地址").grid(row=2, column=0, sticky="w", pady=4)
    ttk.Label(frm, textvariable=server_preview_var, foreground="#555").grid(row=2, column=1, sticky="w", pady=4)

    ttk.Label(frm, text="昵称").grid(row=3, column=0, sticky="w", pady=4)
    e_nick = ttk.Entry(frm, width=42)
    e_nick.insert(0, cfg.nickname)
    e_nick.grid(row=3, column=1, sticky="we", pady=4)

    ttk.Label(frm, text="设备名").grid(row=4, column=0, sticky="w", pady=4)
    ttk.Entry(frm, width=42, textvariable=device_name_var).grid(row=4, column=1, sticky="we", pady=4)
    ttk.Label(
        frm,
        text=("本地端能力：" + ("已注册" if cfg.client_token else "保存后注册")),
        foreground="#666",
    ).grid(row=5, column=1, sticky="w", pady=(0, 4))

    ttk.Label(frm, text="项目保存位置").grid(row=6, column=0, sticky="w", pady=4)
    e_root = ttk.Entry(frm, width=42)
    e_root.insert(0, cfg.sync_root)
    e_root.grid(row=6, column=1, sticky="we", pady=4)
    ttk.Label(
        frm,
        text="需求文件会保存到：项目保存位置\\项目\\需求编号",
        foreground="#666",
    ).grid(row=7, column=1, sticky="w", pady=(0, 4))

    def browse():
        d = filedialog.askdirectory(initialdir=e_root.get() or ".")
        if d:
            e_root.delete(0, "end")
            e_root.insert(0, d)
    ttk.Button(frm, text="选择…", command=browse).grid(row=6, column=2, padx=4)

    ttk.Label(frm, text="项目网盘同步").grid(row=8, column=0, sticky="w", pady=4)
    ttk.Checkbutton(frm, text="开启自动同步", variable=drive_enabled_var).grid(row=8, column=1, sticky="w", pady=4)

    ttk.Label(frm, text="同步模式").grid(row=9, column=0, sticky="w", pady=4)
    mode_frm = ttk.Frame(frm)
    mode_frm.grid(row=9, column=1, sticky="w", pady=4)
    ttk.Radiobutton(mode_frm, text="单向下载", value="download", variable=drive_mode_var).pack(side="left")
    ttk.Radiobutton(mode_frm, text="双向同步", value="two_way", variable=drive_mode_var).pack(side="left", padx=12)

    ttk.Label(frm, text="网盘同步目录").grid(row=10, column=0, sticky="w", pady=4)
    e_drive_root = ttk.Entry(frm, width=42, textvariable=drive_root_var)
    e_drive_root.grid(row=10, column=1, sticky="we", pady=4)
    def browse_drive():
        d = filedialog.askdirectory(initialdir=drive_root_var.get() or ".")
        if d:
            drive_root_var.set(d)
    ttk.Button(frm, text="选择…", command=browse_drive).grid(row=10, column=2, padx=4)

    ttk.Label(frm, text="接单状态").grid(row=11, column=0, sticky="w", pady=4)
    status_frm = ttk.Frame(frm)
    status_frm.grid(row=11, column=1, sticky="w", pady=4)
    ttk.Radiobutton(status_frm, text="空闲", value="free", variable=availability_var).pack(side="left")
    ttk.Radiobutton(status_frm, text="忙碌", value="busy", variable=availability_var).pack(side="left", padx=12)
    ttk.Radiobutton(status_frm, text="其他", value="custom", variable=availability_var).pack(side="left")

    ttk.Label(frm, text="状态备注").grid(row=12, column=0, sticky="w", pady=4)
    ttk.Entry(frm, width=42, textvariable=availability_text_var).grid(row=12, column=1, sticky="we", pady=4)

    ttk.Label(frm, text="DDL 提醒(分钟)").grid(row=13, column=0, sticky="w", pady=4)
    ttk.Entry(frm, width=42, textvariable=reminder_offsets_var).grid(row=13, column=1, sticky="we", pady=4)

    status_lbl = ttk.Label(frm, text="", foreground="red")
    status_lbl.grid(row=14, column=0, columnspan=3, sticky="w", pady=6)

    result = {"ok": False}

    def save():
        try:
            url = build_server_url(server_ip_var.get(), server_port_var.get(), cfg.server_scheme)
            server_scheme, server_ip, server_port = server_parts_from_url(url)
        except ValueError as ex:
            status_lbl.config(text=str(ex), foreground="red")
            return
        nick = e_nick.get().strip()
        device_name = device_name_var.get().strip() or platform.node() or "本地工作台"
        root_dir = e_root.get().strip()
        drive_root = drive_root_var.get().strip()
        if not nick or not device_name or not root_dir or not drive_root:
            status_lbl.config(text="所有字段都必填")
            return
        try:
            reminder_offsets = [int(x.strip()) for x in reminder_offsets_var.get().split(",") if x.strip()]
        except ValueError:
            status_lbl.config(text="DDL 提醒必须是逗号分隔的分钟数", foreground="red")
            return
        status_lbl.config(text="正在连接服务端…", foreground="black")
        root.update_idletasks()
        try:
            tmp_client = ServerClient(Config(
                server_url=url,
                server_ip=server_ip,
                server_port=server_port,
                server_scheme=server_scheme,
            ))
            cookie = tmp_client.identify(nick)
            if not cookie:
                tmp_client.close()
                status_lbl.config(text="未拿到 cookie，请检查服务端", foreground="red")
                return
            device_id, client_token = tmp_client.register_client_device(device_name, platform.platform())
            tmp_client.close()
        except Exception as ex:
            status_lbl.config(text=f"连接失败: {ex}", foreground="red")
            return

        cfg.server_url = url
        cfg.server_ip = server_ip
        cfg.server_port = server_port
        cfg.server_scheme = server_scheme
        cfg.nickname = nick
        cfg.client_device_name = device_name
        cfg.client_device_id = device_id
        cfg.client_token = client_token
        cfg.sync_root = root_dir
        cfg.project_save_root = root_dir
        cfg.drive_sync_enabled = bool(drive_enabled_var.get())
        cfg.drive_sync_mode = drive_mode_var.get() if drive_mode_var.get() in {"download", "two_way"} else "download"
        cfg.drive_sync_root = drive_root
        cfg.availability_status = availability_var.get() if availability_var.get() in {"free", "busy", "custom"} else "free"
        cfg.availability_text = availability_text_var.get().strip()
        cfg.reminder_offsets_minutes = reminder_offsets or [1440, 120, 0]
        cfg.cookie_token = cookie
        save_config(cfg)
        try:
            tmp_client = ServerClient(cfg)
            tmp_client.update_availability(cfg.availability_status, cfg.availability_text)
            tmp_client.close()
        except Exception as ex:
            log(f"status update after save failed: {ex}")
        result["ok"] = True
        root.destroy()

    def cancel():
        root.destroy()

    btn_frm = ttk.Frame(frm)
    btn_frm.grid(row=15, column=0, columnspan=3, pady=12, sticky="e")
    ttk.Button(btn_frm, text="取消", command=cancel).pack(side="right", padx=4)
    ttk.Button(btn_frm, text="保存", command=save).pack(side="right", padx=4)

    frm.columnconfigure(1, weight=1)
    root.protocol("WM_DELETE_WINDOW", cancel)
    root.mainloop()
    return result["ok"]


def pick_requirement_dialog(items: list[dict]) -> dict | None:
    """Modal picker. Returns chosen item or None."""
    root = tk.Tk()
    root.title("选择要交付的需求")
    root.geometry("520x360")
    root.attributes("-topmost", True)

    frm = ttk.Frame(root, padding=12)
    frm.pack(fill="both", expand=True)

    ttk.Label(frm, text="选择要打包并上传的需求：").pack(anchor="w")
    lb = tk.Listbox(frm, height=12)
    lb.pack(fill="both", expand=True, pady=8)
    for it in items:
        lb.insert("end", f"  {it['code']}  ·  {it.get('title') or '(无标题)'}  [{it['status']}]")

    chosen = {"item": None}
    def go():
        sel = lb.curselection()
        if sel:
            chosen["item"] = items[sel[0]]
            root.destroy()
    def cancel():
        root.destroy()

    btns = ttk.Frame(frm)
    btns.pack(fill="x")
    ttk.Button(btns, text="取消", command=cancel).pack(side="right", padx=4)
    ttk.Button(btns, text="选中并上传", command=go).pack(side="right", padx=4)

    root.mainloop()
    return chosen["item"]


# ───────────────────────── tray app ─────────────────────────

def make_icon_image() -> Image.Image:
    img = Image.new("RGB", (64, 64), color=(15, 23, 42))
    d = ImageDraw.Draw(img)
    d.rectangle((10, 10, 54, 54), outline=(244, 244, 245), width=3)
    d.text((20, 18), "需", fill=(244, 244, 245))
    return img


class TrayApp:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.client = ServerClient(cfg)
        self.stop = threading.Event()
        self.event_thread: threading.Thread | None = None
        self.drive_thread: threading.Thread | None = None
        self.reminder_thread: threading.Thread | None = None
        self.icon: pystray.Icon | None = None
        self.service_state = "connecting"
        self.last_heartbeat = ""

    def start(self) -> None:
        self.icon = pystray.Icon(APP_NAME, make_icon_image(), "需求管理大师", self._menu())
        self.event_thread = threading.Thread(target=self._sse_loop, daemon=True)
        self.event_thread.start()
        self.drive_thread = threading.Thread(target=self._drive_sync_loop, daemon=True)
        self.drive_thread.start()
        self.reminder_thread = threading.Thread(target=self._reminder_loop, daemon=True)
        self.reminder_thread.start()
        try:
            self.client.update_availability(self.cfg.availability_status, self.cfg.availability_text)
        except Exception as e:
            log(f"initial availability update failed: {e}")
        if not self.cfg.tray_started_notice_shown:
            notify("需求管理大师已常驻托盘", "右下角托盘图标里可以打开本地工作台、同步文件和上传交付。")
            self.cfg.tray_started_notice_shown = True
            save_config(self.cfg)
        self._update_icon_title()
        log("tray started")
        self.icon.run()

    def stop_all(self, *_: Any) -> None:
        self.stop.set()
        self.client.close()
        if self.icon: self.icon.stop()

    def _menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem(lambda _: f"用户：{self.cfg.nickname or '未识别'}", lambda _: None, enabled=False),
            pystray.MenuItem(lambda _: f"服务：{self._connection_label()}", lambda _: None, enabled=False),
            pystray.MenuItem(lambda _: f"同步：{self._sync_label()}", lambda _: None, enabled=False),
            pystray.MenuItem(lambda _: f"最后心跳：{self.last_heartbeat or '等待中'}", lambda _: None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("打开本地工作台", lambda _: self._open_dashboard(), default=True),
            pystray.MenuItem("打开 Web 派活端", lambda _: webbrowser.open(self.cfg.server_url)),
            pystray.MenuItem("打开项目保存位置", lambda _: open_folder(Path(self.cfg.sync_root))),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("立即同步所有就绪需求", lambda _: threading.Thread(target=self._catchup, daemon=True).start()),
            pystray.MenuItem("立即同步项目网盘", lambda _: threading.Thread(target=self._drive_sync_once, daemon=True).start()),
            pystray.MenuItem("完成任务并上传…", lambda _: threading.Thread(target=self._deliver_flow, daemon=True).start()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda _: f"接单状态：{self._status_label()}",
                             lambda _: threading.Thread(target=self._cycle_availability, daemon=True).start()),
            pystray.MenuItem(lambda _: ("网盘同步：关" if not self.cfg.drive_sync_enabled else f"网盘同步：{'双向' if self.cfg.drive_sync_mode == 'two_way' else '单向'}"),
                             self._toggle_drive_sync),
            pystray.MenuItem(lambda _: ("▶ 已暂停同步" if self.cfg.paused else "⏸ 暂停同步"),
                             self._toggle_pause),
            pystray.MenuItem("设置…", lambda _: threading.Thread(target=self._open_settings, daemon=True).start()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self.stop_all),
        )

    def _open_dashboard(self) -> None:
        """Spawn the dashboard window in a separate process so pystray stays responsive."""
        try:
            here = Path(__file__).resolve().parent
            dash_script = here / "yqgl_dashboard.py"
            if dash_script.exists():
                kwargs: dict[str, Any] = {}
                if platform.system() == "Windows":
                    kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
                subprocess.Popen([sys.executable, str(dash_script)], **kwargs)
                log("spawned local workbench window")
            else:
                webbrowser.open(f"{self.cfg.server_url}/local-workbench")
        except Exception as e:
            log(f"failed to open local workbench: {e}; falling back to browser")
            webbrowser.open(f"{self.cfg.server_url}/local-workbench")

    def _toggle_pause(self, *_: Any) -> None:
        self.cfg.paused = not self.cfg.paused
        save_config(self.cfg)
        if self.icon: self.icon.update_menu()
        log(f"paused={self.cfg.paused}")

    def _status_label(self) -> str:
        if self.cfg.availability_status == "busy":
            return self.cfg.availability_text or "忙碌"
        if self.cfg.availability_status == "custom":
            return self.cfg.availability_text or "其他"
        return "空闲"

    def _sync_label(self) -> str:
        if not self.cfg.drive_sync_enabled:
            return "网盘关"
        return "网盘双向" if self.cfg.drive_sync_mode == "two_way" else "网盘单向"

    def _connection_label(self) -> str:
        if self.service_state == "connected":
            return "在线"
        if self.service_state == "connecting":
            return "连接中"
        return "离线"

    def _set_service_state(self, state: str) -> None:
        self.service_state = state
        if state == "connected":
            self.last_heartbeat = time.strftime("%H:%M:%S")
        self._update_icon_title()
        if self.icon:
            try:
                self.icon.update_menu()
            except Exception:
                pass

    def _update_icon_title(self) -> None:
        if not self.icon:
            return
        title = f"需求管理大师 · {self._connection_label()} · {self._status_label()}"
        try:
            self.icon.title = title[:64]
        except Exception:
            pass

    def _cycle_availability(self, *_: Any) -> None:
        order = ["free", "busy", "custom"]
        idx = order.index(self.cfg.availability_status) if self.cfg.availability_status in order else 0
        self.cfg.availability_status = order[(idx + 1) % len(order)]
        if self.cfg.availability_status == "free":
            self.cfg.availability_text = ""
        elif self.cfg.availability_status == "busy" and not self.cfg.availability_text:
            self.cfg.availability_text = "忙碌"
        elif self.cfg.availability_status == "custom" and not self.cfg.availability_text:
            self.cfg.availability_text = "其他"
        save_config(self.cfg)
        try:
            self.client.update_availability(self.cfg.availability_status, self.cfg.availability_text)
        except Exception as e:
            log(f"availability update failed: {e}")
        self._update_icon_title()
        if self.icon: self.icon.update_menu()

    def _toggle_drive_sync(self, *_: Any) -> None:
        if not self.cfg.drive_sync_enabled:
            self.cfg.drive_sync_enabled = True
            self.cfg.drive_sync_mode = "download"
        elif self.cfg.drive_sync_mode == "download":
            self.cfg.drive_sync_mode = "two_way"
        else:
            self.cfg.drive_sync_enabled = False
            self.cfg.drive_sync_mode = "download"
        save_config(self.cfg)
        self._update_icon_title()
        if self.icon: self.icon.update_menu()
        log(f"drive sync enabled={self.cfg.drive_sync_enabled} mode={self.cfg.drive_sync_mode}")

    def _open_settings(self) -> None:
        if show_first_run_dialog(self.cfg):
            self.client.close()
            self.client = ServerClient(self.cfg)
            try:
                self.client.update_availability(self.cfg.availability_status, self.cfg.availability_text)
            except Exception as e:
                log(f"availability update after settings failed: {e}")
            log("config updated; SSE will reconnect next cycle")

    # ─── SSE handler ───
    def _sse_loop(self) -> None:
        # also do an initial catch-up of unsynced ready reqs
        try: self._catchup()
        except Exception as e: log(f"initial catchup err: {e}")
        self.client.stream_events(self._on_event, self.stop, self._set_service_state)

    def _drive_sync_loop(self) -> None:
        while not self.stop.is_set():
            if self.cfg.drive_sync_enabled and not self.cfg.paused:
                self._drive_sync_once()
            self.stop.wait(45)

    def _drive_sync_once(self) -> None:
        if not self.cfg.drive_sync_enabled:
            return
        try:
            sync_all_project_drives(self.client, self.cfg)
        except Exception as e:
            log(f"drive sync loop failed: {e}")

    def _reminder_loop(self) -> None:
        while not self.stop.is_set():
            if not self.cfg.paused:
                self._check_reminders()
                self._check_notifications()
            self.stop.wait(60)

    def _check_reminders(self) -> None:
        try:
            items = self.client.due_reminders()
        except Exception as e:
            log(f"reminder check failed: {e}")
            return
        changed = False
        today = time.strftime("%Y-%m-%d")
        for item in items:
            due_at = item.get("due_at") or ""
            minutes = int(item.get("minutes_until_due") or 0)
            if minutes < 0:
                bucket = f"overdue:{today}"
            elif minutes <= 0:
                bucket = "due_now"
            elif minutes <= 120:
                bucket = "due_2h"
            elif minutes <= 1440:
                bucket = "due_24h"
            else:
                continue
            key = f"{item.get('requirement_id')}:{bucket}"
            if self.cfg.known_reminders.get(key) == due_at:
                continue
            self.cfg.known_reminders[key] = due_at
            changed = True
            code = item.get("requirement_code") or ""
            progress = item.get("progress_percent")
            phase = item.get("phase") or item.get("status") or ""
            blocked = item.get("blocked_reason") or ""
            progress_line = f"\n进度：{phase} {progress}%" if progress is not None else ""
            blocked_line = f"\n阻塞：{blocked[:80]}" if blocked else ""
            if bucket.startswith("overdue"):
                title = "DDL 已逾期"
                msg = f"{code} · {item.get('title','')}\n已经超时 {abs(minutes)} 分钟。{progress_line}{blocked_line}"
            elif bucket == "due_now":
                title = "DDL 到点了"
                msg = f"{code} · {item.get('title','')}\n现在就到期。{progress_line}{blocked_line}"
            else:
                title = "DDL 快到了"
                msg = f"{code} · {item.get('title','')}\n还有 {minutes} 分钟。{progress_line}{blocked_line}"
            notify(title, msg)
        if changed:
            save_config(self.cfg)

    def _check_notifications(self) -> None:
        try:
            items = self.client.unread_notifications()
        except Exception as e:
            log(f"notification check failed: {e}")
            return
        changed = False
        for item in items:
            notification_id = item.get("id") or ""
            if not notification_id:
                continue
            marker = item.get("updated_at") or item.get("created_at") or ""
            if self.cfg.known_notifications.get(notification_id) == marker:
                continue
            severity = item.get("severity") or "normal"
            ntype = item.get("type") or ""
            important = severity in {"urgent", "high"} or ntype.startswith(("due_", "revision", "workspace_blocked", "assigned"))
            if not important:
                self.cfg.known_notifications[notification_id] = marker
                changed = True
                continue
            self.cfg.known_notifications[notification_id] = marker
            changed = True
            title = item.get("title") or "需求管理大师通知"
            body = item.get("body") or item.get("target_url") or ""
            notify(title, body[:200])
        if changed:
            save_config(self.cfg)

    def _on_event(self, event: str, data: Any) -> None:
        log(f"sse event: {event} {str(data)[:120]}")
        self.last_heartbeat = time.strftime("%H:%M:%S")
        if self.icon:
            try:
                self.icon.update_menu()
            except Exception:
                pass
        if self.cfg.paused:
            return
        if event == "requirement.ready" and isinstance(data, dict):
            req_id = data.get("requirement_id")
            if req_id and req_id not in self.cfg.known_reqs:
                try:
                    target = sync_requirement(self.client, self.cfg, req_id)
                    notify("有新需求待接单",
                           f"{data.get('code', '')} · {data.get('title', '')}\n本地路径：{target}")
                except Exception as e:
                    log(f"sync failed: {e}")
                    notify("同步失败", str(e))
        elif event == "revision.requested" and isinstance(data, dict):
            req_id = data.get("requirement_id")
            if req_id:
                self.cfg.known_revision_requests[req_id] = data.get("reason_preview", "")
                save_config(self.cfg)
            notify("需要返工",
                   f"{data.get('requested_by','?')}：{data.get('reason_preview','')}")
        elif event == "drive.changed" and isinstance(data, dict):
            if self.cfg.drive_sync_enabled:
                threading.Thread(target=self._drive_sync_once, daemon=True).start()

    def _catchup(self) -> None:
        reqs = self.client.list_my_pending()
        new = [r for r in reqs if r["id"] not in self.cfg.known_reqs]
        log(f"catchup: {len(new)} new requirements to sync")
        for r in new:
            try:
                target = sync_requirement(self.client, self.cfg, r["id"])
                notify("有新需求待接单", f"{r['code']} · {r.get('title','')}")
            except Exception as e:
                log(f"sync {r['id']} failed: {e}")

        revisions = self.client.list_all_with_statuses(["revision_requested"], assigned_to_me=True)
        new_revisions = [
            r for r in revisions
            if self.cfg.known_revision_requests.get(r["id"]) != (r.get("updated_at") or r["status"])
        ]
        if new_revisions:
            log(f"catchup: {len(new_revisions)} revision requests to notify")
        for r in new_revisions:
            marker = r.get("updated_at") or r["status"]
            self.cfg.known_revision_requests[r["id"]] = marker
            notify("需要返工", f"{r['code']} · {r.get('title','')}")
        if new_revisions:
            save_config(self.cfg)

    # ─── deliver flow ───
    def _deliver_flow(self) -> None:
        candidates = self.client.list_all_with_statuses(
            ["doing", "claimed", "revision_requested"], assigned_to_me=True,
        )
        if not candidates:
            notify("没有进行中的任务", "在 web 端先把需求接单后再来。")
            return
        item = pick_requirement_dialog(candidates)
        if not item:
            return
        # locate folder
        code = sanitize(item["code"])
        slug = sanitize(item.get("project_slug") or "unknown")
        folder = Path(self.cfg.sync_root) / slug / code
        if not folder.exists():
            notify("本地目录不存在", str(folder))
            return
        log(f"delivering {code} from {folder}")
        notify("打包中…", f"{code}")

        zip_path = APP_DIR / "tmp" / f"{code}-{int(time.time())}.zip"
        try:
            count, _sha = zip_directory(folder, zip_path,
                                         progress=lambda m: log(f"  {m}"))
            log(f"zipped {count} files into {zip_path} ({zip_path.stat().st_size} bytes)")
            notify("上传中…", f"{count} 个文件")
            d = self.client.upload_delivery(item["id"], zip_path,
                                            progress=lambda s, t: log(f"  uploaded {s}/{t}"))
            log(f"upload ok: {d}")
            notify("交付成功", f"{code} 已上传，AI 正在写交付文档…")
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code == 403:
                msg = "你不是这条需求的负责人/协作者，不能交付。"
            else:
                msg = str(e)
            log(f"delivery failed: {msg}")
            notify("交付失败", msg)
        except Exception as e:
            log(f"delivery failed: {e}")
            notify("交付失败", str(e))
        finally:
            try: zip_path.unlink(missing_ok=True)
            except Exception: pass


def open_folder(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)
    if platform.system() == "Windows":
        subprocess.Popen(["explorer", str(p)])
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])


# ───────────────────────── entrypoint ─────────────────────────

def main() -> None:
    cfg = load_config()
    if not cfg.cookie_token or not cfg.client_token or not cfg.nickname or not cfg.server_url:
        if not show_first_run_dialog(cfg):
            log("user cancelled first-run; exiting")
            sys.exit(0)
    log(f"starting with cfg: server={cfg.server_url} nickname={cfg.nickname} sync={cfg.sync_root}")
    TrayApp(cfg).start()


if __name__ == "__main__":
    main()
