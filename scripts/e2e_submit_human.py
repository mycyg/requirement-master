"""E2E: simulate a colleague (提需求方) submitting a requirement for human processing.

Flow:
  1. identify as another user
  2. ensure 'e2e' project exists
  3. create requirement + upload attachment
  4. force-summarize via SSE
  5. submit (NOT auto-process; we want human path)
  6. wait, then ask tray's log file what happened
"""
import json, time, tempfile
from pathlib import Path

import httpx

import os
BASE = os.environ.get("YQGL_BASE", "http://localhost:8080")


def main():
    with httpx.Client(base_url=BASE, timeout=120) as c:
        c.post("/api/auth/identify", json={"nickname": "同事-小李"}).raise_for_status()

        projects = c.get("/api/projects").json()
        pid = next((p["id"] for p in projects if p["slug"] == "e2e"), None)
        if not pid:
            pid = c.post("/api/projects", json={
                "name": "E2E 测试项目", "slug": "e2e",
                "description": "端到端联调用",
            }).json()["id"]
        print(f"project: e2e ({pid})")

        r = c.post(f"/api/projects/{pid}/requirements", json={
            "raw_description": "请帮我整理一份产品上线 checklist 的 Markdown 模板，包含技术验证 / 文案审核 / 数据埋点 / 应急回滚 四个分组。",
            "priority": "high",
        }).json()
        rid = r["id"]
        print(f"requirement: {r['code']} ({rid})")

        # Add an attachment (a tiny text file)
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tf:
            tf.write("参考：上次上线时漏了灰度配置，导致 5 分钟的全量故障。\n回滚耗时 12 分钟。这次模板要求把回滚 SOP 放显眼位置。\n")
            tmp = Path(tf.name)
        with open(tmp, "rb") as f:
            att = c.post(
                f"/api/requirements/{rid}/attachments",
                files={"file": ("背景说明.txt", f, "text/plain")},
            ).json()
            print(f"  attached: {att['filename']} (parsed={att['has_parsed_text']})")
        tmp.unlink(missing_ok=True)

        # Force summarize (skip back-and-forth Q&A)
        print("\nrunning LLM summarize (force)...")
        summary = None
        with c.stream("POST", f"/api/requirements/{rid}/chat", json={"force_summarize": True}, timeout=120) as resp:
            ev = ""; dl = []
            for line in resp.iter_lines():
                if line.startswith("event:"): ev = line[6:].strip()
                elif line.startswith("data:"): dl.append(line[5:].strip())
                elif line == "":
                    if ev == "parsed":
                        try: summary = json.loads("\n".join(dl))
                        except Exception: pass
                    ev = ""; dl = []
        if not summary:
            raise SystemExit("no summary")
        p = summary["payload"]
        print(f"  title: {p['title']}")
        print(f"  complexity: {p.get('complexity')}  ai_doable: {p.get('ai_doable')}")
        print(f"  ai_reason: {p.get('ai_reason')}")

        # 强制走人工路径
        print("\nsubmit → status=ready (human path)")
        c.post(f"/api/requirements/{rid}/submit").raise_for_status()

        return rid, r["code"]


if __name__ == "__main__":
    rid, code = main()
    print(f"\n→ requirement {code} ({rid}) is now in ready state.")
    print(f"  → tray should download to D:\\工作需求\\e2e\\{code}\\ within ~1s")
