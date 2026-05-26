"""End-to-end smoke for M8: simulate the tray client.
- Pick a fresh requirement, do clarify → submit (status=ready).
- Locally make a fake deliverable dir, zip it, upload via chunked endpoints.
- Verify a Delivery row is created and delivery_doc_md gets filled by LLM.
"""
import hashlib, json, os, tempfile, time, zipfile
from pathlib import Path

import httpx

import os
BASE = os.environ.get("YQGL_BASE", "http://localhost:8080")


def main():
    with httpx.Client(base_url=BASE, timeout=180) as c:
        c.post("/api/auth/identify", json={"nickname": "smoke-m8"}).raise_for_status()

        projects = c.get("/api/projects").json()
        pid = next((p["id"] for p in projects if p["slug"] == "smoke-m8"), None)
        if not pid:
            pid = c.post("/api/projects", json={"name": "Smoke M8", "slug": "smoke-m8"}).json()["id"]

        r = c.post(f"/api/projects/{pid}/requirements", json={
            "raw_description": "写一个 README 介绍 yqgl 项目"
        }).json()
        rid = r["id"]
        print(f"req {r['code']} ({rid})")

        # force summarize so we have summary_md
        with c.stream("POST", f"/api/requirements/{rid}/chat", json={"force_summarize": True}, timeout=120) as resp:
            for _ in resp.iter_lines(): pass

        c.post(f"/api/requirements/{rid}/submit").raise_for_status()
        c.post(f"/api/requirements/{rid}/claim").raise_for_status()
        print(f"submitted + claimed; status = {c.get(f'/api/requirements/{rid}').json()['status']}")

        # Build a fake delivery zip
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "deliverables"
            src.mkdir()
            (src / "README.md").write_text(
                "# YQGL\n\n需求管理大师，让团队需求收集与交付自动化。\n\n## 特性\n- LLM Agent 反问澄清\n- 语音输入输出\n- AI 自动交付\n",
                encoding="utf-8",
            )
            (src / "requirement.md").write_text(c.get(f"/api/requirements/{rid}").json()["summary_md"] or "", encoding="utf-8")
            zip_path = Path(td) / "deliv.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
                for p in src.rglob("*"):
                    if p.is_file():
                        z.write(p, p.relative_to(src))

            size = zip_path.stat().st_size
            CHUNK = 5 * 1024 * 1024
            total_chunks = max(1, (size + CHUNK - 1) // CHUNK)
            print(f"\nzip: {size}B, {total_chunks} chunk(s)")

            r1 = c.post(f"/api/requirements/{rid}/delivery/init", json={
                "filename": "deliv.zip", "total_size": size, "total_chunks": total_chunks,
            }).json()
            upload_id = r1["upload_id"]
            print(f"init → upload_id={upload_id}")

            with open(zip_path, "rb") as f:
                for idx in range(total_chunks):
                    buf = f.read(CHUNK)
                    c.put(
                        f"/api/requirements/{rid}/delivery/{upload_id}/chunk/{idx}",
                        content=buf, headers={"Content-Type": "application/octet-stream"},
                    ).raise_for_status()
                    print(f"  chunk {idx} ({len(buf)}B) uploaded")

            f1 = c.post(f"/api/requirements/{rid}/delivery/{upload_id}/finalize").json()
            print(f"finalize → {f1}")

        # Wait for LLM doc to populate
        print("\nwaiting for LLM doc...")
        for i in range(20):
            time.sleep(1.5)
            dl = c.get(f"/api/requirements/{rid}/deliveries").json()
            doc = dl[0].get("delivery_doc_md") or ""
            if "正在撰写" not in doc:
                print(f"  doc ready ({len(doc)} chars):")
                print(doc[:600])
                break
        else:
            print("  doc did not populate in 30s")

        final = c.get(f"/api/requirements/{rid}").json()
        print(f"\nfinal status: {final['status']}")

if __name__ == "__main__":
    main()
