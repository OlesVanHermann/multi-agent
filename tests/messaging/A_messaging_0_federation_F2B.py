#!/usr/bin/env python3
"""Test Frontend→Backend — federation. Hook simulation."""
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
        print("H01 version")
        r = await c.get("/api/messaging/federation/version")
        check("H01 name", r.json().get("server", {}).get("name") == "aiapp-federation", f"{r.json().get('server')}")
        print("H02 keys")
        r2 = await c.get("/api/messaging/federation/keys")
        check("H02 count", len(r2.json().get("server_keys", [])) >= 1, f"{len(r2.json().get('server_keys', []))}")
        print("H03 sendStateEvent")
        r3 = await c.put("/api/messaging/federation/send", json={"origin": "remote.server", "pdus": [{"type": "m.room.member", "room_id": "!r1:remote.server", "sender": "@a:remote.server", "state_key": "@a:remote.server", "content": {"membership": "join"}, "event_id": "$se1", "depth": 1, "origin_server_ts": 1709000000000}], "edus": []})
        check("H03 pdu", r3.json().get("pdu_count") == 1, f"{r3.json().get('pdu_count')}")
        print("H04 getEvent")
        r4 = await c.get("/api/messaging/federation/event/$se1")
        check("H04 type", r4.json().get("event", {}).get("type") == "m.room.member", f"{r4.json().get('event')}")
        print("H05 roomState")
        r5 = await c.get("/api/messaging/federation/state/!r1:remote.server")
        check("H05 count", r5.json().get("state_count") >= 1, f"{r5.json().get('state_count')}")
        print("H06 backfill")
        r6 = await c.get("/api/messaging/federation/backfill/!r1:remote.server?limit=10")
        check("H06 count", r6.json().get("count") >= 1, f"{r6.json().get('count')}")
        print("H07 publicRooms")
        r7 = await c.get("/api/messaging/federation/public-rooms?limit=20")
        check("H07 chunk", isinstance(r7.json().get("chunk"), list), "not list")
    print(f"\n{'='*50}"); print(f"PASS={PASS}  FAIL={FAIL}  TOTAL={PASS+FAIL}")
    if FAIL: sys.exit(1)
if __name__ == "__main__": asyncio.run(main())
