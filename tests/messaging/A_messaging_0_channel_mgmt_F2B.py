#!/usr/bin/env python3
"""Test F2B — channel_mgmt. Frontend→Backend hooks."""
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
        print("F2B-01 list channels has structure")
        r = await c.get("/api/messaging/channel-mgmt/channels")
        data = r.json()
        check("F2B-01 keys", "channels" in data and "total" in data, f"{list(data.keys())}")
        check("F2B-01 count", data.get("total", 0) >= 5, f"total={data.get('total')}")
        print("F2B-02 get channel detail fields")
        r2 = await c.get("/api/messaging/channel-mgmt/channels/C001")
        ch = r2.json()
        check("F2B-02 name", ch.get("name") == "general", f"{ch.get('name')}")
        check("F2B-02 fields", "id" in ch and "created" in ch, f"{list(ch.keys())}")
        print("F2B-03 create + verify in list")
        r3 = await c.post("/api/messaging/channel-mgmt/channels", json={"name": "f2b-test", "is_private": False})
        cid = r3.json().get("id", "")
        check("F2B-03 created", cid != "", "no id")
        r3b = await c.get(f"/api/messaging/channel-mgmt/channels/{cid}")
        check("F2B-03 found", r3b.status_code == 200 and r3b.json().get("name") == "f2b-test", f"{r3b.status_code}")
        print("F2B-04 set topic + verify")
        await c.put(f"/api/messaging/channel-mgmt/channels/{cid}/topic", json={"topic": "F2B Topic"})
        r4 = await c.get(f"/api/messaging/channel-mgmt/channels/{cid}")
        check("F2B-04 topic", r4.json().get("topic") == "F2B Topic", f"{r4.json().get('topic')}")
        print("F2B-05 set purpose + verify")
        await c.put(f"/api/messaging/channel-mgmt/channels/{cid}/purpose", json={"purpose": "F2B Purpose"})
        r5 = await c.get(f"/api/messaging/channel-mgmt/channels/{cid}")
        check("F2B-05 purpose", r5.json().get("purpose") == "F2B Purpose", f"{r5.json().get('purpose')}")
        print("F2B-06 invite + list members")
        await c.post(f"/api/messaging/channel-mgmt/channels/{cid}/members", json={"users": "U_F2B"})
        r6 = await c.get(f"/api/messaging/channel-mgmt/channels/{cid}/members")
        members = r6.json() if isinstance(r6.json(), list) else r6.json().get("members", [])
        check("F2B-06 member", any(m.get("user_id") == "U_F2B" or m.get("id") == "U_F2B" for m in members), f"{len(members)} members")
        print("F2B-07 archive + unarchive")
        r7a = await c.delete(f"/api/messaging/channel-mgmt/channels/{cid}")
        check("F2B-07 archive", r7a.status_code == 200, f"{r7a.status_code}")
        r7b = await c.post(f"/api/messaging/channel-mgmt/channels/{cid}/unarchive")
        check("F2B-07 unarchive", r7b.status_code == 200, f"{r7b.status_code}")
        print("F2B-08 events endpoint")
        r8 = await c.get("/api/messaging/channel-mgmt/events")
        check("F2B-08 ok", r8.status_code == 200, f"{r8.status_code}")
    print(f"\n{'='*50}"); print(f"PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
    if FAIL: sys.exit(1)
if __name__ == "__main__": asyncio.run(main())
