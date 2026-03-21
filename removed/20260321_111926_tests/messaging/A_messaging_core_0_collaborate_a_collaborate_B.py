#!/usr/bin/env python3
"""Test Backend — collaborate (Channels, Messages, DMs, Threads, Reactions)"""
import asyncio
import sys
import os
import json
import tempfile
import shutil
import pathlib

sys.path.insert(0, "/home/ubuntu/aiapp/backend")
sys.path.insert(0, "/home/ubuntu/aiapp/infra/pgsql")

import storage

tmp = tempfile.mkdtemp()
storage.DATA_DIR = pathlib.Path(tmp)
storage.REMOVED_DIR = storage.DATA_DIR / "removed"

from collaborate_api import router
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

# ============================================================
# Helpers
# ============================================================

failures = []

def check(label: str, got, expected):
    if got != expected:
        failures.append(f"FAIL {label}: got {got!r}, expected {expected!r}")
        print(f"  FAIL {label}: got {got!r}, expected {expected!r}")
    else:
        print(f"  OK   {label}")

BASE = "/api/messaging/collaborate"

# ============================================================
# Tests
# ============================================================

async def main():
    app = FastAPI()
    app.include_router(router)
    transport = ASGITransport(app=app)

    feat_dir = storage.DATA_DIR / "messaging" / "collaborate"
    feat_dir.mkdir(parents=True, exist_ok=True)
    storage.REMOVED_DIR.mkdir(parents=True, exist_ok=True)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:

            # ── Channels ──

            # --- T01: GET /channels — empty list ---
            print("T01 list channels empty")
            resp = await c.get(f"{BASE}/channels")
            check("T01 status", resp.status_code, 200)
            check("T01 empty list", resp.json(), [])

            # --- T02: POST /channels — create happy ---
            print("T02 create channel")
            resp = await c.post(f"{BASE}/channels", json={"name": "general", "description": "Main channel"})
            check("T02 status", resp.status_code, 201)
            ch = resp.json()
            check("T02 name", ch["name"], "general")
            check("T02 description", ch["description"], "Main channel")
            check("T02 has id", "id" in ch, True)
            check("T02 has created_at", "created_at" in ch, True)
            ch_id = ch["id"]

            # --- T03: POST /channels — empty name (422) ---
            print("T03 create channel empty name")
            resp = await c.post(f"{BASE}/channels", json={"name": ""})
            check("T03 status", resp.status_code, 422)

            # --- T04: POST /channels — missing name (422) ---
            print("T04 create channel missing name")
            resp = await c.post(f"{BASE}/channels", json={})
            check("T04 status", resp.status_code, 422)

            # --- T05: GET /channels/{id} — found ---
            print("T05 get channel by id")
            resp = await c.get(f"{BASE}/channels/{ch_id}")
            check("T05 status", resp.status_code, 200)
            check("T05 name", resp.json()["name"], "general")

            # --- T06: GET /channels/{id} — not found (404) ---
            print("T06 get channel not found")
            resp = await c.get(f"{BASE}/channels/nonexistent")
            check("T06 status", resp.status_code, 404)

            # --- T07: PATCH /channels/{id} — update name ---
            print("T07 update channel")
            resp = await c.patch(f"{BASE}/channels/{ch_id}", json={"name": "renamed"})
            check("T07 status", resp.status_code, 200)
            check("T07 name", resp.json()["name"], "renamed")

            # --- T08: PATCH /channels/{id} — not found (404) ---
            print("T08 update channel not found")
            resp = await c.patch(f"{BASE}/channels/nonexistent", json={"name": "x"})
            check("T08 status", resp.status_code, 404)

            # --- T09: GET /channels — list has 1 ---
            print("T09 list channels after create")
            resp = await c.get(f"{BASE}/channels")
            check("T09 status", resp.status_code, 200)
            check("T09 count", len(resp.json()), 1)

            # ── Messages ──

            # --- T10: GET /channels/{cid}/messages — empty ---
            print("T10 list messages empty")
            resp = await c.get(f"{BASE}/channels/{ch_id}/messages")
            check("T10 status", resp.status_code, 200)
            check("T10 empty", resp.json(), [])

            # --- T11: POST /channels/{cid}/messages — create happy ---
            print("T11 create message")
            resp = await c.post(f"{BASE}/channels/{ch_id}/messages", json={"content": "Hello world"})
            check("T11 status", resp.status_code, 201)
            msg = resp.json()
            check("T11 content", msg["content"], "Hello world")
            check("T11 author default", msg["author"], "user")
            check("T11 channel_id", msg["channel_id"], ch_id)
            msg_id = msg["id"]

            # --- T12: POST /channels/{cid}/messages — channel not found (404) ---
            print("T12 create message channel not found")
            resp = await c.post(f"{BASE}/channels/nonexistent/messages", json={"content": "test"})
            check("T12 status", resp.status_code, 404)

            # --- T13: POST /channels/{cid}/messages — empty content (422) ---
            print("T13 create message empty content")
            resp = await c.post(f"{BASE}/channels/{ch_id}/messages", json={"content": ""})
            check("T13 status", resp.status_code, 422)

            # --- T14: GET /channels/{cid}/messages — list has 1 ---
            print("T14 list messages after create")
            resp = await c.get(f"{BASE}/channels/{ch_id}/messages")
            check("T14 status", resp.status_code, 200)
            check("T14 count", len(resp.json()), 1)

            # --- T15: DELETE /channels/{cid}/messages/{mid} — happy path ---
            print("T15 delete message happy")
            # Create a throwaway message to delete
            resp = await c.post(f"{BASE}/channels/{ch_id}/messages", json={"content": "to-delete"})
            check("T15 create status", resp.status_code, 201)
            del_msg_id = resp.json()["id"]
            resp = await c.delete(f"{BASE}/channels/{ch_id}/messages/{del_msg_id}")
            check("T15 status", resp.status_code, 200)
            check("T15 body", resp.json()["status"], "deleted")

            # --- T15b: DELETE /channels/{cid}/messages/{mid} — not found (404) ---
            print("T15b delete message not found")
            resp = await c.delete(f"{BASE}/channels/{ch_id}/messages/nonexistent")
            check("T15b status", resp.status_code, 404)

            # ── Search ──

            # --- T16: GET /channels/{cid}/messages/search?q=Hello — match ---
            print("T16 search messages match")
            resp = await c.get(f"{BASE}/channels/{ch_id}/messages/search", params={"q": "hello"})
            check("T16 status", resp.status_code, 200)
            check("T16 count", len(resp.json()), 1)
            check("T16 content", resp.json()[0]["content"], "Hello world")

            # --- T17: GET /channels/{cid}/messages/search?q=zzz — no match ---
            print("T17 search messages no match")
            resp = await c.get(f"{BASE}/channels/{ch_id}/messages/search", params={"q": "zzz"})
            check("T17 status", resp.status_code, 200)
            check("T17 empty", resp.json(), [])

            # --- T18: GET /channels/{cid}/messages/search — missing q (422) ---
            print("T18 search messages missing q")
            resp = await c.get(f"{BASE}/channels/{ch_id}/messages/search")
            check("T18 status", resp.status_code, 422)

            # ── Reactions ──

            # --- T19: POST reactions — add happy ---
            print("T19 add reaction")
            resp = await c.post(
                f"{BASE}/channels/{ch_id}/messages/{msg_id}/reactions",
                json={"emoji": "thumbsup", "user": "alice"},
            )
            check("T19 status", resp.status_code, 201)
            check("T19 reactions", resp.json()["reactions"]["thumbsup"], ["alice"])

            # --- T20: POST reactions — duplicate user no new entry ---
            print("T20 add reaction duplicate user")
            resp = await c.post(
                f"{BASE}/channels/{ch_id}/messages/{msg_id}/reactions",
                json={"emoji": "thumbsup", "user": "alice"},
            )
            check("T20 status", resp.status_code, 201)
            check("T20 no dup", resp.json()["reactions"]["thumbsup"], ["alice"])

            # --- T21: POST reactions — second emoji ---
            print("T21 add second emoji")
            resp = await c.post(
                f"{BASE}/channels/{ch_id}/messages/{msg_id}/reactions",
                json={"emoji": "heart", "user": "bob"},
            )
            check("T21 status", resp.status_code, 201)
            check("T21 heart", resp.json()["reactions"]["heart"], ["bob"])
            check("T21 thumbsup still", resp.json()["reactions"]["thumbsup"], ["alice"])

            # --- T22: POST reactions — message not found (404) ---
            print("T22 reaction message not found")
            resp = await c.post(
                f"{BASE}/channels/{ch_id}/messages/nonexistent/reactions",
                json={"emoji": "x", "user": "u"},
            )
            check("T22 status", resp.status_code, 404)

            # ── DMs ──

            # --- T23: GET /dms — empty ---
            print("T23 list dms empty")
            resp = await c.get(f"{BASE}/dms")
            check("T23 status", resp.status_code, 200)
            check("T23 empty", resp.json(), [])

            # --- T24: POST /dms — create happy ---
            print("T24 create dm")
            resp = await c.post(f"{BASE}/dms", json={"participants": ["alice", "bob"], "name": "chat"})
            check("T24 status", resp.status_code, 201)
            dm = resp.json()
            check("T24 participants", dm["participants"], ["alice", "bob"])
            check("T24 name", dm["name"], "chat")
            dm_id = dm["id"]

            # --- T25: POST /dms — <2 participants (422) ---
            print("T25 create dm too few participants")
            resp = await c.post(f"{BASE}/dms", json={"participants": ["alone"]})
            check("T25 status", resp.status_code, 422)

            # --- T26: GET /dms/{did}/messages — empty ---
            print("T26 list dm messages empty")
            resp = await c.get(f"{BASE}/dms/{dm_id}/messages")
            check("T26 status", resp.status_code, 200)
            check("T26 empty", resp.json(), [])

            # --- T27: POST /dms/{did}/messages — create happy ---
            print("T27 create dm message")
            resp = await c.post(f"{BASE}/dms/{dm_id}/messages", json={"content": "Hi DM", "author": "alice"})
            check("T27 status", resp.status_code, 201)
            dm_msg = resp.json()
            check("T27 content", dm_msg["content"], "Hi DM")
            check("T27 author", dm_msg["author"], "alice")
            dm_msg_id = dm_msg["id"]

            # --- T28: POST /dms/{did}/messages — DM not found (404) ---
            print("T28 create dm message dm not found")
            resp = await c.post(f"{BASE}/dms/nonexistent/messages", json={"content": "test"})
            check("T28 status", resp.status_code, 404)

            # --- T29: DELETE /dms/{did}/messages/{mid} — delete happy ---
            print("T29 delete dm message")
            resp = await c.delete(f"{BASE}/dms/{dm_id}/messages/{dm_msg_id}")
            check("T29 status", resp.status_code, 200)
            check("T29 body", resp.json()["status"], "deleted")

            # --- T30: DELETE /dms/{did}/messages/{mid} — not found (404) ---
            print("T30 delete dm message not found")
            resp = await c.delete(f"{BASE}/dms/{dm_id}/messages/nonexistent")
            check("T30 status", resp.status_code, 404)

            # --- T31: DELETE /dms/{did} — not found (404) ---
            print("T31 delete dm not found")
            resp = await c.delete(f"{BASE}/dms/nonexistent")
            check("T31 status", resp.status_code, 404)

            # --- T32: DELETE /dms/{did} — delete happy + cleanup ---
            print("T32 delete dm with cleanup")
            # First send a message so dm_messages_ file exists
            await c.post(f"{BASE}/dms/{dm_id}/messages", json={"content": "before delete"})
            dm_msg_file = feat_dir / f"dm_messages_{dm_id}.json"
            check("T32 dm_messages file exists before", dm_msg_file.exists(), True)
            resp = await c.delete(f"{BASE}/dms/{dm_id}")
            check("T32 status", resp.status_code, 200)
            check("T32 body", resp.json()["status"], "deleted")
            check("T32 dm_messages file cleaned", dm_msg_file.exists(), False)

            # ── Threads ──

            # --- T33: GET /channels/{cid}/threads — empty ---
            print("T33 list threads empty")
            resp = await c.get(f"{BASE}/channels/{ch_id}/threads")
            check("T33 status", resp.status_code, 200)
            check("T33 empty", resp.json(), [])

            # --- T34: POST /channels/{cid}/threads — create happy ---
            print("T34 create thread")
            resp = await c.post(
                f"{BASE}/channels/{ch_id}/threads",
                json={"channel_id": ch_id, "parent_message_id": msg_id, "content": "Thread start", "author": "alice"},
            )
            check("T34 status", resp.status_code, 201)
            thr = resp.json()
            check("T34 channel_id", thr["channel_id"], ch_id)
            check("T34 parent_message_id", thr["parent_message_id"], msg_id)
            check("T34 has replies", len(thr["replies"]), 1)
            check("T34 first reply content", thr["replies"][0]["content"], "Thread start")
            thr_id = thr["id"]

            # --- T35: POST /channels/{cid}/threads — channel not found (404) ---
            print("T35 create thread channel not found")
            resp = await c.post(
                f"{BASE}/channels/nonexistent/threads",
                json={"channel_id": "nonexistent", "parent_message_id": "x", "content": "fail"},
            )
            check("T35 status", resp.status_code, 404)

            # --- T36: POST /channels/{cid}/threads/{tid}/replies — add reply happy ---
            print("T36 add thread reply")
            resp = await c.post(
                f"{BASE}/channels/{ch_id}/threads/{thr_id}/replies",
                json={"content": "Reply 1", "author": "bob"},
            )
            check("T36 status", resp.status_code, 201)
            thr_updated = resp.json()
            check("T36 replies count", len(thr_updated["replies"]), 2)
            check("T36 reply content", thr_updated["replies"][1]["content"], "Reply 1")
            check("T36 reply author", thr_updated["replies"][1]["author"], "bob")

            # --- T37: POST /channels/{cid}/threads/{tid}/replies — thread not found (404) ---
            print("T37 add reply thread not found")
            resp = await c.post(
                f"{BASE}/channels/{ch_id}/threads/nonexistent/replies",
                json={"content": "fail"},
            )
            check("T37 status", resp.status_code, 404)

            # --- T38: GET /channels/{cid}/threads — list has 1 ---
            print("T38 list threads after create")
            resp = await c.get(f"{BASE}/channels/{ch_id}/threads")
            check("T38 status", resp.status_code, 200)
            check("T38 count", len(resp.json()), 1)

            # ── Channel delete cleanup ──

            # --- T39: DELETE /channels/{id} — verify messages_ + threads_ cleanup ---
            print("T39 delete channel with cleanup")
            msg_file = feat_dir / f"messages_{ch_id}.json"
            thr_file = feat_dir / f"threads_{ch_id}.json"
            check("T39 msg file exists before", msg_file.exists(), True)
            check("T39 thr file exists before", thr_file.exists(), True)
            resp = await c.delete(f"{BASE}/channels/{ch_id}")
            check("T39 status", resp.status_code, 200)
            check("T39 body", resp.json()["status"], "deleted")
            check("T39 msg file cleaned", msg_file.exists(), False)
            check("T39 thr file cleaned", thr_file.exists(), False)

            # --- T40: DELETE /channels/{id} — not found (404) ---
            print("T40 delete channel not found")
            resp = await c.delete(f"{BASE}/channels/nonexistent")
            check("T40 status", resp.status_code, 404)

            # --- T41: Disk state — channels.json empty after all deletes ---
            print("T41 disk state channels empty")
            channels_file = feat_dir / "channels.json"
            if channels_file.exists():
                disk_data = json.loads(channels_file.read_text())
                check("T41 disk empty", disk_data, [])
            else:
                check("T41 disk file gone (ok)", True, True)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Verdict
    if failures:
        print(f"\n{'='*40}\n{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  {f}")
        sys.exit(1)
    else:
        print(f"\nAll checks passed.")

if __name__ == "__main__":
    asyncio.run(main())
