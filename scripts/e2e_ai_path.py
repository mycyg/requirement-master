"""E2E: AI 自动处理路径。

1. 同事提交一个 AI-friendly 需求
2. summarize → 显示 complexity / ai_doable
3. 触发 /auto-process
4. 实时订阅 SSE 看 AI 干活的全过程
5. 验证 delivered + 下载交付包确认内容
"""
import asyncio, json, sys
import httpx

import os
BASE = os.environ.get("YQGL_BASE", "http://localhost:8080")


async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=180) as c:
        await c.post("/api/auth/identify", json={"nickname": "同事-小李"})

        # ensure e2e project
        ps = (await c.get("/api/projects")).json()
        pid = next((p["id"] for p in ps if p["slug"] == "e2e"), None)

        r = (await c.post(f"/api/projects/{pid}/requirements", json={
            "raw_description": "请写一个 Python 函数 word_count(path: str) -> dict[str,int]，"
                               "读取文本文件，返回单词频率字典（不区分大小写，去掉标点）。"
                               "另外写一个 demo.py 演示用法，并准备一个 sample.txt 测试文件。",
            "priority": "normal",
        })).json()
        rid = r["id"]
        print(f"requirement: {r['code']} ({rid})")

        # force summarize
        summary = None
        async with c.stream("POST", f"/api/requirements/{rid}/chat",
                            json={"force_summarize": True}, timeout=120) as resp:
            ev = ""; dl = []
            async for line in resp.aiter_lines():
                if line.startswith("event:"): ev = line[6:].strip()
                elif line.startswith("data:"): dl.append(line[5:].strip())
                elif line == "":
                    if ev == "parsed":
                        try: summary = json.loads("\n".join(dl))
                        except Exception: pass
                    ev = ""; dl = []

        p = summary["payload"]
        print(f"  title: {p['title']}")
        print(f"  complexity={p.get('complexity')}  ai_doable={p.get('ai_doable')}")
        print(f"  ai_reason: {p.get('ai_reason')}")

        if not p.get("ai_doable"):
            print("LLM 拒绝交给 AI，退出")
            return

        # subscribe SSE for live events
        done_evt = asyncio.Event()
        last_status = {"v": None}

        async def listen():
            async with c.stream("GET", f"/api/push/stream/req/{rid}", timeout=600) as resp:
                ev = ""; dl = []
                async for line in resp.aiter_lines():
                    if line.startswith("event:"): ev = line[6:].strip()
                    elif line.startswith("data:"): dl.append(line[5:].strip())
                    elif line == "":
                        if ev:
                            try: d = json.loads("\n".join(dl))
                            except Exception: d = "\n".join(dl)
                            print(f"  ← {ev}: {(json.dumps(d, ensure_ascii=False) if isinstance(d, dict) else str(d))[:160]}")
                            if ev == "requirement.updated" and isinstance(d, dict):
                                last_status["v"] = d.get("status")
                                if d.get("status") in ("delivered", "ready"):
                                    done_evt.set(); return
                            elif ev == "ai.failed":
                                done_evt.set(); return
                        ev = ""; dl = []

        listen_task = asyncio.create_task(listen())
        await asyncio.sleep(0.3)

        print("\n→ triggering /auto-process")
        await c.post(f"/api/requirements/{rid}/auto-process")

        try:
            await asyncio.wait_for(done_evt.wait(), timeout=300)
        except asyncio.TimeoutError:
            print("⚠ timed out")
        listen_task.cancel()

        final = (await c.get(f"/api/requirements/{rid}")).json()
        print(f"\nfinal status: {final['status']}")

        if final["status"] == "delivered":
            dl = (await c.get(f"/api/requirements/{rid}/deliveries")).json()
            print(f"\ndelivery files: {[f['name'] for f in dl[0]['files']]}")
            print(f"delivery doc preview:\n{dl[0]['delivery_doc_md'][:500]}")
        else:
            print("ai 翻车了，转人工")


if __name__ == "__main__":
    asyncio.run(main())
