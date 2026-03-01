#!/usr/bin/env python3
"""Test Backend — channel_mgmt. 12 endpoints."""
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
    from channel_mgmt_api import router
    app = FastAPI(); app.include_router(router); transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=True) as c:
        print("T01 list channels")
        r = await c.get("/api/messaging/channel-mgmt/channels")
        check("T01 count", r.json().get("total", len(r.json().get("channels", []))) >= 5, f"{r.json().get('total')}")
        print("T02 get channel")
        r2 = await c.get("/api/messaging/channel-mgmt/channels/C001")
        check("T02 name", r2.json().get("name") == "general", f"{r2.json().get('name')}")
        print("T03 get 404")
        r3 = await c.get("/api/messaging/channel-mgmt/channels/FAKE")
        check("T03 404", r3.status_code == 404, f"{r3.status_code}")
        print("T04 create channel")
        r4 = await c.post("/api/messaging/channel-mgmt/channels", json={"name": "test-chan", "is_private": False})
        check("T04 ok", r4.status_code in (200, 201), f"{r4.status_code}")
        cid = r4.json().get("id", "")
        check("T04 id", cid != "", "no id")
        print("T05 set topic")
        r5 = await c.put(f"/api/messaging/channel-mgmt/channels/{cid}/topic", json={"topic": "Test topic"})
        check("T05 ok", r5.status_code == 200, f"{r5.status_code}")
        print("T06 set purpose")
        r6 = await c.put(f"/api/messaging/channel-mgmt/channels/{cid}/purpose", json={"purpose": "Test purpose"})
        check("T06 ok", r6.status_code == 200, f"{r6.status_code}")
        print("T07 list members")
        r7 = await c.get("/api/messaging/channel-mgmt/channels/C001/members")
        check("T07 ok", r7.status_code == 200, f"{r7.status_code}")
        print("T08 invite member")
        r8 = await c.post(f"/api/messaging/channel-mgmt/channels/{cid}/members", json={"users": "U_TEST"})
        check("T08 ok", r8.status_code in (200, 201), f"{r8.status_code}")
        print("T09 kick member")
        r9 = await c.delete(f"/api/messaging/channel-mgmt/channels/{cid}/members/U_TEST")
        check("T09 ok", r9.status_code in (200, 404), f"{r9.status_code}")
        print("T10 archive channel")
        r10 = await c.delete(f"/api/messaging/channel-mgmt/channels/{cid}")
        check("T10 ok", r10.status_code == 200, f"{r10.status_code}")
        print("T11 unarchive")
        r11 = await c.post(f"/api/messaging/channel-mgmt/channels/{cid}/unarchive")
        check("T11 ok", r11.status_code == 200, f"{r11.status_code}")
        print("T12 channel events")
        r12 = await c.get("/api/messaging/channel-mgmt/events")
        check("T12 ok", r12.status_code == 200, f"{r12.status_code}")
        print("T13 stats")
        r13 = await c.get("/api/messaging/channel-mgmt/stats")
        check("T13 ok", r13.status_code == 200, f"{r13.status_code}")
    print(f"\n{'='*50}"); print(f"PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
    if FAIL: sys.exit(1)
if __name__ == "__main__": asyncio.run(main())
