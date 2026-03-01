#!/usr/bin/env python3
"""Test Frontend→Backend — app_manifest. Hook simulation."""
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
        print("H01 createManifest")
        r = await c.post("/api/messaging/app-manifest", json={"name": "f2b-hook-app", "display": {"description": "F2B test"}})
        check("H01 status", r.status_code in (200, 201), f"{r.status_code}")
        mid = r.json().get("manifest", {}).get("id", r.json().get("id", ""))
        check("H01 id", mid != "", f"no id in {list(r.json().keys())}")
        print("H02 listManifests")
        r2 = await c.get("/api/messaging/app-manifest")
        check("H02 status", r2.status_code == 200, f"{r2.status_code}")
        print("H03 validateManifest")
        r3 = await c.post("/api/messaging/app-manifest/validate", json={"manifest": {"name": "valid-app", "display_information": {"name": "Valid App", "description": "ok"}, "settings": {}, "features": {}, "oauth_config": {}}})
        check("H03 valid", r3.json().get("valid") is True, f"{r3.json()}")
        print("H04 fetchSchema")
        r4 = await c.get("/api/messaging/app-manifest/schema")
        check("H04 status", r4.status_code == 200, f"{r4.status_code}")
        print("H05 deleteManifest")
        if mid:
            r5 = await c.delete(f"/api/messaging/app-manifest/{mid}")
            check("H05 status", r5.status_code == 200, f"{r5.status_code}")
        else:
            check("H05 status", True, "skip")
    print(f"\n{'='*50}"); print(f"PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
    if FAIL: sys.exit(1)
if __name__ == "__main__": asyncio.run(main())
