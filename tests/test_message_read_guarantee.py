"""Invariant A8 : un message envoyé est reçu ET fini par être lu.

Constat du 19/08/2026 (triangle 334) : le canal livrait (DELIVERED) mais la
lecture dépendait d'un « prochain vrai tour » du destinataire qui pouvait ne
jamais arriver — 11 messages « stored; not injected into TUI » pendant 4 h
chez un Master idle. Quatre mécanismes ferment le trou :

1. annexation avec échéance (idle-flush) : un agent idle avec du contenu
   parqué ouvre UN tour de synthèse borné ;
2. accusés de lecture ma:bus:v1:read:* : READ ≠ DELIVERED ;
3. enveloppe last_* conservée après la fin du tour : les rapports émis
   pendant le travail post-tour ne partent plus en unattributed/rescue ;
4. watchdog : backlog non-lu au-delà de l'échéance et bridge périmé alertés.
"""

import argparse
import os
import sys
import time
from queue import Queue
from threading import Lock
from unittest.mock import MagicMock

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "agent-bridge"))


def _bridge(agent_id, redis_client=None):
    from agent import TmuxAgent, State
    instance = object.__new__(TmuxAgent)
    instance.agent_id = agent_id
    instance.inbox = f"agent:{agent_id}:inbox"
    instance.redis = redis_client if redis_client is not None else MagicMock()
    instance.metrics = None
    instance.prompt_queue = Queue()
    instance._inflight_ids = set()
    instance._inflight_lock = Lock()
    instance._log = MagicMock()
    instance._log_event = MagicMock()
    instance._wal = MagicMock()
    instance._ack_inbox = MagicMock()
    instance.state = State.IDLE
    instance._last_turn_end_ts = 0.0
    instance._last_flush_ts = 0.0
    instance._composer_orphan = {"text": "", "since": 0.0, "alerted": False}
    return instance


IDLE_PANE = {"busy": False, "login_required": False, "waiting_approval": False}


# ── 1. Annexation avec échéance (idle-flush) ────────────────────────────


class TestIdleFlush:
    def _parked(self, agent, entries):
        agent.redis.hget.return_value = None
        agent.redis.xrange.side_effect = lambda stream, **kw: (
            entries if stream.endswith(":supervision") else [])

    def test_flush_queues_one_synthesis_turn_with_parked_content(self):
        agent = _bridge("961-861")
        self._parked(agent, [("7-0", {
            "from_agent": "961-361", "event": "MASTER_REPORT",
            "status": "PARTIAL", "summary": "lot 2 écrit, suite en cours",
            "event_id": "event-flush-1"})])

        assert agent._maybe_flush_parked(dict(IDLE_PANE)) is True
        task = agent.prompt_queue.get_nowait()
        assert task["source"] == "annex_flush"
        assert "lot 2 écrit" in task["prompt"]
        assert task["_annexed_refs"], "les entrées annexées doivent être tracées"

    def test_flush_turn_opens_no_obligation(self):
        """Le tour de synthèse ne doit dû ni terminal corrélé ni rapport."""
        agent = _bridge("961-861")
        self._parked(agent, [("8-0", {
            "from_agent": "961-361", "event": "STATUS",
            "prompt": "progression", "event_id": "event-flush-2"})])
        assert agent._maybe_flush_parked(dict(IDLE_PANE)) is True
        task = agent.prompt_queue.get_nowait()
        assert agent._requires_correlated_event(task) is False
        assert agent._requires_master_report(task) is False

    def test_flush_waits_for_idle_age(self):
        agent = _bridge("961-861")
        agent._last_turn_end_ts = time.time()  # tour tout juste terminé
        self._parked(agent, [("9-0", {"prompt": "x", "event_id": "e"})])
        assert agent._maybe_flush_parked(dict(IDLE_PANE)) is False
        assert agent.prompt_queue.empty()

    def test_flush_refuses_busy_or_unknown_pane(self):
        agent = _bridge("961-861")
        self._parked(agent, [("10-0", {"prompt": "x", "event_id": "e"})])
        assert agent._maybe_flush_parked({"busy": True}) is False
        assert agent._maybe_flush_parked(None) is False
        assert agent.prompt_queue.empty()

    def test_flush_skips_when_a_real_turn_is_queued(self):
        agent = _bridge("961-861")
        agent.prompt_queue.put({"prompt": "vrai travail"})
        self._parked(agent, [("11-0", {"prompt": "x", "event_id": "e"})])
        assert agent._maybe_flush_parked(dict(IDLE_PANE)) is False

    def test_flush_respects_min_interval(self):
        agent = _bridge("961-861")
        agent._last_flush_ts = time.time()
        self._parked(agent, [("12-0", {"prompt": "x", "event_id": "e"})])
        assert agent._maybe_flush_parked(dict(IDLE_PANE)) is False

    def test_flush_without_pending_content_is_silent(self):
        agent = _bridge("961-861")
        agent.redis.hget.return_value = None
        agent.redis.xrange.return_value = []
        assert agent._maybe_flush_parked(dict(IDLE_PANE)) is False
        assert agent.prompt_queue.empty()


# ── 2. Dédup inter-streams : rapport + copie wake = UNE ligne ───────────


class TestCrossStreamDedup:
    def test_report_and_its_wake_copy_are_annexed_once(self):
        """publish_event.lua écrit le rapport dans :reports ET sa copie wake
        dans l'inbox (classée ensuite :supervision). Même report_id → une
        seule ligne dans l'annexe du même tour."""
        agent = _bridge("961-161")  # coordinateur : draine aussi :reports
        agent.redis.hget.return_value = None
        shared = {
            "schema": "ma.bus.v1",
            "report_id": "report-shared-1",
            "decision_id": "decision-shared-1",
            "from_agent": "961-361",
            "event": "MASTER_REPORT",
            "status": "PARTIAL",
            "summary": "déploiement fait, suite verte",
        }

        def pending(stream, **_kw):
            if stream.endswith(":reports"):
                return [("20-0", dict(shared, event_id="event-report-1"))]
            if stream.endswith(":supervision"):
                return [("20-0", dict(shared, event_id="event-wake-1",
                                      prompt="[RAPPORT PARTIAL] ..."))]
            return []

        agent.redis.xrange.side_effect = pending
        enriched = agent._attach_pending_reports({"prompt": "tour réel"})
        assert enriched["prompt"].count("déploiement fait, suite verte") == 1
        assert len(enriched["_annexed_refs"]) == 1

    def test_unrelated_entries_with_same_stream_id_are_both_kept(self):
        """Deux streams peuvent produire le même id brut à la même ms pour
        deux messages différents : l'id brut n'est pas une identité."""
        agent = _bridge("961-861")
        agent.redis.hget.return_value = None

        def pending(stream, **_kw):
            if stream.endswith(":control"):
                return [("30-0", {"from_agent": "watchdog",
                                  "event": "TERMINAL_PENDING",
                                  "detail": "silence observé",
                                  "event_id": "event-a"})]
            if stream.endswith(":supervision"):
                return [("30-0", {"from_agent": "961-561", "event": "STATUS",
                                  "prompt": "score en cours",
                                  "event_id": "event-b"})]
            return []

        agent.redis.xrange.side_effect = pending
        enriched = agent._attach_pending_reports({"prompt": "tour réel"})
        assert "silence observé" in enriched["prompt"]
        assert "score en cours" in enriched["prompt"]
        assert len(enriched["_annexed_refs"]) == 2


# ── 3. Accusés de lecture ────────────────────────────────────────────────


class TestReadReceipts:
    def test_receipts_cover_turn_message_and_annexed_entries(self, redis_client):
        agent = _bridge("962-362", redis_client)
        task = {
            "event_id": "event-read-own",
            "msg_id": "100-0",
            "_turn_id": "turn-read-1",
            "_annexed_refs": [
                {"stream": "agent:962-362:supervision", "msg_id": "40-0",
                 "event_id": "event-read-annex"},
                {"stream": "agent:962-362:control", "msg_id": "41-0",
                 "event_id": ""},
            ],
        }
        agent._publish_read_receipts(task)
        own = redis_client.hgetall("ma:bus:v1:read:event-read-own")
        assert own["read_by"] == "962-362"
        assert own["turn_id"] == "turn-read-1"
        assert int(own["read_at"]) > 0
        annex = redis_client.hgetall("ma:bus:v1:read:event-read-annex")
        assert annex["stream"] == "agent:962-362:supervision"
        fallback = redis_client.hgetall(
            "ma:bus:v1:read:stream:agent:962-362:control:41-0")
        assert fallback["read_by"] == "962-362"
        assert redis_client.hget("agent:962-362", "last_read_at")

    def test_no_receipt_without_identity_or_annex(self, redis_client):
        agent = _bridge("962-462", redis_client)
        before = len(list(redis_client.scan_iter(match="ma:bus:v1:read:*")))
        agent._publish_read_receipts({"prompt": "tour CLI sans enveloppe"})
        after = len(list(redis_client.scan_iter(match="ma:bus:v1:read:*")))
        assert after == before


# ── 4. Enveloppe conservée après la fin du tour (last_*) ─────────────────


class TestTurnEnvelopePersistence:
    def test_business_turn_envelope_survives_turn_end(self, redis_client):
        agent = _bridge("963-363", redis_client)
        agent._persist_turn_envelope({
            "_turn_id": "turn-env-1",
            "task_id": "task127",
            "cycle": "refonte",
            "correlation_id": "task127-plan-dev",
            "from_agent": "963-163",
            "owner": "963-363",
            "source": "redis",
        })
        state = redis_client.hgetall("agent:963-363")
        assert state["last_task_id"] == "task127"
        assert state["last_correlation"] == "task127-plan-dev"
        assert state["last_requester"] == "963-163"
        assert int(state["last_turn_ended_at"]) > 0

    def test_turn_without_business_envelope_never_erases_last(self, redis_client):
        agent = _bridge("963-363", redis_client)
        redis_client.hset("agent:963-363", mapping={
            "last_task_id": "task127", "last_correlation": "corr-x"})
        agent._persist_turn_envelope({
            "prompt": "flush", "source": "annex_flush"})
        assert redis_client.hget("agent:963-363", "last_task_id") == "task127"


# ── 5. resolve_context : repli last_* frais, jamais le tour ─────────────


def _report_args(from_agent, to_agent):
    return argparse.Namespace(
        kind="report", from_agent=from_agent, to_agent=to_agent,
        event="PARTIAL", source_turn_id="", task_id="", cycle="",
        correlation_id="", requester="", owner="", origin="",
        expected_event="")


class TestContextFallback:
    def test_fresh_last_envelope_attributes_post_turn_report(self, redis_client):
        import bus_protocol
        redis_client.delete("agent:964-364")
        redis_client.hset("agent:964-364", mapping={
            "last_turn_id": "turn-prev-1",
            "last_task_id": "task127",
            "last_cycle": "refonte",
            "last_correlation": "task127-plan-dev",
            "last_requester": "964-164",
            "last_owner": "964-364",
            "last_turn_origin": "redis",
            "last_turn_ended_at": int(time.time()) - 60,
        })
        ctx = bus_protocol.resolve_context(
            redis_client, _report_args("964-364", "964-164"))
        assert ctx["task_id"] == "task127"
        assert ctx["cycle"] == "refonte"
        assert ctx["correlation_id"] == "task127-plan-dev"
        assert ctx["requester"] == "964-164"
        # Le tour n'hérite JAMAIS : la dédup des rapports est par tour et
        # deux rapports post-tour doivent rester deux tours distincts.
        assert ctx["source_turn_id"] != "turn-prev-1"

    def test_stale_last_envelope_falls_back_to_unattributed(self, redis_client):
        import bus_protocol
        redis_client.delete("agent:964-464")
        redis_client.hset("agent:964-464", mapping={
            "last_task_id": "task-old",
            "last_correlation": "corr-old",
            "last_turn_ended_at": int(time.time()) - 999999,
        })
        ctx = bus_protocol.resolve_context(
            redis_client, _report_args("964-464", "964-164"))
        assert ctx["task_id"] == "unattributed"
        assert ctx["correlation_id"].startswith("rescue-")

    def test_current_envelope_still_wins_over_last(self, redis_client):
        import bus_protocol
        redis_client.delete("agent:964-564")
        redis_client.hset("agent:964-564", mapping={
            "current_task_id": "task-current",
            "current_cycle": "c9",
            "current_correlation": "corr-current",
            "last_task_id": "task-old",
            "last_cycle": "c1",
            "last_correlation": "corr-old",
            "last_turn_ended_at": int(time.time()) - 10,
        })
        ctx = bus_protocol.resolve_context(
            redis_client, _report_args("964-564", "964-164"))
        assert ctx["task_id"] == "task-current"
        assert ctx["correlation_id"] == "corr-current"


# ── 6. Watchdog : backlog non-lu et bridge périmé ────────────────────────


@pytest.fixture()
def watchdog(redis_client):
    import healthcheck
    return healthcheck.AgentWatchdog(redis_client)


class TestWatchdogUnread:
    def test_old_unread_parked_entry_raises_one_alert(self, redis_client, watchdog):
        agent_id = "965-865"
        redis_client.delete(f"agent:{agent_id}:supervision")
        redis_client.xadd(
            f"agent:{agent_id}:supervision",
            {"prompt": "jamais lu"}, id="1000-1")  # epoch ~1970 → très vieux
        before = redis_client.xlen("monitoring:alerts") \
            if redis_client.exists("monitoring:alerts") else 0
        assert watchdog._check_unread(agent_id) == "unread_backlog"
        assert int(redis_client.hget(
            f"agent:{agent_id}", "unread_backlog_s")) > 0
        alerts = redis_client.xrange("monitoring:alerts")
        assert len(alerts) == before + 1
        # Dédup par transition : un second cycle n'alerte pas de nouveau.
        assert watchdog._check_unread(agent_id) == "unread_backlog"
        assert redis_client.xlen("monitoring:alerts") == before + 1

    def test_backlog_behind_cursor_is_considered_read(self, redis_client, watchdog):
        agent_id = "965-765"
        redis_client.delete(f"agent:{agent_id}:supervision")
        redis_client.xadd(
            f"agent:{agent_id}:supervision",
            {"prompt": "déjà annexé"}, id="1000-1")
        redis_client.hset(
            f"agent:{agent_id}", "supervision_cursor", "1000-1")
        assert watchdog._check_unread(agent_id) is None
        assert int(redis_client.hget(
            f"agent:{agent_id}", "unread_backlog_s")) == 0


class TestWatchdogStaleBridge:
    def test_bridge_older_than_disk_is_flagged_once(self, redis_client, watchdog):
        import healthcheck
        agent_id = "965-665"
        disk = healthcheck.bridge_code_mtime_on_disk()
        redis_client.hset(
            f"agent:{agent_id}", "bridge_code_mtime", disk - 100000)
        assert watchdog._check_stale_bridge(agent_id) == "stale_bridge"
        assert watchdog._check_stale_bridge(agent_id) == "stale_bridge"
        alerts = [
            fields for _id, fields in redis_client.xrange("monitoring:alerts")
            if fields.get("agent_id") == agent_id]
        assert len(alerts) == 1
        assert "reload-bridge" in alerts[0]["message"]

    def test_current_bridge_is_not_flagged(self, redis_client, watchdog):
        import healthcheck
        agent_id = "965-565"
        redis_client.hset(
            f"agent:{agent_id}", "bridge_code_mtime",
            healthcheck.bridge_code_mtime_on_disk())
        assert watchdog._check_stale_bridge(agent_id) is None

    def test_legacy_bridge_without_fingerprint_is_ignored(self, redis_client, watchdog):
        assert watchdog._check_stale_bridge("965-465") is None


# ── 6b. Slot logique de terminal : dédup indépendante du tour (A9) ──────


def _terminal_args(signal, event="DONE", from_agent="967-367",
                   to_agent="967-167"):
    return argparse.Namespace(
        from_agent=from_agent, to_agent=to_agent, event=event, signal=signal,
        completion_maxlen=1000, inbox_maxlen=10000, ttl=604800)


def _terminal_ctx(turn, corr, task="task-slot", cycle="c1"):
    return {
        "source_turn_id": turn, "task_id": task, "cycle": cycle,
        "correlation_id": corr, "requester": "967-167", "owner": "967-367",
        "origin": "redis",
    }


def _count_by_corr(redis_client, stream, corr):
    return sum(
        1 for _id, fields in redis_client.xrange(stream)
        if fields.get("correlation_id") == corr)


class TestTerminalLogicalSlot:
    """Constat 22/08 (triangle 334) : un done.sh émis hors-tour puis rejoué
    dans le tour suivant portait deux source_turn_id → deux event_id → le
    rejeu strict passait pour un NOUVEAU terminal et le Master consommait
    deux tours pour la même livraison. Le slot logique
    (from,to,event,task,cycle,corr) ferme ce chemin quel que soit le tour."""

    def test_cross_turn_identical_replay_is_already_delivered(self, redis_client):
        import bus_protocol
        corr = "corr-slot-replay"
        first = bus_protocol.publish_terminal(
            redis_client, _terminal_args("DONE livraison X"),
            _terminal_ctx("turn-slot-a", corr))
        assert first[0] == "CREATED"
        replay = bus_protocol.publish_terminal(
            redis_client, _terminal_args("DONE livraison X"),
            _terminal_ctx("turn-slot-b", corr))  # AUTRE tour, même contenu
        assert replay[0] == "REPLAY"
        assert replay[2] == "ALREADY_DELIVERED"
        # Le rejeu est identifié par la livraison ORIGINALE.
        assert replay[4] == first[4]
        # Une seule écriture : ni completion ni inbox dupliquées.
        assert _count_by_corr(redis_client, "completion", corr) == 1
        assert _count_by_corr(
            redis_client, "agent:967-167:inbox", corr) == 1

    def test_cross_turn_divergent_replay_is_refused(self, redis_client):
        import bus_protocol
        corr = "corr-slot-conflict"
        first = bus_protocol.publish_terminal(
            redis_client, _terminal_args("DONE version 1"),
            _terminal_ctx("turn-slot-c", corr))
        assert first[0] == "CREATED"
        divergent = bus_protocol.publish_terminal(
            redis_client, _terminal_args("DONE version 2 corrigée"),
            _terminal_ctx("turn-slot-d", corr))
        assert divergent[0] == "CONFLICT"
        assert divergent[2] == "NOT_DELIVERED"
        assert _count_by_corr(redis_client, "completion", corr) == 1

    def test_new_cycle_reopens_the_slot(self, redis_client):
        import bus_protocol
        corr = "corr-slot-newcycle"
        assert bus_protocol.publish_terminal(
            redis_client, _terminal_args("DONE v1"),
            _terminal_ctx("turn-slot-e", corr, cycle="c1"))[0] == "CREATED"
        # Contenu différent + NOUVEAU cycle = nouveau slot → livré.
        reopened = bus_protocol.publish_terminal(
            redis_client, _terminal_args("DONE v2 après rework"),
            _terminal_ctx("turn-slot-f", corr, cycle="c2"))
        assert reopened[0] == "CREATED"
        assert _count_by_corr(redis_client, "completion", corr) == 2

    def test_same_turn_strict_replay_still_replays(self, redis_client):
        import bus_protocol
        corr = "corr-slot-sameturn"
        ctx = _terminal_ctx("turn-slot-g", corr)
        assert bus_protocol.publish_terminal(
            redis_client, _terminal_args("DONE idem"), ctx)[0] == "CREATED"
        replay = bus_protocol.publish_terminal(
            redis_client, _terminal_args("DONE idem"), ctx)
        assert replay[0] == "REPLAY"
        assert replay[2] == "ALREADY_DELIVERED"


class TestDoneShTurnIndependentDedup:
    """Bout-en-bout shell : le retry cross-tour de done.sh rend
    ALREADY_DELIVERED (exit 0) et le contenu divergent rend le refus
    NOT_DELIVERED (exit 3) avec la marche à suivre."""

    SENDER = "968-368"
    MASTER = "968-168"

    def _run_done(self, redis_client, turn, details):
        import subprocess
        connection = redis_client.connection_pool.connection_kwargs
        env = os.environ.copy()
        env.pop("TMUX", None)
        env.pop("TMUX_PANE", None)
        env.update({
            "REDIS_HOST": str(connection["host"]),
            "REDIS_PORT": str(connection["port"]),
            "REDIS_DB": str(connection.get("db", 0)),
            "REDIS_PASSWORD": "",
            "FROM_AGENT": self.SENDER,
            "TURN_ID": turn,
            "TASK_ID": "task-donesh",
            "CYCLE": "c7",
            "CORRELATION_ID": "corr-donesh-slot",
            "REQUESTER_ID": self.MASTER,
            "OWNER_ID": self.SENDER,
            "TURN_ORIGIN": "bridge",
        })
        return subprocess.run(
            ["bash", os.path.join(ROOT, "scripts", "done.sh"),
             self.MASTER, "DONE", details],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=15)

    def test_retry_from_another_turn_and_divergence(self, redis_client):
        first = self._run_done(
            redis_client, "turn-done-1", "fix livré, tests verts")
        assert first.returncode in (0, 2), first.stderr  # 2 = ORPHANED (pas de tmux)
        retry = self._run_done(
            redis_client, "turn-done-2", "fix livré, tests verts")
        assert retry.returncode == 0, retry.stderr
        assert "state=ALREADY_DELIVERED" in retry.stdout
        divergent = self._run_done(
            redis_client, "turn-done-3", "fix livré, tests verts, v2")
        assert divergent.returncode == 3
        assert "state=NOT_DELIVERED" in divergent.stderr
        assert "CYCLE/CORR" in divergent.stderr
        # Une seule livraison réelle dans completion.
        assert _count_by_corr(
            redis_client, "completion", "corr-donesh-slot") == 1


# ── 7. Composer orphelin : saisi mais jamais soumis ─────────────────────


class TestComposerOrphan:
    PANE = "sortie précédente\n❯ redémarre voice-agent et vérifie le duplex\n"

    def test_stable_unsubmitted_text_alerts_once(self):
        agent = _bridge("966-266")
        pane_state = dict(IDLE_PANE)
        assert agent._check_composer_orphan(self.PANE, pane_state) is None
        agent._composer_orphan["since"] = time.time() - 9999
        detail = agent._check_composer_orphan(self.PANE, pane_state)
        assert detail and "composer" in detail
        assert agent.redis.xadd.called
        # Une seule alerte tant que le texte ne change pas.
        assert agent._check_composer_orphan(self.PANE, pane_state) is None

    def test_empty_composer_resets_state(self):
        agent = _bridge("966-266")
        agent._check_composer_orphan(self.PANE, dict(IDLE_PANE))
        agent._composer_orphan["since"] = time.time() - 9999
        assert agent._check_composer_orphan(
            "travail\n❯ \n", dict(IDLE_PANE)) is None
        assert agent._composer_orphan["text"] == ""

    def test_busy_pane_never_alerts(self):
        agent = _bridge("966-266")
        agent._composer_orphan = {
            "text": "x", "since": time.time() - 9999, "alerted": False}
        assert agent._check_composer_orphan(
            self.PANE, {"busy": True}) is None
