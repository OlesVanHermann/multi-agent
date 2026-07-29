"""Aucun message ne doit être parqué dans un stream que personne ne lit.

Audit 2026-07-29 : quatre streams (quarantine, supervision, terminals,
control) avaient un écrivain et aucun lecteur — le contenu était perdu
pendant que send.sh/done.sh annonçaient `DELIVERED`. Le non-réveil reste
la règle (anti-bruit v3.2.12) ; c'est l'absence de drainage qui était le
défaut.
"""

import os
import re
import subprocess
import sys
from queue import Queue
from threading import Lock
from unittest.mock import MagicMock

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "agent-bridge"))

LIB = os.path.join(ROOT, "scripts", "lib.sh")
SEND = os.path.join(ROOT, "scripts", "send.sh")
DONE = os.path.join(ROOT, "scripts", "done.sh")


def _bridge(agent_id):
    from agent import TmuxAgent
    instance = object.__new__(TmuxAgent)
    instance.agent_id = agent_id
    instance.redis = MagicMock()
    instance.metrics = None
    instance.prompt_queue = Queue()
    instance._inflight_ids = set()
    instance._inflight_lock = Lock()
    instance._log = MagicMock()
    instance._wal = MagicMock()
    instance._ack_inbox = MagicMock()
    return instance


# ── Drainage universel des streams parqués ──────────────────────────────

@pytest.mark.parametrize("agent_id", ["300", "334-834", "334-134"])
def test_parked_streams_are_drained_for_every_agent(agent_id):
    """control/terminals/supervision sont drainés quel que soit le rôle :
    un worker doit voir la question qui lui a été posée, un Master à ID nu
    doit voir le TERMINAL_PENDING que le watchdog lui écrit."""
    agent = _bridge(agent_id)
    drained = {name for name, _cursor, _header in agent._pending_streams()}
    for suffix in ("control", "terminals", "supervision"):
        assert f"agent:{agent_id}:{suffix}" in drained, suffix


def test_reports_stream_stays_reserved_to_triangle_coordinators():
    """Seul un coordinateur reçoit des rapports de subordonnés."""
    assert not any(
        name.endswith(":reports")
        for name, _c, _h in _bridge("334-834")._pending_streams())
    assert any(
        name.endswith(":reports")
        for name, _c, _h in _bridge("334-134")._pending_streams())


def test_parked_terminal_content_reaches_the_next_real_turn():
    """Le contenu d'un terminal parqué (champ prompt) est annexé, pas une
    ligne vide : c'est tout l'intérêt du drainage."""
    agent = _bridge("334-834")
    agent.redis.hget.return_value = None
    agent.redis.xrange.side_effect = lambda stream, **kw: (
        [("5-0", {"from_agent": "334-534", "event": "INFO_REQUIRED",
                  "prompt": "quelle version de l'API as-tu ciblée ?"})]
        if stream.endswith(":terminals") else [])

    enriched = agent._attach_pending_reports({"prompt": "travail en cours"})

    assert "quelle version de l'API as-tu ciblée ?" in enriched["prompt"]
    assert "travail en cours" in enriched["prompt"]


def test_draining_never_wakes_nor_answers():
    """Le drainage annexe au PROCHAIN vrai tour : il ne crée aucun tour et
    n'émet rien (l'anti-bruit v3.2.12 reste intact)."""
    agent = _bridge("334-834")
    agent.redis.hget.return_value = None
    agent.redis.xrange.return_value = [
        ("1-0", {"from_agent": "watchdog", "event": "TERMINAL_PENDING",
                 "detail": "silence observé"})]

    agent._attach_pending_reports({"prompt": "x"})

    assert agent.prompt_queue.empty()
    assert not agent.redis.xadd.called


# ── Vérité des états de livraison ───────────────────────────────────────

def test_done_reports_parked_no_wake_for_non_coordinator_targets():
    source = open(DONE, encoding="utf-8").read()
    assert "PARKED_NO_WAKE" in source
    parked = source.index("PARKED_NO_WAKE")
    delivered = source.rindex("state=DELIVERED")
    assert parked < delivered, "le cas parqué doit précéder le DELIVERED"


def test_anti_self_send_runs_after_triangle_resolution():
    """Depuis 300-301, « done.sh 301 » est résolu en 300-301 : un contrôle
    placé avant la résolution laissait passer le terminal auto-adressé."""
    source = open(DONE, encoding="utf-8").read()
    resolve = source.index("resolve_triangle_target")
    guard = source.index('if [ "$FROM_AGENT" = "$TO_AGENT" ]')
    assert resolve < guard


# ── Adressage : broadcast et cible globale explicite ────────────────────

def test_send_broadcast_fans_out_and_never_writes_agent_all_inbox():
    source = open(SEND, encoding="utf-8").read()
    assert 'TO_AGENT" = "all"' in source
    assert "list_live_agent_ids" in source, "fan-out réel attendu"
    assert "broadcast sans destinataire" in source, "échec franc si personne"
    # Aucun XADD ne doit pouvoir viser agent:all:inbox : le fan-out sort
    # avant la résolution/émission unitaire.
    broadcast = source.index('TO_AGENT" = "all"')
    unicast = source.index("# Envoyer via Redis Streams")
    assert broadcast < unicast


def _resolve(sender, target):
    return subprocess.run(
        ["bash", "-c",
         f'source "{LIB}"; resolve_triangle_target "{sender}" "{target}" t'],
        capture_output=True, text=True).stdout.strip()


def test_global_target_escape_is_never_rewritten():
    """`=100` joint le Master global même si le coordinateur local tourne."""
    assert _resolve("300-301", "=100") == "100"
    assert _resolve("300-301", "=300-100") == "300-100"


def test_unknown_triangle_member_keeps_the_global_target():
    """Aucune session vivante et aucun membre connu : conserver la cible
    nue, dont l'inbox sera rejouée — au lieu de la détourner vers une
    inbox de triangle que personne ne démarrera."""
    assert _resolve("999-901", "100") == "100"


@pytest.mark.parametrize("script", [SEND, DONE])
def test_scripts_accept_the_global_escape_syntax(script):
    source = open(script, encoding="utf-8").read()
    assert 'is_valid_agent_id "${TO_AGENT#=}"' in source


# ── Contradictor : plus aucun canal invisible ───────────────────────────

def test_contradictor_collects_supervision_and_control_streams():
    source = open(
        os.path.join(ROOT, "scripts", "agent-bridge", "contradictor.py"),
        encoding="utf-8").read()
    assert re.search(
        r'for source_name in \("inbox", "outbox", "reports", "control"\)',
        source), "reports/control doivent être collectés"
    assert '"external_or_direct_messages"' in source, (
        "un message hors triangle ne doit plus disparaître de l'analyse")
