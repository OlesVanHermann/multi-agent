#!/usr/bin/env python3
"""Test Frontend→Backend — ai_search. Hook simulation."""
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
    from ai_search_api import router
    app = FastAPI(); app.include_router(router); transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=True) as c:
        print("H01 search")
        r = await c.get("/api/messaging/ai-search/search?q=test")
        check("H01 status", r.status_code == 200, f"{r.status_code}")
        check("H01 list", isinstance(r.json(), list), f"type={type(r.json())}")
        print("H02 natural")
        r2 = await c.post("/api/messaging/ai-search/search/natural", json={"query": "find bugs"})
        check("H02 status", r2.status_code == 200, f"{r2.status_code}")
        check("H02 confidence", r2.json().get("confidence") is not None, "no confidence")
        print("H03 recaps")
        r3 = await c.get("/api/messaging/ai-search/recaps")
        check("H03 status", r3.status_code == 200, f"{r3.status_code}")
        check("H03 list", isinstance(r3.json(), list), "not list")
        print("H04 summaries")
        r4 = await c.get("/api/messaging/ai-search/summaries")
        check("H04 status", r4.status_code == 200, f"{r4.status_code}")
        check("H04 list", isinstance(r4.json(), list), "not list")
        print("H05 assistants")
        r5 = await c.get("/api/messaging/ai-search/assistants")
        check("H05 status", r5.status_code == 200, f"{r5.status_code}")
        check("H05 list", isinstance(r5.json(), list), "not list")
    print(f"\n{'='*50}"); print(f"PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
    if FAIL: sys.exit(1)
if __name__ == "__main__": asyncio.run(main())
