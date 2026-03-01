#!/usr/bin/env python3
"""Test Backend — channel_ops. 12 endpoints."""
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
    from channel_ops_api import router
    app = FastAPI(); app.include_router(router); transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=True) as c:
        print("T01 get settings")
        r = await c.get("/api/messaging/channel-ops/settings/C001")
        check("T01 ok", r.status_code == 200, f"{r.status_code}")
        check("T01 name", r.json().get("channel_name") is not None, f"{r.json()}")
        print("T02 set topic")
        r2 = await c.put("/api/messaging/channel-ops/settings/C001/topic", json={"topic": "New topic"})
        check("T02 ok", r2.status_code == 200, f"{r2.status_code}")
        print("T03 set purpose")
        r3 = await c.put("/api/messaging/channel-ops/settings/C001/purpose", json={"purpose": "New purpose"})
        check("T03 ok", r3.status_code == 200, f"{r3.status_code}")
        print("T04 list members")
        r4 = await c.get("/api/messaging/channel-ops/members/C001")
        check("T04 ok", r4.status_code == 200, f"{r4.status_code}")
        print("T05 get member detail")
        members = r4.json() if isinstance(r4.json(), list) else r4.json().get("members", [])
        if members:
            uid = members[0].get("user_id", "")
            r5 = await c.get(f"/api/messaging/channel-ops/members/C001/{uid}")
            check("T05 ok", r5.status_code == 200, f"{r5.status_code}")
        else:
            check("T05 ok", True, "skip")
        print("T06 remove member")
        r6 = await c.post("/api/messaging/channel-ops/members/C001/remove", json={"user_id": "U_TEST_REMOVE"})
        check("T06 ok", r6.status_code in (200, 404), f"{r6.status_code}")
        print("T07 channel history")
        r7 = await c.get("/api/messaging/channel-ops/history/C001")
        check("T07 ok", r7.status_code == 200, f"{r7.status_code}")
        print("T08 thread replies")
        r8 = await c.get("/api/messaging/channel-ops/history/C001/thread/1709000001.000100")
        check("T08 ok", r8.status_code == 200, f"{r8.status_code}")
        print("T09 search messages")
        r9 = await c.post("/api/messaging/channel-ops/history/search", json={"query": "test", "channel_id": "C001"})
        check("T09 ok", r9.status_code == 200, f"{r9.status_code}")
        print("T10 list activity")
        r10 = await c.get("/api/messaging/channel-ops/activity")
        check("T10 ok", r10.status_code == 200, f"{r10.status_code}")
        print("T11 analyze health")
        r11 = await c.post("/api/messaging/channel-ops/activity/analyze", json={"channel_id": "C001"})
        check("T11 ok", r11.status_code == 200, f"{r11.status_code}")
        print("T12 settings 404")
        r12 = await c.get("/api/messaging/channel-ops/settings/FAKE")
        check("T12 404", r12.status_code == 404, f"{r12.status_code}")
    print(f"\n{'='*50}"); print(f"PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
    if FAIL: sys.exit(1)
if __name__ == "__main__": asyncio.run(main())
