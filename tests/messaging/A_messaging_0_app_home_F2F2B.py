#!/usr/bin/env python3
"""Test Full-scenario Frontend→Frontend→Backend — app_home."""
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
        print("S01 publish view")
        r = await c.post("/api/messaging/app-home/views", json={"user_id": "U001", "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "Welcome"}}]})
        check("S01 ok", r.json().get("ok") is True, f"{r.json().get('ok')}")
        print("S02 check config")
        r2 = await c.get("/api/messaging/app-home/config")
        check("S02 ok", r2.status_code == 200, f"{r2.status_code}")
        print("S03 check visitors")
        r3 = await c.get("/api/messaging/app-home/visitors")
        check("S03 ok", r3.status_code == 200, f"{r3.status_code}")
        print("S04 generate deep link")
        r4 = await c.post("/api/messaging/app-home/deep-link", json={"team_id": "T001", "app_id": "A001"})
        check("S04 link", r4.json().get("link") is not None, "no link")
        print("S05 about section")
        r5 = await c.get("/api/messaging/app-home/about")
        check("S05 ok", r5.status_code == 200, f"{r5.status_code}")
        print("S06 publish second view")
        r6 = await c.post("/api/messaging/app-home/views", json={"user_id": "U002", "blocks": []})
        check("S06 ok", r6.json().get("ok") is True, f"{r6.json().get('ok')}")
    print(f"\n{'='*50}"); print(f"PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
    if FAIL: sys.exit(1)
if __name__ == "__main__": asyncio.run(main())
