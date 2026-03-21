"""
Tests unitaires pour orchestrator.py (scripts/agent-bridge/orchestrator.py)
EF-002 — Couverture : 3 modes (séquentiel, parallèle, pipeline) × 2 cas (nominal, erreur)

Réf spec 342 : CA-003 (≥100 LOC, 3 modes × 2 cas)
CT-001 : Format messages Redis Streams préservé (from, type, payload, timestamp)
"""
import pytest
import time
import os
import sys
from unittest.mock import MagicMock, patch, call

# Add agent-bridge to path
_BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(_BASE, 'core', 'agent-bridge'))


# === Fixtures ===

@pytest.fixture
def mock_redis():
    """Mock Redis client pour les tests orchestrator"""
    with patch('orchestrator.r') as mock_r:
        mock_r.ping.return_value = True
        yield mock_r


# === Mode Séquentiel ===

class TestSequentialWorkflow:
    """EF-002 — Mode séquentiel : Explorer → Developer → Tester"""

    def test_seq_nominal_sends_in_order(self, mock_redis):
        """Cas nominal : les 3 étapes s'exécutent en séquence (EF-002)"""
        from orchestrator import send_and_wait

        # Mock xread to return responses
        responses = iter([
            # Response from agent 200 (Explorer)
            [("ma:agent:200:outbox", [("1-0", {"response": "Found 3 .py files"})])],
            # Response from agent 300 (Developer)
            [("ma:agent:300:outbox", [("2-0", {"response": "Created index.py"})])],
            # Response from agent 500 (Tester)
            [("ma:agent:500:outbox", [("3-0", {"response": "All tests pass"})])],
        ])
        mock_redis.xread.side_effect = lambda *a, **kw: next(responses)

        r1 = send_and_wait(200, "List .py files", from_agent=100)
        r2 = send_and_wait(300, f"Create index from: {r1}", from_agent=100)
        r3 = send_and_wait(500, f"Test: {r2}", from_agent=100)

        assert r1 == "Found 3 .py files"
        assert r2 == "Created index.py"
        assert r3 == "All tests pass"
        assert mock_redis.xadd.call_count == 3

    def test_seq_error_timeout(self, mock_redis):
        """Cas erreur : timeout si agent ne répond pas (EF-002)"""
        from orchestrator import send_and_wait

        mock_redis.xread.return_value = None  # No response

        with pytest.raises(TimeoutError) as exc_info:
            send_and_wait(200, "Should timeout", from_agent=100, timeout=1)

        assert "No response from agent 200" in str(exc_info.value)


# === Mode Parallèle ===

class TestParallelWorkflow:
    """EF-002 — Mode parallèle : broadcast + collect"""

    def test_par_nominal_broadcast_and_collect(self, mock_redis):
        """Cas nominal : broadcast à 3 workers et collecte des réponses (EF-002)"""
        from orchestrator import broadcast, collect_responses

        workers = [300, 301, 302]
        broadcast(workers, "Do task", from_agent=100)

        # Verify 3 messages sent
        assert mock_redis.xadd.call_count == 3
        for i, worker in enumerate(workers):
            call_args = mock_redis.xadd.call_args_list[i]
            assert call_args[0][0] == f"ma:agent:{worker}:inbox"
            assert call_args[0][1]['prompt'] == "Do task"
            assert call_args[0][1]['from_agent'] == 100

        # Mock collecting responses
        call_count = 0
        def mock_xread(streams, block=2000, count=10):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [
                    ("ma:agent:300:outbox", [("1-0", {"response": "done A"})]),
                    ("ma:agent:301:outbox", [("2-0", {"response": "done B"})]),
                ]
            elif call_count == 2:
                return [
                    ("ma:agent:302:outbox", [("3-0", {"response": "done C"})]),
                ]
            return None

        mock_redis.xread.side_effect = mock_xread

        responses = collect_responses(workers, timeout=5)
        assert len(responses) == 3
        assert responses["300"] == "done A"
        assert responses["301"] == "done B"
        assert responses["302"] == "done C"

    def test_par_error_partial_responses(self, mock_redis):
        """Cas erreur : timeout avec réponses partielles (EF-002)"""
        from orchestrator import collect_responses

        workers = [300, 301, 302]

        call_count = 0
        def mock_xread(streams, block=2000, count=10):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [("ma:agent:300:outbox", [("1-0", {"response": "done A"})])]
            return None  # Other agents never respond

        mock_redis.xread.side_effect = mock_xread

        responses = collect_responses(workers, timeout=1)

        # Should have partial results (only agent 300 responded)
        assert "300" in responses
        assert len(responses) < len(workers)


# === Mode Pipeline ===

class TestPipelineWorkflow:
    """EF-002 — Mode pipeline : Explorer → Master → Devs → Merge → Test"""

    def test_pipeline_nominal_full_flow(self, mock_redis):
        """Cas nominal : pipeline complet avec toutes les étapes (EF-002)"""
        from orchestrator import send_and_wait

        step_responses = [
            # Explorer (200) response
            [("ma:agent:200:outbox", [("1-0", {"response": "Spec: add email validation"})])],
            # Master (100) response
            [("ma:agent:100:outbox", [("2-0", {"response": "Dispatched to 300,301,302"})])],
            # Merge (400) response
            [("ma:agent:400:outbox", [("3-0", {"response": "Merged 3 branches"})])],
            # Test (500) response
            [("ma:agent:500:outbox", [("4-0", {"response": "12/12 tests pass"})])],
        ]
        mock_redis.xread.side_effect = lambda *a, **kw: step_responses.pop(0) if step_responses else None

        # Run pipeline steps
        spec = send_and_wait(200, "Analyse project/", from_agent=100, timeout=5)
        assert "email validation" in spec

        dispatch = send_and_wait(100, f"Dispatch: {spec}", from_agent=0, timeout=5)
        assert "Dispatched" in dispatch

        merge = send_and_wait(400, "Cherry-pick dev branches", from_agent=100, timeout=5)
        assert "Merged" in merge

        test = send_and_wait(500, "Run all tests", from_agent=100, timeout=5)
        assert "pass" in test

    def test_pipeline_error_merge_failure(self, mock_redis):
        """Cas erreur : échec du merge dans le pipeline (EF-002)"""
        from orchestrator import send_and_wait

        step_responses = [
            # Explorer OK
            [("ma:agent:200:outbox", [("1-0", {"response": "Spec ready"})])],
            # Master OK
            [("ma:agent:100:outbox", [("2-0", {"response": "Dispatched"})])],
        ]
        mock_redis.xread.side_effect = lambda *a, **kw: step_responses.pop(0) if step_responses else None

        send_and_wait(200, "Analyse", from_agent=100, timeout=5)
        send_and_wait(100, "Dispatch", from_agent=0, timeout=5)

        # Merge times out
        with pytest.raises(TimeoutError):
            send_and_wait(400, "Cherry-pick", from_agent=100, timeout=1)


# === Validation CT-001 : Format messages ===

class TestMessageFormat:
    """CT-001 — Vérification du format des messages Redis Streams"""

    def test_message_contains_required_fields(self, mock_redis):
        """Les messages envoyés contiennent from_agent, timestamp (CT-001)"""
        from orchestrator import send_and_wait

        mock_redis.xread.return_value = [
            ("ma:agent:200:outbox", [("1-0", {"response": "ok"})])
        ]

        send_and_wait(200, "test", from_agent=100)

        # Check the xadd call
        add_call = mock_redis.xadd.call_args
        msg_data = add_call[0][1]

        assert 'prompt' in msg_data
        assert 'from_agent' in msg_data
        assert 'timestamp' in msg_data
        assert msg_data['from_agent'] == 100

    def test_inbox_key_format(self, mock_redis):
        """Les clés inbox suivent le format ma:agent:{ID}:inbox (CT-001)"""
        from orchestrator import send_and_wait, MA_PREFIX

        mock_redis.xread.return_value = [
            ("ma:agent:300:outbox", [("1-0", {"response": "ok"})])
        ]

        send_and_wait(300, "hello", from_agent=100)

        add_call = mock_redis.xadd.call_args
        key = add_call[0][0]
        assert key == f"{MA_PREFIX}:agent:300:inbox"
