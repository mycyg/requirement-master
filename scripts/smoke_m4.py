"""End-to-end smoke for M4: identify, create req, upload, start SSE chat, print events."""
import json
import sys
import tempfile
from pathlib import Path

import httpx

import os
BASE = os.environ.get("YQGL_BASE", "http://localhost:8080")


def main() -> None:
    with httpx.Client(base_url=BASE, timeout=120) as c:
        # auth + setup project + req
        c.post("/api/auth/identify", json={"nickname": "smoke-m4"}).raise_for_status()

        projects = c.get("/api/projects").json()
        project_id = next((p["id"] for p in projects if p["slug"] == "smoke-m4"), None)
        if not project_id:
            r = c.post("/api/projects", json={"name": "Smoke M4", "slug": "smoke-m4"})
            r.raise_for_status()
            project_id = r.json()["id"]

        req = c.post(
            f"/api/projects/{project_id}/requirements",
            json={"raw_description": "我有一份产品需求 Excel 和一张设计参考图，希望做出一个能批量处理订单数据并导出报表的工具。"},
        ).json()
        req_id = req["id"]
        print(f"req: {req['code']}  id={req_id}")

        # upload a small "spec" text
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tf:
            tf.write("订单字段:\n- order_id\n- customer\n- amount\n- created_at\n\n需求是按客户聚合每月销售额。\n")
            tmp = Path(tf.name)
        with open(tmp, "rb") as f:
            r = c.post(
                f"/api/requirements/{req_id}/attachments",
                files={"file": ("orders_spec.txt", f, "text/plain")},
            )
            r.raise_for_status()
        tmp.unlink(missing_ok=True)

        # SSE chat
        print("\n=== SSE chat (first turn) ===")
        events = _run_sse(c, req_id, force=False)
        parsed = next((e["data"] for e in events if e["event"] == "parsed"), None)
        if not parsed:
            print("✗ no parsed event")
            sys.exit(1)

        print("\n=== parsed action ===")
        print(json.dumps(parsed, ensure_ascii=False, indent=2))

        # answer the first question (try a synthetic answer)
        action = parsed.get("action")
        payload = parsed.get("payload", {})

        if action == "ask_choice" and payload.get("options"):
            key = payload["options"][0]["key"]
            print(f"\n=== answering choice: {key} ===")
            c.post(
                f"/api/requirements/{req_id}/chat/answer",
                json={"selected_option_key": key, "other_text": "已自动回答测试值"},
            ).raise_for_status()
        elif action == "ask_open":
            print("\n=== answering open ===")
            c.post(
                f"/api/requirements/{req_id}/chat/answer",
                json={"text": "目标是导出一个 Excel 月度报表，按客户分组汇总。"},
            ).raise_for_status()
        elif action == "summarize":
            print("\n=== LLM 一次性 summarize 了（少见但可接受）===")
            return

        # second turn — force summarize
        print("\n=== SSE chat (force_summarize) ===")
        events2 = _run_sse(c, req_id, force=True)
        parsed2 = next((e["data"] for e in events2 if e["event"] == "parsed"), None)
        if parsed2 and parsed2.get("action") == "summarize":
            print("\n✓ summarize OK")
            print("title:", parsed2["payload"].get("title"))
            print("summary_md (first 500 chars):")
            print((parsed2["payload"].get("summary_md") or "")[:500])
        else:
            print("✗ no summarize on forced turn")
            sys.exit(1)

        # confirm requirement status now = ready
        req_now = c.get(f"/api/requirements/{req_id}").json()
        print(f"\n→ requirement status = {req_now['status']}, title = {req_now['title']!r}")
        assert req_now["status"] == "ready"

    print("\n✓ M4 smoke OK")


def _run_sse(client: httpx.Client, req_id: str, *, force: bool) -> list[dict]:
    events: list[dict] = []
    thinking_chars = 0
    text_chars = 0
    with client.stream(
        "POST",
        f"/api/requirements/{req_id}/chat",
        json={"force_summarize": force},
        timeout=120,
    ) as r:
        r.raise_for_status()
        ev: dict = {"event": "", "data": ""}
        for line in r.iter_lines():
            if line.startswith("event:"):
                ev["event"] = line[6:].strip()
            elif line.startswith("data:"):
                ev["data"] = line[5:].strip()
            elif line == "":
                if ev["event"]:
                    if ev["event"] == "thinking":
                        thinking_chars += len(ev["data"])
                    elif ev["event"] == "text":
                        text_chars += len(ev["data"])
                    else:
                        # parsed / error / done → keep full
                        try:
                            ev["data"] = json.loads(ev["data"])
                        except Exception:
                            pass
                        events.append(dict(ev))
                ev = {"event": "", "data": ""}
    print(f"  → streamed {thinking_chars} thinking chars, {text_chars} text chars, {len(events)} non-stream events")
    return events


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n✗ FAIL: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
