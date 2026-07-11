"""
F2 — Corrélation requêtes/réponses (correlation_id)

send_and_wait ne doit retenir que la réponse portant SON correlation_id ;
les réponses sans correlation_id (bridges anciens) restent acceptées.
"""
import os
import sys
import time
import threading
from queue import Queue
from unittest.mock import MagicMock

import pytest

_HERE = os.path.dirname(os.path.realpath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
sys.path.insert(0, os.path.join(_REPO_ROOT, 'scripts', 'agent-bridge'))

PREFIX = "TESTF2"


def _redis_or_skip():
    try:
        import redis
        r = redis.Redis(host='localhost', port=6379,
                        password=os.environ.get('REDIS_PASSWORD') or None,
                        decode_responses=True, socket_connect_timeout=2)
        r.ping()
        return r
    except Exception:
        pytest.skip("Redis indisponible")


class TestBridgePropagation:
    def test_inbox_correlation_id_lands_in_queue_task(self):
        from agent import TmuxAgent
        agent = object.__new__(TmuxAgent)
        agent.agent_id = "300"
        agent.inbox = "A:agent:300:inbox"
        agent.group = "bridge"
        agent.consumer = "agent-300"
        agent.prompt_queue = Queue()
        agent._inflight_ids = set()
        agent._inflight_lock = __import__("threading").Lock()
        agent.metrics = None
        agent.redis = MagicMock()
        agent._log = MagicMock()

        agent._handle_inbox_message("1-0", {
            "prompt": "hello", "from_agent": "100",
            "correlation_id": "abc-123"})

        task = agent.prompt_queue.get(timeout=1)
        assert task['correlation_id'] == "abc-123"

    def test_missing_correlation_id_defaults_empty(self):
        from agent import TmuxAgent
        agent = object.__new__(TmuxAgent)
        agent.agent_id = "300"
        agent.inbox = "A:agent:300:inbox"
        agent.group = "bridge"
        agent.consumer = "agent-300"
        agent.prompt_queue = Queue()
        agent._inflight_ids = set()
        agent._inflight_lock = __import__("threading").Lock()
        agent.metrics = None
        agent.redis = MagicMock()
        agent._log = MagicMock()

        agent._handle_inbox_message("2-0", {"prompt": "hi", "from_agent": "100"})
        task = agent.prompt_queue.get(timeout=1)
        assert task['correlation_id'] == ''


class TestSendAndWaitCorrelation:
    def _setup_orchestrator(self, monkeypatch, r):
        import orchestrator as orch
        monkeypatch.setattr(orch, 'MA_PREFIX', PREFIX)
        monkeypatch.setattr(orch, 'r', r)
        return orch

    def test_wrong_correlation_skipped_right_one_returned(self, monkeypatch):
        """Concurrence : la réponse d'une AUTRE requête ne doit pas être prise."""
        r = _redis_or_skip()
        orch = self._setup_orchestrator(monkeypatch, r)
        inbox = f"{PREFIX}:agent:300:inbox"
        outbox = f"{PREFIX}:agent:300:outbox"
        r.delete(inbox, outbox)

        result = {}

        def caller():
            try:
                result['response'] = orch.send_and_wait('300', 'task A', timeout=15)
            except Exception as e:
                result['error'] = e

        t = threading.Thread(target=caller, daemon=True)
        t.start()
        try:
            # Attendre que la requête (avec son correlation_id) soit émise
            deadline = time.time() + 10
            entries = []
            while time.time() < deadline and not entries:
                entries = r.xrange(inbox)
                time.sleep(0.05)
            assert entries, "send_and_wait n'a rien émis"
            _, req = entries[0]
            cid = req['correlation_id']
            assert cid

            time.sleep(0.3)  # laisser le caller entrer dans xread('$')

            # Réponse d'une autre requête (mauvais correlation_id) — ignorée
            r.xadd(outbox, {'response': 'WRONG answer',
                            'from_agent': '300',
                            'correlation_id': 'other-request',
                            'timestamp': int(time.time())})
            # Puis la bonne
            r.xadd(outbox, {'response': 'RIGHT answer',
                            'from_agent': '300',
                            'correlation_id': cid,
                            'timestamp': int(time.time())})

            t.join(timeout=15)
            assert not t.is_alive()
            assert result.get('response') == 'RIGHT answer'
        finally:
            r.delete(inbox, outbox)

    def test_legacy_response_without_correlation_accepted(self, monkeypatch):
        """Compat : un bridge ancien n'écho pas correlation_id → accepté."""
        r = _redis_or_skip()
        orch = self._setup_orchestrator(monkeypatch, r)
        inbox = f"{PREFIX}:agent:301:inbox"
        outbox = f"{PREFIX}:agent:301:outbox"
        r.delete(inbox, outbox)

        result = {}

        def caller():
            try:
                result['response'] = orch.send_and_wait('301', 'task B', timeout=15)
            except Exception as e:
                result['error'] = e

        t = threading.Thread(target=caller, daemon=True)
        t.start()
        try:
            deadline = time.time() + 10
            while time.time() < deadline and not r.xrange(inbox):
                time.sleep(0.05)
            time.sleep(0.3)

            r.xadd(outbox, {'response': 'legacy answer',
                            'from_agent': '301',
                            'timestamp': int(time.time())})

            t.join(timeout=15)
            assert not t.is_alive()
            assert result.get('response') == 'legacy answer'
        finally:
            r.delete(inbox, outbox)
