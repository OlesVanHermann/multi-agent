#!/usr/bin/env python3
"""Classification déterministe des événements avant toute injection TUI."""

import hashlib
import json


# L'événement vide reste accepté pour les anciennes enveloppes structurées
# créées avant l'introduction de DISPATCH. MESSAGE reste actionnable tant que
# send.sh l'émet par défaut entre agents (arbitrage 2026-07-28) : le stream
# supervision n'a pas de consommateur worker, le reclasser couperait les
# pipelines existants. La suppression du bruit de courtoisie est un contrat
# de prompt (NOOP = silence à l'émission), pas une reclassification transport.
ACTIONABLE = {"", "MESSAGE", "DISPATCH", "DECISION_REQUIRED"}
TERMINAL = {
    "DONE", "SCORE", "BLOCKED", "ERROR", "INFO_REQUIRED", "ARTIFACT_READY",
    "CONCLUSION", "ARBITRAGE", "PROMPT_RELOADED",
}
SUPERVISION = {"MASTER_REPORT", "STATUS", "PROGRESS", "ACK"}
CONTROL = {
    "STALL", "STALL_NUDGE", "STATUS_REQUIRED", "PROTOCOL_ERROR",
    "TERMINAL_PENDING", "LATE_EVENT", "STALE_EVENT", "DUPLICATE",
    "RUNTIME_INCONSISTENCY",
}


def classify(data):
    if str(data.get("type", "") or "") == "reload_prompt":
        return "actionable"
    event = str(data.get("event", "") or "").upper()
    sender = str(data.get("from_agent", "") or "")
    # Une commande opérateur reste actionnable sans forcer l'utilisateur à
    # connaître le protocole inter-agent. MESSAGE est sinon une narration
    # stockée sans tour modèle.
    if sender in {"cli", "manual"} and event in {"", "MESSAGE"}:
        return "actionable"
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
    """Un nouveau terminal réveille son destinataire décisionnaire.

    Triangle : seul le Master NNN-1XX décide (DECISION_REQUIRED unique).
    Pipeline à IDs nus (mode standard) : pas de coordinateur dédié — le
    destinataire est réveillé, sinon un DONE ou un INFO_REQUIRED
    n'atteindrait jamais personne.
    """
    target = str(target_agent)
    if "-" not in target:
        return True
    return triangle_master(target) == target
