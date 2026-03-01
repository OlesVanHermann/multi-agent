#!/usr/bin/env python3
"""Test Frontend→Backend — app_home. Hook simulation."""
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
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=True) as c:
        print("H01 publishView")
        r = await c.post("/api/messaging/app-home/views", json={"user_id": "U001", "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "Hello"}}]})
        check("H01 status", r.status_code in (200, 201), f"{r.status_code}")
        check("H01 ok", r.json().get("ok") is True, f"{r.json().get('ok')}")
        print("H02 fetchConfig")
        r2 = await c.get("/api/messaging/app-home/config")
        check("H02 status", r2.status_code == 200, f"{r2.status_code}")
        print("H03 fetchVisitors")
        r3 = await c.get("/api/messaging/app-home/visitors")
        check("H03 status", r3.status_code == 200, f"{r3.status_code}")
        print("H04 generateDeepLink")
        r4 = await c.post("/api/messaging/app-home/deep-link", json={"team_id": "T001", "app_id": "A001"})
        check("H04 status", r4.status_code == 200, f"{r4.status_code}")
        check("H04 link", r4.json().get("link") is not None, "no link")
        print("H05 fetchAbout")
        r5 = await c.get("/api/messaging/app-home/about")
        check("H05 status", r5.status_code == 200, f"{r5.status_code}")
    print(f"\n{'='*50}"); print(f"PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
    if FAIL: sys.exit(1)
if __name__ == "__main__": asyncio.run(main())
