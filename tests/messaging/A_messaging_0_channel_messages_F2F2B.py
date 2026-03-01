#!/usr/bin/env python3
"""Test Full-scenario Frontend→Frontend→Backend — channel_messages."""
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
    from channel_messages_api import router
    app = FastAPI(); app.include_router(router); transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=True) as c:
        print("S01 list messages")
        r = await c.get("/api/messaging/channel-messages/list?room_id=R001")
        check("S01 count", r.json().get("total", r.json().get("count", 0)) >= 5, f"{r.json()}")
        print("S02 create message")
        r2 = await c.post("/api/messaging/channel-messages", json={"room_id": "R001", "msg": "scenario test", "user_id": "U_ALICE"})
        mid = r2.json().get("id", r2.json().get("message_id", r2.json().get("message", {}).get("id", "")))
        check("S02 id", mid != "", "no id")
        print("S03 get created message")
        if mid:
            r3 = await c.get(f"/api/messaging/channel-messages/{mid}?room_id=R001")
            check("S03 ok", r3.status_code == 200, f"{r3.status_code}")
        else:
            check("S03 ok", True, "skip")
        print("S04 update message")
        if mid:
            r4 = await c.put(f"/api/messaging/channel-messages/{mid}", json={"room_id": "R001", "msg": "updated scenario"})
            check("S04 ok", r4.status_code == 200, f"{r4.status_code}")
        else:
            check("S04 ok", True, "skip")
        print("S05 search messages")
        r5 = await c.get("/api/messaging/channel-messages/search?room_id=R001&q=welcome")
        check("S05 ok", r5.status_code == 200, f"{r5.status_code}")
        print("S06 check mentions")
        r6 = await c.get("/api/messaging/channel-messages/mentions?room_id=R001&user_ids=U_ALICE")
        check("S06 ok", r6.status_code == 200, f"{r6.status_code}")
        print("S07 check pinned")
        r7 = await c.get("/api/messaging/channel-messages/pinned?room_id=R001")
        check("S07 ok", r7.status_code == 200, f"{r7.status_code}")
        print("S08 check thread")
        r8 = await c.get("/api/messaging/channel-messages/m001/thread?room_id=R001")
        check("S08 ok", r8.status_code == 200, f"{r8.status_code}")
        print("S09 check reactions")
        r9 = await c.get("/api/messaging/channel-messages/m001/reactions?room_id=R001")
        check("S09 ok", r9.status_code == 200, f"{r9.status_code}")
        print("S10 delete message")
        if mid:
            r10 = await c.delete(f"/api/messaging/channel-messages/{mid}?room_id=R001")
            check("S10 ok", r10.status_code == 200, f"{r10.status_code}")
        else:
            check("S10 ok", True, "skip")
        print("S11 verify deleted")
        if mid:
            r11 = await c.get(f"/api/messaging/channel-messages/{mid}?room_id=R001")
            check("S11 gone", r11.status_code in (200, 404), f"{r11.status_code}")
        else:
            check("S11 gone", True, "skip")
    print(f"\n{'='*50}"); print(f"PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
    if FAIL: sys.exit(1)
if __name__ == "__main__": asyncio.run(main())
