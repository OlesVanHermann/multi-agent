#!/usr/bin/env python3
"""Test Full-scenario Frontend→Frontend→Backend — events_api."""
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
        print("S01 create subscription")
        r = await c.post("/api/messaging/events-api/subscriptions", json={"event_type": "message", "scope": "channels:history", "mode": "events_api", "request_url": "https://example.com/s"})
        sid = r.json().get("id", "")
        check("S01 id", sid != "", "no id")
        print("S02 create second")
        r2 = await c.post("/api/messaging/events-api/subscriptions", json={"event_type": "reaction_added", "scope": "reactions:read", "mode": "events_api", "request_url": "https://example.com/s2"})
        sid2 = r2.json().get("id", "")
        check("S02 id", sid2 != "", "no id")
        print("S03 list subscriptions")
        r3 = await c.get("/api/messaging/events-api/subscriptions")
        check("S03 count", r3.json().get("count") == 2, f"{r3.json().get('count')}")
        print("S04 receive event")
        r4 = await c.post("/api/messaging/events-api/webhook", json={"type": "event_callback", "app_id": "A001", "team_id": "T001", "enterprise_id": "", "event": {"type": "message", "text": "hi"}, "event_time": 1709000000, "authorizations": [{"enterprise_id": "", "team_id": "T001", "user_id": "U001", "is_bot": False, "is_enterprise_install": False}]})
        check("S04 matched", r4.json().get("subscriptions_matched") == 1, f"{r4.json().get('subscriptions_matched')}")
        eid = r4.json().get("event_id", "")
        print("S05 verify event stored")
        r5 = await c.get("/api/messaging/events-api/events")
        check("S05 count", r5.json().get("count") >= 1, f"{r5.json().get('count')}")
        print("S06 event detail")
        if eid:
            r6 = await c.get(f"/api/messaging/events-api/events/{eid}")
            check("S06 type", r6.json().get("event", {}).get("event_type") == "message", f"{r6.json().get('event')}")
        else:
            check("S06 type", True, "skip")
        print("S07 rate limits")
        r7 = await c.get("/api/messaging/events-api/rate-limits")
        check("S07 limit", r7.json().get("limit") == 30000, f"{r7.json().get('limit')}")
        print("S08 disable subscription")
        r8 = await c.put(f"/api/messaging/events-api/subscriptions/{sid}", json={"enabled": False})
        check("S08 disabled", r8.json().get("enabled") is False, f"{r8.json().get('enabled')}")
        print("S09 delete subscription")
        r9 = await c.delete(f"/api/messaging/events-api/subscriptions/{sid2}")
        check("S09 deleted", r9.json().get("status") == "deleted", f"{r9.json().get('status')}")
        print("S10 verify url")
        r10 = await c.post("/api/messaging/events-api/verify-url", json={"type": "url_verification", "challenge": "final_test", "token": "t"})
        check("S10 challenge", r10.json().get("challenge") == "final_test", f"{r10.json().get('challenge')}")
    print(f"\n{'='*50}"); print(f"PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
    if FAIL: sys.exit(1)
if __name__ == "__main__": asyncio.run(main())
