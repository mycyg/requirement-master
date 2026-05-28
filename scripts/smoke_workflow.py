"""Fast API smoke test for the core requirement workflow.

This script avoids LLM calls and external services. It exercises identity,
project/request creation, attachment permissions, dispatch, sync manifest access,
claiming, and assignee-only status transitions against a temporary SQLite DB.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


def expect(status_code: int, actual: int, body: str) -> None:
    assert actual == status_code, f"expected {status_code}, got {actual}: {body}"


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="yqgl-smoke-"))
    try:
        os.environ["DATABASE_URL"] = "sqlite:///" + str(root / "test.db").replace("\\", "/")
        os.environ["DATA_DIR"] = str(root / "data")
        os.environ["APP_ENV"] = "development"
        os.environ["COOKIE_SECRET"] = "dev-test-secret"
        os.environ["LLM_API_KEY"] = ""

        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

        from fastapi.testclient import TestClient

        from db import SessionLocal, engine
        from main import app
        from models import Requirement, User
        due = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()

        with TestClient(app) as alice, TestClient(app) as bob, TestClient(app) as carl, TestClient(app) as dana:
            r = alice.post("/api/auth/identify", json={"nickname": "alice"})
            expect(200, r.status_code, r.text)
            alice_id = r.json()["id"]
            r = bob.post("/api/auth/identify", json={"nickname": "bob"})
            expect(200, r.status_code, r.text)
            bob_id = r.json()["id"]
            r = carl.post("/api/auth/identify", json={"nickname": "carl"})
            expect(200, r.status_code, r.text)
            carl_id = r.json()["id"]
            r = dana.post("/api/auth/identify", json={"nickname": "dana"})
            expect(200, r.status_code, r.text)
            dana_id = r.json()["id"]
            # Re-identifying as an existing nickname from a fresh client reuses
            # the account (LAN trust model). This used to 409, but that locked
            # any user out of their account after cookie expiry — see
            # services/auth.py /identify for details.
            with TestClient(app) as intruder:
                r = intruder.post("/api/auth/identify", json={"nickname": "alice"})
                expect(200, r.status_code, r.text)
                assert r.json()["id"] == alice_id, r.text

            def register_device(client, name: str) -> tuple[dict[str, str], str]:
                resp = client.post(
                    "/api/client-devices/register",
                    json={"device_name": f"smoke-{name}", "platform": "smoke"},
                )
                expect(201, resp.status_code, resp.text)
                body = resp.json()
                return {"X-YQGL-Client-Token": body["client_token"]}, body["device"]["id"]

            bob_local, bob_device_id = register_device(bob, "bob")
            carl_local, _ = register_device(carl, "carl")
            dana_local, _ = register_device(dana, "dana")

            r = alice.post("/api/projects", json={"name": "Smoke", "slug": "smoke"})
            expect(201, r.status_code, r.text)
            project_id = r.json()["id"]

            r = alice.post("/api/projects", json={"name": "State Smoke", "slug": "state-smoke"})
            expect(201, r.status_code, r.text)
            state_project_id = r.json()["id"]
            r = alice.post(
                f"/api/projects/{state_project_id}/requirements",
                json={"raw_description": "Archived project should seal child flows", "priority": "normal", "due_at": due},
            )
            expect(201, r.status_code, r.text)
            state_req_id = r.json()["id"]
            r = alice.post(f"/api/requirements/{state_req_id}/comments", json={"body": "before archive"})
            expect(200, r.status_code, r.text)
            r = bob.post(f"/api/projects/{state_project_id}/archive")
            expect(403, r.status_code, r.text)
            r = alice.post(f"/api/projects/{state_project_id}/archive")
            expect(200, r.status_code, r.text)
            assert r.json()["archived"] is True and r.json()["deleted_at"] is None, r.text
            for path in (
                f"/api/requirements/{state_req_id}/chat/messages",
                f"/api/requirements/{state_req_id}/comments",
                f"/api/requirements/{state_req_id}/activity",
            ):
                r = alice.get(path)
                expect(404, r.status_code, r.text)
            r = alice.post(f"/api/requirements/{state_req_id}/chat/answer", json={"text": "after archive"})
            expect(404, r.status_code, r.text)
            r = alice.get("/api/projects")
            expect(200, r.status_code, r.text)
            assert state_project_id not in {p["id"] for p in r.json()}, r.text
            r = alice.get("/api/projects", params={"state": "archived"})
            expect(200, r.status_code, r.text)
            assert state_project_id in {p["id"] for p in r.json()}, r.text
            r = alice.post(f"/api/projects/{state_project_id}/restore")
            expect(200, r.status_code, r.text)
            assert r.json()["archived"] is False, r.text
            r = alice.delete(f"/api/projects/{state_project_id}")
            expect(200, r.status_code, r.text)
            assert r.json()["deleted_at"] and r.json()["deleted_by_nickname"] == "alice", r.text
            r = alice.get("/api/projects", params={"state": "deleted"})
            expect(200, r.status_code, r.text)
            assert state_project_id in {p["id"] for p in r.json()}, r.text
            r = alice.post(f"/api/projects/{state_project_id}/restore")
            expect(200, r.status_code, r.text)
            assert r.json()["deleted_at"] is None and r.json()["archived"] is False, r.text

            r = alice.get("/api/users", params={"search": "bo"})
            expect(200, r.status_code, r.text)
            bob_option = next((u for u in r.json() if u["id"] == bob_id), None)
            assert bob_option, r.text
            assert bob_option["is_online"] is True, r.text
            assert "last_seen_at" in bob_option, r.text
            r = bob.put("/api/users/me/status", json={"availability_status": "busy", "availability_text": "smoke busy"})
            expect(200, r.status_code, r.text)
            assert r.json()["availability_status"] == "busy", r.text

            r = alice.post(f"/api/projects/{project_id}/drive/folders", json={"name": "docs"})
            expect(200, r.status_code, r.text)
            docs_id = r.json()["id"]
            r = alice.post(
                f"/api/projects/{project_id}/drive/folders/{docs_id}/comments",
                json={"body": "这里是普通说明，文件按 smoke 测试放。"},
            )
            expect(201, r.status_code, r.text)
            assert r.json()["status"] in {"posted", "draft_created"}, r.text
            r = alice.post(
                f"/api/projects/{project_id}/drive/folders/{docs_id}/comments",
                json={"body": "需求补充：请增加一个 smoke 导出按钮。"},
            )
            expect(201, r.status_code, r.text)
            assert r.json()["status"] == "draft_created" and r.json()["draft_requirement_id"], r.text
            drive_body = b"# Drive smoke\n\nhello from the project drive"
            r = alice.post(
                f"/api/projects/{project_id}/drive/upload/init",
                json={
                    "filename": "readme.md",
                    "total_size": len(drive_body),
                    "total_chunks": 1,
                    "mime": "text/markdown",
                    "parent_id": docs_id,
                    "conflict": "cancel",
                },
            )
            expect(200, r.status_code, r.text)
            upload_id = r.json()["upload_id"]
            assert upload_id, r.text
            r = alice.put(
                f"/api/projects/{project_id}/drive/upload/{upload_id}/chunk/0",
                content=drive_body,
                headers={"Content-Type": "application/octet-stream"},
            )
            expect(200, r.status_code, r.text)
            r = alice.post(f"/api/projects/{project_id}/drive/upload/{upload_id}/finalize")
            expect(200, r.status_code, r.text)
            drive_file_id = r.json()["id"]

            r = alice.post(
                f"/api/projects/{project_id}/drive/upload/init",
                json={
                    "filename": "readme.md",
                    "total_size": len(drive_body),
                    "total_chunks": 1,
                    "mime": "text/markdown",
                    "parent_id": docs_id,
                    "conflict": "cancel",
                },
            )
            expect(200, r.status_code, r.text)
            assert r.json()["conflict"] == "name_exists" and r.json()["upload_id"] is None, r.text

            r = bob.get(f"/api/projects/{project_id}/drive", params={"parent_id": docs_id})
            expect(200, r.status_code, r.text)
            assert any(i["id"] == drive_file_id for i in r.json()["items"]), r.text
            r = bob.get(f"/api/drive/files/{drive_file_id}/preview")
            expect(200, r.status_code, r.text)
            assert r.json()["preview_type"] == "markdown" and "Drive smoke" in r.json()["content"], r.text
            r = bob.get(f"/api/drive/files/{drive_file_id}/download")
            expect(200, r.status_code, r.text)
            assert r.content == drive_body, r.text

            r = alice.patch(f"/api/drive/items/{drive_file_id}", json={"name": "renamed.md"})
            expect(200, r.status_code, r.text)
            r = alice.post("/api/drive/bulk-download", json={"item_ids": [docs_id]})
            expect(200, r.status_code, r.text)
            assert r.content.startswith(b"PK"), "bulk zip should be a zip file"
            r = alice.delete(f"/api/drive/items/{drive_file_id}")
            expect(200, r.status_code, r.text)
            r = alice.get(f"/api/projects/{project_id}/drive", params={"trash": "true"})
            expect(200, r.status_code, r.text)
            assert any(i["id"] == drive_file_id for i in r.json()["items"]), r.text
            r = alice.post(f"/api/drive/items/{drive_file_id}/restore")
            expect(200, r.status_code, r.text)
            r = alice.post(f"/api/projects/{project_id}/drive/undo")
            expect(200, r.status_code, r.text)

            r = alice.post(
                f"/api/projects/{project_id}/requirements",
                json={"raw_description": "Build a smoke-test artifact", "priority": "normal", "due_at": due},
            )
            expect(201, r.status_code, r.text)
            req_id = r.json()["id"]

            r = alice.post(
                f"/api/projects/{project_id}/requirements",
                json={"raw_description": "No DDL should not dispatch", "priority": "normal"},
            )
            expect(201, r.status_code, r.text)
            no_due_id = r.json()["id"]
            db = SessionLocal()
            try:
                no_due = db.query(Requirement).filter(Requirement.id == no_due_id).one()
                no_due.title = "No DDL"
                no_due.summary_md = "## Goal\nNo DDL\n\n## Acceptance Criteria\n- Submit should fail"
                no_due.status = "summary_ready"
                db.commit()
            finally:
                db.close()
            r = alice.post(f"/api/requirements/{no_due_id}/submit")
            expect(400, r.status_code, r.text)

            r = alice.post(
                f"/api/requirements/{req_id}/attachments",
                files={"file": ("note.txt", b"hello", "text/plain")},
            )
            expect(200, r.status_code, r.text)
            attachment_id = r.json()["id"]

            r = bob.get(f"/api/requirements/{req_id}/attachments")
            expect(403, r.status_code, r.text)
            r = bob.get(f"/api/requirements/{req_id}")
            expect(403, r.status_code, r.text)
            r = bob.get(f"/api/requirements/{req_id}/chat/messages")
            expect(403, r.status_code, r.text)
            r = bob.get(f"/api/requirements/{req_id}/comments")
            expect(403, r.status_code, r.text)
            r = bob.get(f"/api/requirements/{req_id}/activity")
            expect(403, r.status_code, r.text)
            r = bob.get(f"/api/requirements?project_id={project_id}")
            expect(200, r.status_code, r.text)
            assert req_id not in {item["id"] for item in r.json()}, r.text

            r = alice.patch(f"/api/requirements/{req_id}/status", json={"status": "ready"})
            expect(400, r.status_code, r.text)

            db = SessionLocal()
            try:
                req = db.query(Requirement).filter(Requirement.id == req_id).one()
                req.title = "Smoke artifact"
                req.summary_md = "## Background\nSmoke test\n\n## Acceptance Criteria\n- Pass"
                req.status = "summary_ready"
                db.commit()
            finally:
                db.close()

            r = alice.post(f"/api/requirements/{req_id}/submit")
            expect(200, r.status_code, r.text)
            r = alice.get("/api/calendar/events")
            expect(200, r.status_code, r.text)
            assert any(e["requirement_id"] == req_id for e in r.json()), r.text
            r = alice.get("/api/calendar/events", params={
                "start": datetime.now(timezone.utc).isoformat(),
                "end": (datetime.now(timezone.utc) + timedelta(days=5)).isoformat(),
            })
            expect(200, r.status_code, r.text)
            assert any(e["requirement_id"] == req_id for e in r.json()), r.text

            r = bob.get(f"/api/requirements/{req_id}")
            expect(200, r.status_code, r.text)
            r = bob.get(f"/api/requirements/{req_id}/attachments")
            expect(200, r.status_code, r.text)
            r = bob.get(f"/api/files/{attachment_id}")
            expect(200, r.status_code, r.text)
            r = bob.get(f"/api/requirements/{req_id}/sync-manifest")
            expect(403, r.status_code, r.text)
            r = bob.get(f"/api/requirements/{req_id}/sync-manifest", headers=bob_local)
            expect(200, r.status_code, r.text)
            r = bob.post(f"/api/requirements/{req_id}/sync-ack")
            expect(403, r.status_code, r.text)
            r = bob.post(f"/api/requirements/{req_id}/sync-ack", headers=bob_local)
            expect(200, r.status_code, r.text)

            r = bob.post(f"/api/requirements/{req_id}/claim")
            expect(403, r.status_code, r.text)
            r = bob.post(f"/api/requirements/{req_id}/claim", headers=bob_local)
            expect(200, r.status_code, r.text)
            r = bob.get(f"/api/requirements/{req_id}/assignees")
            expect(200, r.status_code, r.text)
            assert any(a["user_id"] == bob_id and a["role"] == "lead" for a in r.json()), r.text
            r = bob.post(f"/api/requirements/{req_id}/sync-ack", headers=bob_local)
            expect(200, r.status_code, r.text)
            r = bob.patch(f"/api/requirements/{req_id}/status", json={"status": "doing"})
            expect(403, r.status_code, r.text)
            r = bob.patch(f"/api/requirements/{req_id}/status", json={"status": "doing"}, headers=bob_local)
            expect(200, r.status_code, r.text)
            r = bob.post(f"/api/client-devices/{bob_device_id}/revoke")
            expect(200, r.status_code, r.text)

            r = alice.patch(f"/api/requirements/{req_id}/status", json={"status": "cancelled"})
            expect(200, r.status_code, r.text)

            r = alice.post(
                f"/api/requirements/{req_id}/attachments",
                files={"file": ("late.txt", b"late", "text/plain")},
            )
            expect(403, r.status_code, r.text)

            r = alice.post(
                f"/api/projects/{project_id}/requirements",
                json={
                    "raw_description": "Assigned group delivery",
                    "priority": "high",
                    "lead_user_id": bob_id,
                    "collaborator_user_ids": [carl_id],
                    "due_at": due,
                },
            )
            expect(201, r.status_code, r.text)
            assigned_id = r.json()["id"]
            assert any(a["user_id"] == bob_id and a["role"] == "lead" for a in r.json()["assignees"]), r.text
            assert any(a["user_id"] == carl_id and a["role"] == "collaborator" for a in r.json()["assignees"]), r.text

            r = bob.get(f"/api/requirements/{assigned_id}")
            expect(200, r.status_code, r.text)
            r = carl.get(f"/api/requirements/{assigned_id}")
            expect(200, r.status_code, r.text)
            r = dana.get(f"/api/requirements/{assigned_id}")
            expect(403, r.status_code, r.text)

            r = alice.post(
                f"/api/requirements/{assigned_id}/attachments",
                files={"file": ("assigned.txt", b"assigned hello", "text/plain")},
            )
            expect(200, r.status_code, r.text)
            assigned_attachment_id = r.json()["id"]

            db = SessionLocal()
            try:
                req = db.query(Requirement).filter(Requirement.id == assigned_id).one()
                req.title = "Assigned group delivery"
                req.summary_md = "## Goal\nAssigned group delivery\n\n## Acceptance Criteria\n- Multiple workers can deliver"
                req.status = "summary_ready"
                db.commit()
            finally:
                db.close()

            r = alice.post(f"/api/requirements/{assigned_id}/submit")
            expect(200, r.status_code, r.text)

            r = alice.get(f"/api/requirements/{assigned_id}/workspaces")
            expect(200, r.status_code, r.text)
            workspaces = r.json()
            assert {w["user_id"] for w in workspaces} == {bob_id, carl_id}, r.text
            carl_workspace = next(w for w in workspaces if w["user_id"] == carl_id)
            r = dana.get(f"/api/requirements/{assigned_id}/workspaces")
            expect(403, r.status_code, r.text)
            r = carl.patch(
                f"/api/requirements/{assigned_id}/workspaces/me",
                json={"phase": "Smoke doing", "progress_percent": 42, "status_note": "halfway", "blocked_reason": "waiting for smoke"},
                headers=carl_local,
            )
            expect(200, r.status_code, r.text)
            assert r.json()["progress_percent"] == 42 and r.json()["blocked_reason"], r.text
            r = carl.post(f"/api/requirements/{assigned_id}/workspaces/me/items", json={"title": "write smoke item"}, headers=carl_local)
            expect(201, r.status_code, r.text)
            item_id = r.json()["id"]
            r = carl.patch(f"/api/workspace-items/{item_id}", json={"status": "done"}, headers=carl_local)
            expect(200, r.status_code, r.text)
            assert r.json()["status"] == "done", r.text
            r = carl.post(f"/api/requirements/{assigned_id}/workspaces/me/updates", json={"body": "workspace smoke update"}, headers=carl_local)
            expect(201, r.status_code, r.text)
            r = bob.patch(f"/api/workspace-items/{item_id}", json={"status": "todo"}, headers=bob_local)
            expect(403, r.status_code, r.text)

            for client in (bob, carl, dana):
                r = client.get(f"/api/requirements/{assigned_id}")
                expect(200, r.status_code, r.text)
                r = client.get(f"/api/requirements/{assigned_id}/attachments")
                expect(200, r.status_code, r.text)
                r = client.get(f"/api/files/{assigned_attachment_id}")
                expect(200, r.status_code, r.text)

            r = dana.post(f"/api/requirements/{assigned_id}/claim", headers=dana_local)
            expect(403, r.status_code, r.text)
            r = carl.post(f"/api/requirements/{assigned_id}/claim")
            expect(403, r.status_code, r.text)
            r = carl.post(f"/api/requirements/{assigned_id}/claim", headers=dana_local)
            expect(403, r.status_code, r.text)
            r = carl.post(f"/api/requirements/{assigned_id}/claim", headers=carl_local)
            expect(200, r.status_code, r.text)
            r = carl.patch(f"/api/requirements/{assigned_id}/status", json={"status": "doing"})
            expect(403, r.status_code, r.text)
            r = carl.patch(f"/api/requirements/{assigned_id}/status", json={"status": "doing"}, headers=carl_local)
            expect(200, r.status_code, r.text)

            r = dana.post(
                f"/api/requirements/{assigned_id}/delivery/init",
                json={"filename": "dana.zip", "total_size": 1, "total_chunks": 1},
                headers=dana_local,
            )
            expect(403, r.status_code, r.text)
            r = carl.post(
                f"/api/requirements/{assigned_id}/delivery/init",
                json={"filename": "carl.zip", "total_size": 1, "total_chunks": 1},
                headers=carl_local,
            )
            expect(200, r.status_code, r.text)

            r = alice.put(
                f"/api/requirements/{assigned_id}/assignees",
                json={"lead_user_id": bob_id, "collaborator_user_ids": [carl_id, dana_id]},
            )
            expect(200, r.status_code, r.text)
            assert any(a["user_id"] == dana_id and a["role"] == "collaborator" for a in r.json()), r.text
            r = alice.get(f"/api/requirements/{assigned_id}/workspaces")
            expect(200, r.status_code, r.text)
            assert {w["user_id"] for w in r.json()} == {bob_id, carl_id, dana_id}, r.text
            r = dana.post(
                f"/api/requirements/{assigned_id}/delivery/init",
                json={"filename": "dana.zip", "total_size": 1, "total_chunks": 1},
                headers=dana_local,
            )
            expect(200, r.status_code, r.text)
            r = carl.get(f"/api/requirements/{assigned_id}/sync-manifest", headers=carl_local)
            expect(200, r.status_code, r.text)
            assert any(w["nickname"] == "carl" for w in r.json()["workspaces"]), r.text

            r = alice.patch(
                f"/api/requirements/{assigned_id}/planning",
                json={"estimate_hours": 6, "estimate_confidence": "medium", "planning_note": "smoke planning note"},
            )
            expect(200, r.status_code, r.text)
            assert r.json()["estimate_hours"] == 6, r.text
            r = alice.post(f"/api/requirements/{assigned_id}/decompositions", json={"stage": "dispatch"})
            expect(200, r.status_code, r.text)
            dispatch_plan_id = r.json()["id"]
            dispatch_job_id = r.json()["job_id"]
            for _ in range(10):
                r = alice.get(f"/api/jobs/{dispatch_job_id}")
                expect(200, r.status_code, r.text)
                if r.json()["status"] in {"succeeded", "failed"}:
                    break
                time.sleep(0.1)
            assert r.json()["status"] == "succeeded", r.text
            r = alice.get(f"/api/requirements/{assigned_id}/decompositions")
            expect(200, r.status_code, r.text)
            dispatch_plan = next(p for p in r.json() if p["id"] == dispatch_plan_id)
            assert dispatch_plan["items"], r.text
            r = alice.post(f"/api/decompositions/{dispatch_plan_id}/confirm")
            expect(200, r.status_code, r.text)
            assert r.json()["acceptance_items"], r.text
            r = carl.post(f"/api/requirements/{assigned_id}/decompositions", json={"stage": "worker"})
            expect(403, r.status_code, r.text)
            r = carl.post(f"/api/requirements/{assigned_id}/decompositions", json={"stage": "worker"}, headers=carl_local)
            expect(200, r.status_code, r.text)
            worker_plan_id = r.json()["id"]
            worker_job_id = r.json()["job_id"]
            for _ in range(10):
                r = carl.get(f"/api/jobs/{worker_job_id}")
                expect(200, r.status_code, r.text)
                if r.json()["status"] in {"succeeded", "failed"}:
                    break
                time.sleep(0.1)
            assert r.json()["status"] == "succeeded", r.text
            r = carl.post(f"/api/decompositions/{worker_plan_id}/confirm")
            expect(403, r.status_code, r.text)
            r = carl.post(f"/api/decompositions/{worker_plan_id}/confirm", headers=carl_local)
            expect(200, r.status_code, r.text)
            assert r.json()["workspace_items"], r.text
            r = carl.get(f"/api/requirements/{assigned_id}/sync-manifest", headers=carl_local)
            expect(200, r.status_code, r.text)
            assert r.json()["acceptance_items"] and r.json()["task_plans"], r.text

            db = SessionLocal()
            try:
                alice_user = db.query(User).filter(User.id == alice_id).first()
                assert alice_user is not None
                alice_user.is_admin = True
                db.commit()
            finally:
                db.close()

            r = alice.post("/api/knowledge/reindex", json={})
            expect(200, r.status_code, r.text)
            r = alice.get("/api/knowledge/search", params={"q": "Assigned group delivery", "project_id": project_id})
            expect(200, r.status_code, r.text)
            assert r.json()["hits"], r.text
            r = alice.post("/api/knowledge/ask", json={"question": "Assigned group delivery 的验收标准是什么？", "project_id": project_id})
            expect(200, r.status_code, r.text)
            run_id = r.json()["id"]
            for _ in range(10):
                r = alice.get(f"/api/knowledge/runs/{run_id}")
                expect(200, r.status_code, r.text)
                if r.json()["status"] in {"succeeded", "failed"}:
                    break
                time.sleep(0.1)
            assert r.json()["status"] == "succeeded" and r.json()["citations"], r.text

            r = alice.get("/api/planning/workload", params={"project_id": project_id})
            expect(200, r.status_code, r.text)
            assert any(row["user_id"] == carl_id and row["task_count"] >= 1 for row in r.json()), r.text
            r = bob.get("/api/notifications", params={"status": "unread"})
            expect(200, r.status_code, r.text)
            assert any(n["type"] in {"assigned", "due_soon", "due_changed"} for n in r.json()), r.text
            notification_id = r.json()[0]["id"]
            r = bob.post(f"/api/notifications/{notification_id}/read")
            expect(200, r.status_code, r.text)
            assert r.json()["read_at"], r.text
            r = alice.get("/api/project-health")
            expect(200, r.status_code, r.text)
            assert any(p["project_id"] == project_id for p in r.json()), r.text
            r = alice.get(f"/api/projects/{project_id}/health")
            expect(200, r.status_code, r.text)
            assert "score" in r.json() and "risks" in r.json(), r.text

            r = alice.get("/api/voice/voices")
            expect(200, r.status_code, r.text)
            assert "ready" in r.json(), r.text

            meeting_body = "会议记录：需求补充，请增加 smoke 会议导出的按钮，并进入需求评估。".encode("utf-8")
            r = alice.post(
                f"/api/projects/{project_id}/meetings/upload/init",
                json={
                    "filename": "meeting.txt",
                    "total_size": len(meeting_body),
                    "total_chunks": 1,
                    "mime": "text/plain",
                    "title": "Smoke meeting",
                },
            )
            expect(200, r.status_code, r.text)
            meeting_upload_id = r.json()["upload_id"]
            r = alice.put(
                f"/api/projects/{project_id}/meetings/upload/{meeting_upload_id}/chunk/0",
                content=meeting_body,
                headers={"Content-Type": "application/octet-stream"},
            )
            expect(200, r.status_code, r.text)
            r = alice.post(f"/api/projects/{project_id}/meetings/upload/{meeting_upload_id}/finalize")
            expect(200, r.status_code, r.text)
            meeting_id = r.json()["id"]
            job_id = r.json()["job_id"]
            for _ in range(20):
                r = alice.get(f"/api/jobs/{job_id}")
                expect(200, r.status_code, r.text)
                if r.json()["status"] in {"succeeded", "failed"}:
                    break
                time.sleep(0.1)
            assert r.json()["status"] == "succeeded", r.text
            r = alice.get(f"/api/meetings/{meeting_id}")
            expect(200, r.status_code, r.text)
            meeting = r.json()
            assert meeting["status"] == "ready" and meeting["minutes_md"], r.text
            actionable = next(i for i in meeting["insights"] if i["kind"] in {"new_requirement", "requirement_change"})
            r = alice.post(f"/api/meeting-insights/{actionable['id']}/confirm")
            expect(200, r.status_code, r.text)
            created_req_id = r.json()["created_requirement_id"]
            assert created_req_id, r.text
            r = alice.get(f"/api/requirements/{created_req_id}")
            expect(200, r.status_code, r.text)
            assert r.json()["source_meeting_id"] == meeting_id, r.text

            normal_body = "会议记录：只是同步一下文件已经放到网盘。".encode("utf-8")
            r = alice.post(
                f"/api/projects/{project_id}/meetings/upload/init",
                json={"filename": "normal.txt", "total_size": len(normal_body), "total_chunks": 1, "mime": "text/plain"},
            )
            expect(200, r.status_code, r.text)
            normal_upload_id = r.json()["upload_id"]
            r = alice.put(
                f"/api/projects/{project_id}/meetings/upload/{normal_upload_id}/chunk/0",
                content=normal_body,
                headers={"Content-Type": "application/octet-stream"},
            )
            expect(200, r.status_code, r.text)
            r = alice.post(f"/api/projects/{project_id}/meetings/upload/{normal_upload_id}/finalize")
            expect(200, r.status_code, r.text)
            normal_meeting_id = r.json()["id"]
            normal_job_id = r.json()["job_id"]
            for _ in range(20):
                r = alice.get(f"/api/jobs/{normal_job_id}")
                expect(200, r.status_code, r.text)
                if r.json()["status"] in {"succeeded", "failed"}:
                    break
                time.sleep(0.1)
            r = alice.get(f"/api/meetings/{normal_meeting_id}")
            expect(200, r.status_code, r.text)
            normal_insight = r.json()["insights"][0]
            r = alice.post(f"/api/meeting-insights/{normal_insight['id']}/dismiss")
            expect(200, r.status_code, r.text)
            assert r.json()["status"] == "dismissed", r.text

            r = alice.post(
                f"/api/projects/{project_id}/requirements",
                json={"raw_description": "Chunk owner check", "priority": "normal", "due_at": due},
            )
            expect(201, r.status_code, r.text)
            req2_id = r.json()["id"]
            r = alice.post(
                f"/api/requirements/{req2_id}/upload/init",
                json={"filename": "chunk.txt", "total_size": 5, "total_chunks": 1, "mime": "text/plain"},
            )
            expect(200, r.status_code, r.text)
            upload_id = r.json()["upload_id"]
            r = bob.put(
                f"/api/requirements/{req2_id}/upload/{upload_id}/chunk/0",
                content=b"hello",
                headers={"Content-Type": "application/octet-stream"},
            )
            expect(403, r.status_code, r.text)

        engine.dispose()
        print("workflow smoke ok")
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
