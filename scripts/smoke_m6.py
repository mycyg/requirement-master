"""Smoke for M6: submit a clarified requirement, verify push event + manifest."""
import asyncio
import json
import sys

import httpx

import os
BASE = os.environ.get("YQGL_BASE", "http://localhost:8080")


async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=60) as c:
        # Use the existing smoke-m4 user; pick the most recent ready requirement
        await c.post("/api/auth/identify", json={"nickname": "smoke-m4"})
        reqs = (await c.get("/api/requirements?mine=true")).json()
        ready = [r for r in reqs if r["status"] == "ready"]
        if not ready:
            print("no ready requirements; run smoke_m4 first")
            sys.exit(1)
        req = ready[0]
        req_id = req["id"]
        print(f"submitting {req['code']} ({req_id})")

        # subscribe to push stream
        received: list[dict] = []

        async def listen():
            async with c.stream("GET", "/api/push/stream", timeout=30) as r:
                ev: dict = {"event": "", "data": ""}
                async for line in r.aiter_lines():
                    if line.startswith("event:"):
                        ev["event"] = line[6:].strip()
                    elif line.startswith("data:"):
                        ev["data"] = line[5:].strip()
                    elif line == "":
                        if ev["event"]:
                            try:
                                ev["data"] = json.loads(ev["data"])
                            except Exception:
                                pass
                            received.append(dict(ev))
                            print(f"  ← event: {ev['event']}  data: {ev['data']}")
                            if ev["event"] == "requirement.ready":
                                return
                        ev = {"event": "", "data": ""}

        listen_task = asyncio.create_task(listen())
        await asyncio.sleep(0.5)

        # submit
        r = await c.post(f"/api/requirements/{req_id}/submit")
        r.raise_for_status()
        print(f"submit response: {r.json()}")

        try:
            await asyncio.wait_for(listen_task, timeout=10)
        except asyncio.TimeoutError:
            print("✗ did not receive requirement.ready within 10s")
            listen_task.cancel()
            sys.exit(1)

        assert any(e["event"] == "requirement.ready" for e in received), received

        # manifest
        m = (await c.get(f"/api/requirements/{req_id}/sync-manifest")).json()
        print("\nmanifest:")
        print(json.dumps({k: v for k, v in m.items() if k != "chat"}, ensure_ascii=False, indent=2)[:800])
        assert m["code"] and m["summary_md"], m

    print("\n✓ M6 smoke OK")


if __name__ == "__main__":
    asyncio.run(main())
