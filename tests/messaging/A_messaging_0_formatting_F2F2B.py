#!/usr/bin/env python3
"""Test Full-scenario Frontend→Frontend→Backend — formatting."""
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
        print("S01 format rules")
        r = await c.get("/api/messaging/formatting/format-rules")
        check("S01 count", len(r.json()) == 7, f"{len(r.json())}")
        print("S02 preview bold+italic")
        r2 = await c.post("/api/messaging/formatting/preview", json={"text": "*bold* _italic_ ~strike~"})
        html = r2.json().get("html", "")
        check("S02 bold", "<strong>bold</strong>" in html, "no bold")
        check("S02 italic", "<em>italic</em>" in html, "no italic")
        check("S02 strike", "<del>strike</del>" in html, "no strike")
        print("S03 preview code")
        r3 = await c.post("/api/messaging/formatting/preview", json={"text": "`code`"})
        check("S03 code", "<code>code</code>" in r3.json().get("html", ""), "no code")
        print("S04 emojis")
        r4 = await c.get("/api/messaging/formatting/emojis")
        check("S04 count", len(r4.json()) == 10, f"{len(r4.json())}")
        print("S05 create custom emoji")
        r5 = await c.post("/api/messaging/formatting/emojis", json={"name": "scenario", "value": ":scenario:"})
        check("S05 201", r5.status_code == 201, f"{r5.status_code}")
        print("S06 parse mentions")
        r6 = await c.post("/api/messaging/formatting/parse-mentions", json={"text": "@alice #general @here"})
        check("S06 count", len(r6.json()) == 3, f"{len(r6.json())}")
        print("S07 escape XSS")
        r7 = await c.post("/api/messaging/formatting/escape", json={"text": "<script>alert(1)</script>"})
        esc = r7.json().get("escaped", "")
        check("S07 safe", "<script>" not in esc and "&lt;" in esc, f"{esc}")
        print("S08 delete emoji")
        r8 = await c.delete("/api/messaging/formatting/emojis/scenario")
        check("S08 deleted", r8.json().get("status") == "deleted", f"{r8.json().get('status')}")
        print("S09 verify deleted")
        r9 = await c.delete("/api/messaging/formatting/emojis/scenario")
        check("S09 404", r9.status_code == 404, f"{r9.status_code}")
    print(f"\n{'='*50}"); print(f"PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
    if FAIL: sys.exit(1)
if __name__ == "__main__": asyncio.run(main())
