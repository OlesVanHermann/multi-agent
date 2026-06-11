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
    agent.metrics = None
    agent.redis = MagicMock()
    agent._log = MagicMock()
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

    def test_response_message_acked_immediately(self):
        agent = _make_agent()
        agent._handle_inbox_message("2-0", {
            "type": "response", "from_agent": "200",
            "response": "result", "complete": "true"})

        task = agent.prompt_queue.get(timeout=1)
        assert "[FROM 200]" in task['prompt']
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

        agent._listen_redis()

        # Drain '0' d'abord (jusqu'à vide), puis lecture '>'
        assert calls[0] == '0'
        assert '>' in calls
        assert calls.index('>') > calls.index('0')
        task = agent.prompt_queue.get(timeout=1)
        assert task['prompt'] == "pending msg"
        assert task['ack_id'] == "9-0"
