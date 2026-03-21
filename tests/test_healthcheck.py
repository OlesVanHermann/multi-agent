"""
Tests pour healthcheck.py — EF-002 (watchdog) + EF-005 (tests healthcheck)
CT-004 : pytest + unittest.mock
CT-010 : Mock Redis, pas de pollution prod
CT-003 : Vérifie que le code existant n'est pas modifié

CA-002 : Watchdog détecte agent down et redémarre < 25s
CA-003 : Circuit breaker bloque après 3 restarts en 5 min
CA-006 : 10 tests minimum
"""
import pytest
import time
import json
import os
import sys
import importlib.util
from unittest.mock import MagicMock, patch, call

# R-SYMLINKPROOF P13 FIX C4: Load healthcheck.py via importlib.util
# to avoid conftest sys.path pollution (scripts/agent-bridge eclipses 345-output)
_HERE = os.path.dirname(os.path.realpath(__file__))
_OUTPUT = os.path.abspath(os.path.join(_HERE, '..'))
_HEALTHCHECK_PATH = os.path.join(_OUTPUT, 'healthcheck.py')

_spec = importlib.util.spec_from_file_location("healthcheck", _HEALTHCHECK_PATH)
healthcheck = importlib.util.module_from_spec(_spec)
sys.modules['healthcheck'] = healthcheck  # Allow patch('healthcheck.xxx') to work
_spec.loader.exec_module(healthcheck)

check_agents = healthcheck.check_agents
AgentWatchdog = healthcheck.AgentWatchdog
WATCHDOG_POLL_INTERVAL = healthcheck.WATCHDOG_POLL_INTERVAL
WATCHDOG_FAIL_THRESHOLD = healthcheck.WATCHDOG_FAIL_THRESHOLD
CIRCUIT_BREAKER_MAX_RESTARTS = healthcheck.CIRCUIT_BREAKER_MAX_RESTARTS
CIRCUIT_BREAKER_WINDOW = healthcheck.CIRCUIT_BREAKER_WINDOW
STREAM_MAXLEN = healthcheck.STREAM_MAXLEN


class TestCheckAgentsExisting:
    """Tests du code existant check_agents() — CT-003 (inchangé)."""

    @patch('healthcheck.r')
    def test_check_agents_detects_active(self, mock_r):
        """EF-005 : Détection agent actif (heartbeat < 30s)."""
        mock_r.keys.return_value = ["ma:agent:300"]
        mock_r.hgetall.return_value = {
            "status": "idle",
            "last_seen": str(int(time.time()) - 10),
            "queue_size": "0",
            "tasks_completed": "5",
            "session_id": "abc12345678"
        }

        agents = check_agents()

        assert "300" in agents
        assert agents["300"]["healthy"] is True
        assert agents["300"]["status"] == "idle"

    @patch('healthcheck.r')
    def test_check_agents_detects_stale(self, mock_r):
        """EF-005 : Détection agent inactif (heartbeat > 30s)."""
        mock_r.keys.return_value = ["ma:agent:300"]
        mock_r.hgetall.return_value = {
            "status": "busy",
            "last_seen": str(int(time.time()) - 60),
            "tasks_completed": "2",
            "session_id": "xyz"
        }

        agents = check_agents()

        assert "300" in agents
        assert agents["300"]["healthy"] is False

    @patch('healthcheck.r')
    def test_check_agents_empty(self, mock_r):
        """EF-005 : 0 agents enregistrés → dict vide."""
        mock_r.keys.return_value = []

        agents = check_agents()

        assert agents == {}

    @patch('healthcheck.r')
    def test_check_agents_filters_subkeys(self, mock_r):
        """EF-005 : Filtre les sous-clés (inbox, outbox)."""
        mock_r.keys.return_value = [
            "ma:agent:300",
            "ma:agent:300:inbox",
            "ma:agent:300:outbox"
        ]
        mock_r.hgetall.return_value = {
            "status": "idle",
            "last_seen": str(int(time.time())),
            "session_id": ""
        }

        agents = check_agents()

        assert len(agents) == 1
        assert "300" in agents


class TestWatchdogInit:
    """EF-002 — Initialisation du watchdog."""

    def test_default_configuration(self):
        """EF-002 : Configuration par défaut du watchdog."""
        redis_mock = MagicMock()
        wd = AgentWatchdog(redis_mock, prefix="test")

        assert wd.poll_interval == WATCHDOG_POLL_INTERVAL
        assert wd.fail_threshold == WATCHDOG_FAIL_THRESHOLD
        assert wd.max_restarts == CIRCUIT_BREAKER_MAX_RESTARTS
        assert wd.breaker_window == CIRCUIT_BREAKER_WINDOW

    def test_custom_configuration(self):
        """EF-002 : Seuils personnalisables."""
        redis_mock = MagicMock()
        wd = AgentWatchdog(redis_mock, prefix="test",
                           poll_interval=10, fail_threshold=5,
                           max_restarts=5, breaker_window=600)

        assert wd.poll_interval == 10
        assert wd.fail_threshold == 5
        assert wd.max_restarts == 5
        assert wd.breaker_window == 600


class TestWatchdogDiscovery:
    """EF-002 — Découverte des agents."""

    def test_discover_via_redis_heartbeat(self):
        """EF-002 : Découverte via mi:agent:*:heartbeat (source de vérité)."""
        redis_mock = MagicMock()
        redis_mock.keys.return_value = [
            "mi:agent:300:heartbeat",
            "mi:agent:345:heartbeat"
        ]
        wd = AgentWatchdog(redis_mock, prefix="mi")

        agents = wd.discover_agents()

        assert agents == ["300", "345"]

    @patch('healthcheck.subprocess.run')
    def test_discover_tmux_fallback(self, mock_run):
        """EF-002 : Fallback tmux si Redis échoue."""
        redis_mock = MagicMock()
        redis_mock.keys.side_effect = Exception("Redis down")
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="ma-agent-300\nma-agent-345\nother-session\n")
        wd = AgentWatchdog(redis_mock, prefix="mi")

        agents = wd.discover_agents()

        assert "300" in agents
        assert "345" in agents

    def test_discover_no_agents(self):
        """EF-002 : Aucun agent actif → liste vide."""
        redis_mock = MagicMock()
        redis_mock.keys.return_value = []
        wd = AgentWatchdog(redis_mock, prefix="test")

        agents = wd.discover_agents()

        assert agents == []


class TestWatchdogHealthCheck:
    """EF-002, CA-002 — Vérification health check."""

    @patch('healthcheck.urlopen')
    def test_healthy_agent(self, mock_urlopen):
        """EF-002 : Agent en bonne santé retourne les données health."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "status": "healthy", "agent_id": "300",
            "uptime_seconds": 100, "redis_connected": True,
            "pty_active": True, "last_heartbeat_ts": int(time.time())
        }).encode()
        mock_urlopen.return_value = mock_resp

        redis_mock = MagicMock()
        wd = AgentWatchdog(redis_mock, prefix="test")

        result = wd.check_health("300")

        assert result is not None
        assert result["status"] == "healthy"

    @patch('healthcheck.urlopen')
    def test_unreachable_agent(self, mock_urlopen):
        """EF-002 : Agent injoignable retourne None."""
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("Connection refused")

        redis_mock = MagicMock()
        wd = AgentWatchdog(redis_mock, prefix="test")

        result = wd.check_health("300")

        assert result is None

    def test_invalid_agent_id(self):
        """EF-002 : Agent ID non numérique retourne None."""
        redis_mock = MagicMock()
        wd = AgentWatchdog(redis_mock, prefix="test")

        result = wd.check_health("abc")

        assert result is None

    def test_compound_agent_id_port(self):
        """EF-002 : Agent composé 345-500 → port calculé depuis 345."""
        redis_mock = MagicMock()
        wd = AgentWatchdog(redis_mock, prefix="test", health_port_base=9100)

        with patch('healthcheck.urlopen') as mock_url:
            mock_url.side_effect = OSError("connection refused")  # R-REGTEST C3: use caught exception type
            result = wd.check_health("345-500")
            # Verify the URL used port 9100+345=9445
            call_url = mock_url.call_args[0][0]
            assert "9445" in call_url
            assert result is None  # Health check failed → None


class TestWatchdogRestart:
    """EF-002, CA-002 — Auto-restart."""

    @patch('healthcheck.subprocess.run')
    def test_restart_agent_success(self, mock_run):
        """EF-002, CA-002 : Restart réussi via tmux."""
        mock_run.return_value = MagicMock(returncode=0)
        redis_mock = MagicMock()
        wd = AgentWatchdog(redis_mock, prefix="test")

        result = wd.restart_agent("300")

        assert result is True
        assert mock_run.call_count == 2  # C-c + python3 agent.py

    @patch('healthcheck.subprocess.run')
    def test_restart_agent_failure(self, mock_run):
        """EF-002 : Restart échoué."""
        mock_run.side_effect = FileNotFoundError("tmux not found")
        redis_mock = MagicMock()
        wd = AgentWatchdog(redis_mock, prefix="test")

        result = wd.restart_agent("300")

        assert result is False


class TestWatchdogCircuitBreaker:
    """EF-002, CA-003 — Circuit breaker."""

    def test_circuit_closed_by_default(self):
        """CA-003 : Circuit fermé par défaut (restarts autorisés)."""
        redis_mock = MagicMock()
        wd = AgentWatchdog(redis_mock, prefix="test", max_restarts=3, breaker_window=300)

        assert wd.is_circuit_open("300") is False

    def test_circuit_opens_after_max_restarts(self):
        """CA-003 : Circuit s'ouvre après 3 restarts en 5 min."""
        redis_mock = MagicMock()
        wd = AgentWatchdog(redis_mock, prefix="test", max_restarts=3, breaker_window=300)

        now = time.time()
        wd._restart_history["300"] = [now - 100, now - 50, now - 10]

        assert wd.is_circuit_open("300") is True
        assert wd._circuit_open["300"] is True

    def test_circuit_respects_window(self):
        """CA-003 : Restarts hors fenêtre ne comptent pas."""
        redis_mock = MagicMock()
        wd = AgentWatchdog(redis_mock, prefix="test", max_restarts=3, breaker_window=300)

        now = time.time()
        # 3 restarts mais les 2 premiers hors fenêtre (>300s ago)
        wd._restart_history["300"] = [now - 400, now - 350, now - 10]

        assert wd.is_circuit_open("300") is False

    def test_record_restart_tracks_history(self):
        """CA-003 : _record_restart enregistre le timestamp."""
        redis_mock = MagicMock()
        wd = AgentWatchdog(redis_mock, prefix="test")

        wd._record_restart("300")

        assert len(wd._restart_history["300"]) == 1

    def test_record_restart_cleans_old(self):
        """CA-003 : _record_restart nettoie les vieux timestamps."""
        redis_mock = MagicMock()
        wd = AgentWatchdog(redis_mock, prefix="test", breaker_window=60)

        now = time.time()
        wd._restart_history["300"] = [now - 100, now - 80]  # All > 60s ago
        wd._record_restart("300")

        # Only the new one should remain
        assert len(wd._restart_history["300"]) == 1


class TestWatchdogProcessAgent:
    """EF-002 — Logique process_agent complète."""

    @patch('healthcheck.urlopen')
    def test_healthy_resets_fail_count(self, mock_urlopen):
        """EF-002 : Agent sain remet le compteur à 0."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"status": "healthy"}).encode()
        mock_urlopen.return_value = mock_resp

        redis_mock = MagicMock()
        wd = AgentWatchdog(redis_mock, prefix="test")
        wd._fail_counts["300"] = 2

        result = wd.process_agent("300")

        assert result == "healthy"
        assert wd._fail_counts["300"] == 0

    @patch('healthcheck.urlopen')
    def test_failing_increments_count(self, mock_urlopen):
        """EF-002 : Échec incrémente le compteur sans restart."""
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("refused")

        redis_mock = MagicMock()
        wd = AgentWatchdog(redis_mock, prefix="test", fail_threshold=3)

        result = wd.process_agent("300")

        assert result == "failing"
        assert wd._fail_counts["300"] == 1

    @patch('healthcheck.subprocess.run')
    @patch('healthcheck.urlopen')
    def test_threshold_triggers_restart(self, mock_urlopen, mock_run):
        """EF-002, CA-002 : 3 échecs consécutifs → restart."""
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("refused")
        mock_run.return_value = MagicMock(returncode=0)

        redis_mock = MagicMock()
        wd = AgentWatchdog(redis_mock, prefix="test", fail_threshold=3)
        wd._fail_counts["300"] = 2  # Will become 3 → threshold

        result = wd.process_agent("300")

        assert result == "restarted"
        assert wd._fail_counts["300"] == 0
        # Verify restart event published
        redis_mock.xadd.assert_called()

    @patch('healthcheck.urlopen')
    def test_circuit_open_blocks_restart(self, mock_urlopen):
        """CA-003 : Circuit ouvert bloque le restart."""
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("refused")

        redis_mock = MagicMock()
        wd = AgentWatchdog(redis_mock, prefix="test", fail_threshold=3,
                           max_restarts=3, breaker_window=300)
        wd._fail_counts["300"] = 2
        wd._circuit_open["300"] = True

        result = wd.process_agent("300")

        assert result == "circuit_open"
        # Should publish critical alert
        xadd_calls = redis_mock.xadd.call_args_list
        assert any("alert:critical" in str(c) for c in xadd_calls)

    @patch('healthcheck.urlopen')
    def test_recovery_resets_circuit(self, mock_urlopen):
        """EF-002 : Agent récupéré réouvre le circuit."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"status": "healthy"}).encode()
        mock_urlopen.return_value = mock_resp

        redis_mock = MagicMock()
        wd = AgentWatchdog(redis_mock, prefix="test")
        wd._fail_counts["300"] = 3
        wd._circuit_open["300"] = True

        result = wd.process_agent("300")

        assert result == "healthy"
        assert wd._circuit_open["300"] is False


class TestWatchdogEvents:
    """CT-002, CT-009 — Publication événements monitoring."""

    def test_publish_event_uses_xtrim(self):
        """CT-009 : xadd avec maxlen=1000, approximate=True."""
        redis_mock = MagicMock()
        wd = AgentWatchdog(redis_mock, prefix="test")

        wd._publish_event("agent_restart", "300", {"reason": "test"})

        call_args = redis_mock.xadd.call_args
        assert call_args.kwargs.get("maxlen") == STREAM_MAXLEN
        assert call_args.kwargs.get("approximate") is True

    def test_publish_event_format(self):
        """CT-002 : Format from/type/agent_id/timestamp/payload."""
        redis_mock = MagicMock()
        wd = AgentWatchdog(redis_mock, prefix="test")

        wd._publish_event("agent_restart", "300", {"reason": "test"})

        call_args = redis_mock.xadd.call_args
        stream = call_args[0][0]
        data = call_args[0][1]
        assert stream == "test:monitoring:restart"
        assert data["from"] == "watchdog"
        assert data["type"] == "agent_restart"
        assert data["agent_id"] == "300"
        assert "timestamp" in data

    def test_publish_alert_stream(self):
        """CT-002 : Alerte publiée sur mi:monitoring:alerts."""
        redis_mock = MagicMock()
        wd = AgentWatchdog(redis_mock, prefix="test")

        wd._publish_alert("critical", "300", "test alert")

        call_args = redis_mock.xadd.call_args
        stream = call_args[0][0]
        data = call_args[0][1]
        assert stream == "test:monitoring:alerts"
        assert data["type"] == "alert:critical"


class TestWatchdogRunCycle:
    """EF-002 — Cycle complet du watchdog."""

    @patch('healthcheck.urlopen')
    def test_run_cycle_returns_results(self, mock_urlopen):
        """EF-002 : run_cycle retourne le statut de chaque agent."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"status": "healthy"}).encode()
        mock_urlopen.return_value = mock_resp

        redis_mock = MagicMock()
        redis_mock.keys.return_value = ["test:agent:300:heartbeat"]
        wd = AgentWatchdog(redis_mock, prefix="test")

        results = wd.run_cycle()

        assert "300" in results
        assert results["300"] == "healthy"
