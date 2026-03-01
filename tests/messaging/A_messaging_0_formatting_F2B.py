#!/usr/bin/env python3
"""Test Frontend→Backend — formatting. Hook simulation."""
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
    from formatting_api import router
    app = FastAPI(); app.include_router(router); transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=True) as c:
        print("H01 formatRules")
        r = await c.get("/api/messaging/formatting/format-rules")
        check("H01 count", len(r.json()) == 7, f"{len(r.json())}")
        print("H02 preview")
        r2 = await c.post("/api/messaging/formatting/preview", json={"text": "*bold* _italic_"})
        check("H02 bold", "<strong>bold</strong>" in r2.json().get("html", ""), f"{r2.json().get('html')}")
        check("H02 italic", "<em>italic</em>" in r2.json().get("html", ""), f"{r2.json().get('html')}")
        print("H03 emojis")
        r3 = await c.get("/api/messaging/formatting/emojis")
        check("H03 count", len(r3.json()) == 10, f"{len(r3.json())}")
        print("H04 createEmoji")
        r4 = await c.post("/api/messaging/formatting/emojis", json={"name": "hooktest", "value": ":hooktest:"})
        check("H04 201", r4.status_code == 201, f"{r4.status_code}")
        print("H05 parseMentions")
        r5 = await c.post("/api/messaging/formatting/parse-mentions", json={"text": "@alice #general @here"})
        check("H05 count", len(r5.json()) == 3, f"{len(r5.json())}")
        print("H06 escape")
        r6 = await c.post("/api/messaging/formatting/escape", json={"text": "<b>test</b>"})
        check("H06 lt", "&lt;" in r6.json().get("escaped", ""), "no lt")
        print("H07 deleteEmoji")
        r7 = await c.delete("/api/messaging/formatting/emojis/hooktest")
        check("H07 deleted", r7.json().get("status") == "deleted", f"{r7.json().get('status')}")
    print(f"\n{'='*50}"); print(f"PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
    if FAIL: sys.exit(1)
if __name__ == "__main__": asyncio.run(main())
