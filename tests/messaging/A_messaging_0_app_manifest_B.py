#!/usr/bin/env python3
"""Test Backend — app_manifest. 12 endpoints: create, list, validate, schema, get, update, delete, export, import, features, functions, workflows."""
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
        print("T01 create manifest")
        r = await c.post("/api/messaging/app-manifest", json={"name": "TestApp", "display": {"description": "A test"}})
        check("T01 ok", r.status_code in (200, 201), f"{r.status_code}")
        mid = r.json().get("id", r.json().get("manifest_id", r.json().get("manifest", {}).get("id", "")))
        check("T01 id", mid != "", f"no id in {list(r.json().keys())}")
        print("T02 list manifests")
        r2 = await c.get("/api/messaging/app-manifest")
        check("T02 count", r2.json().get("count", len(r2.json().get("manifests", []))) >= 1, f"{r2.json()}")
        print("T03 validate")
        r3 = await c.post("/api/messaging/app-manifest/validate", json={"manifest": {"name": "Valid", "display": {}}})
        check("T03 ok", r3.status_code == 200, f"{r3.status_code}")
        print("T04 schema")
        r4 = await c.get("/api/messaging/app-manifest/schema")
        check("T04 ok", r4.status_code == 200, f"{r4.status_code}")
        print("T05 get manifest")
        r5 = await c.get(f"/api/messaging/app-manifest/{mid}")
        check("T05 ok", r5.status_code == 200, f"{r5.status_code}")
        print("T06 get 404")
        r6 = await c.get("/api/messaging/app-manifest/nonexistent_manifest_xyz")
        check("T06 404", r6.status_code == 404, f"{r6.status_code}")
        print("T07 update manifest")
        r7 = await c.put(f"/api/messaging/app-manifest/{mid}", json={"display": {"description": "Updated"}})
        check("T07 ok", r7.status_code == 200, f"{r7.status_code}")
        print("T08 export json")
        r8 = await c.post("/api/messaging/app-manifest/export", json={"manifest_id": mid, "format": "json"})
        check("T08 ok", r8.status_code == 200, f"{r8.status_code}")
        print("T09 import")
        r9 = await c.post("/api/messaging/app-manifest/import", json={"raw": "{\"name\": \"Imported\"}", "format": "json"})
        check("T09 ok", r9.status_code in (200, 201), f"{r9.status_code}")
        print("T10 features")
        r10 = await c.get(f"/api/messaging/app-manifest/{mid}/features")
        check("T10 ok", r10.status_code == 200, f"{r10.status_code}")
        print("T11 functions")
        r11 = await c.get(f"/api/messaging/app-manifest/{mid}/functions")
        check("T11 ok", r11.status_code == 200, f"{r11.status_code}")
        print("T12 workflows")
        r12 = await c.get(f"/api/messaging/app-manifest/{mid}/workflows")
        check("T12 ok", r12.status_code == 200, f"{r12.status_code}")
        print("T13 delete manifest")
        r13 = await c.delete(f"/api/messaging/app-manifest/{mid}")
        check("T13 ok", r13.status_code == 200, f"{r13.status_code}")
        print("T14 delete 404")
        r14 = await c.delete("/api/messaging/app-manifest/nonexistent_manifest_xyz")
        check("T14 404", r14.status_code == 404, f"{r14.status_code}")
    print(f"\n{'='*50}"); print(f"PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
    if FAIL: sys.exit(1)
if __name__ == "__main__": asyncio.run(main())
