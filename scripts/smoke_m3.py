"""End-to-end smoke test for M3: identify → project → requirement → upload → list → status."""
import json
import sys
import tempfile
from pathlib import Path

import httpx

import os
BASE = os.environ.get("YQGL_BASE", "http://localhost:8080")


def jp(label: str, r: httpx.Response) -> dict:
    print(f"\n== {label}  [{r.status_code}] ==")
    try:
        data = r.json()
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return data
    except Exception:
        print(r.text[:500])
        return {}


def main() -> None:
    with httpx.Client(base_url=BASE, timeout=30) as c:
        d = jp("identify", c.post("/api/auth/identify", json={"nickname": "smoke-m3"}))
        assert d.get("nickname") == "smoke-m3", d

        d = jp("create project", c.post("/api/projects", json={
            "name": "Smoke Project",
            "slug": "smoke",
            "description": "End-to-end test project",
        }))
        if d.get("id"):
            project_id = d["id"]
        else:
            # likely already exists; fetch list
            projects = jp("list projects", c.get("/api/projects"))
            project_id = next(p["id"] for p in projects if p["slug"] == "smoke")

        d = jp("create requirement", c.post(f"/api/projects/{project_id}/requirements", json={
            "raw_description": "请帮我做一个能自动给 PDF 加水印的小工具，命令行就行",
            "priority": "normal",
        }))
        req_id = d["id"]
        code = d["code"]
        print(f"\n  ↳ req_id={req_id}  code={code}")

        # Make a small text file and upload it
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tf:
            tf.write("这是一个示例参考文档。\n第二行 - 测试 markitdown 解析。\n")
            tmp_path = Path(tf.name)
        try:
            with open(tmp_path, "rb") as f:
                d = jp(
                    "upload simple",
                    c.post(
                        f"/api/requirements/{req_id}/attachments",
                        files={"file": (tmp_path.name, f, "text/plain")},
                    ),
                )
            att_id = d["id"]
            assert d["has_parsed_text"], "expected text file to be parsed"
        finally:
            tmp_path.unlink(missing_ok=True)

        jp("list attachments", c.get(f"/api/requirements/{req_id}/attachments"))

        d = jp("download attachment", c.get(f"/api/files/{att_id}"))  # JSON-print best-effort; will dump raw
        # already printed text content

        jp("status → clarifying", c.patch(
            f"/api/requirements/{req_id}/status", json={"status": "clarifying"},
        ))

        rows = jp("list requirements (mine)", c.get("/api/requirements?mine=true"))
        assert any(r["id"] == req_id for r in rows)

    print("\n✓ M3 smoke OK")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n✗ FAIL: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
