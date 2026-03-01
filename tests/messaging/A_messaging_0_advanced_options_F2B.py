#!/usr/bin/env python3
"""Test Frontend→Backend — advanced_options. Hook simulation."""
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
    from advanced_options_api import router
    app = FastAPI(); app.include_router(router); transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=True) as c:
        print("H01 fetchPreferences")
        r = await c.get("/api/messaging/advanced-options/preferences")
        check("H01 status", r.status_code == 200, f"{r.status_code}")
        check("H01 total", r.json().get("total") == 18, f"{r.json().get('total')}")
        print("H02 fetchByCategory")
        r2 = await c.get("/api/messaging/advanced-options/preferences/display")
        check("H02 status", r2.status_code == 200, f"{r2.status_code}")
        print("H03 invalidCategory")
        r3 = await c.get("/api/messaging/advanced-options/preferences/fake")
        check("H03 404", r3.status_code == 404, f"{r3.status_code}")
        print("H04 updatePreferences")
        r4 = await c.put("/api/messaging/advanced-options/preferences", json={"preferences": [{"name": "send_on_ctrl_enter", "value": True}]})
        check("H04 status", r4.status_code == 200, f"{r4.status_code}")
        check("H04 updated", r4.json().get("updated_count") == 1, f"{r4.json().get('updated_count')}")
        print("H05 fetchDisplay")
        r5 = await c.get("/api/messaging/advanced-options/display")
        check("H05 status", r5.status_code == 200, f"{r5.status_code}")
        print("H06 fetchLocale")
        r6 = await c.get("/api/messaging/advanced-options/locale")
        check("H06 status", r6.status_code == 200, f"{r6.status_code}")
        print("H07 requestExport")
        r7 = await c.post("/api/messaging/advanced-options/export", json={"format": "json"})
        check("H07 status", r7.status_code == 200, f"{r7.status_code}")
        check("H07 ok", r7.json().get("ok") is True, f"{r7.json().get('ok')}")
        print("H08 fetchDebug")
        r8 = await c.get("/api/messaging/advanced-options/debug")
        check("H08 status", r8.status_code == 200, f"{r8.status_code}")
    print(f"\n{'='*50}"); print(f"PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
    if FAIL: sys.exit(1)
if __name__ == "__main__": asyncio.run(main())
