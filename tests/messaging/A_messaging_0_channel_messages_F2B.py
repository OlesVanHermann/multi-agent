#!/usr/bin/env python3
"""Test Frontend→Backend — channel_messages. Hook simulation."""
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
        # Hook: fetchMessages → GET /list
        print("H01 fetchMessages")
        r = await c.get("/api/messaging/channel-messages/list?room_id=R001")
        check("H01 status", r.status_code == 200, f"{r.status_code}")
        check("H01 count", r.json().get("total", r.json().get("count", 0)) >= 5, f"{r.json()}")
        # Hook: createMessage → POST /
        print("H02 createMessage")
        r2 = await c.post("/api/messaging/channel-messages", json={"room_id": "R001", "msg": "hook test", "user_id": "U_HOOK"})
        check("H02 status", r2.status_code in (200, 201), f"{r2.status_code}")
        mid = r2.json().get("id", r2.json().get("message_id", r2.json().get("message", {}).get("id", "")))
        check("H02 id", mid != "", "no id")
        # Hook: getMessage → GET /{id}
        print("H03 getMessage")
        if mid:
            r3 = await c.get(f"/api/messaging/channel-messages/{mid}?room_id=R001")
            check("H03 status", r3.status_code == 200, f"{r3.status_code}")
        else:
            check("H03 status", True, "skip")
        # Hook: updateMessage → PUT /{id}
        print("H04 updateMessage")
        if mid:
            r4 = await c.put(f"/api/messaging/channel-messages/{mid}", json={"room_id": "R001", "msg": "updated"})
            check("H04 status", r4.status_code == 200, f"{r4.status_code}")
        else:
            check("H04 status", True, "skip")
        # Hook: searchMessages → GET /search
        print("H05 searchMessages")
        r5 = await c.get("/api/messaging/channel-messages/search?room_id=R001&q=welcome")
        check("H05 status", r5.status_code == 200, f"{r5.status_code}")
        # Hook: fetchMentions → GET /mentions
        print("H06 fetchMentions")
        r6 = await c.get("/api/messaging/channel-messages/mentions?room_id=R001&user_ids=U_ALICE")
        check("H06 status", r6.status_code == 200, f"{r6.status_code}")
        # Hook: fetchThread → GET /{id}/thread
        print("H07 fetchThread")
        r7 = await c.get("/api/messaging/channel-messages/m001/thread?room_id=R001")
        check("H07 status", r7.status_code == 200, f"{r7.status_code}")
        # Hook: deleteMessage → DELETE /{id}
        print("H08 deleteMessage")
        if mid:
            r8 = await c.delete(f"/api/messaging/channel-messages/{mid}?room_id=R001")
            check("H08 status", r8.status_code == 200, f"{r8.status_code}")
        else:
            check("H08 status", True, "skip")
    print(f"\n{'='*50}"); print(f"PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
    if FAIL: sys.exit(1)
if __name__ == "__main__": asyncio.run(main())
