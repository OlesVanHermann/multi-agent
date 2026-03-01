#!/usr/bin/env python3
"""Test Backend — collab_events. 12 endpoints."""
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
    from collab_events_api import router
    app = FastAPI(); app.include_router(router); transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=True) as c:
        print("T01 list shared invites")
        r = await c.get("/api/messaging/collab-events/shared-invites")
        invites = r.json()
        check("T01 list", isinstance(invites, list) and len(invites) >= 6, f"{len(invites)}")
        print("T02 get shared invite")
        iid = invites[0].get("id", "") if invites else ""
        if iid:
            r2 = await c.get(f"/api/messaging/collab-events/shared-invites/{iid}")
            check("T02 ok", r2.status_code == 200, f"{r2.status_code}")
        else:
            check("T02 ok", True, "skip")
        print("T03 create shared invite")
        r3 = await c.post("/api/messaging/collab-events/shared-invites", json={"inviting_team_id": "T001", "inviting_team_name": "Test", "inviting_user_id": "U001", "inviting_user_name": "tester", "channel_id": "C001", "channel_name": "test"})
        check("T03 ok", r3.status_code in (200, 201), f"{r3.status_code}")
        print("T04 list subteams")
        r4 = await c.get("/api/messaging/collab-events/subteams")
        subs = r4.json()
        check("T04 list", isinstance(subs, list) and len(subs) >= 5, f"{len(subs)}")
        print("T05 get subteam")
        stid = subs[0].get("id", "") if subs else ""
        if stid:
            r5 = await c.get(f"/api/messaging/collab-events/subteams/{stid}")
            check("T05 ok", r5.status_code == 200, f"{r5.status_code}")
        else:
            check("T05 ok", True, "skip")
        print("T06 simulate subteam event")
        r6 = await c.post("/api/messaging/collab-events/subteam-simulate", json={"action": "created", "subteam_id": "ST001", "name": "Test", "handle": "test"})
        check("T06 ok", r6.status_code == 200, f"{r6.status_code}")
        print("T07 list collab types")
        r7 = await c.get("/api/messaging/collab-events/collab-types")
        types = r7.json()
        check("T07 list", isinstance(types, list) and len(types) >= 10, f"{len(types)}")
        print("T08 get collab type")
        if types:
            etype = types[0].get("event_type", "")
            r8 = await c.get(f"/api/messaging/collab-events/collab-types/{etype}")
            check("T08 ok", r8.status_code == 200, f"{r8.status_code}")
        else:
            check("T08 ok", True, "skip")
        print("T09 list event log")
        r9 = await c.get("/api/messaging/collab-events/event-log")
        check("T09 ok", r9.status_code == 200, f"{r9.status_code}")
        print("T10 log collab event")
        r10 = await c.post("/api/messaging/collab-events/event-log", json={"event_type": "shared_channel_invite", "category": "shared_channel", "team_id": "T001", "summary": "test event"})
        check("T10 ok", r10.status_code in (200, 201), f"{r10.status_code}")
        print("T11 analyze patterns")
        r11 = await c.post("/api/messaging/collab-events/event-analyze", json={"team_id": "T001"})
        check("T11 ok", r11.status_code == 200, f"{r11.status_code}")
        print("T12 delete invite")
        new_invs = await c.get("/api/messaging/collab-events/shared-invites")
        inv_list = new_invs.json()
        if inv_list:
            did = inv_list[-1].get("id", "")
            r12 = await c.delete(f"/api/messaging/collab-events/shared-invites/{did}")
            check("T12 ok", r12.status_code == 200, f"{r12.status_code}")
        else:
            check("T12 ok", True, "skip")
    print(f"\n{'='*50}"); print(f"PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
    if FAIL: sys.exit(1)
if __name__ == "__main__": asyncio.run(main())
