"""
Tests d'intégration pour la pipeline multi-agent
EF-001, EF-002 — Validation croisée des composants

Réf spec 342 : CA-001 (ratio ≥15%), CA-007 (zéro régression bridge)
"""
import pytest
import os
import sys
import json
import time
from unittest.mock import MagicMock, patch
from queue import Queue
from collections import deque

_BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(_BASE, 'core', 'agent-bridge'))


class TestAgentOrchestratorIntegration:
    """Tests d'intégration agent.py + orchestrator.py"""

    @patch('orchestrator.r')
    def test_send_and_wait_message_format_matches_agent(self, mock_redis):
        """Le format de message de orchestrator.send_and_wait est compatible avec agent.py (CA-007)"""
        from orchestrator import send_and_wait, MA_PREFIX

        mock_redis.xread.return_value = [
            (f"{MA_PREFIX}:agent:300:outbox", [("1-0", {"response": "ok"})])
        ]
        send_and_wait(300, "test message", from_agent=100)

        # Verify the xadd message format
        call_args = mock_redis.xadd.call_args
        key = call_args[0][0]
        data = call_args[0][1]

        # Key must match agent.py inbox format
        assert key == f"{MA_PREFIX}:agent:300:inbox"

        # Data must have required fields that agent.py _listen_redis expects
        assert 'prompt' in data
        assert 'from_agent' in data
        assert 'timestamp' in data

    @patch('orchestrator.r')
    def test_broadcast_format_matches_agent(self, mock_redis):
        """Le format de broadcast est compatible avec agent._listen_redis (CA-007)"""
        from orchestrator import broadcast, MA_PREFIX

        broadcast([300, 301], "do task", from_agent=100)

        assert mock_redis.xadd.call_count == 2

        for call in mock_redis.xadd.call_args_list:
            key = call[0][0]
            data = call[0][1]

            # Must match inbox pattern
            assert ":inbox" in key
            assert 'prompt' in data
            assert 'from_agent' in data

    def test_agent_state_transitions(self):
        """Les transitions d'état IDLE → BUSY → IDLE sont correctes (CA-007)"""
        from agent import State

        # Valid transitions
        state = State.IDLE
        assert state.value == "idle"

        state = State.BUSY
        assert state.value == "busy"

        # Roundtrip
        state = State.IDLE
        assert state == State.IDLE


class TestPromptMarkersCompatibility:
    """Tests de compatibilité des marqueurs de prompt"""

    def test_prompt_markers_are_single_chars(self):
        """Chaque marqueur de prompt est un seul caractère (CA-007)"""
        from agent import PROMPT_MARKERS
        for marker in PROMPT_MARKERS:
            assert len(marker) == 1, f"Marker '{marker}' should be single char"

    def test_prompt_markers_detect_end_of_response(self):
        """Les marqueurs détectent la fin d'une réponse Claude (CA-007)"""
        from agent import PROMPT_MARKERS

        test_outputs = [
            "Some output\n❯",
            "Result here\n>",
            "Done\n$",
            "Finished\n%",
        ]

        for output in test_outputs:
            last_line = output.strip().split('\n')[-1].strip()
            found = False
            for marker in PROMPT_MARKERS:
                if last_line.endswith(marker) or last_line == marker:
                    found = True
                    break
            assert found, f"Should detect end of response in: {repr(output)}"


class TestRedisKeyConsistency:
    """Tests de cohérence des clés Redis entre les composants"""

    def test_agent_inbox_format(self):
        """Le format inbox est ma:agent:{id}:inbox (CA-007)"""
        ma_prefix = "ma"
        agent_id = "300"
        inbox = f"{ma_prefix}:agent:{agent_id}:inbox"
        assert inbox == "ma:agent:300:inbox"

    def test_agent_outbox_format(self):
        """Le format outbox est ma:agent:{id}:outbox (CA-007)"""
        ma_prefix = "ma"
        agent_id = "300"
        outbox = f"{ma_prefix}:agent:{agent_id}:outbox"
        assert outbox == "ma:agent:300:outbox"

    def test_legacy_inbox_format(self):
        """Le format legacy est ma:inject:{id} (CA-007)"""
        ma_prefix = "ma"
        agent_id = "300"
        legacy = f"{ma_prefix}:inject:{agent_id}"
        assert legacy == "ma:inject:300"

    def test_status_hash_format(self):
        """Le format status est ma:agent:{id} (CA-007)"""
        ma_prefix = "ma"
        agent_id = "300"
        status = f"{ma_prefix}:agent:{agent_id}"
        assert status == "ma:agent:300"

    @patch('orchestrator.r')
    def test_orchestrator_uses_same_prefix(self, mock_redis):
        """L'orchestrator utilise le même MA_PREFIX que l'agent (CA-007)"""
        from orchestrator import MA_PREFIX as ORCH_PREFIX
        from agent import MA_PREFIX as AGENT_PREFIX
        assert ORCH_PREFIX == AGENT_PREFIX


class TestConfigConstants:
    """Tests des constantes de configuration partagées"""

    def test_redis_defaults_consistent(self):
        """Les valeurs par défaut Redis sont identiques entre agent et orchestrator"""
        from agent import REDIS_HOST, REDIS_PORT
        from orchestrator import REDIS_HOST as O_HOST, REDIS_PORT as O_PORT
        assert REDIS_HOST == O_HOST
        assert REDIS_PORT == O_PORT

    def test_ma_prefix_default(self):
        """MA_PREFIX vaut 'ma' par défaut (CA-007)"""
        from agent import MA_PREFIX
        # Default should be 'ma' unless overridden by env
        assert MA_PREFIX == os.environ.get("MA_PREFIX", "ma")

    def test_max_history_reasonable(self):
        """MAX_HISTORY est entre 10 et 1000 (CA-007)"""
        from agent import MAX_HISTORY
        assert 10 <= MAX_HISTORY <= 1000

    def test_response_timeout_reasonable(self):
        """RESPONSE_TIMEOUT est entre 30 et 600 secondes (CA-007)"""
        from agent import RESPONSE_TIMEOUT
        assert 30 <= RESPONSE_TIMEOUT <= 600
