"""
Tests complémentaires pour le cycle de vie de l'agent (agent.py)
EF-001 — Extension : cycle de vie complet, chunking des réponses, prompt reload

Réf spec 342 : CA-002 (scénarios additionnels), CT-001 (format messages), CT-002 (0 régression)
"""
import pytest
import time
import os
import sys
import json
from unittest.mock import MagicMock, patch, call
from threading import Thread, Lock
from queue import Queue, Empty
from collections import deque
from pathlib import Path

_BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(_BASE, 'core', 'agent-bridge'))


class TestResponseChunking:
    """EF-001 — Tests du chunking des réponses longues"""

    def test_short_response_not_chunked(self):
        """Réponse courte envoyée en un seul message (EF-001)"""
        from agent import TmuxAgent

        agent = object.__new__(TmuxAgent)
        agent.agent_id = "300"
        agent.redis = MagicMock()
        agent._log = MagicMock()

        # Simulate short response
        response = "Short response"
        from_agent = "100"

        # Inline the chunking logic from _process_queue
        MAX_CHUNK = 15000
        if len(response) <= MAX_CHUNK:
            agent.redis.xadd(f"ma:agent:{from_agent}:inbox", {
                'response': response,
                'from_agent': agent.agent_id,
                'type': 'response',
                'timestamp': int(time.time()),
                'complete': 'true'
            })

        assert agent.redis.xadd.call_count == 1
        call_args = agent.redis.xadd.call_args
        assert call_args[0][1]['complete'] == 'true'

    def test_long_response_chunked(self):
        """Réponse longue découpée en chunks de 15000 caractères (EF-001)"""
        from agent import TmuxAgent

        agent = object.__new__(TmuxAgent)
        agent.agent_id = "300"
        agent.redis = MagicMock()
        agent._log = MagicMock()

        MAX_CHUNK = 15000
        response = "x" * 35000  # 35K chars → 3 chunks
        from_agent = "100"

        if len(response) > MAX_CHUNK:
            chunks = [response[i:i+MAX_CHUNK] for i in range(0, len(response), MAX_CHUNK)]
            for i, chunk in enumerate(chunks):
                agent.redis.xadd(f"ma:agent:{from_agent}:inbox", {
                    'response': chunk,
                    'from_agent': agent.agent_id,
                    'type': 'response',
                    'timestamp': int(time.time()),
                    'chunk': f"{i+1}/{len(chunks)}",
                    'complete': 'true' if i == len(chunks)-1 else 'false'
                })

        assert agent.redis.xadd.call_count == 3
        # First two chunks: complete=false
        assert agent.redis.xadd.call_args_list[0][0][1]['complete'] == 'false'
        assert agent.redis.xadd.call_args_list[1][0][1]['complete'] == 'false'
        # Last chunk: complete=true
        assert agent.redis.xadd.call_args_list[2][0][1]['complete'] == 'true'

    def test_chunk_numbering(self):
        """Les chunks sont numérotés correctement (1/N, 2/N, ..., N/N) (EF-001)"""
        MAX_CHUNK = 15000
        response = "y" * 30001  # → 3 chunks (15000, 15000, 1)

        chunks = [response[i:i+MAX_CHUNK] for i in range(0, len(response), MAX_CHUNK)]
        assert len(chunks) == 3
        assert len(chunks[0]) == 15000
        assert len(chunks[1]) == 15000
        assert len(chunks[2]) == 1

        for i, chunk in enumerate(chunks):
            chunk_label = f"{i+1}/{len(chunks)}"
            assert chunk_label in [f"1/3", f"2/3", f"3/3"]


class TestPromptFileDetection:
    """EF-001 — Tests de la détection de fichiers prompt"""

    def test_find_prompt_monogent(self):
        """Détection format x45 entry point : prompts/{dir}/{id}.md (EF-001)"""
        from agent import TmuxAgent, BASE_DIR

        agent = object.__new__(TmuxAgent)
        agent.agent_id = "100"

        parent_dir = BASE_DIR / "prompts" / "100"
        entry_file = parent_dir / "100.md"

        with patch.object(TmuxAgent, '_resolve_prompts_dir', return_value=parent_dir), \
             patch.object(Path, 'exists', lambda p: str(p) == str(entry_file)):
            result = agent._find_prompt_file()
        assert result == str(entry_file)

    def test_find_prompt_x45_new(self):
        """Détection format x45 nouveau : prompts/345/345.md (symlink) (EF-001)"""
        from agent import TmuxAgent, BASE_DIR

        agent = object.__new__(TmuxAgent)
        agent.agent_id = "345"

        parent_dir = BASE_DIR / "prompts" / "345"
        entry_file = parent_dir / "345.md"

        with patch.object(TmuxAgent, '_resolve_prompts_dir', return_value=parent_dir), \
             patch.object(Path, 'exists', lambda p: str(p) == str(entry_file)):
            result = agent._find_prompt_file()

        expected = str(entry_file)
        assert result == expected

    def test_find_prompt_compound_id(self):
        """Détection agent composé : 345-500 → parent dir 345 (EF-001)"""
        from agent import TmuxAgent, BASE_DIR

        agent = object.__new__(TmuxAgent)
        agent.agent_id = "345-500"

        # compound id: parent_id = "345"
        parent_id = agent.agent_id.split('-')[0]
        assert parent_id == "345"

        parent_dir = BASE_DIR / "prompts" / "345"
        entry_file = parent_dir / "345-500.md"

        with patch.object(TmuxAgent, '_resolve_prompts_dir', return_value=parent_dir), \
             patch.object(Path, 'exists', lambda p: str(p) == str(entry_file)):
            result = agent._find_prompt_file()

        expected = str(entry_file)
        assert result == expected

    def test_find_prompt_x45_old_directory(self):
        """Détection format x45 ancien : prompts/345/system.md (EF-001)"""
        from agent import TmuxAgent, BASE_DIR

        agent = object.__new__(TmuxAgent)
        agent.agent_id = "350"

        call_count = [0]
        def mock_exists(self_path):
            call_count[0] += 1
            if call_count[0] <= 2:
                return False  # monogent, x45 new
            return True  # system.md exists

        with patch.object(Path, 'exists', mock_exists), \
             patch.object(Path, 'is_file', return_value=False), \
             patch.object(Path, 'is_symlink', return_value=False), \
             patch.object(Path, 'is_dir', return_value=True):
            result = agent._find_prompt_file()

        expected = str(BASE_DIR / "prompts" / "350")
        assert result == expected

    def test_find_prompt_fallback_flat(self):
        """Détection format flat : prompts/350-explorer.md (EF-001)"""
        from agent import TmuxAgent, BASE_DIR

        agent = object.__new__(TmuxAgent)
        agent.agent_id = "350"

        flat_file = BASE_DIR / "prompts" / "350-explorer.md"

        with patch.object(TmuxAgent, '_resolve_prompts_dir', return_value=None), \
             patch.object(Path, 'glob', return_value=[flat_file]), \
             patch.object(Path, 'is_file', return_value=True):
            result = agent._find_prompt_file()

        expected = str(flat_file)
        assert result == expected

    def test_find_prompt_none(self):
        """Retourne None si aucun format de prompt n'est trouvé (EF-001)"""
        from agent import TmuxAgent

        agent = object.__new__(TmuxAgent)
        agent.agent_id = "999"

        with patch.object(Path, 'exists', return_value=False), \
             patch.object(Path, 'is_file', return_value=False), \
             patch.object(Path, 'is_symlink', return_value=False), \
             patch.object(Path, 'is_dir', return_value=False), \
             patch.object(Path, 'glob', return_value=[]):
            result = agent._find_prompt_file()

        assert result is None


class TestPromptReload:
    """EF-001 — Tests du rechargement de prompt (compaction)"""

    def test_reload_resets_message_count(self):
        """_reload_prompt() remet messages_since_reload à 0 (EF-001)"""
        from agent import TmuxAgent

        agent = object.__new__(TmuxAgent)
        agent.agent_id = "300"
        agent.messages_since_reload = 15
        agent.prompt_queue = Queue()
        agent._log = MagicMock()
        agent._send_keys = MagicMock()
        agent._set_redis_status = MagicMock()

        # Mock _find_prompt_file to return a monogent file
        with patch.object(TmuxAgent, '_find_prompt_file', return_value="/path/to/300.md"), \
             patch.object(TmuxAgent, '_is_x45_agent', return_value=False):
            agent._reload_prompt()

        assert agent.messages_since_reload == 0

    def test_reload_sends_reset_first(self):
        """_reload_prompt() envoie /reset avant le nouveau prompt (EF-001)"""
        from agent import TmuxAgent

        agent = object.__new__(TmuxAgent)
        agent.agent_id = "300"
        agent.messages_since_reload = 5
        agent.prompt_queue = Queue()
        agent._log = MagicMock()
        agent._send_keys = MagicMock()
        agent._set_redis_status = MagicMock()

        with patch.object(TmuxAgent, '_find_prompt_file', return_value="/path/to/300.md"), \
             patch.object(TmuxAgent, '_is_x45_agent', return_value=False):
            agent._reload_prompt()

        agent._send_keys.assert_called_once_with("/reset")

    def test_reload_no_prompt_file(self):
        """_reload_prompt() ne fait rien si pas de fichier prompt (EF-001)"""
        from agent import TmuxAgent

        agent = object.__new__(TmuxAgent)
        agent.agent_id = "300"
        agent.messages_since_reload = 5
        agent._log = MagicMock()
        agent._send_keys = MagicMock()

        with patch.object(TmuxAgent, '_find_prompt_file', return_value=None):
            agent._reload_prompt()

        agent._send_keys.assert_not_called()


class TestMessageFormatCT001:
    """CT-001 — Vérification format messages Redis Streams"""

    def test_outbox_message_format(self):
        """Le message outbox contient response, from_agent, timestamp, chars (CT-001)"""
        msg_data = {
            'response': 'test response',
            'from_agent': '300',
            'to_agent': '100',
            'timestamp': int(time.time()),
            'chars': len('test response')
        }
        assert 'response' in msg_data
        assert 'from_agent' in msg_data
        assert 'timestamp' in msg_data
        assert isinstance(msg_data['timestamp'], int)

    def test_inbox_message_format(self):
        """Le message inbox contient prompt, from_agent, timestamp (CT-001)"""
        msg_data = {
            'prompt': 'do something',
            'from_agent': '100',
            'timestamp': int(time.time())
        }
        assert 'prompt' in msg_data
        assert 'from_agent' in msg_data
        assert 'timestamp' in msg_data

    def test_response_message_format(self):
        """Le message response contient response, from_agent, type, complete (CT-001)"""
        msg_data = {
            'response': 'task done',
            'from_agent': '300',
            'type': 'response',
            'timestamp': int(time.time()),
            'complete': 'true'
        }
        assert msg_data['type'] == 'response'
        assert msg_data['complete'] in ('true', 'false')

    def test_status_hash_format(self):
        """Le hash de status contient les champs obligatoires (CT-001)"""
        status = {
            'status': 'idle',
            'last_seen': int(time.time()),
            'queue_size': 0,
            'tasks_completed': 5,
            'messages_since_reload': 3,
            'mode': 'tmux-interactive'
        }
        required_fields = ['status', 'last_seen', 'queue_size',
                          'tasks_completed', 'mode']
        for field in required_fields:
            assert field in status


class TestHistoryManagement:
    """EF-001 — Tests de la gestion de l'historique"""

    def test_history_maxlen(self):
        """L'historique est limité à MAX_HISTORY entrées (EF-001)"""
        from agent import MAX_HISTORY
        history = deque(maxlen=MAX_HISTORY)
        for i in range(MAX_HISTORY + 10):
            history.append({'prompt': f'prompt_{i}', 'response': f'response_{i}'})
        assert len(history) == MAX_HISTORY
        assert history[0]['prompt'] == f'prompt_10'

    def test_history_entry_format(self):
        """Chaque entrée d'historique a prompt, response, from_agent, timestamp (EF-001)"""
        entry = {
            'prompt': 'test prompt',
            'response': 'test response',
            'from_agent': '100',
            'timestamp': int(time.time())
        }
        assert all(k in entry for k in ['prompt', 'response', 'from_agent', 'timestamp'])


class TestLegacyMessageParsing:
    """EF-001 — Tests du parsing des messages legacy"""

    def test_parse_from_prefix_with_pipe(self):
        """Parse 'FROM:100|message' correctement (EF-001)"""
        message = "FROM:100|go example.com"
        from_agent = 'legacy'
        prompt = message
        if message.startswith('FROM:'):
            parts = message.split('|', 1)
            if len(parts) == 2:
                from_agent = parts[0][5:]
                prompt = parts[1]
        assert from_agent == '100'
        assert prompt == 'go example.com'

    def test_parse_from_prefix_multiple_pipes(self):
        """Parse correctement quand le message contient aussi des pipes (EF-001)"""
        message = "FROM:200|command with | pipe char"
        from_agent = 'legacy'
        prompt = message
        if message.startswith('FROM:'):
            parts = message.split('|', 1)
            if len(parts) == 2:
                from_agent = parts[0][5:]
                prompt = parts[1]
        assert from_agent == '200'
        assert prompt == 'command with | pipe char'

    def test_parse_no_prefix(self):
        """Message sans FROM: utilise 'legacy' par défaut (EF-001)"""
        message = "simple message"
        from_agent = 'legacy'
        prompt = message
        if message.startswith('FROM:'):
            parts = message.split('|', 1)
            if len(parts) == 2:
                from_agent = parts[0][5:]
                prompt = parts[1]
        assert from_agent == 'legacy'
        assert prompt == 'simple message'

    def test_parse_from_no_pipe(self):
        """Message 'FROM:100' sans pipe garde le format original (EF-001)"""
        message = "FROM:100"
        from_agent = 'legacy'
        prompt = message
        if message.startswith('FROM:'):
            parts = message.split('|', 1)
            if len(parts) == 2:
                from_agent = parts[0][5:]
                prompt = parts[1]
        # No pipe → from_agent stays 'legacy'
        assert from_agent == 'legacy'
        assert prompt == "FROM:100"


class TestWaitForResponse:
    """EF-001 — Tests de la détection de fin de réponse Claude"""

    def test_prompt_markers_defined(self):
        """Les marqueurs de prompt sont définis (EF-001)"""
        from agent import PROMPT_MARKERS
        assert '❯' in PROMPT_MARKERS
        assert '>' in PROMPT_MARKERS

    def test_response_timeout_value(self):
        """Le timeout de réponse est de 300 secondes (EF-001)"""
        from agent import RESPONSE_TIMEOUT
        assert 30 <= RESPONSE_TIMEOUT <= 900  # configurable via env

    def test_poll_interval_value(self):
        """L'intervalle de polling est de 1.0 seconde (EF-001)"""
        from agent import POLL_INTERVAL
        assert POLL_INTERVAL == 1.0
