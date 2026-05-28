"""Pure-HTTP simulation of the Tauri client onboarding chain.

Verifies the exact API calls the client makes:
  POST /api/auth/identify              → sets yqgl_id cookie
  POST /api/client-devices/register    → returns { device, client_token }
  GET  /api/auth/me  (with cookie)
  GET  /api/requirements?assigned_to_me=true  (with worker token)
  GET  /api/notifications?status=unread  (cookie auth)

Run:
    python scripts/e2e_client_onboarding.py [nickname]
"""
from __future__ import annotations

import sys
import platform

import httpx

BASE = "http://192.168.0.224:8080"


def main() -> int:
    nickname = sys.argv[1] if len(sys.argv) > 1 else f"e2e-onb-{platform.node()}"

    with httpx.Client(base_url=BASE, timeout=15) as c:
        print(f"== identify({nickname!r}) ==")
        r = c.post("/api/auth/identify", json={"nickname": nickname})
        r.raise_for_status()
        idy = r.json()
        print(f"   → id={idy['id']}  nickname={idy['nickname']}  created={idy.get('created')}")
        assert "yqgl_id" in c.cookies, "no yqgl_id cookie returned"

        print("== me ==")
        r = c.get("/api/auth/me")
        r.raise_for_status()
        me = r.json()
        print(f"   → {me}")
        assert me and me.get("id") == idy["id"]

        print("== register_device ==")
        r = c.post("/api/client-devices/register",
                   json={"device_name": platform.node(), "platform": sys.platform})
        r.raise_for_status()
        reg = r.json()
        token = reg["client_token"]
        device_id = reg["device"]["id"]
        print(f"   → device_id={device_id}  token_prefix={token[:8]}…")
        assert reg["device"]["device_name"]

        # Now hit a worker-only endpoint
        headers = {"X-YQGL-Client-Token": token}
        print("== claim eligibility check (require_local_client) — list_my ==")
        r = c.get("/api/requirements", params={"assigned_to_me": "true"}, headers=headers)
        r.raise_for_status()
        rows = r.json()
        print(f"   → {len(rows)} requirement(s) assigned to me")

        print("== notifications (cookie) ==")
        r = c.get("/api/notifications", params={"status": "unread"})
        r.raise_for_status()
        print(f"   → {len(r.json())} unread notification(s)")

        print("\nOK — full onboarding chain works.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
