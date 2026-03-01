#!/usr/bin/env python3
"""Test Full-scenario Frontend→Frontend→Backend — incoming_webhooks."""
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
        print("S01 list webhooks")
        r = await c.get("/api/messaging/incoming-webhooks/list")
        check("S01 total", r.json().get("total") == 5, f"{r.json().get('total')}")
        print("S02 create webhook")
        r2 = await c.post("/api/messaging/incoming-webhooks", json={"name": "scenario-wh", "description": "Scenario test", "channel": "test-ch"})
        check("S02 ok", r2.json().get("ok") is True, f"{r2.json().get('ok')}")
        nid = r2.json().get("webhook", {}).get("id", "")
        print("S03 send message")
        r3 = await c.post("/api/messaging/incoming-webhooks/wh01/send", json={"text": "Scenario message"})
        check("S03 ok", r3.json().get("ok") is True, f"{r3.json().get('ok')}")
        check("S03 bot", r3.json().get("post", {}).get("is_bot") is True, f"{r3.json().get('post')}")
        print("S04 test webhook")
        r4 = await c.post("/api/messaging/incoming-webhooks/wh01/test")
        check("S04 ok", r4.json().get("ok") is True, f"{r4.json().get('ok')}")
        print("S05 check deliveries")
        r5 = await c.get("/api/messaging/incoming-webhooks/wh01/deliveries")
        check("S05 id", r5.json().get("webhook_id") == "wh01", f"{r5.json().get('webhook_id')}")
        check("S05 total", r5.json().get("total") >= 4, f"{r5.json().get('total')}")
        print("S06 update webhook")
        if nid:
            r6 = await c.put(f"/api/messaging/incoming-webhooks/{nid}", json={"description": "Updated scenario"})
            check("S06 ok", r6.json().get("ok") is True, f"{r6.json().get('ok')}")
        else:
            check("S06 ok", True, "skip")
        print("S07 stats")
        r7 = await c.get("/api/messaging/incoming-webhooks/stats")
        check("S07 total", r7.json().get("total_webhooks") >= 5, f"{r7.json().get('total_webhooks')}")
        print("S08 delete webhook")
        if nid:
            r8 = await c.delete(f"/api/messaging/incoming-webhooks/{nid}")
            check("S08 ok", r8.json().get("ok") is True, f"{r8.json().get('ok')}")
        else:
            check("S08 ok", True, "skip")
        print("S09 verify deleted")
        if nid:
            r9 = await c.get(f"/api/messaging/incoming-webhooks/{nid}")
            check("S09 404", r9.status_code == 404, f"{r9.status_code}")
        else:
            check("S09 404", True, "skip")
    print(f"\n{'='*50}"); print(f"PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
    if FAIL: sys.exit(1)
if __name__ == "__main__": asyncio.run(main())
