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
    "CONCLUSION", "ADVISORY_CONCLUSION", "ARBITRAGE", "PROMPT_RELOADED",
}
SUPERVISION = {"MASTER_REPORT", "STATUS", "PROGRESS", "ACK"}
CONTROL = {
    "STALL", "STALL_NUDGE", "STATUS_REQUIRED", "PROTOCOL_ERROR",
    "TERMINAL_PENDING", "LATE_EVENT", "STALE_EVENT", "DUPLICATE",
    "RUNTIME_INCONSISTENCY",
}


def _digest(namespace, material):
    """Retourne une identité Redis stable, bornée et sans contenu sensible."""
    encoded = json.dumps(
        {"namespace": namespace, **material}, ensure_ascii=False,
        sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def source_turn_id(data):
    """Identité du tour émetteur (schéma v1, puis alias historique)."""
    return str(
        data.get("source_turn_id", "")
        or data.get("turn_id", "")
        or "")


def source_report_id(data):
    """Identité du rapport source, avec compatibilité du hotfix initial."""
    return str(
        data.get("source_report_id", "")
        or data.get("related_report_id", "")
        or "")


def decision_status(data):
    """Statut métier commun au terminal et à son réveil de supervision."""
    event = str(data.get("event", "") or "").upper()
    status = str(data.get("status", "") or "").upper()
    if status in {"BLOCKED", "INFO_REQUIRED"}:
        return status
    if event in {"BLOCKED", "INFO_REQUIRED"}:
        return event
    return status if event == "DECISION_REQUIRED" else ""


def decision_identity(data):
    """Identifie une décision indépendamment de son canal report/done.

    ``report-master.sh`` peut réveiller le coordinateur avant que ``done.sh``
    publie le terminal canonique. Les deux enveloppes doivent donc partager
    une identité qui ne dépend ni du texte de présentation ni du type de
    canal. Un identifiant explicite v1 est prioritaire ; sinon le tour source
    permet une dérivation déterministe. Sans l'un de ces deux pivots, on ne
    déduplique pas sémantiquement : c'est le repli legacy fail-open qui évite
    de confondre deux vrais tours anciens portant la même corrélation.
    """
    status = decision_status(data)
    # Le publisher transporte decision_id sur toutes les enveloppes pour
    # l'audit, mais le slot partagé ne déduplique que les deux décisions
    # bloquantes. Sans cette garde, un MESSAGE normal puis un DONE du même
    # tour partageraient l'identité et le terminal serait supprimé.
    if not status:
        return ""
    explicit = str(data.get("decision_id", "") or "")
    if explicit:
        return explicit
    source_turn = source_turn_id(data)
    if not source_turn:
        return ""
    return _digest("decision", {
        "from_agent": str(data.get("from_agent", "") or ""),
        "status": status,
        "task_id": str(data.get("task_id", "") or ""),
        "cycle": str(data.get("cycle", "") or ""),
        "correlation_id": str(data.get("correlation_id", "") or ""),
        "source_turn_id": source_turn,
    })


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
    # La taxonomie sert à optimiser le routage, jamais à décider si un agent
    # a le droit de parler à un autre. Un événement applicatif nouveau ou
    # inconnu qui transporte réellement un message doit donc atteindre le
    # destinataire. La quarantaine reste réservée aux enveloppes sans contenu.
    if str(data.get("prompt", "") or "").strip():
        return "actionable"
    return "quarantine"


def event_fingerprint(data):
    explicit = str(data.get("event_id", "") or "")
    if explicit:
        return _digest("event-id", {"event_id": explicit})
    material = {
        key: str(data.get(key, "") or "")
        for key in (
            "from_agent", "event", "task_id", "cycle", "correlation_id",
            "artifact", "sha256", "payload_sha256", "prompt", "status",
            "classification",
        )
    }
    material["source_turn_id"] = source_turn_id(data)
    material["source_report_id"] = source_report_id(data)
    return _digest("event", material)


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
