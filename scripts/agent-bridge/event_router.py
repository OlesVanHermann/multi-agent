#!/usr/bin/env python3
"""Classification déterministe des événements avant toute injection TUI."""

import hashlib
import json


ACTIONABLE = {"", "MESSAGE", "DISPATCH", "INFO_REQUIRED", "DECISION_REQUIRED"}
TERMINAL = {
    "DONE", "SCORE", "BLOCKED", "ERROR", "ARTIFACT_READY",
    "CONCLUSION", "ARBITRAGE", "PROMPT_RELOADED",
}
SUPERVISION = {"MASTER_REPORT", "STATUS", "PROGRESS", "ACK"}
CONTROL = {
    "STALL", "STALL_NUDGE", "STATUS_REQUIRED", "PROTOCOL_ERROR",
    "LATE_EVENT", "STALE_EVENT", "DUPLICATE",
}


def classify(data):
    event = str(data.get("event", "") or "").upper()
    if event in TERMINAL:
        return "terminal"
    if event in SUPERVISION:
        return "supervision"
    if event in CONTROL:
        return "control"
    if event in ACTIONABLE:
        return "actionable"
    return "quarantine"


def event_fingerprint(data):
    material = {
        key: str(data.get(key, "") or "")
        for key in (
            "from_agent", "event", "task_id", "cycle", "correlation_id",
            "artifact", "sha256", "prompt",
        )
    }
    encoded = json.dumps(
        material, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def triangle_master(agent_id):
    text = str(agent_id)
    if "-" not in text:
        return ""
    triangle, member = text.split("-", 1)
    if not (triangle.isdigit() and member.isdigit()
            and len(triangle) == len(member) == 3):
        return ""
    return f"{triangle}-1{member[1:]}"


def should_wake_for_terminal(target_agent, data):
    """Un nouveau terminal réveille seulement son Master pour décision."""
    return triangle_master(target_agent) == str(target_agent)
