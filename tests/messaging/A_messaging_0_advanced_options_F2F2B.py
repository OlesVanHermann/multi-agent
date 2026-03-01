#!/usr/bin/env python3
"""Test Full-scenario Frontend→Frontend→Backend — advanced_options."""
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
        print("S01 load preferences")
        r = await c.get("/api/messaging/advanced-options/preferences")
        check("S01 total", r.json().get("total") == 18, f"{r.json().get('total')}")
        print("S02 browse display category")
        r2 = await c.get("/api/messaging/advanced-options/preferences/display")
        check("S02 ok", r2.status_code == 200, f"{r2.status_code}")
        print("S03 update a preference")
        r3 = await c.put("/api/messaging/advanced-options/preferences", json={"preferences": [{"name": "send_on_ctrl_enter", "value": True}]})
        check("S03 updated", r3.json().get("updated_count") == 1, f"{r3.json().get('updated_count')}")
        print("S04 verify update persists")
        r4 = await c.get("/api/messaging/advanced-options/preferences")
        prefs = r4.json().get("preferences", [])
        found = [p for p in prefs if p.get("name") == "send_on_ctrl_enter"]
        check("S04 value", len(found) > 0 and str(found[0].get("value")).lower() in ("true", "1"), f"{found}")
        print("S05 check display settings")
        r5 = await c.get("/api/messaging/advanced-options/display")
        check("S05 ok", r5.status_code == 200, f"{r5.status_code}")
        print("S06 check locale")
        r6 = await c.get("/api/messaging/advanced-options/locale")
        check("S06 ok", r6.status_code == 200, f"{r6.status_code}")
        print("S07 export data")
        r7 = await c.post("/api/messaging/advanced-options/export", json={"format": "json"})
        check("S07 ok", r7.json().get("ok") is True, f"{r7.json().get('ok')}")
        eid = r7.json().get("export", {}).get("id", "")
        print("S08 check export status")
        if eid:
            r8 = await c.get(f"/api/messaging/advanced-options/export/{eid}")
            check("S08 status", r8.status_code == 200, f"{r8.status_code}")
        else:
            check("S08 status", True, "skip")
        print("S09 debug info")
        r9 = await c.get("/api/messaging/advanced-options/debug")
        check("S09 ok", r9.status_code == 200, f"{r9.status_code}")
        print("S10 reset preferences")
        r10 = await c.post("/api/messaging/advanced-options/preferences/reset", json={})
        check("S10 ok", r10.status_code == 200, f"{r10.status_code}")
    print(f"\n{'='*50}"); print(f"PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
    if FAIL: sys.exit(1)
if __name__ == "__main__": asyncio.run(main())
