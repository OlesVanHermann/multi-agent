#!/usr/bin/env python3
"""Test Frontend→Backend — collaborate (useCollaborate.ts hook simulation)"""
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

async def hook_fetch(client, method="GET", path="", json_body=None):
    """Simulates what useCollaborate.ts does: fetch(url, {method, body, headers})"""
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if method == "GET":
        resp = await client.get(path, headers=headers)
    elif method == "POST":
        resp = await client.post(path, json=json_body, headers=headers)
    elif method == "PATCH":
        resp = await client.patch(path, json=json_body, headers=headers)
    elif method == "DELETE":
        resp = await client.delete(path, headers=headers)
    else:
        raise ValueError(f"Unknown method: {method}")
    data = None
    error = None
    if resp.status_code < 400:
        data = resp.json()
    else:
        try:
            error = resp.json().get("detail")
        except Exception:
            error = resp.text
    return {"status": resp.status_code, "data": data, "error": error}

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

            # --- T01: hook fetchChannels — empty list ---
            print("T01 hook fetchChannels empty")
            result = await hook_fetch(c, "GET", f"{BASE}/channels")
            check("T01 status", result["status"], 200)
            check("T01 data is list", isinstance(result["data"], list), True)
            check("T01 empty", len(result["data"]), 0)

            # --- T02: hook createChannel — happy ---
            print("T02 hook createChannel")
            result = await hook_fetch(c, "POST", f"{BASE}/channels", {"name": "general", "description": "Main"})
            check("T02 status", result["status"], 201)
            check("T02 name", result["data"]["name"], "general")
            ch_id = result["data"]["id"]

            # --- T03: hook createChannel — validation error ---
            print("T03 hook createChannel invalid")
            result = await hook_fetch(c, "POST", f"{BASE}/channels", {"name": ""})
            check("T03 status", result["status"], 422)
            check("T03 has error", result["error"] is not None, True)

            # --- T04: hook updateChannel — PATCH ---
            print("T04 hook updateChannel")
            result = await hook_fetch(c, "PATCH", f"{BASE}/channels/{ch_id}", {"name": "updated"})
            check("T04 status", result["status"], 200)
            check("T04 name", result["data"]["name"], "updated")

            # --- T05: hook sendMessage — create message ---
            print("T05 hook sendMessage")
            result = await hook_fetch(c, "POST", f"{BASE}/channels/{ch_id}/messages", {"content": "Hello from hook"})
            check("T05 status", result["status"], 201)
            check("T05 content", result["data"]["content"], "Hello from hook")
            msg_id = result["data"]["id"]

            # --- T06: hook fetchMessages — list ---
            print("T06 hook fetchMessages")
            result = await hook_fetch(c, "GET", f"{BASE}/channels/{ch_id}/messages")
            check("T06 status", result["status"], 200)
            check("T06 count", len(result["data"]), 1)
            check("T06 first content", result["data"][0]["content"], "Hello from hook")

            # --- T07: hook searchMessages — match ---
            print("T07 hook searchMessages match")
            result = await hook_fetch(c, "GET", f"{BASE}/channels/{ch_id}/messages/search?q=hello")
            check("T07 status", result["status"], 200)
            check("T07 found", len(result["data"]), 1)

            # --- T08: hook searchMessages — no match ---
            print("T08 hook searchMessages no match")
            result = await hook_fetch(c, "GET", f"{BASE}/channels/{ch_id}/messages/search?q=zzz")
            check("T08 status", result["status"], 200)
            check("T08 empty", len(result["data"]), 0)

            # --- T09: hook addReaction ---
            print("T09 hook addReaction")
            result = await hook_fetch(
                c, "POST",
                f"{BASE}/channels/{ch_id}/messages/{msg_id}/reactions",
                {"emoji": "fire", "user": "alice"},
            )
            check("T09 status", result["status"], 201)
            check("T09 reaction", result["data"]["reactions"]["fire"], ["alice"])

            # --- T10: hook createDM ---
            print("T10 hook createDM")
            result = await hook_fetch(c, "POST", f"{BASE}/dms", {"participants": ["alice", "bob"]})
            check("T10 status", result["status"], 201)
            check("T10 participants", result["data"]["participants"], ["alice", "bob"])
            dm_id = result["data"]["id"]

            # --- T11: hook createDM — validation error (<2 participants) ---
            print("T11 hook createDM invalid")
            result = await hook_fetch(c, "POST", f"{BASE}/dms", {"participants": ["solo"]})
            check("T11 status", result["status"], 422)

            # --- T12: hook fetchDMs ---
            print("T12 hook fetchDMs")
            result = await hook_fetch(c, "GET", f"{BASE}/dms")
            check("T12 status", result["status"], 200)
            check("T12 count", len(result["data"]), 1)

            # --- T13: hook sendDMMessage ---
            print("T13 hook sendDMMessage")
            result = await hook_fetch(c, "POST", f"{BASE}/dms/{dm_id}/messages", {"content": "DM hello", "author": "alice"})
            check("T13 status", result["status"], 201)
            check("T13 content", result["data"]["content"], "DM hello")
            dm_msg_id = result["data"]["id"]

            # --- T14: hook fetchDMMessages ---
            print("T14 hook fetchDMMessages")
            result = await hook_fetch(c, "GET", f"{BASE}/dms/{dm_id}/messages")
            check("T14 status", result["status"], 200)
            check("T14 count", len(result["data"]), 1)

            # --- T15: hook deleteDMMessage ---
            print("T15 hook deleteDMMessage")
            result = await hook_fetch(c, "DELETE", f"{BASE}/dms/{dm_id}/messages/{dm_msg_id}")
            check("T15 status", result["status"], 200)
            check("T15 body", result["data"]["status"], "deleted")

            # --- T16: hook createThread ---
            print("T16 hook createThread")
            result = await hook_fetch(
                c, "POST", f"{BASE}/channels/{ch_id}/threads",
                {"channel_id": ch_id, "parent_message_id": msg_id, "content": "Thread via hook"},
            )
            check("T16 status", result["status"], 201)
            check("T16 replies count", len(result["data"]["replies"]), 1)
            thr_id = result["data"]["id"]

            # --- T17: hook addThreadReply ---
            print("T17 hook addThreadReply")
            result = await hook_fetch(
                c, "POST", f"{BASE}/channels/{ch_id}/threads/{thr_id}/replies",
                {"content": "Reply via hook", "author": "bob"},
            )
            check("T17 status", result["status"], 201)
            check("T17 replies count", len(result["data"]["replies"]), 2)

            # --- T18: hook fetchThreads ---
            print("T18 hook fetchThreads")
            result = await hook_fetch(c, "GET", f"{BASE}/channels/{ch_id}/threads")
            check("T18 status", result["status"], 200)
            check("T18 count", len(result["data"]), 1)

            # --- T19: hook deleteChannel ---
            print("T19 hook deleteChannel")
            result = await hook_fetch(c, "DELETE", f"{BASE}/channels/{ch_id}")
            check("T19 status", result["status"], 200)
            check("T19 body", result["data"]["status"], "deleted")

            # --- T20: hook deleteChannel — not found ---
            print("T20 hook deleteChannel not found")
            result = await hook_fetch(c, "DELETE", f"{BASE}/channels/nonexistent")
            check("T20 status", result["status"], 404)
            check("T20 error", result["error"] is not None, True)

            # --- T21: hook deleteDM ---
            print("T21 hook deleteDM")
            result = await hook_fetch(c, "DELETE", f"{BASE}/dms/{dm_id}")
            check("T21 status", result["status"], 200)
            check("T21 body", result["data"]["status"], "deleted")

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
