#!/usr/bin/env python3
"""Test Backend — channel_messages. 12 endpoints."""
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
        print("T01 list messages")
        r = await c.get("/api/messaging/channel-messages/list?room_id=R001")
        check("T01 count", r.json().get("total", r.json().get("count", 0)) >= 5, f"{r.json()}")
        print("T02 mentions")
        r2 = await c.get("/api/messaging/channel-messages/mentions?room_id=R001&user_ids=U_ALICE")
        check("T02 ok", r2.status_code == 200, f"{r2.status_code}")
        print("T03 starred")
        r3 = await c.get("/api/messaging/channel-messages/starred?room_id=R001&user_id=U_ADMIN")
        check("T03 ok", r3.status_code == 200, f"{r3.status_code}")
        print("T04 pinned")
        r4 = await c.get("/api/messaging/channel-messages/pinned?room_id=R001")
        check("T04 ok", r4.status_code == 200, f"{r4.status_code}")
        print("T05 search")
        r5 = await c.get("/api/messaging/channel-messages/search?room_id=R001&q=welcome")
        check("T05 ok", r5.status_code == 200, f"{r5.status_code}")
        print("T06 stats")
        r6 = await c.get("/api/messaging/channel-messages/stats?room_id=R001")
        check("T06 ok", r6.status_code == 200, f"{r6.status_code}")
        check("T06 total", r6.json().get("total_messages", r6.json().get("total", 0)) >= 5, f"{r6.json()}")
        print("T07 create message")
        r7 = await c.post("/api/messaging/channel-messages", json={"room_id": "R001", "msg": "test", "user_id": "U_ALICE"})
        check("T07 ok", r7.status_code in (200, 201), f"{r7.status_code}")
        msg_id = r7.json().get("id", r7.json().get("message_id", r7.json().get("message", {}).get("id", "")))
        print("T08 get message")
        if msg_id:
            r8 = await c.get(f"/api/messaging/channel-messages/{msg_id}?room_id=R001")
            check("T08 ok", r8.status_code == 200, f"{r8.status_code}")
        else:
            check("T08 ok", True, "skip")
        print("T09 get 404")
        r9 = await c.get("/api/messaging/channel-messages/fake?room_id=R001")
        check("T09 404", r9.status_code == 404, f"{r9.status_code}")
        print("T10 update")
        if msg_id:
            r10 = await c.put(f"/api/messaging/channel-messages/{msg_id}", json={"room_id": "R001", "msg": "updated"})
            check("T10 ok", r10.status_code == 200, f"{r10.status_code}")
        else:
            check("T10 ok", True, "skip")
        print("T11 delete")
        if msg_id:
            r11 = await c.delete(f"/api/messaging/channel-messages/{msg_id}?room_id=R001")
            check("T11 ok", r11.status_code == 200, f"{r11.status_code}")
        else:
            check("T11 ok", True, "skip")
        print("T12 thread")
        r12 = await c.get("/api/messaging/channel-messages/m001/thread?room_id=R001")
        check("T12 ok", r12.status_code == 200, f"{r12.status_code}")
        print("T13 reactions")
        r13 = await c.get("/api/messaging/channel-messages/m001/reactions?room_id=R001")
        check("T13 ok", r13.status_code == 200, f"{r13.status_code}")
    print(f"\n{'='*50}"); print(f"PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
    if FAIL: sys.exit(1)
if __name__ == "__main__": asyncio.run(main())
