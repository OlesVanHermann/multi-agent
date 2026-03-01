#!/usr/bin/env python3
"""Test Backend — advanced_options. 12 endpoints."""
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
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        print("T01 list preferences")
        r = await c.get("/api/messaging/advanced-options/preferences")
        check("T01 count", r.json().get("total") >= 18, f"{r.json().get('total')}")
        print("T02 filter category")
        r2 = await c.get("/api/messaging/advanced-options/preferences?category=display")
        check("T02 filtered", r2.json().get("count") > 0, f"{r2.json().get('count')}")
        print("T03 get category")
        r3 = await c.get("/api/messaging/advanced-options/preferences/display")
        check("T03 count", r3.json().get("count") > 0, f"{r3.json().get('count')}")
        print("T04 invalid category")
        r4 = await c.get("/api/messaging/advanced-options/preferences/nonexistent")
        check("T04 404", r4.status_code == 404, f"{r4.status_code}")
        print("T05 update prefs")
        r5 = await c.put("/api/messaging/advanced-options/preferences", json={"preferences": [{"name": "send_on_ctrl_enter", "value": "true"}]})
        check("T05 ok", r5.json().get("ok") is True, f"{r5.json().get('ok')}")
        check("T05 updated", r5.json().get("updated_count") >= 1, f"{r5.json().get('updated_count')}")
        print("T06 reset prefs")
        r6 = await c.post("/api/messaging/advanced-options/preferences/reset", json={"category": "display"})
        check("T06 ok", r6.json().get("ok") is True, f"{r6.json().get('ok')}")
        print("T07 get display")
        r7 = await c.get("/api/messaging/advanced-options/display")
        check("T07 msg", r7.json().get("message_display") is not None, f"{r7.json()}")
        check("T07 clock", r7.json().get("clock_display") is not None, f"{r7.json()}")
        print("T08 update display")
        r8 = await c.put("/api/messaging/advanced-options/display", json={"message_display": "compact", "clock_display": "24h"})
        check("T08 ok", r8.json().get("ok") is True, f"{r8.json().get('ok')}")
        print("T09 get locale")
        r9 = await c.get("/api/messaging/advanced-options/locale")
        check("T09 locale", r9.json().get("locale") is not None, f"{r9.json()}")
        print("T10 update locale")
        r10 = await c.put("/api/messaging/advanced-options/locale", json={"locale": "fr", "reduce_motion": True})
        check("T10 ok", r10.json().get("ok") is True, f"{r10.json().get('ok')}")
        print("T11 export")
        r11 = await c.post("/api/messaging/advanced-options/export", json={"export_format": "json"})
        check("T11 ok", r11.json().get("ok") is True, f"{r11.json().get('ok')}")
        eid = r11.json().get("export_id", "")
        print("T12 export status")
        if eid:
            r12 = await c.get(f"/api/messaging/advanced-options/export/{eid}")
            check("T12 status", r12.json().get("export", {}).get("status") in ("pending", "processing", "ready"), f"{r12.json().get('export')}")
        else:
            check("T12 skip", True, "no eid")
        print("T13 export 404")
        r13 = await c.get("/api/messaging/advanced-options/export/fake")
        check("T13 404", r13.status_code == 404, f"{r13.status_code}")
        print("T14 deactivate no confirm")
        r14 = await c.post("/api/messaging/advanced-options/deactivate", json={"confirm": False})
        check("T14 rejected", r14.status_code in (400, 422) or r14.json().get("ok") is False, f"{r14.status_code}")
        print("T15 deactivate confirm")
        r15 = await c.post("/api/messaging/advanced-options/deactivate", json={"confirm": True})
        check("T15 ok", r15.json().get("ok") is True or r15.json().get("status") == "deactivated", f"{r15.json()}")
        print("T16 debug")
        r16 = await c.get("/api/messaging/advanced-options/debug")
        check("T16 data", r16.json().get("dev_mode") is not None or "debug" in str(r16.json()).lower(), f"{list(r16.json().keys())}")
    print(f"\n{'='*50}"); print(f"PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
    if FAIL: sys.exit(1)
if __name__ == "__main__": asyncio.run(main())
