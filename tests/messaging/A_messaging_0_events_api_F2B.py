#!/usr/bin/env python3
"""Test Frontend→Backend — events_api. Hook simulation."""
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
    from events_api_api import router
    app = FastAPI(); app.include_router(router); transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=True) as c:
        print("H01 createSubscription")
        r = await c.post("/api/messaging/events-api/subscriptions", json={"event_type": "message", "scope": "channels:history", "mode": "events_api", "request_url": "https://example.com/h"})
        check("H01 status", r.status_code in (200, 201), f"{r.status_code}")
        sid = r.json().get("id", "")
        check("H01 id", sid != "", "no id")
        print("H02 listSubscriptions")
        r2 = await c.get("/api/messaging/events-api/subscriptions")
        check("H02 count", r2.json().get("count") == 1, f"{r2.json().get('count')}")
        print("H03 updateSubscription")
        r3 = await c.put(f"/api/messaging/events-api/subscriptions/{sid}", json={"enabled": False})
        check("H03 disabled", r3.json().get("enabled") is False, f"{r3.json().get('enabled')}")
        print("H04 receiveWebhook")
        r4 = await c.post("/api/messaging/events-api/webhook", json={"type": "event_callback", "app_id": "A001", "team_id": "T001", "enterprise_id": "", "event": {"type": "message", "text": "hi"}, "event_time": 1709000000, "authorizations": []})
        check("H04 ok", r4.json().get("ok") is True, f"{r4.json().get('ok')}")
        print("H05 listEvents")
        r5 = await c.get("/api/messaging/events-api/events")
        check("H05 count", r5.json().get("count") >= 1, f"{r5.json().get('count')}")
        print("H06 verifyUrl")
        r6 = await c.post("/api/messaging/events-api/verify-url", json={"type": "url_verification", "challenge": "abc", "token": "t"})
        check("H06 challenge", r6.json().get("challenge") == "abc", f"{r6.json().get('challenge')}")
        print("H07 rateLimits")
        r7 = await c.get("/api/messaging/events-api/rate-limits")
        check("H07 limit", r7.json().get("limit") == 30000, f"{r7.json().get('limit')}")
        print("H08 config")
        r8 = await c.get("/api/messaging/events-api/config")
        check("H08 reasons", len(r8.json().get("retry_reasons", [])) == 6, f"{len(r8.json().get('retry_reasons', []))}")
        print("H09 deleteSubscription")
        r9 = await c.delete(f"/api/messaging/events-api/subscriptions/{sid}")
        check("H09 deleted", r9.json().get("status") == "deleted", f"{r9.json().get('status')}")
    print(f"\n{'='*50}"); print(f"PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
    if FAIL: sys.exit(1)
if __name__ == "__main__": asyncio.run(main())
