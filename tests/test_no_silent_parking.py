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


def test_blocking_report_that_opens_turn_is_not_annexed_twice():
    """Le réveil contient déjà le résumé du rapport. Le drainage du rapport
    source et du terminal canonique de la même décision doit avancer ses
    curseurs sans recopier le texte dans le prompt du même tour.
    """
    agent = _bridge("334-134")
    agent.redis.hget.return_value = None
    decision = "decision-one"
    report_id = "report-one"

    def pending(stream, **_kwargs):
        if stream.endswith(":reports"):
            return [("10-0", {
                "schema": "ma.bus.v1",
                "report_id": report_id,
                "event_id": "report-event-one",
                "decision_id": decision,
                "source_turn_id": "turn-one",
                "from_agent": "334-334",
                "event": "MASTER_REPORT",
                "status": "INFO_REQUIRED",
                "summary": "choix opérateur indispensable",
            })]
        if stream.endswith(":terminals"):
            return [("11-0", {
                "schema": "ma.bus.v1",
                "event_id": "terminal-event-one",
                "decision_id": decision,
                "source_turn_id": "turn-one",
                "from_agent": "334-334",
                "event": "INFO_REQUIRED",
                "status": "INFO_REQUIRED",
                "prompt": "choix opérateur indispensable",
            })]
        return []

    agent.redis.xrange.side_effect = pending
    opening = {
        "prompt": "[BLOCAGE INFO_REQUIRED] choix opérateur indispensable",
        "msg_id": "wake-stream-id",
        "event": "DECISION_REQUIRED",
        "event_id": "wake-event-one",
        "decision_id": decision,
        "source_turn_id": "turn-one",
        "source_report_id": report_id,
        "related_report_id": report_id,
        "status": "INFO_REQUIRED",
        "from_agent": "334-334",
    }

    enriched = agent._attach_pending_reports(opening)

    assert enriched["prompt"].count("choix opérateur indispensable") == 1
    assert "RAPPORTS DE SUPERVISION NOUVEAUX" not in enriched["prompt"]
    assert "TERMINAUX REÇUS" not in enriched["prompt"]
    advanced = {
        call.args[1]: call.args[2] for call in agent.redis.hset.call_args_list
    }
    assert advanced["reports_cursor"] == "10-0"
    assert advanced["terminals_cursor"] == "11-0"


def test_nonblocking_decision_id_does_not_hide_pending_terminal():
    """Le decision_id v1 accompagne aussi les messages ordinaires pour
    l'audit. Il ne devient une clé de déduplication que pour un vrai blocage :
    un MESSAGE ne doit donc jamais masquer le DONE du même tour source.
    """
    agent = _bridge("334-134")
    agent.redis.hget.return_value = None

    def pending(stream, **_kwargs):
        if stream.endswith(":terminals"):
            return [("21-0", {
                "schema": "ma.bus.v1",
                "event_id": "terminal-event-two",
                "decision_id": "audit-decision-two",
                "source_turn_id": "turn-two",
                "from_agent": "334-334",
                "event": "DONE",
                "status": "DONE",
                "prompt": "résultat métier effectivement terminé",
            })]
        return []

    agent.redis.xrange.side_effect = pending
    opening = {
        "prompt": "mise à jour intermédiaire",
        "msg_id": "message-stream-id",
        "event": "MESSAGE",
        "event_id": "message-event-two",
        "decision_id": "audit-decision-two",
        "source_turn_id": "turn-two",
        "from_agent": "334-334",
    }

    enriched = agent._attach_pending_reports(opening)

    assert "mise à jour intermédiaire" in enriched["prompt"]
    assert "résultat métier effectivement terminé" in enriched["prompt"]
    assert "TERMINAUX REÇUS" in enriched["prompt"]


@pytest.mark.parametrize("order", ["report-first", "terminal-first"])
def test_consumed_blocking_decision_never_leaks_into_next_turn(order):
    """Wake et terminal ouvrent un seul tour dans les deux ordres. Leurs
    copies parquées sont ensuite drainées sans être annexées au tour suivant.
    """
    agent = _bridge("334-134")
    reservations = {}

    def reserve(name, value, **kwargs):
        if kwargs.get("nx") and name in reservations:
            return False
        reservations[name] = value
        return True

    agent.redis.set.side_effect = reserve
    agent.redis.get.side_effect = reservations.get
    decision = "blocking-decision-three"
    common = {
        "schema_version": "ma.bus.v1",
        "from_agent": "334-334",
        "task_id": "task-three",
        "cycle": "3",
        "correlation_id": "corr-three",
        "source_turn_id": "turn-three",
        "decision_id": decision,
        "status": "INFO_REQUIRED",
    }
    wake = {
        **common,
        "type": "prompt",
        "prompt": "réveil bloquant à ne voir qu'une fois",
        "event": "DECISION_REQUIRED",
        "event_id": "wake-three",
        "source_report_id": "report-three",
        "classification": "supervision_blocking",
    }
    terminal = {
        **common,
        "type": "prompt",
        "prompt": "terminal bloquant à ne pas rejouer",
        "event": "INFO_REQUIRED",
        "event_id": "terminal-three",
    }
    sequence = (
        (("31-0", wake), ("32-0", terminal))
        if order == "report-first"
        else (("31-0", terminal), ("32-0", wake))
    )
    for msg_id, event in sequence:
        agent._handle_inbox_message(msg_id, event)

    assert agent.prompt_queue.qsize() == 1
    agent.prompt_queue.get_nowait()

    def pending(stream, **_kwargs):
        if stream.endswith(":reports"):
            return [("40-0", {
                **common,
                "report_id": "report-three",
                "event_id": "report-event-three",
                "event": "MASTER_REPORT",
                "summary": "rapport bloquant déjà consommé",
            })]
        if stream.endswith(":terminals"):
            return [("41-0", terminal)]
        return []

    agent.redis.hget.return_value = None
    agent.redis.xrange.side_effect = pending
    following = agent._attach_pending_reports({
        "prompt": "tour métier suivant",
        "event": "MESSAGE",
        "from_agent": "cli",
    })

    assert following["prompt"] == "tour métier suivant"
    advanced = {
        call.args[1]: call.args[2] for call in agent.redis.hset.call_args_list
    }
    assert advanced["reports_cursor"] == "40-0"
    assert advanced["terminals_cursor"] == "41-0"


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
    # La branche broadcast doit précéder la publication unicast. L'XADD est
    # centralisé dans bus_protocol/Lua : send.sh ne construit plus de clé
    # agent:all:inbox lui-même.
    broadcast = source.index('TO_AGENT" = "all"')
    unicast = source.index('PUBLISH_OUTPUT=$(publish_message "$TO_AGENT"')
    assert broadcast < unicast
    assert "XADD" not in source, "send.sh délègue toute écriture au publisher"


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
