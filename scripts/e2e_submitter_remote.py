"""Pure-HTTP simulation of the Tauri client SUBMITTER chain against prod.

Exercises every endpoint the new submitter.rs Tauri commands wrap:
  POST /api/auth/identify                              → cookie
  POST /api/client-devices/register                    → worker token
  GET  /api/projects?state=active                      → list_my_projects
  GET  /api/users?search=                              → list_users
  POST /api/projects/{id}/requirements                 → create_requirement
  POST /api/requirements/{id}/upload/init|chunk|finalize → upload_attachment (3+ MB → multi-chunk)
  POST /api/requirements/{id}/submit                   → submit_requirement
  POST /api/requirements/{id}/claim (second identity)  → simulate claimant
  POST /api/requirements/{id}/delivery/init|...        → simulate delivery
  GET  /api/requirements/{id}/deliveries               → list deliveries
  GET  /api/deliveries/{delivery_id}/package           → download_delivery
  POST /api/requirements/{id}/accept                   → accept_requirement

Run:
    python scripts/e2e_submitter_remote.py [submitter_nick] [claimant_nick]
"""
from __future__ import annotations

import hashlib
import io
import sys
import tempfile
import zipfile
from pathlib import Path

import httpx

import os
# Two NICs on the same prod box: 0.224 (LAN) and 5.53 (separate subnet). Either
# works; override with YQGL_BASE if the route to one is flaky.
BASE = os.environ.get("YQGL_BASE", "http://192.168.5.53:8080")
# Make all base_url+timeouts more lenient since prod is on a flaky NIC.
TIMEOUT = 60
CHUNK_SIZE = 5 * 1024 * 1024


def identify(c: httpx.Client, nickname: str) -> tuple[str, str]:
    """Returns (user_id, worker_token)."""
    r = c.post("/api/auth/identify", json={"nickname": nickname})
    r.raise_for_status()
    user_id = r.json()["id"]
    r = c.post("/api/client-devices/register",
               json={"device_name": f"submitter-e2e", "platform": "test"})
    r.raise_for_status()
    return user_id, r.json()["client_token"]


def upload_attachment(c: httpx.Client, req_id: str, token: str, payload: bytes, filename: str) -> str:
    """Returns attachment id."""
    total = len(payload)
    chunks = (total + CHUNK_SIZE - 1) // CHUNK_SIZE
    r = c.post(f"/api/requirements/{req_id}/upload/init",
               json={"filename": filename, "total_size": total, "total_chunks": chunks,
                     "mime": "application/octet-stream"},
               headers={"X-YQGL-Client-Token": token})
    r.raise_for_status()
    upload_id = r.json()["upload_id"]
    for i in range(chunks):
        piece = payload[i * CHUNK_SIZE:(i + 1) * CHUNK_SIZE]
        r = c.put(f"/api/requirements/{req_id}/upload/{upload_id}/chunk/{i}",
                  content=piece,
                  headers={"X-YQGL-Client-Token": token, "Content-Type": "application/octet-stream"})
        r.raise_for_status()
    r = c.post(f"/api/requirements/{req_id}/upload/{upload_id}/finalize",
               headers={"X-YQGL-Client-Token": token})
    r.raise_for_status()
    return r.json()["id"]


def deliver(c: httpx.Client, req_id: str, token: str) -> None:
    """Simulate the claimant uploading a delivery zip."""
    # tiny zip
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.md", "# e2e delivery\nsmoke test artifact\n")
    payload = buf.getvalue()
    total = len(payload)
    chunks = 1
    r = c.post(f"/api/requirements/{req_id}/delivery/init",
               json={"filename": f"delivery-{req_id}.zip", "total_size": total,
                     "total_chunks": chunks, "mime": "application/zip"},
               headers={"X-YQGL-Client-Token": token})
    r.raise_for_status()
    upload_id = r.json()["upload_id"]
    # Path params (NOT query string) — backend route is
    # PUT /requirements/{req_id}/delivery/{upload_id}/chunk/{idx}
    # POST /requirements/{req_id}/delivery/{upload_id}/finalize
    r = c.put(f"/api/requirements/{req_id}/delivery/{upload_id}/chunk/0",
              content=payload,
              headers={"X-YQGL-Client-Token": token, "Content-Type": "application/octet-stream"})
    r.raise_for_status()
    r = c.post(f"/api/requirements/{req_id}/delivery/{upload_id}/finalize",
               headers={"X-YQGL-Client-Token": token})
    r.raise_for_status()


def main() -> int:
    submitter_nick = sys.argv[1] if len(sys.argv) > 1 else "e2e-submitter-小光"
    claimant_nick = sys.argv[2] if len(sys.argv) > 2 else "e2e-claimant-小杨"

    # === Submitter session ===
    with httpx.Client(base_url=BASE, timeout=30) as sc:
        print(f"== submitter identify({submitter_nick!r}) ==")
        s_uid, s_tok = identify(sc, submitter_nick)
        print(f"   → user={s_uid}, token={s_tok[:8]}…")

        print("== list_my_projects ==")
        r = sc.get("/api/projects", params={"state": "active"})
        r.raise_for_status()
        projects = r.json()
        assert projects, "no projects on prod — run set_admin.py for 小光?"
        project = projects[0]
        print(f"   → using project {project['name']} ({project['id']})")

        print("== list_users(search='') ==")
        r = sc.get("/api/users", params={"search": ""})
        r.raise_for_status()
        users = r.json()
        print(f"   → {len(users)} users known")

        print("== create_requirement ==")
        from datetime import datetime, timedelta
        due = (datetime.utcnow() + timedelta(hours=24)).isoformat() + "Z"
        r = sc.post(f"/api/projects/{project['id']}/requirements",
                    json={"raw_description": "E2E submitter smoke: 双 Space 闭环验证",
                          "priority": "normal",
                          "lead_user_id": None,
                          "collaborator_user_ids": [],
                          "due_at": due})
        r.raise_for_status()
        req = r.json()
        req_id = req["id"]
        print(f"   → req {req['code']} ({req_id})")

        print("== upload_attachment (12 MB → 3 chunks) ==")
        big = b"YQGL-E2E-" * (12 * 1024 * 1024 // 9)
        att_id = upload_attachment(sc, req_id, s_tok, big, "e2e-spec.bin")
        print(f"   → attachment {att_id[:8]}…  ({len(big)} bytes)")

        print("== finalize-summary (skip AI clarification, brand new endpoint) ==")
        r = sc.post(f"/api/requirements/{req_id}/finalize-summary",
                    json={},  # let backend derive summary from raw_description
                    headers={"X-YQGL-Client-Token": s_tok})
        r.raise_for_status()
        print(f"   → status = {r.json().get('status')}  (should be summary_ready)")

        print("== submit_requirement ==")
        r = sc.post(f"/api/requirements/{req_id}/submit",
                    headers={"X-YQGL-Client-Token": s_tok})
        r.raise_for_status()
        print(f"   → status = {r.json().get('status')}")

    # === Claimant session ===
    with httpx.Client(base_url=BASE, timeout=30) as cc:
        print(f"\n== claimant identify({claimant_nick!r}) ==")
        c_uid, c_tok = identify(cc, claimant_nick)
        print(f"   → user={c_uid}")

        print("== claim ==")
        r = cc.post(f"/api/requirements/{req_id}/claim",
                    headers={"X-YQGL-Client-Token": c_tok})
        r.raise_for_status()
        print(f"   → claimed")

        print("== patch_status doing → delivered (simulate work + deliver) ==")
        r = cc.patch(f"/api/requirements/{req_id}/status",
                     json={"status": "doing"},
                     headers={"X-YQGL-Client-Token": c_tok})
        r.raise_for_status()

        print("== deliver (1-chunk zip) ==")
        deliver(cc, req_id, c_tok)
        print(f"   → delivered")

    # === Submitter accepts ===
    with httpx.Client(base_url=BASE, timeout=30) as sc:
        sc.post("/api/auth/identify", json={"nickname": submitter_nick}).raise_for_status()
        r = sc.post("/api/client-devices/register",
                    json={"device_name": "submitter-e2e", "platform": "test"})
        r.raise_for_status()
        s_tok = r.json()["client_token"]

        print("\n== list deliveries (download_delivery prereq) ==")
        r = sc.get(f"/api/requirements/{req_id}/deliveries",
                   headers={"X-YQGL-Client-Token": s_tok})
        r.raise_for_status()
        deliveries = r.json()
        print(f"   → {len(deliveries)} delivery rounds")
        assert deliveries, "no deliveries — claimant flow broke"

        print("== download package ==")
        d_id = deliveries[0]["id"]
        r = sc.get(f"/api/deliveries/{d_id}/package",
                   headers={"X-YQGL-Client-Token": s_tok})
        r.raise_for_status()
        print(f"   → {len(r.content)} bytes (zip)")

        print("== accept_requirement ==")
        r = sc.post(f"/api/requirements/{req_id}/accept",
                    headers={"X-YQGL-Client-Token": s_tok})
        r.raise_for_status()
        print(f"   → status = {r.json().get('status')}")

    print("\nOK — full 派活 → 接活 → 验收 chain works against prod.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
