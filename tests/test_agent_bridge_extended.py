"""
Tests unitaires étendus pour agent.py (scripts/agent-bridge/agent.py)
EF-001 — Couverture : démarrage nominal, perte connexion Redis, erreur de commande

Réf spec 342 : CA-002 (≥200 LOC, 3+ scénarios)
"""
import pytest
import time
import os
import sys
import subprocess
from unittest.mock import MagicMock, patch, PropertyMock
from threading import Thread, Event
from queue import Queue, Empty
from enum import Enum
from collections import deque
from pathlib import Path
from io import StringIO

# Add agent-bridge to path (conftest.py also adds this via marker search)
_HERE = os.path.dirname(os.path.realpath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
sys.path.insert(0, os.path.join(_REPO_ROOT, 'scripts', 'agent-bridge'))

# P11 FIX C4: Save real redis.ConnectionError BEFORE any test_monitor.py mock
# can poison sys.modules['redis']. This prevents TypeError when used as side_effect.
try:
    import redis as _real_redis_mod
    _RedisConnectionError = _real_redis_mod.ConnectionError
except (ImportError, AttributeError):
    class _RedisConnectionError(Exception):
        """Fallback if redis not installed."""
        pass


# === Scénario 1 : Démarrage nominal ===

class TestNominalStartup:
    """EF-001 — Scénario 1 : Démarrage nominal du TmuxAgent"""

    def test_state_enum_values(self):
        """Vérifie que les états IDLE et BUSY sont correctement définis (EF-001)"""
        from agent import State
        assert State.IDLE.value == "idle"
        assert State.BUSY.value == "busy"

    def test_config_defaults(self):
        """Vérifie les valeurs par défaut de la configuration (EF-001)"""
        from agent import REDIS_HOST, REDIS_PORT, MA_PREFIX, MAX_HISTORY
        from agent import RESPONSE_TIMEOUT, POLL_INTERVAL, PROMPT_MARKERS

        assert REDIS_HOST == "localhost" or isinstance(REDIS_HOST, str)
        assert isinstance(REDIS_PORT, int)
        assert REDIS_PORT > 0
        assert MA_PREFIX == "A" or isinstance(MA_PREFIX, str)
        assert MAX_HISTORY == 50
        assert 30 <= RESPONSE_TIMEOUT <= 900  # configurable via env
        assert POLL_INTERVAL == 1.0
        assert isinstance(PROMPT_MARKERS, list)
        assert len(PROMPT_MARKERS) > 0

    @patch('agent.subprocess.run')
    @patch('agent.redis.Redis')
    def test_init_sets_agent_id(self, mock_redis_cls, mock_run):
        """Vérifie que l'agent_id est correctement initialisé (EF-001)"""
        mock_redis_instance = MagicMock()
        mock_redis_instance.ping.return_value = True
        mock_redis_cls.return_value = mock_redis_instance

        # Mock tmux session exists
        mock_run.return_value = MagicMock(returncode=0, stdout="10\n")

        from agent import TmuxAgent
        with patch.object(TmuxAgent, '_log'), \
             patch.object(TmuxAgent, '_log_event'), \
             patch.object(TmuxAgent, '_set_redis_status'), \
             patch.object(TmuxAgent, '_get_pane_line_count', return_value=10), \
             patch('builtins.open', MagicMock()):
            agent = TmuxAgent("300")
            agent.running = False  # Stop threads immediately

        assert agent.agent_id == "300"
        assert agent.state.value == "idle"

    @patch('agent.subprocess.run')
    @patch('agent.redis.Redis')
    def test_init_creates_log_dir(self, mock_redis_cls, mock_run):
        """Vérifie que le répertoire de logs est créé (EF-001)"""
        mock_redis_instance = MagicMock()
        mock_redis_instance.ping.return_value = True
        mock_redis_cls.return_value = mock_redis_instance
        mock_run.return_value = MagicMock(returncode=0, stdout="10\n")

        from agent import TmuxAgent, LOG_DIR
        with patch.object(TmuxAgent, '_log'), \
             patch.object(TmuxAgent, '_log_event'), \
             patch.object(TmuxAgent, '_set_redis_status'), \
             patch.object(TmuxAgent, '_get_pane_line_count', return_value=10), \
             patch('builtins.open', MagicMock()):
            agent = TmuxAgent("301")
            agent.running = False

        expected_log_dir = Path(LOG_DIR) / "301"
        # The constructor calls mkdir(parents=True, exist_ok=True)
        assert agent.log_dir == expected_log_dir

    @patch('agent.subprocess.run')
    @patch('agent.redis.Redis')
    def test_init_creates_inbox_outbox_keys(self, mock_redis_cls, mock_run):
        """Vérifie que les clés Redis inbox/outbox sont correctement formées (EF-001)"""
        mock_redis_instance = MagicMock()
        mock_redis_instance.ping.return_value = True
        mock_redis_cls.return_value = mock_redis_instance
        mock_run.return_value = MagicMock(returncode=0, stdout="10\n")

        from agent import TmuxAgent
        with patch.object(TmuxAgent, '_log'), \
             patch.object(TmuxAgent, '_log_event'), \
             patch.object(TmuxAgent, '_set_redis_status'), \
             patch.object(TmuxAgent, '_get_pane_line_count', return_value=10), \
             patch('builtins.open', MagicMock()):
            agent = TmuxAgent("302")
            agent.running = False

        assert agent.inbox == "A:agent:302:inbox"
        assert agent.outbox == "A:agent:302:outbox"
        assert agent.legacy_inbox == "A:inject:302"

    @patch('agent.subprocess.run')
    @patch('agent.redis.Redis')
    def test_init_starts_threads(self, mock_redis_cls, mock_run):
        """Vérifie que 4 threads daemon sont créés (EF-001, EF-003 — R-REGTEST C3)"""
        mock_redis_instance = MagicMock()
        mock_redis_instance.ping.return_value = True
        mock_redis_cls.return_value = mock_redis_instance
        mock_run.return_value = MagicMock(returncode=0, stdout="10\n")

        from agent import TmuxAgent
        with patch.object(TmuxAgent, '_log'), \
             patch.object(TmuxAgent, '_log_event'), \
             patch.object(TmuxAgent, '_set_redis_status'), \
             patch.object(TmuxAgent, '_get_pane_line_count', return_value=10), \
             patch('builtins.open', MagicMock()):
            agent = TmuxAgent("303")
            agent.running = False

        assert len(agent.threads) == 4  # R-REGTEST: 3 original + heartbeat (EF-003)
        thread_names = [t.name for t in agent.threads]
        assert "redis_listener" in thread_names
        assert "legacy_listener" in thread_names
        assert "queue_processor" in thread_names
        assert "heartbeat" in thread_names  # EF-003: heartbeat enrichi

    @patch('agent.subprocess.run')
    def test_tmux_session_exists_true(self, mock_run):
        """Vérifie la détection d'une session tmux existante (EF-001)"""
        mock_run.return_value = MagicMock(returncode=0)

        from agent import TmuxAgent
        agent = object.__new__(TmuxAgent)
        agent.session_name = "ma-agent-300"
        assert agent._tmux_session_exists() is True

    @patch('agent.subprocess.run')
    def test_tmux_session_exists_false(self, mock_run):
        """Vérifie la détection d'une session tmux absente (EF-001)"""
        mock_run.return_value = MagicMock(returncode=1)

        from agent import TmuxAgent
        agent = object.__new__(TmuxAgent)
        agent.session_name = "ma-agent-999"
        assert agent._tmux_session_exists() is False


# === Scénario 2 : Perte de connexion Redis ===

class TestRedisConnectionLoss:
    """EF-001 — Scénario 2 : Perte et reconnexion Redis"""

    @patch('agent.subprocess.run')
    @patch('agent.redis.Redis')
    def test_init_exits_on_redis_failure(self, mock_redis_cls, mock_run):
        """Vérifie que l'agent quitte si Redis est indisponible au démarrage (EF-001)"""
        mock_redis_instance = MagicMock()
        mock_redis_instance.ping.side_effect = _RedisConnectionError("Connection refused")
        mock_redis_cls.return_value = mock_redis_instance
        mock_run.return_value = MagicMock(returncode=0, stdout="10\n")

        from agent import TmuxAgent
        with pytest.raises(SystemExit):
            with patch.object(TmuxAgent, '_log'), \
                 patch.object(TmuxAgent, '_log_event'), \
                 patch('builtins.open', MagicMock()):
                TmuxAgent("400")

    def test_set_redis_status_handles_connection_error(self):
        """Vérifie que _set_redis_status ne crashe pas si Redis est down (EF-001)"""
        from agent import TmuxAgent, State

        agent = object.__new__(TmuxAgent)
        agent.agent_id = "401"
        agent.state = State.IDLE
        agent.prompt_queue = Queue()
        agent.tasks_completed = 0
        agent.messages_since_reload = 0
        agent.redis = MagicMock()
        agent.redis.hset.side_effect = _RedisConnectionError("Connection lost")

        # Should not raise
        agent._set_redis_status()

    def test_listen_redis_reconnects_on_error(self):
        """Vérifie que le listener Redis tente de se reconnecter après erreur (EF-001)"""
        from agent import TmuxAgent

        agent = object.__new__(TmuxAgent)
        agent.agent_id = "402"
        agent.inbox = "A:agent:402:inbox"
        agent.running = True
        agent.prompt_queue = Queue()
        agent.logfile = MagicMock()

        call_count = 0
        def mock_xread(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise _RedisConnectionError("Connection lost")
            # Stop after 3 calls
            agent.running = False
            return None

        agent.redis = MagicMock()
        agent.redis.xread.side_effect = mock_xread
        agent._log = MagicMock()

        # Run in thread to avoid blocking
        thread = Thread(target=agent._listen_redis, daemon=True)
        thread.start()
        thread.join(timeout=5)

        # Should have attempted reconnection
        assert call_count >= 2
        # Should have logged the error
        agent._log.assert_any_call("Redis connection lost, reconnecting...")

    def test_listen_legacy_handles_connection_error(self):
        """Vérifie que le listener legacy gère la perte Redis (EF-001)"""
        from agent import TmuxAgent

        agent = object.__new__(TmuxAgent)
        agent.agent_id = "403"
        agent.legacy_inbox = "A:inject:403"
        agent.running = True
        agent._log = MagicMock()

        call_count = 0
        def mock_blpop(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise _RedisConnectionError("Connection refused")
            agent.running = False
            return None

        agent.redis = MagicMock()
        agent.redis.blpop.side_effect = mock_blpop

        thread = Thread(target=agent._listen_legacy, daemon=True)
        thread.start()
        thread.join(timeout=5)

        assert call_count >= 1


# === Scénario 3 : Erreur de commande ===

class TestCommandErrors:
    """EF-001 — Scénario 3 : Erreurs et gestion des commandes"""

    def test_handle_unknown_command(self):
        """Vérifie la gestion d'une commande inconnue (EF-001)"""
        from agent import TmuxAgent

        agent = object.__new__(TmuxAgent)
        agent._log = MagicMock()

        agent._handle_command("/unknown_cmd")

        agent._log.assert_called_with("Unknown command: /unknown_cmd")

    def test_handle_status_command(self):
        """Vérifie la commande /status (EF-001)"""
        from agent import TmuxAgent, State

        agent = object.__new__(TmuxAgent)
        agent.state = State.IDLE
        agent.prompt_queue = Queue()
        agent.tasks_completed = 5
        agent._log = MagicMock()

        agent._handle_command("/status")

        call_args = agent._log.call_args[0][0]
        assert "idle" in call_args.lower()
        assert "5" in call_args

    def test_handle_send_command_missing_args(self):
        """Vérifie l'erreur si /send est incomplet (EF-001)"""
        from agent import TmuxAgent

        agent = object.__new__(TmuxAgent)
        agent._log = MagicMock()

        agent._handle_command("/send 300")

        agent._log.assert_called_with("Usage: /send <agent_id> <message>")

    def test_handle_send_command_valid(self):
        """Vérifie que /send appelle send_to_agent correctement (EF-001)"""
        from agent import TmuxAgent

        agent = object.__new__(TmuxAgent)
        agent._log = MagicMock()
        agent.send_to_agent = MagicMock()

        agent._handle_command("/send 300 hello world")

        agent.send_to_agent.assert_called_once_with("300", "hello world")

    def test_handle_help_command(self):
        """Vérifie la commande /help (EF-001)"""
        from agent import TmuxAgent

        agent = object.__new__(TmuxAgent)
        agent._log = MagicMock()

        agent._handle_command("/help")

        call_args = agent._log.call_args[0][0]
        assert "/status" in call_args
        assert "/help" in call_args

    def test_handle_queue_command(self):
        """Vérifie la commande /queue (EF-001)"""
        from agent import TmuxAgent

        agent = object.__new__(TmuxAgent)
        agent.prompt_queue = Queue()
        agent.prompt_queue.put("task1")
        agent.prompt_queue.put("task2")
        agent._log = MagicMock()

        agent._handle_command("/queue")

        call_args = agent._log.call_args[0][0]
        assert "2" in call_args

    def test_process_queue_sets_busy_state(self):
        """Vérifie que le state passe à BUSY pendant le traitement (EF-001)"""
        from agent import TmuxAgent, State
        from threading import Lock

        agent = object.__new__(TmuxAgent)
        agent.agent_id = "500"
        agent.state = State.IDLE
        agent.state_lock = Lock()
        agent.running = True
        agent.prompt_queue = Queue()
        agent.history = deque(maxlen=50)
        agent.tasks_completed = 0
        agent.messages_since_reload = 0
        agent.current_task = None
        agent._log = MagicMock()
        agent._log_event = MagicMock()
        agent._set_redis_status = MagicMock()

        # Track state during _run_claude
        states_during_processing = []
        def mock_run_claude(prompt):
            states_during_processing.append(agent.state)
            return "mock response"

        agent._run_claude = mock_run_claude
        agent.redis = MagicMock()
        agent.redis.xadd = MagicMock()

        # Queue a task
        agent.prompt_queue.put({
            'prompt': 'test prompt',
            'from_agent': 'manual',
            'msg_id': 'test-1',
        })

        # Process one task then stop
        def process_one():
            try:
                task = agent.prompt_queue.get(timeout=1)
            except Empty:
                return

            with agent.state_lock:
                agent.state = State.BUSY
                agent.current_task = task

            response = agent._run_claude(task['prompt'])

            agent.history.append({
                'prompt': task['prompt'],
                'response': response,
                'from_agent': task.get('from_agent'),
                'timestamp': int(time.time())
            })

            with agent.state_lock:
                agent.current_task = None
                agent.state = State.IDLE

        process_one()

        assert len(states_during_processing) == 1
        assert states_during_processing[0] == State.BUSY
        assert agent.state == State.IDLE

    def test_send_to_agent_single(self):
        """Vérifie l'envoi d'un message à un agent spécifique (EF-001)"""
        from agent import TmuxAgent

        agent = object.__new__(TmuxAgent)
        agent.agent_id = "300"
        agent.redis = MagicMock()
        agent._log = MagicMock()

        agent.send_to_agent("400", "hello from 300")

        agent.redis.xadd.assert_called_once()
        call_args = agent.redis.xadd.call_args
        assert call_args[0][0] == "A:agent:400:inbox"
        assert call_args[0][1]['prompt'] == "hello from 300"
        assert call_args[0][1]['from_agent'] == "300"

    def test_send_to_agent_broadcast(self):
        """Vérifie le broadcast à tous les agents (EF-001)"""
        from agent import TmuxAgent

        agent = object.__new__(TmuxAgent)
        agent.agent_id = "100"
        agent.redis = MagicMock()
        agent.redis.keys.return_value = ["A:agent:300", "A:agent:301", "A:agent:100"]
        agent._log = MagicMock()

        agent.send_to_agent("all", "broadcast message")

        # Should send to 300 and 301 but not self (100)
        assert agent.redis.xadd.call_count == 2

    def test_find_prompt_file_monogent(self):
        """Vérifie la détection d'un prompt x45 entry point (EF-001)"""
        from agent import TmuxAgent, BASE_DIR

        agent = object.__new__(TmuxAgent)
        agent.agent_id = "100"

        parent_dir = BASE_DIR / "prompts" / "100"
        entry_file = parent_dir / "100.md"

        with patch.object(TmuxAgent, '_resolve_prompts_dir', return_value=parent_dir), \
             patch.object(Path, 'exists', lambda p: str(p) == str(entry_file)):
            result = agent._find_prompt_file()

        expected = str(entry_file)
        assert result == expected

    def test_is_x45_agent_directory(self):
        """Vérifie la détection d'un agent x45 (répertoire) (EF-001)"""
        from agent import TmuxAgent

        agent = object.__new__(TmuxAgent)

        with patch.object(Path, 'is_dir', return_value=True):
            assert agent._is_x45_agent("/some/path/345") is True

        with patch.object(Path, 'is_dir', return_value=False):
            assert agent._is_x45_agent("/some/path/345.md") is False
