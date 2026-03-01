#!/usr/bin/env python3
"""Test Full-scenario Frontend→Frontend→Backend — ai_search."""
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
        print("S01 search messages")
        r = await c.get("/api/messaging/ai-search/search?q=hello")
        check("S01 list", isinstance(r.json(), list), f"type={type(r.json())}")
        print("S02 natural search")
        r2 = await c.post("/api/messaging/ai-search/search/natural", json={"query": "find bugs"})
        check("S02 confidence", r2.json().get("confidence") is not None, "no confidence")
        print("S03 browse recaps")
        r3 = await c.get("/api/messaging/ai-search/recaps")
        check("S03 list", isinstance(r3.json(), list), "not list")
        recaps = r3.json()
        print("S04 view recap detail")
        if recaps:
            chan = recaps[0].get("channel_id", "C001")
            r4 = await c.get(f"/api/messaging/ai-search/recaps/{chan}")
            check("S04 ok", r4.status_code == 200, f"{r4.status_code}")
        else:
            check("S04 ok", True, "skip")
        print("S05 browse summaries")
        r5 = await c.get("/api/messaging/ai-search/summaries")
        check("S05 list", isinstance(r5.json(), list), "not list")
        print("S06 generate summary")
        r6 = await c.post("/api/messaging/ai-search/summaries/generate", json={"channel_id": "C001", "thread_ts": "1709000099.000100"})
        check("S06 ok", r6.status_code == 200, f"{r6.status_code}")
        print("S07 browse assistants")
        r7 = await c.get("/api/messaging/ai-search/assistants")
        check("S07 list", isinstance(r7.json(), list), "not list")
        print("S08 view assistant detail")
        assts = r7.json()
        if assts:
            aid = assts[0].get("id", "a001")
            r8 = await c.get(f"/api/messaging/ai-search/assistants/{aid}")
            check("S08 ok", r8.status_code == 200, f"{r8.status_code}")
        else:
            check("S08 ok", True, "skip")
    print(f"\n{'='*50}"); print(f"PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
    if FAIL: sys.exit(1)
if __name__ == "__main__": asyncio.run(main())
