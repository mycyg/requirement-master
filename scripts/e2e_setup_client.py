"""Pre-create %APPDATA%\\yqgl\\config.json with a real signed cookie.

This skips the tkinter first-run dialog so the tray can run headlessly during E2E.
"""
import json
import os
from pathlib import Path

import httpx

import os
BASE = os.environ.get("YQGL_BASE", "http://localhost:8080")
NICKNAME = "接单人-mycyg"
SYNC_ROOT = "D:/工作需求"

APPDATA = Path(os.environ.get("APPDATA", str(Path.home() / ".config")))
APP_DIR = APPDATA / "yqgl"
APP_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = APP_DIR / "config.json"

# Start fresh: blow away known_reqs so the tray catches up everything
print(f"Resetting {CONFIG_PATH}")

with httpx.Client(base_url=BASE) as c:
    r = c.post("/api/auth/identify", json={"nickname": NICKNAME})
    r.raise_for_status()
    cookie = r.cookies.get("yqgl_id", "")
    if not cookie:
        raise SystemExit("no cookie returned")
    me = c.get("/api/auth/me", cookies={"yqgl_id": cookie}).json()
    print(f"  identified as: {me}")

cfg = {
    "server_url": BASE,
    "nickname": NICKNAME,
    "cookie_token": cookie,
    "sync_root": SYNC_ROOT,
    "paused": False,
    "known_reqs": {},
}
CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"  wrote config to {CONFIG_PATH}")

# Also blow away the previous sync root for a clean test
for old in (Path(SYNC_ROOT) / "e2e",):
    if old.exists():
        import shutil
        shutil.rmtree(old)
        print(f"  cleaned {old}")

# clear old log
log = APP_DIR / "client.log"
if log.exists():
    log.unlink()
    print(f"  cleared {log}")
