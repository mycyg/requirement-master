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

import httpx
from PIL import Image, ImageDraw
import pystray

# ───────────────────────── config ─────────────────────────

APP_NAME = "yqgl"
APP_DIR = Path(os.environ.get("APPDATA", str(Path.home() / ".config"))) / APP_NAME
CONFIG_PATH = APP_DIR / "config.json"
DEFAULT_SYNC_ROOT = Path("D:/工作需求")


@dataclass
class Config:
    server_url: str = "http://localhost:8080"
    nickname: str = ""
    cookie_token: str = ""           # signed cookie (yqgl_id) value
    sync_root: str = str(DEFAULT_SYNC_ROOT)
    paused: bool = False
    known_reqs: dict[str, str] = field(default_factory=dict)  # req_id -> code (avoid duplicate downloads)
    known_revision_requests: dict[str, str] = field(default_factory=dict)  # req_id -> updated_at marker


def load_config() -> Config:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.exists():
        try:
            d = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            return Config(**{**Config().__dict__, **d})
        except Exception:
            pass
    return Config()


def save_config(cfg: Config) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
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
        self._client = httpx.Client(
            base_url=cfg.server_url, cookies=cookies, timeout=httpx.Timeout(60, read=None),
        )

    def close(self) -> None:
        try: self._client.close()
        except Exception: pass

    def identify(self, nickname: str) -> str:
        r = self._client.post("/api/auth/identify", json={"nickname": nickname})
        r.raise_for_status()
        cookie = r.cookies.get("yqgl_id", "")
        return cookie

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

    def stream_events(self, on_event: Callable[[str, Any], None], stop: threading.Event) -> None:
        """Long-poll SSE. Auto-reconnect with exponential backoff."""
        backoff = 1.0
        while not stop.is_set():
            try:
                with self._client.stream("GET", "/api/push/stream", timeout=None) as r:
                    r.raise_for_status()
                    backoff = 1.0
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
        "raw_description", "chat", "assignees",
    )}
    (target / "metadata.json").write_text(
        json.dumps(meta_keep, ensure_ascii=False, indent=2), encoding="utf-8",
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
    root.geometry("460x320")
    root.attributes("-topmost", True)

    frm = ttk.Frame(root, padding=20)
    frm.pack(fill="both", expand=True)

    ttk.Label(frm, text="服务端地址").grid(row=0, column=0, sticky="w", pady=4)
    e_url = ttk.Entry(frm, width=42)
    e_url.insert(0, cfg.server_url)
    e_url.grid(row=0, column=1, sticky="we", pady=4)

    ttk.Label(frm, text="昵称").grid(row=1, column=0, sticky="w", pady=4)
    e_nick = ttk.Entry(frm, width=42)
    e_nick.insert(0, cfg.nickname)
    e_nick.grid(row=1, column=1, sticky="we", pady=4)

    ttk.Label(frm, text="本地同步根目录").grid(row=2, column=0, sticky="w", pady=4)
    e_root = ttk.Entry(frm, width=42)
    e_root.insert(0, cfg.sync_root)
    e_root.grid(row=2, column=1, sticky="we", pady=4)

    def browse():
        d = filedialog.askdirectory(initialdir=e_root.get() or ".")
        if d:
            e_root.delete(0, "end")
            e_root.insert(0, d)
    ttk.Button(frm, text="选择…", command=browse).grid(row=2, column=2, padx=4)

    status_lbl = ttk.Label(frm, text="", foreground="red")
    status_lbl.grid(row=3, column=0, columnspan=3, sticky="w", pady=6)

    result = {"ok": False}

    def save():
        url = e_url.get().strip()
        nick = e_nick.get().strip()
        root_dir = e_root.get().strip()
        if not url or not nick or not root_dir:
            status_lbl.config(text="所有字段都必填")
            return
        status_lbl.config(text="正在连接服务端…", foreground="black")
        root.update_idletasks()
        try:
            tmp_client = ServerClient(Config(server_url=url))
            cookie = tmp_client.identify(nick)
            tmp_client.close()
            if not cookie:
                status_lbl.config(text="未拿到 cookie，请检查服务端", foreground="red")
                return
        except Exception as ex:
            status_lbl.config(text=f"连接失败: {ex}", foreground="red")
            return

        cfg.server_url = url
        cfg.nickname = nick
        cfg.sync_root = root_dir
        cfg.cookie_token = cookie
        save_config(cfg)
        result["ok"] = True
        root.destroy()

    def cancel():
        root.destroy()

    btn_frm = ttk.Frame(frm)
    btn_frm.grid(row=4, column=0, columnspan=3, pady=12, sticky="e")
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
        self.icon: pystray.Icon | None = None

    def start(self) -> None:
        self.icon = pystray.Icon(APP_NAME, make_icon_image(), "需求管理大师", self._menu())
        self.event_thread = threading.Thread(target=self._sse_loop, daemon=True)
        self.event_thread.start()
        log("tray started")
        self.icon.run()

    def stop_all(self, *_: Any) -> None:
        self.stop.set()
        self.client.close()
        if self.icon: self.icon.stop()

    def _menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem("打开接单看板", lambda _: self._open_dashboard(), default=True),
            pystray.MenuItem("打开主界面 (浏览器)", lambda _: webbrowser.open(self.cfg.server_url)),
            pystray.MenuItem("打开同步目录", lambda _: open_folder(Path(self.cfg.sync_root))),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("立即同步所有就绪需求", lambda _: threading.Thread(target=self._catchup, daemon=True).start()),
            pystray.MenuItem("完成任务并上传…", lambda _: threading.Thread(target=self._deliver_flow, daemon=True).start()),
            pystray.Menu.SEPARATOR,
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
                log("spawned dashboard window")
            else:
                webbrowser.open(f"{self.cfg.server_url}/dashboard")
        except Exception as e:
            log(f"failed to open dashboard: {e}; falling back to browser")
            webbrowser.open(f"{self.cfg.server_url}/dashboard")

    def _toggle_pause(self, *_: Any) -> None:
        self.cfg.paused = not self.cfg.paused
        save_config(self.cfg)
        if self.icon: self.icon.update_menu()
        log(f"paused={self.cfg.paused}")

    def _open_settings(self) -> None:
        if show_first_run_dialog(self.cfg):
            self.client.close()
            self.client = ServerClient(self.cfg)
            log("config updated; SSE will reconnect next cycle")

    # ─── SSE handler ───
    def _sse_loop(self) -> None:
        # also do an initial catch-up of unsynced ready reqs
        try: self._catchup()
        except Exception as e: log(f"initial catchup err: {e}")
        self.client.stream_events(self._on_event, self.stop)

    def _on_event(self, event: str, data: Any) -> None:
        log(f"sse event: {event} {str(data)[:120]}")
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
    if not cfg.cookie_token or not cfg.nickname or not cfg.server_url:
        if not show_first_run_dialog(cfg):
            log("user cancelled first-run; exiting")
            sys.exit(0)
    log(f"starting with cfg: server={cfg.server_url} nickname={cfg.nickname} sync={cfg.sync_root}")
    TrayApp(cfg).start()


if __name__ == "__main__":
    main()
