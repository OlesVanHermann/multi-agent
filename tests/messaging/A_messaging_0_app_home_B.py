#!/usr/bin/env python3
"""Test Backend — app_home. 12 endpoints."""
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
    from app_home_api import router
    app = FastAPI(); app.include_router(router); transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        print("T01 publish view")
        r = await c.post("/api/messaging/app-home/views", json={"user_id": "U001", "view": {"type": "home", "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "Hello"}}]}})
        check("T01 ok", r.json().get("ok") is True or r.status_code == 200, f"{r.status_code}")
        print("T02 get view")
        r2 = await c.get("/api/messaging/app-home/views/U001")
        check("T02 ok", r2.status_code == 200, f"{r2.status_code}")
        print("T03 update view")
        r3 = await c.put("/api/messaging/app-home/views/U001", json={"view": {"type": "home", "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "Updated"}}]}})
        check("T03 ok", r3.status_code == 200, f"{r3.status_code}")
        print("T04 delete view")
        r4 = await c.delete("/api/messaging/app-home/views/U001")
        check("T04 ok", r4.status_code == 200, f"{r4.status_code}")
        print("T05 get config")
        r5 = await c.get("/api/messaging/app-home/config")
        check("T05 ok", r5.status_code == 200, f"{r5.status_code}")
        print("T06 update config")
        r6 = await c.put("/api/messaging/app-home/config", json={"home_tab_enabled": True})
        check("T06 ok", r6.status_code == 200, f"{r6.status_code}")
        print("T07 send message")
        r7 = await c.post("/api/messaging/app-home/messages", json={"user_id": "U001", "text": "Hello"})
        check("T07 ok", r7.status_code in (200, 201), f"{r7.status_code}")
        print("T08 message history")
        r8 = await c.get("/api/messaging/app-home/messages/U001")
        check("T08 ok", r8.status_code == 200, f"{r8.status_code}")
        print("T09 visitors")
        r9 = await c.get("/api/messaging/app-home/visitors")
        check("T09 ok", r9.status_code == 200, f"{r9.status_code}")
        print("T10 visitor detail")
        r10 = await c.get("/api/messaging/app-home/visitors/U001")
        check("T10 ok", r10.status_code == 200, f"{r10.status_code}")
        print("T11 deep-link")
        r11 = await c.post("/api/messaging/app-home/deep-link", json={"team_id": "T001", "app_id": "A001", "tab": "home"})
        check("T11 ok", r11.status_code == 200, f"{r11.status_code}")
        check("T11 link", r11.json().get("link") is not None, f"{list(r11.json().keys())}")
        print("T12 about")
        r12 = await c.get("/api/messaging/app-home/about")
        check("T12 ok", r12.status_code == 200, f"{r12.status_code}")
    print(f"\n{'='*50}"); print(f"PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
    if FAIL: sys.exit(1)
if __name__ == "__main__": asyncio.run(main())
