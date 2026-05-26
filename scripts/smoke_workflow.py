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

        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

        from fastapi.testclient import TestClient

        from db import SessionLocal, engine
        from main import app
        from models import Requirement

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

            r = alice.post("/api/projects", json={"name": "Smoke", "slug": "smoke"})
            expect(201, r.status_code, r.text)
            project_id = r.json()["id"]

            r = alice.get("/api/users", params={"search": "bo"})
            expect(200, r.status_code, r.text)
            assert any(u["id"] == bob_id for u in r.json()), r.text

            r = alice.post(
                f"/api/projects/{project_id}/requirements",
                json={"raw_description": "Build a smoke-test artifact", "priority": "normal"},
            )
            expect(201, r.status_code, r.text)
            req_id = r.json()["id"]

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

            r = bob.get(f"/api/requirements/{req_id}")
            expect(200, r.status_code, r.text)
            r = bob.get(f"/api/requirements/{req_id}/attachments")
            expect(200, r.status_code, r.text)
            r = bob.get(f"/api/files/{attachment_id}")
            expect(200, r.status_code, r.text)
            r = bob.get(f"/api/requirements/{req_id}/sync-manifest")
            expect(200, r.status_code, r.text)
            r = bob.post(f"/api/requirements/{req_id}/sync-ack")
            expect(200, r.status_code, r.text)

            r = bob.post(f"/api/requirements/{req_id}/claim")
            expect(200, r.status_code, r.text)
            r = bob.get(f"/api/requirements/{req_id}/assignees")
            expect(200, r.status_code, r.text)
            assert any(a["user_id"] == bob_id and a["role"] == "lead" for a in r.json()), r.text
            r = bob.post(f"/api/requirements/{req_id}/sync-ack")
            expect(200, r.status_code, r.text)
            r = bob.patch(f"/api/requirements/{req_id}/status", json={"status": "doing"})
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

            for client in (bob, carl, dana):
                r = client.get(f"/api/requirements/{assigned_id}")
                expect(200, r.status_code, r.text)
                r = client.get(f"/api/requirements/{assigned_id}/attachments")
                expect(200, r.status_code, r.text)
                r = client.get(f"/api/files/{assigned_attachment_id}")
                expect(200, r.status_code, r.text)

            r = dana.post(f"/api/requirements/{assigned_id}/claim")
            expect(403, r.status_code, r.text)
            r = carl.post(f"/api/requirements/{assigned_id}/claim")
            expect(200, r.status_code, r.text)
            r = carl.patch(f"/api/requirements/{assigned_id}/status", json={"status": "doing"})
            expect(200, r.status_code, r.text)

            r = dana.post(
                f"/api/requirements/{assigned_id}/delivery/init",
                json={"filename": "dana.zip", "total_size": 1, "total_chunks": 1},
            )
            expect(403, r.status_code, r.text)
            r = carl.post(
                f"/api/requirements/{assigned_id}/delivery/init",
                json={"filename": "carl.zip", "total_size": 1, "total_chunks": 1},
            )
            expect(200, r.status_code, r.text)

            r = alice.put(
                f"/api/requirements/{assigned_id}/assignees",
                json={"lead_user_id": bob_id, "collaborator_user_ids": [carl_id, dana_id]},
            )
            expect(200, r.status_code, r.text)
            assert any(a["user_id"] == dana_id and a["role"] == "collaborator" for a in r.json()), r.text
            r = dana.post(
                f"/api/requirements/{assigned_id}/delivery/init",
                json={"filename": "dana.zip", "total_size": 1, "total_chunks": 1},
            )
            expect(200, r.status_code, r.text)

            r = alice.get("/api/voice/voices")
            expect(200, r.status_code, r.text)
            assert "ready" in r.json(), r.text

            r = alice.post(
                f"/api/projects/{project_id}/requirements",
                json={"raw_description": "Chunk owner check", "priority": "normal"},
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
