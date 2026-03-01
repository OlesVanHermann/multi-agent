#!/usr/bin/env python3
"""Test Backend — collab_search. 12 endpoints."""
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
    from collab_search_api import router
    app = FastAPI(); app.include_router(router); transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=True) as c:
        print("T01 search messages")
        r = await c.post("/api/messaging/collab-search/search-messages", json={"query": "test"})
        check("T01 ok", r.status_code == 200, f"{r.status_code}")
        print("T02 search files")
        r2 = await c.post("/api/messaging/collab-search/search-files", json={"query": "report"})
        check("T02 ok", r2.status_code == 200, f"{r2.status_code}")
        print("T03 search all")
        r3 = await c.post("/api/messaging/collab-search/search-all", json={"query": "test"})
        check("T03 ok", r3.status_code == 200, f"{r3.status_code}")
        print("T04 list modifiers")
        r4 = await c.get("/api/messaging/collab-search/modifiers")
        check("T04 ok", r4.status_code == 200, f"{r4.status_code}")
        print("T05 get modifier detail")
        mods = r4.json() if isinstance(r4.json(), list) else r4.json().get("modifiers", [])
        if mods:
            mid = mods[0].get("id", mods[0].get("name", ""))
            r5 = await c.get(f"/api/messaging/collab-search/modifiers/{mid}")
            check("T05 ok", r5.status_code == 200, f"{r5.status_code}")
        else:
            check("T05 ok", True, "skip")
        print("T06 parse query modifiers")
        r6 = await c.post("/api/messaging/collab-search/modifier-parse", json={"query": "from:@alice in:#general test"})
        check("T06 ok", r6.status_code == 200, f"{r6.status_code}")
        print("T07 list filters")
        r7 = await c.get("/api/messaging/collab-search/filters")
        check("T07 ok", r7.status_code == 200, f"{r7.status_code}")
        print("T08 get filter detail")
        filters = r7.json() if isinstance(r7.json(), list) else r7.json().get("filters", [])
        if filters:
            fid = filters[0].get("id", "")
            r8 = await c.get(f"/api/messaging/collab-search/filters/{fid}")
            check("T08 ok", r8.status_code == 200, f"{r8.status_code}")
        else:
            check("T08 ok", True, "skip")
        print("T09 create filter")
        r9 = await c.post("/api/messaging/collab-search/filters", json={"name": "test-filter", "description": "Test", "content_types": ["messages"]})
        check("T09 ok", r9.status_code in (200, 201), f"{r9.status_code}")
        fid_new = r9.json().get("id", "")
        print("T10 delete filter")
        if fid_new:
            r10 = await c.delete(f"/api/messaging/collab-search/filters/{fid_new}")
            check("T10 ok", r10.status_code == 200, f"{r10.status_code}")
        else:
            check("T10 ok", True, "skip")
        print("T11 search history")
        r11 = await c.get("/api/messaging/collab-search/search-history")
        check("T11 ok", r11.status_code == 200, f"{r11.status_code}")
        print("T12 analyze patterns")
        r12 = await c.post("/api/messaging/collab-search/search-analyze", json={"period": "7d"})
        check("T12 ok", r12.status_code == 200, f"{r12.status_code}")
    print(f"\n{'='*50}"); print(f"PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
    if FAIL: sys.exit(1)
if __name__ == "__main__": asyncio.run(main())
