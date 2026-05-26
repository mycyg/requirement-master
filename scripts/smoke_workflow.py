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

        with TestClient(app) as alice, TestClient(app) as bob:
            expect(200, alice.post("/api/auth/identify", json={"nickname": "alice"}).status_code, "")
            expect(200, bob.post("/api/auth/identify", json={"nickname": "bob"}).status_code, "")

            r = alice.post("/api/projects", json={"name": "Smoke", "slug": "smoke"})
            expect(201, r.status_code, r.text)
            project_id = r.json()["id"]

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
            expect(403, r.status_code, r.text)

            r = bob.post(f"/api/requirements/{req_id}/claim")
            expect(200, r.status_code, r.text)
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
