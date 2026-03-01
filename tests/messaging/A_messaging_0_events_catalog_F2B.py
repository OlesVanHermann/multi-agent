#!/usr/bin/env python3
"""Test Frontend→Backend — events_catalog. Hook simulation."""
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
        print("H01 listAll")
        r = await c.get("/api/messaging/events-catalog/list")
        check("H01 total", r.json().get("total") >= 70, f"{r.json().get('total')}")
        print("H02 filterCategory")
        r2 = await c.get("/api/messaging/events-catalog/list?category=app")
        check("H02 count", r2.json().get("count") >= 7, f"{r2.json().get('count')}")
        print("H03 search")
        r3 = await c.get("/api/messaging/events-catalog/search?q=channel")
        check("H03 found", r3.json().get("count") >= 5, f"{r3.json().get('count')}")
        print("H04 categories")
        r4 = await c.get("/api/messaging/events-catalog/categories")
        check("H04 count", r4.json().get("count") == 10, f"{r4.json().get('count')}")
        print("H05 apiTypes")
        r5 = await c.get("/api/messaging/events-catalog/api-types")
        check("H05 count", len(r5.json().get("api_types", [])) == 3, f"{len(r5.json().get('api_types', []))}")
        print("H06 subtypes")
        r6 = await c.get("/api/messaging/events-catalog/message-subtypes")
        check("H06 count", r6.json().get("subtypes_count") >= 20, f"{r6.json().get('subtypes_count')}")
        print("H07 subscribe")
        r7 = await c.post("/api/messaging/events-catalog/subscribe", json={"event_names": ["message", "reaction_added"], "api_type": "events"})
        check("H07 ok", r7.json().get("ok") is True, f"{r7.json().get('ok')}")
        print("H08 subscriptions")
        r8 = await c.get("/api/messaging/events-catalog/subscriptions")
        check("H08 count", r8.json().get("count") >= 2, f"{r8.json().get('count')}")
        print("H09 scopeMap")
        r9 = await c.get("/api/messaging/events-catalog/scope-map")
        check("H09 count", r9.json().get("count") >= 70, f"{r9.json().get('count')}")
        print("H10 stats")
        r10 = await c.get("/api/messaging/events-catalog/stats")
        check("H10 total", r10.json().get("total_events") >= 70, f"{r10.json().get('total_events')}")
    print(f"\n{'='*50}"); print(f"PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
    if FAIL: sys.exit(1)
if __name__ == "__main__": asyncio.run(main())
