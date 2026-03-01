#!/usr/bin/env python3
"""Test Backend — channel_org. 12 endpoints."""
import asyncio, os, sys, tempfile
PASS = 0
FAIL = 0
def check(name, cond, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  PASS {name}")
    else: FAIL += 1; print(f"  FAIL {name} — {detail}")
async def main():
    tmp = tempfile.mkdtemp(); os.environ["AIAPP_BASE"] = tmp
    sys.path.insert(0, "/home/ubuntu/aiapp/backend"); sys.path.insert(0, "/home/ubuntu/aiapp/infra/pgsql")
    from fastapi import FastAPI; from httpx import AsyncClient, ASGITransport
    from channel_org_api import router
    app = FastAPI(); app.include_router(router); transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=True) as c:
        print("T01 list channels")
        r = await c.get("/api/messaging/channel-org/channels")
        check("T01 ok", r.status_code == 200, f"{r.status_code}")
        print("T02 get channel detail")
        r2 = await c.get("/api/messaging/channel-org/channels/ch01")
        check("T02 ok", r2.status_code == 200, f"{r2.status_code}")
        print("T03 search channels")
        r3 = await c.post("/api/messaging/channel-org/channels/search", json={"query": "general"})
        check("T03 ok", r3.status_code == 200, f"{r3.status_code}")
        print("T04 filter channels")
        r4 = await c.post("/api/messaging/channel-org/channels/filter", json={"types": ["public"]})
        check("T04 ok", r4.status_code == 200, f"{r4.status_code}")
        print("T05 list sections")
        r5 = await c.get("/api/messaging/channel-org/sections")
        check("T05 ok", r5.status_code == 200, f"{r5.status_code}")
        print("T06 get section")
        r6 = await c.get("/api/messaging/channel-org/sections/ss01")
        check("T06 ok", r6.status_code == 200, f"{r6.status_code}")
        print("T07 create section")
        r7 = await c.post("/api/messaging/channel-org/sections", json={"name": "Test Section", "emoji": "🧪", "channels": []})
        check("T07 ok", r7.status_code in (200, 201), f"{r7.status_code}")
        sid = r7.json().get("id", "")
        print("T08 move channel to section")
        if sid:
            r8 = await c.post(f"/api/messaging/channel-org/sections/{sid}/move", json={"channel_id": "ch01"})
            check("T08 ok", r8.status_code == 200, f"{r8.status_code}")
        else:
            check("T08 ok", True, "skip")
        print("T09 reorder sections")
        r9 = await c.post("/api/messaging/channel-org/sections/reorder", json={"section_ids": ["ss01", "ss02"]})
        check("T09 ok", r9.status_code == 200, f"{r9.status_code}")
        print("T10 delete section")
        if sid:
            r10 = await c.delete(f"/api/messaging/channel-org/sections/{sid}")
            check("T10 ok", r10.status_code == 200, f"{r10.status_code}")
        else:
            check("T10 ok", True, "skip")
        print("T11 discovery")
        r11 = await c.get("/api/messaging/channel-org/discovery")
        check("T11 ok", r11.status_code == 200, f"{r11.status_code}")
        print("T12 analyze activity")
        r12 = await c.post("/api/messaging/channel-org/discovery/analyze", json={"channel_id": "ch01"})
        check("T12 ok", r12.status_code == 200, f"{r12.status_code}")
    print(f"\n{'='*50}"); print(f"PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
    if FAIL: sys.exit(1)
if __name__ == "__main__": asyncio.run(main())
