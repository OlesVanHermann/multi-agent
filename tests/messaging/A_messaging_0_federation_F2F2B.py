#!/usr/bin/env python3
"""Test Full-scenario Frontend→Frontend→Backend — federation."""
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
    from federation_api import router
    app = FastAPI(); app.include_router(router); transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=True) as c:
        print("S01 check version")
        r = await c.get("/api/messaging/federation/version")
        check("S01 name", r.json().get("server", {}).get("name") == "aiapp-federation", f"{r.json().get('server')}")
        print("S02 check keys")
        r2 = await c.get("/api/messaging/federation/keys")
        check("S02 keys", len(r2.json().get("server_keys", [])) >= 1, f"{len(r2.json().get('server_keys', []))}")
        print("S03 send state event")
        r3 = await c.put("/api/messaging/federation/send", json={"origin": "remote.server", "pdus": [{"type": "m.room.member", "room_id": "!rm1:remote.server", "sender": "@alice:remote.server", "state_key": "@alice:remote.server", "content": {"membership": "join"}, "event_id": "$sce1", "depth": 1, "origin_server_ts": 1709000000000}], "edus": [{"edu_type": "m.presence", "content": {"user_id": "@alice:remote.server", "presence": "online", "last_active_ago": 1000, "currently_active": True, "status_msg": "Hi"}}]})
        check("S03 pdu", r3.json().get("pdu_count") == 1, f"{r3.json().get('pdu_count')}")
        check("S03 edu", r3.json().get("edu_count") == 1, f"{r3.json().get('edu_count')}")
        print("S04 send message event")
        r4 = await c.put("/api/messaging/federation/send", json={"origin": "remote.server", "pdus": [{"type": "m.room.message", "room_id": "!rm1:remote.server", "sender": "@alice:remote.server", "content": {"body": "Hello"}, "event_id": "$sce2", "state_key": None, "depth": 2, "origin_server_ts": 1709000001000}], "edus": []})
        check("S04 pdu", r4.json().get("pdu_count") == 1, f"{r4.json().get('pdu_count')}")
        print("S05 get state")
        r5 = await c.get("/api/messaging/federation/state/!rm1:remote.server")
        check("S05 count", r5.json().get("state_count") >= 1, f"{r5.json().get('state_count')}")
        print("S06 backfill")
        r6 = await c.get("/api/messaging/federation/backfill/!rm1:remote.server?limit=10")
        check("S06 count", r6.json().get("count") >= 2, f"{r6.json().get('count')}")
        print("S07 make-join")
        r7 = await c.get("/api/messaging/federation/make-join/!rm1:remote.server/@bob:local")
        check("S07 sender", r7.json().get("event", {}).get("sender") == "@bob:local", f"{r7.json().get('event')}")
        print("S08 presence")
        r8 = await c.get("/api/messaging/federation/presence?user_ids=@alice:remote.server")
        check("S08 count", r8.json().get("count") == 1, f"{r8.json().get('count')}")
        check("S08 online", r8.json().get("presence", [{}])[0].get("presence") == "online", f"{r8.json().get('presence')}")
        print("S09 public rooms")
        r9 = await c.get("/api/messaging/federation/public-rooms?limit=20")
        check("S09 chunk", isinstance(r9.json().get("chunk"), list), "not list")
    print(f"\n{'='*50}"); print(f"PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
    if FAIL: sys.exit(1)
if __name__ == "__main__": asyncio.run(main())
