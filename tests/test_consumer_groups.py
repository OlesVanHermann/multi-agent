"""
A4 — Consumer groups Redis (XREADGROUP + XACK) dans agent.py

Vérifie : création idempotente du groupe, routage des messages inbox
(prompt → queue avec ack_id, response/reload → XACK immédiat), et
acquittement uniquement après publication de la réponse.
"""
import os
import sys
import re
import time
from queue import Queue
from unittest.mock import MagicMock

import pytest

_HERE = os.path.dirname(os.path.realpath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
sys.path.insert(0, os.path.join(_REPO_ROOT, 'scripts', 'agent-bridge'))

try:
    import redis as _real_redis_mod
    _RedisResponseError = _real_redis_mod.ResponseError
except (ImportError, AttributeError):
    class _RedisResponseError(Exception):
        pass


def _make_agent():
    from agent import TmuxAgent
    agent = object.__new__(TmuxAgent)
    agent.agent_id = "300"
    agent.inbox = "A:agent:300:inbox"
    agent.outbox = "A:agent:300:outbox"
    agent.group = "bridge"
    agent.consumer = "agent-300"
    agent.running = True
    agent.prompt_queue = Queue()
    agent._inflight_ids = set()
    agent._inflight_lock = __import__("threading").Lock()
    agent.metrics = None
    agent.redis = MagicMock()
    agent._log = MagicMock()
    agent._log_event = MagicMock()
    agent._wal = MagicMock()
    return agent


class TestEnsureGroup:
    def test_creates_group_with_mkstream(self):
        agent = _make_agent()
        agent._ensure_group()
        agent.redis.xgroup_create.assert_called_once_with(
            agent.inbox, "bridge", id='$', mkstream=True)

    def test_busygroup_is_ignored(self):
        agent = _make_agent()
        agent.redis.xgroup_create.side_effect = _RedisResponseError(
            "BUSYGROUP Consumer Group name already exists")
        agent._ensure_group()  # ne doit pas lever

    def test_other_response_error_raises(self):
        agent = _make_agent()
        agent.redis.xgroup_create.side_effect = _RedisResponseError("WRONGTYPE")
        with pytest.raises(_RedisResponseError):
            agent._ensure_group()


class TestHandleInboxMessage:
    def test_prompt_queued_with_ack_id_not_acked_yet(self):
        agent = _make_agent()
        agent._handle_inbox_message("1-0", {"prompt": "hello", "from_agent": "100"})

        task = agent.prompt_queue.get(timeout=1)
        assert task['ack_id'] == "1-0"
        assert task['from_agent'] == "100"
        agent.redis.xack.assert_not_called()

    def test_response_transcript_acked_without_tui_injection(self):
        agent = _make_agent()
        agent._handle_inbox_message("2-0", {
            "type": "response", "from_agent": "200",
            "response": "result", "complete": "true"})

        assert agent.prompt_queue.empty()
        agent.redis.xack.assert_called_once_with(agent.inbox, "bridge", "2-0")

    def test_reload_prompt_acked_immediately(self):
        agent = _make_agent()
        agent._reload_prompt = MagicMock()
        agent._handle_inbox_message("3-0", {"type": "reload_prompt", "from_agent": "000"})

        agent._reload_prompt.assert_called_once()
        agent.redis.xack.assert_called_once_with(agent.inbox, "bridge", "3-0")

    def test_trimmed_pending_entry_acked(self):
        agent = _make_agent()
        agent._handle_inbox_message("4-0", None)
        agent.redis.xack.assert_called_once_with(agent.inbox, "bridge", "4-0")
        assert agent.prompt_queue.empty()

    def test_unknown_type_acked(self):
        agent = _make_agent()
        agent._handle_inbox_message("5-0", {"type": "whatever", "x": "y"})
        agent.redis.xack.assert_called_once_with(agent.inbox, "bridge", "5-0")
        assert agent.prompt_queue.empty()

    def test_invalid_from_agent_sanitized(self):
        agent = _make_agent()
        agent._handle_inbox_message("6-0", {
            "prompt": "hi", "from_agent": "; rm -rf /"})
        task = agent.prompt_queue.get(timeout=1)
        assert task['from_agent'] == 'unknown'


class TestAckAfterPublish:
    def test_ack_inbox_calls_xack(self):
        agent = _make_agent()
        agent._ack_inbox("7-0")
        agent.redis.xack.assert_called_once_with(agent.inbox, "bridge", "7-0")

    def test_ack_inbox_swallows_errors(self):
        agent = _make_agent()
        agent.redis.xack.side_effect = Exception("down")
        agent._ack_inbox("8-0")  # ne doit pas lever


class TestPendingDrain:
    def test_startup_drains_pending_then_reads_new(self):
        """Reprise après crash : les messages pendants (id '0') sont rejoués
        avant la lecture des nouveaux (id '>')."""
        agent = _make_agent()
        calls = []

        def mock_xreadgroup(group, consumer, streams, **kwargs):
            stream_id = list(streams.values())[0]
            calls.append(stream_id)
            if stream_id == '0' and calls.count('0') == 1:
                return [(agent.inbox, [("9-0", {"prompt": "pending msg", "from_agent": "100"})])]
            if stream_id == '0':
                return [(agent.inbox, [])]
            agent.running = False
            return None

        agent.redis.xreadgroup.side_effect = mock_xreadgroup

        import threading
        t = threading.Thread(target=agent._listen_redis, daemon=True)
        t.start()
        deadline = time.time() + 2
        while agent.prompt_queue.empty() and time.time() < deadline:
            time.sleep(0.01)
        agent.running = False
        t.join(timeout=2)

        # Un seul pending est reclame. Les nouveaux restent dans Redis tant
        # que ce message n'est pas publie puis XACK.
        assert calls[0] == '0'
        assert '>' not in calls
        task = agent.prompt_queue.get(timeout=1)
        assert task['prompt'] == "pending msg"
        assert task['ack_id'] == "9-0"


# === G2 — Reprise après crash sur VRAI Redis (sémantique du protocole) ===

import shutil  # noqa: E402
import socket  # noqa: E402
import subprocess  # noqa: E402


@pytest.fixture(scope="module")
def real_redis():
    """redis-server privé éphémère (port libre, sans persistance)."""
    if shutil.which("redis-server") is None:
        pytest.skip("redis-server absent")
    redis_mod = pytest.importorskip("redis")
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    proc = subprocess.Popen(
        ["redis-server", "--port", str(port), "--bind", "127.0.0.1",
         "--save", "", "--appendonly", "no"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    client = redis_mod.Redis(host="127.0.0.1", port=port, decode_responses=True)
    deadline = time.time() + 10
    while True:
        try:
            client.ping()
            break
        except redis_mod.exceptions.ConnectionError:
            if time.time() > deadline:
                proc.terminate()
                pytest.skip("redis-server n'a pas démarré")
            time.sleep(0.1)
    yield client
    proc.terminate()
    proc.wait(timeout=5)


class TestCrashRecoveryRealRedis:
    """G2 — protocole de reprise du bridge (groupe 'bridge', drain id '0')
    vérifié contre un vrai Redis : un message lu mais non acquitté avant un
    crash est rejoué au redémarrage ; un message acquitté ne l'est jamais
    (pas de doublon)."""

    def test_unacked_replayed_acked_not_duplicated(self, real_redis):
        r = real_redis
        stream, group, consumer = "G2:agent:300:inbox", "bridge", "agent-300"
        r.xgroup_create(stream, group, id='$', mkstream=True)

        id1 = r.xadd(stream, {"prompt": "tache 1", "from_agent": "cli"})
        id2 = r.xadd(stream, {"prompt": "tache 2", "from_agent": "cli"})

        # Run 1 : le bridge lit les deux messages, n'acquitte que le premier
        # (réponse publiée), puis crashe avant d'acquitter le second.
        result = r.xreadgroup(group, consumer, {stream: '>'}, count=10)
        read_ids = [mid for mid, _ in result[0][1]]
        assert read_ids == [id1, id2]
        r.xack(stream, group, id1)

        # Run 2 (redémarrage) : drain des pendants avec id '0'
        # (même protocole que _listen_redis) — seul le non-acquitté revient.
        pending = r.xreadgroup(group, consumer, {stream: '0'}, count=10)
        pending_msgs = pending[0][1]
        assert [mid for mid, _ in pending_msgs] == [id2], \
            "le message non acquitté doit être rejoué, l'acquitté jamais (doublon)"
        assert pending_msgs[0][1]["prompt"] == "tache 2"

        # Retraitement puis ack → plus rien en attente
        r.xack(stream, group, id2)
        drained = r.xreadgroup(group, consumer, {stream: '0'}, count=10)
        assert not drained or not drained[0][1]
        assert r.xpending(stream, group)["pending"] == 0

    def test_messages_before_group_creation_not_consumed(self, real_redis):
        """Le groupe est créé avec id='$' : seuls les messages postérieurs
        sont consommés (comportement assumé du bridge, A4)."""
        r = real_redis
        stream, group = "G2:agent:301:inbox", "bridge"
        r.xadd(stream, {"prompt": "avant groupe", "from_agent": "cli"})
        r.xgroup_create(stream, group, id='$', mkstream=True)
        after = r.xadd(stream, {"prompt": "apres groupe", "from_agent": "cli"})

        result = r.xreadgroup(group, "agent-301", {stream: '>'}, count=10)
        assert [mid for mid, _ in result[0][1]] == [after]
