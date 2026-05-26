"""End-to-end smoke for M12: create requirement → summarize → auto-process via AI agent."""
import json
import sys
import time
import asyncio

import httpx

import os
BASE = os.environ.get("YQGL_BASE", "http://localhost:8080")


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=120) as c:
        await c.post("/api/auth/identify", json={"nickname": "smoke-m12"})

        projects = (await c.get("/api/projects")).json()
        pid = next((p["id"] for p in projects if p["slug"] == "smoke-m12"), None)
        if not pid:
            pid = (await c.post("/api/projects", json={"name": "Smoke M12", "slug": "smoke-m12"})).json()["id"]

        r = (await c.post(f"/api/projects/{pid}/requirements", json={
            "raw_description": "请帮我写一个 Python 脚本 fizzbuzz.py，对 1-30 应用经典 FizzBuzz 规则，把结果打印出来。"
        })).json()
        rid = r["id"]
        print(f"req {r['code']} ({rid})")

        # Force summarize directly
        print("\n=== chat force_summarize ===")
        async with c.stream("POST", f"/api/requirements/{rid}/chat", json={"force_summarize": True}, timeout=120) as resp:
            event = ""; data_lines = []; parsed = None
            async for line in resp.aiter_lines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].strip())
                elif line == "":
                    if event == "parsed":
                        try:
                            parsed = json.loads("\n".join(data_lines))
                        except Exception as e:
                            print(f"parse err: {e}")
                    event = ""; data_lines = []

        if not parsed or parsed["action"] != "summarize":
            print(f"FAIL: no summarize, got: {parsed}")
            sys.exit(1)
        p = parsed["payload"]
        print(f"  title: {p['title']}")
        print(f"  complexity: {p.get('complexity')}")
        print(f"  ai_doable: {p.get('ai_doable')}")
        print(f"  ai_reason: {p.get('ai_reason', '')[:200]}")

        if not p.get("ai_doable"):
            print("⚠ LLM says not AI-doable; aborting")
            sys.exit(0)

        # Subscribe to per-requirement push stream BEFORE triggering
        events_received: list[dict] = []
        done_evt = asyncio.Event()

        async def listener():
            async with c.stream("GET", f"/api/push/stream/req/{rid}", timeout=600) as r:
                ev = ""; dl = []
                async for line in r.aiter_lines():
                    if line.startswith("event:"):
                        ev = line[6:].strip()
                    elif line.startswith("data:"):
                        dl.append(line[5:].strip())
                    elif line == "":
                        if ev:
                            try:
                                d = json.loads("\n".join(dl))
                            except Exception:
                                d = "\n".join(dl)
                            events_received.append({"event": ev, "data": d})
                            t = ev
                            preview = json.dumps(d, ensure_ascii=False)[:120] if isinstance(d, dict) else str(d)[:120]
                            print(f"  ← {t}: {preview}")
                            if t in ("requirement.updated",) and isinstance(d, dict) and d.get("status") in ("delivered", "ready"):
                                done_evt.set()
                                return
                            if t == "ai.failed":
                                done_evt.set()
                                return
                        ev = ""; dl = []

        listen_task = asyncio.create_task(listener())
        await asyncio.sleep(0.3)

        # Trigger auto-process
        print("\n=== trigger /auto-process ===")
        ap = await c.post(f"/api/requirements/{rid}/auto-process")
        ap.raise_for_status()
        print(f"  response: {ap.json()}")

        try:
            await asyncio.wait_for(done_evt.wait(), timeout=360)
        except asyncio.TimeoutError:
            print("⚠ timed out waiting for completion")
        listen_task.cancel()

        # Final state
        final = (await c.get(f"/api/requirements/{rid}")).json()
        print(f"\nFinal status: {final['status']}")

        if final["status"] == "delivered":
            print("\n✅ AI delivered. Inspecting...")
            # Optional: download package would need a download endpoint for delivery; for now just show meta.
            print(f"  delivered_at: {final.get('delivered_at')}")
        elif final["status"] == "ready":
            print("\n❌ AI 翻车，转人工")

if __name__ == "__main__":
    asyncio.run(main())
