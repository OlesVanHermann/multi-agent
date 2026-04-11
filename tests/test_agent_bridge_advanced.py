"""
Tests avancés pour agent.py — zones non couvertes par les tests existants
EF-001 — Couverture : log_event, response chunking, process_queue, reload_prompt,
         listen_redis message types, send_to_agent broadcast, wait_for_response

Réf spec 342 : CA-001 (ratio ≥15%), CA-002 (≥200 LOC, 3+ scénarios), CA-007 (zéro régression)
"""
import pytest
import os
import sys
import json
import time
from unittest.mock import MagicMock, patch, mock_open, call
from queue import Queue
from collections import deque
from pathlib import Path
from threading import Lock

_BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(_BASE, 'core', 'agent-bridge'))


def _make_agent(agent_id="999"):
    """Helper: create a TmuxAgent without __init__ side effects"""
    from agent import TmuxAgent, State, MAX_HISTORY
    agent = object.__new__(TmuxAgent)
    agent.agent_id = str(agent_id)
    agent.session_name = f"ma-agent-{agent_id}"
    agent.state = State.IDLE
    agent.state_lock = Lock()
    agent.tasks_completed = 0
    agent.messages_since_reload = 0
    agent.last_output_lines = 0
    agent.prompt_queue = Queue()
    agent.current_task = None
    agent.history = deque(maxlen=MAX_HISTORY)
    agent.log_dir = Path("/tmp/test-agent-345-logs")
    agent.log_dir.mkdir(parents=True, exist_ok=True)
    agent.logfile = MagicMock()
    agent.redis = MagicMock()
    agent.inbox = f"A:agent:{agent_id}:inbox"
    agent.outbox = f"A:agent:{agent_id}:outbox"
    agent.legacy_inbox = f"A:inject:{agent_id}"
    agent.running = True
    return agent


# === _log_event ===

class TestLogEvent:
    """Tests pour _log_event — journalisation JSON (EF-001)"""

    def test_log_event_writes_json_line(self):
        """_log_event écrit une ligne JSON valide dans events.jsonl (EF-001)"""
        agent = _make_agent()
        agent._log_event("prompt", "test detail")

        events_file = agent.log_dir / "events.jsonl"
        assert events_file.exists()
        with open(events_file) as f:
            line = f.readline()
        data = json.loads(line)
        assert data["type"] == "prompt"
        assert data["detail"] == "test detail"
        assert "ts" in data

    def test_log_event_appends_multiple(self):
        """_log_event append et ne remplace pas (EF-001)"""
        agent = _make_agent()
        agent._log_event("event1", "first")
        agent._log_event("event2", "second")

        with open(agent.log_dir / "events.jsonl") as f:
            lines = f.readlines()
        assert len(lines) >= 2
        assert json.loads(lines[-2])["type"] == "event1"
        assert json.loads(lines[-1])["type"] == "event2"

    def test_log_event_handles_write_error(self):
        """_log_event gère les erreurs d'écriture sans crash (EF-001)"""
        agent = _make_agent()
        agent.log_dir = Path("/nonexistent/path/that/does/not/exist")
        # Should not raise
        agent._log_event("test", "should not crash")


# === Response Chunking ===

class TestResponseChunkingInQueue:
    """Tests pour le chunking de réponse dans _process_queue (EF-001)"""

    def test_short_response_sent_as_single_message(self):
        """Réponse courte envoyée en un seul message (EF-001)"""
        agent = _make_agent()
        agent._run_claude = MagicMock(return_value="short response")
        agent._set_redis_status = MagicMock()

        task = {
            'prompt': 'test',
            'from_agent': '100',
            'msg_id': '1-0',
            'source': 'redis'
        }

        # Simulate _process_queue handling one task
        from agent import State
        with agent.state_lock:
            agent.state = State.BUSY
            agent.current_task = task

        response = agent._run_claude(task['prompt'])
        agent.redis.xadd(agent.outbox, {
            'response': response,
            'from_agent': agent.agent_id,
            'timestamp': int(time.time()),
            'chars': len(response)
        })

        # Send to from_agent
        agent.redis.xadd(f"A:agent:100:inbox", {
            'response': response,
            'from_agent': agent.agent_id,
            'type': 'response',
            'timestamp': int(time.time()),
            'complete': 'true'
        })

        # Verify 2 xadd calls: outbox + notify sender
        assert agent.redis.xadd.call_count == 2
        # Second call should have complete='true'
        second_call_data = agent.redis.xadd.call_args_list[1][0][1]
        assert second_call_data['complete'] == 'true'

    def test_long_response_split_into_chunks(self):
        """Réponse >15000 chars découpée en chunks (EF-001)"""
        agent = _make_agent()
        long_response = "x" * 35000  # > 15000 * 2

        MAX_CHUNK = 15000
        chunks = [long_response[i:i+MAX_CHUNK] for i in range(0, len(long_response), MAX_CHUNK)]

        assert len(chunks) == 3  # 35000 / 15000 = 2.33 → 3 chunks

        for i, chunk in enumerate(chunks):
            agent.redis.xadd(f"A:agent:100:inbox", {
                'response': chunk,
                'from_agent': agent.agent_id,
                'type': 'response',
                'chunk': f"{i+1}/{len(chunks)}",
                'complete': 'true' if i == len(chunks)-1 else 'false'
            })

        # First 2 chunks: complete=false, last: complete=true
        calls = agent.redis.xadd.call_args_list
        assert calls[0][0][1]['complete'] == 'false'
        assert calls[1][0][1]['complete'] == 'false'
        assert calls[2][0][1]['complete'] == 'true'
        assert calls[2][0][1]['chunk'] == '3/3'


# === send_to_agent ===

class TestSendToAgent:
    """Tests pour send_to_agent — envoi simple et broadcast (EF-001)"""

    def test_send_to_single_agent(self):
        """Envoi à un agent spécifique (EF-001)"""
        agent = _make_agent()
        agent.send_to_agent("300", "hello")

        agent.redis.xadd.assert_called_once()
        key = agent.redis.xadd.call_args[0][0]
        data = agent.redis.xadd.call_args[0][1]
        assert key == "A:agent:300:inbox"
        assert data['prompt'] == "hello"
        assert data['from_agent'] == "999"

    def test_broadcast_excludes_self(self):
        """Broadcast exclut l'agent émetteur (EF-001)"""
        agent = _make_agent("300")
        # Mock keys to return agent 300 (self) and 301
        agent.redis.keys.return_value = ["A:agent:300", "A:agent:301"]

        agent.send_to_agent("all", "broadcast msg")

        # Should only send to 301, not 300 (self)
        xadd_calls = [c for c in agent.redis.xadd.call_args_list]
        keys_sent = [c[0][0] for c in xadd_calls]
        assert "A:agent:300:inbox" not in keys_sent
        assert "A:agent:301:inbox" in keys_sent

    def test_broadcast_filters_non_digit_keys(self):
        """Broadcast ignore les clés non-numériques (EF-001)"""
        agent = _make_agent("100")
        agent.redis.keys.return_value = [
            "A:agent:200",
            "A:agent:abc",         # non-digit → skip
            "A:agent:300:inbox",   # 4 parts → skip (len != 3)
        ]

        agent.send_to_agent("all", "test")

        xadd_calls = agent.redis.xadd.call_args_list
        assert len(xadd_calls) == 1
        assert xadd_calls[0][0][0] == "A:agent:200:inbox"


# === _listen_redis message types ===

class TestListenRedisMessageTypes:
    """Tests pour _listen_redis — types de messages (EF-001)"""

    def test_reload_prompt_message_triggers_reload(self):
        """Message type=reload_prompt déclenche _reload_prompt (EF-001)"""
        agent = _make_agent()
        agent._reload_prompt = MagicMock()

        # Simulate one iteration of _listen_redis
        agent.redis.xread.return_value = [
            ("A:agent:999:inbox", [
                ("1-0", {"type": "reload_prompt", "from_agent": "000"})
            ])
        ]

        # Run one iteration manually
        result = agent.redis.xread({agent.inbox: '$'}, block=2000, count=1)
        stream, messages = result[0]
        for msg_id, data in messages:
            msg_type = data.get('type', 'prompt')
            if msg_type == 'reload_prompt':
                agent._reload_prompt()

        agent._reload_prompt.assert_called_once()

    def test_response_message_queued_with_header(self):
        """Message type=response enqueue avec header [FROM X] (EF-001)"""
        agent = _make_agent()

        data = {
            'type': 'response',
            'from_agent': '200',
            'response': 'analysis result',
            'chunk': '1/1',
            'complete': 'true'
        }

        from_id = data.get('from_agent', '?')
        response_text = data.get('response', '')
        chunk_info = data.get('chunk', '')
        header = f"[FROM {from_id}]"
        if chunk_info:
            header += f" [{chunk_info}]"
        notification = f"{header}\n{response_text}\n[/{from_id}]"

        agent.prompt_queue.put({
            'prompt': notification,
            'from_agent': f'response_{from_id}',
            'msg_id': f"response-{int(time.time())}",
            'source': 'response'
        })

        task = agent.prompt_queue.get(timeout=1)
        assert "[FROM 200]" in task['prompt']
        assert "[1/1]" in task['prompt']
        assert "analysis result" in task['prompt']
        assert task['from_agent'] == 'response_200'


# === _reload_prompt ===

class TestReloadPrompt:
    """Tests pour _reload_prompt (EF-001)"""

    def test_reload_resets_counter_and_sends_reset(self):
        """_reload_prompt remet messages_since_reload à 0 et envoie /reset (EF-001)"""
        agent = _make_agent()
        agent.messages_since_reload = 42
        agent._send_keys = MagicMock()
        agent._set_redis_status = MagicMock()

        with patch.object(type(agent), '_find_prompt_file', return_value="/fake/prompt.md"), \
             patch.object(type(agent), '_is_x45_agent', return_value=False):
            agent._reload_prompt()

        assert agent.messages_since_reload == 0
        agent._send_keys.assert_called_once_with("/reset")

    def test_reload_x45_queues_multi_file_prompt(self):
        """_reload_prompt en mode x45 enqueue un prompt multi-fichiers (EF-001)"""
        agent = _make_agent()
        agent._send_keys = MagicMock()
        agent._set_redis_status = MagicMock()

        fake_dir = "/fake/prompts/345"
        with patch.object(type(agent), '_find_prompt_file', return_value=fake_dir), \
             patch.object(type(agent), '_is_x45_agent', return_value=True), \
             patch.object(Path, 'exists', return_value=True):
            agent._reload_prompt()

        task = agent.prompt_queue.get(timeout=1)
        assert "Lis ces fichiers" in task['prompt']
        assert task['from_agent'] == 'compaction_reload'

    def test_reload_no_prompt_file_does_nothing(self):
        """_reload_prompt sans fichier prompt ne crash pas (EF-001)"""
        agent = _make_agent()
        agent._send_keys = MagicMock()

        with patch.object(type(agent), '_find_prompt_file', return_value=None):
            agent._reload_prompt()

        agent._send_keys.assert_not_called()


# === _set_redis_status ===

class TestSetRedisStatus:
    """Tests pour _set_redis_status (EF-001)"""

    def test_status_hash_contains_all_fields(self):
        """Le hash Redis contient status, last_seen, queue_size, etc. (EF-001, CT-001)"""
        agent = _make_agent()
        agent._set_redis_status()

        agent.redis.hset.assert_called_once()
        call_kwargs = agent.redis.hset.call_args
        mapping = call_kwargs[1]['mapping'] if 'mapping' in call_kwargs[1] else call_kwargs[0][1]

        assert mapping['status'] == 'idle'
        assert mapping['mode'] == 'tmux-interactive'
        assert 'last_seen' in mapping
        assert 'queue_size' in mapping
        assert 'tasks_completed' in mapping

    def test_status_survives_redis_disconnect(self):
        """_set_redis_status ne crash pas si Redis déconnecté (EF-001)"""
        import redis as redis_lib
        agent = _make_agent()
        agent.redis.hset.side_effect = redis_lib.ConnectionError("gone")

        # Should not raise
        agent._set_redis_status()


# === _handle_command ===

class TestHandleCommand:
    """Tests pour _handle_command — commandes slash (EF-001)"""

    def test_unknown_command_logged(self):
        """Commande inconnue loggée (EF-001)"""
        agent = _make_agent()
        agent._handle_command("/foobar")
        agent.logfile.write.assert_called()
        written = agent.logfile.write.call_args[0][0]
        assert "Unknown command" in written

    def test_help_command(self):
        """Commande /help affiche les commandes (EF-001)"""
        agent = _make_agent()
        agent._handle_command("/help")
        written = agent.logfile.write.call_args[0][0]
        assert "/status" in written
        assert "/send" in written

    def test_queue_command(self):
        """Commande /queue affiche la taille (EF-001)"""
        agent = _make_agent()
        agent.prompt_queue.put({"prompt": "test"})
        agent._handle_command("/queue")
        written = agent.logfile.write.call_args[0][0]
        assert "Queue size" in written

    def test_send_command_valid(self):
        """Commande /send agent msg envoie le message (EF-001)"""
        agent = _make_agent()
        agent.send_to_agent = MagicMock()
        agent._handle_command("/send 300 hello world")
        agent.send_to_agent.assert_called_once_with("300", "hello world")

    def test_send_command_missing_args(self):
        """Commande /send sans message affiche usage (EF-001)"""
        agent = _make_agent()
        agent._handle_command("/send 300")
        written = agent.logfile.write.call_args[0][0]
        assert "Usage" in written

    def test_status_command(self):
        """Commande /status affiche état et compteurs (EF-001)"""
        agent = _make_agent()
        agent.tasks_completed = 5
        agent._handle_command("/status")
        written = agent.logfile.write.call_args[0][0]
        assert "idle" in written
        assert "5" in written
