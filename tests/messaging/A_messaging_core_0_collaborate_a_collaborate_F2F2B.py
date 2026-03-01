#!/usr/bin/env python3
"""Test Frontend→Frontend→Backend (agent) — collaborate
Full user scenario: create workspace, chat, react, thread, DM, cleanup."""
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
# Full User Scenario
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

            # --- S1: User opens Collaborate panel — empty state ---
            print("S1 initial state")
            resp = await c.get(f"{BASE}/channels")
            check("S1 channels status", resp.status_code, 200)
            check("S1 channels empty", len(resp.json()), 0)
            resp = await c.get(f"{BASE}/dms")
            check("S1 dms status", resp.status_code, 200)
            check("S1 dms empty", len(resp.json()), 0)

            # --- S2: User creates two channels ---
            print("S2 create channels")
            resp = await c.post(f"{BASE}/channels", json={"name": "general", "description": "Main discussion"})
            check("S2 ch1 status", resp.status_code, 201)
            ch1_id = resp.json()["id"]
            check("S2 ch1 has id", ch1_id is not None, True)

            resp = await c.post(f"{BASE}/channels", json={"name": "random"})
            check("S2 ch2 status", resp.status_code, 201)
            ch2_id = resp.json()["id"]
            check("S2 ch2 default desc", resp.json()["description"], "")

            # --- S3: User verifies channel list ---
            print("S3 verify channel list")
            resp = await c.get(f"{BASE}/channels")
            check("S3 status", resp.status_code, 200)
            check("S3 count", len(resp.json()), 2)
            names = [ch["name"] for ch in resp.json()]
            check("S3 general in list", "general" in names, True)
            check("S3 random in list", "random" in names, True)

            # --- S4: User clicks channel and sends messages ---
            print("S4 send messages to channel")
            resp = await c.post(f"{BASE}/channels/{ch1_id}/messages", json={"content": "Hello everyone!", "author": "alice"})
            check("S4 msg1 status", resp.status_code, 201)
            msg1_id = resp.json()["id"]
            check("S4 msg1 author", resp.json()["author"], "alice")

            resp = await c.post(f"{BASE}/channels/{ch1_id}/messages", json={"content": "Welcome to general!", "author": "bob"})
            check("S4 msg2 status", resp.status_code, 201)
            msg2_id = resp.json()["id"]

            resp = await c.post(f"{BASE}/channels/{ch1_id}/messages", json={"content": "Let's discuss the project"})
            check("S4 msg3 status", resp.status_code, 201)
            msg3_id = resp.json()["id"]
            check("S4 msg3 default author", resp.json()["author"], "user")

            # --- S5: User views messages ---
            print("S5 view messages")
            resp = await c.get(f"{BASE}/channels/{ch1_id}/messages")
            check("S5 status", resp.status_code, 200)
            check("S5 count", len(resp.json()), 3)

            # --- S6: User searches messages ---
            print("S6 search messages")
            resp = await c.get(f"{BASE}/channels/{ch1_id}/messages/search", params={"q": "welcome"})
            check("S6 status", resp.status_code, 200)
            check("S6 found", len(resp.json()), 1)
            check("S6 content", resp.json()[0]["content"], "Welcome to general!")

            resp = await c.get(f"{BASE}/channels/{ch1_id}/messages/search", params={"q": "HELLO"})
            check("S6 case insensitive", len(resp.json()), 1)

            resp = await c.get(f"{BASE}/channels/{ch1_id}/messages/search", params={"q": "nonexistent"})
            check("S6 no match", len(resp.json()), 0)

            # --- S7: User reacts to a message ---
            print("S7 add reactions")
            resp = await c.post(
                f"{BASE}/channels/{ch1_id}/messages/{msg1_id}/reactions",
                json={"emoji": "thumbsup", "user": "bob"},
            )
            check("S7 react1 status", resp.status_code, 201)
            check("S7 react1 users", resp.json()["reactions"]["thumbsup"], ["bob"])

            resp = await c.post(
                f"{BASE}/channels/{ch1_id}/messages/{msg1_id}/reactions",
                json={"emoji": "thumbsup", "user": "carol"},
            )
            check("S7 react2 status", resp.status_code, 201)
            check("S7 react2 users", resp.json()["reactions"]["thumbsup"], ["bob", "carol"])

            # Duplicate — carol again
            resp = await c.post(
                f"{BASE}/channels/{ch1_id}/messages/{msg1_id}/reactions",
                json={"emoji": "thumbsup", "user": "carol"},
            )
            check("S7 no dup", resp.json()["reactions"]["thumbsup"], ["bob", "carol"])

            # Different emoji
            resp = await c.post(
                f"{BASE}/channels/{ch1_id}/messages/{msg1_id}/reactions",
                json={"emoji": "heart", "user": "alice"},
            )
            check("S7 heart", resp.json()["reactions"]["heart"], ["alice"])

            # --- S8: User creates a thread ---
            print("S8 create thread")
            resp = await c.post(
                f"{BASE}/channels/{ch1_id}/threads",
                json={"channel_id": ch1_id, "parent_message_id": msg1_id, "content": "Thread start", "author": "alice"},
            )
            check("S8 status", resp.status_code, 201)
            thr_id = resp.json()["id"]
            check("S8 parent", resp.json()["parent_message_id"], msg1_id)
            check("S8 replies", len(resp.json()["replies"]), 1)
            check("S8 first reply", resp.json()["replies"][0]["content"], "Thread start")

            # --- S9: User adds replies to thread ---
            print("S9 thread replies")
            resp = await c.post(
                f"{BASE}/channels/{ch1_id}/threads/{thr_id}/replies",
                json={"content": "Good point!", "author": "bob"},
            )
            check("S9 reply1 status", resp.status_code, 201)
            check("S9 reply1 count", len(resp.json()["replies"]), 2)

            resp = await c.post(
                f"{BASE}/channels/{ch1_id}/threads/{thr_id}/replies",
                json={"content": "I agree", "author": "carol"},
            )
            check("S9 reply2 status", resp.status_code, 201)
            check("S9 reply2 count", len(resp.json()["replies"]), 3)

            # --- S10: User views threads ---
            print("S10 view threads")
            resp = await c.get(f"{BASE}/channels/{ch1_id}/threads")
            check("S10 status", resp.status_code, 200)
            check("S10 count", len(resp.json()), 1)
            check("S10 replies count", len(resp.json()[0]["replies"]), 3)

            # --- S11: User starts a DM ---
            print("S11 create DM")
            resp = await c.post(f"{BASE}/dms", json={"participants": ["alice", "bob"], "name": "Private chat"})
            check("S11 status", resp.status_code, 201)
            dm_id = resp.json()["id"]
            check("S11 name", resp.json()["name"], "Private chat")
            check("S11 participants", resp.json()["participants"], ["alice", "bob"])

            # --- S12: User sends DM messages ---
            print("S12 DM messages")
            resp = await c.post(f"{BASE}/dms/{dm_id}/messages", json={"content": "Hey Bob!", "author": "alice"})
            check("S12 msg1 status", resp.status_code, 201)
            dm_msg1_id = resp.json()["id"]

            resp = await c.post(f"{BASE}/dms/{dm_id}/messages", json={"content": "Hey Alice!", "author": "bob"})
            check("S12 msg2 status", resp.status_code, 201)
            dm_msg2_id = resp.json()["id"]

            resp = await c.get(f"{BASE}/dms/{dm_id}/messages")
            check("S12 list status", resp.status_code, 200)
            check("S12 list count", len(resp.json()), 2)

            # --- S13: User deletes a DM message ---
            print("S13 delete DM message")
            resp = await c.delete(f"{BASE}/dms/{dm_id}/messages/{dm_msg1_id}")
            check("S13 status", resp.status_code, 200)
            check("S13 body", resp.json()["status"], "deleted")

            resp = await c.get(f"{BASE}/dms/{dm_id}/messages")
            check("S13 remaining", len(resp.json()), 1)
            check("S13 remaining content", resp.json()[0]["content"], "Hey Alice!")

            # --- S14: User renames channel ---
            print("S14 rename channel")
            resp = await c.patch(f"{BASE}/channels/{ch1_id}", json={"name": "general-v2", "description": "Updated"})
            check("S14 status", resp.status_code, 200)
            check("S14 name", resp.json()["name"], "general-v2")
            check("S14 desc", resp.json()["description"], "Updated")

            # --- S15: User deletes a message ---
            print("S15 delete channel message")
            resp = await c.delete(f"{BASE}/channels/{ch1_id}/messages/{msg3_id}")
            check("S15 status", resp.status_code, 200)
            check("S15 body", resp.json()["status"], "deleted")

            resp = await c.get(f"{BASE}/channels/{ch1_id}/messages")
            check("S15 remaining", len(resp.json()), 2)

            # --- S16: Error cases in flow ---
            print("S16 error cases")
            resp = await c.get(f"{BASE}/channels/nonexistent")
            check("S16 channel 404", resp.status_code, 404)

            resp = await c.post(f"{BASE}/channels/{ch1_id}/messages", json={"content": ""})
            check("S16 empty content 422", resp.status_code, 422)

            resp = await c.post(f"{BASE}/dms", json={"participants": ["solo"]})
            check("S16 dm <2 participants 422", resp.status_code, 422)

            resp = await c.post(f"{BASE}/channels/nonexistent/messages", json={"content": "fail"})
            check("S16 msg to bad channel 404", resp.status_code, 404)

            # --- S17: User deletes the DM ---
            print("S17 delete DM")
            dm_msg_file = feat_dir / f"dm_messages_{dm_id}.json"
            check("S17 dm_msg file exists", dm_msg_file.exists(), True)
            resp = await c.delete(f"{BASE}/dms/{dm_id}")
            check("S17 status", resp.status_code, 200)
            check("S17 body", resp.json()["status"], "deleted")
            check("S17 dm_msg file cleaned", dm_msg_file.exists(), False)

            resp = await c.get(f"{BASE}/dms")
            check("S17 dms empty", len(resp.json()), 0)

            # --- S18: User deletes channels ---
            print("S18 delete channels")
            msg_file = feat_dir / f"messages_{ch1_id}.json"
            thr_file = feat_dir / f"threads_{ch1_id}.json"
            check("S18 msg file exists", msg_file.exists(), True)
            check("S18 thr file exists", thr_file.exists(), True)

            resp = await c.delete(f"{BASE}/channels/{ch1_id}")
            check("S18 ch1 status", resp.status_code, 200)
            check("S18 msg file cleaned", msg_file.exists(), False)
            check("S18 thr file cleaned", thr_file.exists(), False)

            resp = await c.delete(f"{BASE}/channels/{ch2_id}")
            check("S18 ch2 status", resp.status_code, 200)

            # --- S19: Final state — everything clean ---
            print("S19 final state")
            resp = await c.get(f"{BASE}/channels")
            check("S19 channels empty", len(resp.json()), 0)
            resp = await c.get(f"{BASE}/dms")
            check("S19 dms empty", len(resp.json()), 0)

            # Verify disk state
            channels_file = feat_dir / "channels.json"
            dms_file = feat_dir / "dms.json"
            if channels_file.exists():
                check("S19 disk channels", json.loads(channels_file.read_text()), [])
            if dms_file.exists():
                check("S19 disk dms", json.loads(dms_file.read_text()), [])

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Verdict
    if failures:
        print(f"\n{'='*40}\n{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  {f}")
        sys.exit(1)
    else:
        print("All checks passed.")

if __name__ == "__main__":
    asyncio.run(main())
