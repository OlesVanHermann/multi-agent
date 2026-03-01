#!/usr/bin/env python3
"""Test Full-scenario Frontend→Frontend→Backend — events_catalog."""
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
    from events_catalog_api import router
    app = FastAPI(); app.include_router(router); transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=True) as c:
        print("S01 browse all events")
        r = await c.get("/api/messaging/events-catalog/list")
        check("S01 total", r.json().get("total") >= 70, f"{r.json().get('total')}")
        print("S02 browse categories")
        r2 = await c.get("/api/messaging/events-catalog/categories")
        check("S02 count", r2.json().get("count") == 10, f"{r2.json().get('count')}")
        print("S03 search events")
        r3 = await c.get("/api/messaging/events-catalog/search?q=message")
        check("S03 found", r3.json().get("count") >= 3, f"{r3.json().get('count')}")
        print("S04 subscribe to events")
        r4 = await c.post("/api/messaging/events-catalog/subscribe", json={"event_names": ["message", "reaction_added", "pin_added"], "api_type": "events"})
        check("S04 ok", r4.json().get("ok") is True, f"{r4.json().get('ok')}")
        check("S04 created", r4.json().get("created_count") == 3, f"{r4.json().get('created_count')}")
        print("S05 check subscriptions")
        r5 = await c.get("/api/messaging/events-catalog/subscriptions")
        check("S05 count", r5.json().get("count") == 3, f"{r5.json().get('count')}")
        print("S06 check scope map")
        r6 = await c.get("/api/messaging/events-catalog/scope-map")
        check("S06 count", r6.json().get("count") >= 70, f"{r6.json().get('count')}")
        print("S07 stats")
        r7 = await c.get("/api/messaging/events-catalog/stats")
        check("S07 total", r7.json().get("total_events") >= 70, f"{r7.json().get('total_events')}")
        check("S07 cats", r7.json().get("total_categories") == 10, f"{r7.json().get('total_categories')}")
        print("S08 event detail")
        r8 = await c.get("/api/messaging/events-catalog/app_mention")
        check("S08 name", r8.json().get("event", {}).get("name") == "app_mention", f"{r8.json().get('event')}")
        print("S09 subtypes")
        r9 = await c.get("/api/messaging/events-catalog/message-subtypes")
        check("S09 count", r9.json().get("subtypes_count") >= 20, f"{r9.json().get('subtypes_count')}")
    print(f"\n{'='*50}"); print(f"PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
    if FAIL: sys.exit(1)
if __name__ == "__main__": asyncio.run(main())
