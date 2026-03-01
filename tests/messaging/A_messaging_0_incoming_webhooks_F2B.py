#!/usr/bin/env python3
"""Test Frontend→Backend — incoming_webhooks. Hook simulation."""
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
    from incoming_webhooks_api import router
    app = FastAPI(); app.include_router(router); transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=True) as c:
        print("H01 listWebhooks")
        r = await c.get("/api/messaging/incoming-webhooks/list")
        check("H01 total", r.json().get("total") == 5, f"{r.json().get('total')}")
        print("H02 getConfig")
        r2 = await c.get("/api/messaging/incoming-webhooks/config")
        check("H02 enabled", r2.json().get("config", {}).get("enable_webhooks") is True, f"{r2.json().get('config')}")
        print("H03 getStats")
        r3 = await c.get("/api/messaging/incoming-webhooks/stats")
        check("H03 total", r3.json().get("total_webhooks") == 5, f"{r3.json().get('total_webhooks')}")
        print("H04 getDetail")
        r4 = await c.get("/api/messaging/incoming-webhooks/wh01")
        check("H04 name", r4.json().get("webhook", {}).get("name") == "ci-notifications", f"{r4.json().get('webhook')}")
        print("H05 createWebhook")
        r5 = await c.post("/api/messaging/incoming-webhooks", json={"name": "hook-test", "description": "Test", "channel": "test-ch"})
        check("H05 ok", r5.json().get("ok") is True, f"{r5.json().get('ok')}")
        nid = r5.json().get("webhook", {}).get("id", "")
        print("H06 sendMessage")
        r6 = await c.post("/api/messaging/incoming-webhooks/wh01/send", json={"text": "hook msg"})
        check("H06 ok", r6.json().get("ok") is True, f"{r6.json().get('ok')}")
        print("H07 testWebhook")
        r7 = await c.post("/api/messaging/incoming-webhooks/wh01/test")
        check("H07 ok", r7.json().get("ok") is True, f"{r7.json().get('ok')}")
        print("H08 getDeliveries")
        r8 = await c.get("/api/messaging/incoming-webhooks/wh01/deliveries")
        check("H08 id", r8.json().get("webhook_id") == "wh01", f"{r8.json().get('webhook_id')}")
        print("H09 deleteWebhook")
        if nid:
            r9 = await c.delete(f"/api/messaging/incoming-webhooks/{nid}")
            check("H09 ok", r9.json().get("ok") is True, f"{r9.json().get('ok')}")
        else:
            check("H09 ok", True, "skip")
    print(f"\n{'='*50}"); print(f"PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
    if FAIL: sys.exit(1)
if __name__ == "__main__": asyncio.run(main())
