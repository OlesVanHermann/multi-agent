#!/usr/bin/env python3
"""Test Full-scenario Frontend→Frontend→Backend — app_manifest."""
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
    from app_manifest_api import router
    app = FastAPI(); app.include_router(router); transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=True) as c:
        print("S01 create manifest")
        r = await c.post("/api/messaging/app-manifest", json={"name": "scenario-app", "display": {"description": "Scenario test"}})
        check("S01 status", r.status_code in (200, 201), f"{r.status_code}")
        mid = r.json().get("manifest", {}).get("id", r.json().get("id", ""))
        check("S01 id", mid != "", f"no id in {list(r.json().keys())}")
        print("S02 list manifests")
        r2 = await c.get("/api/messaging/app-manifest")
        check("S02 ok", r2.status_code == 200, f"{r2.status_code}")
        print("S03 get detail")
        if mid:
            r3 = await c.get(f"/api/messaging/app-manifest/{mid}")
            check("S03 ok", r3.status_code == 200, f"{r3.status_code}")
        else:
            check("S03 ok", True, "skip")
        print("S04 validate")
        r4 = await c.post("/api/messaging/app-manifest/validate", json={"manifest": {"name": "test", "display_information": {"name": "Test App"}}})
        check("S04 valid", r4.json().get("valid") is True, f"{r4.json()}")
        print("S05 schema")
        r5 = await c.get("/api/messaging/app-manifest/schema")
        check("S05 ok", r5.status_code == 200, f"{r5.status_code}")
        print("S06 features")
        if mid:
            r6 = await c.get(f"/api/messaging/app-manifest/{mid}/features")
            check("S06 ok", r6.status_code == 200, f"{r6.status_code}")
        else:
            check("S06 ok", True, "skip")
        print("S07 delete")
        if mid:
            r7 = await c.delete(f"/api/messaging/app-manifest/{mid}")
            check("S07 ok", r7.status_code == 200, f"{r7.status_code}")
        else:
            check("S07 ok", True, "skip")
        print("S08 verify deleted")
        if mid:
            r8 = await c.get(f"/api/messaging/app-manifest/{mid}")
            check("S08 404", r8.status_code == 404, f"{r8.status_code}")
        else:
            check("S08 404", True, "skip")
    print(f"\n{'='*50}"); print(f"PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
    if FAIL: sys.exit(1)
if __name__ == "__main__": asyncio.run(main())
