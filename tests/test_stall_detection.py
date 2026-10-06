"""Un silence long est observé sans réveil modèle ni faux timeout métier."""
import time

import pytest

import healthcheck
import wal

AGENT = "300"


def _watchdog(redis_client):
    watchdog = healthcheck.AgentWatchdog(redis_client, stall_threshold=100)

    def fake_send(agent_id, data, message):
        redis_client.xadd(
            f"agent:{agent_id}:inbox",
            {
                "prompt": message,
                "from_agent": "watchdog",
                "event": "STATUS_REQUIRED",
                "task_id": data.get("task_id", ""),
                "cycle": data.get("cycle", ""),
                "correlation_id": data.get("correlation_id", ""),
            })
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    watchdog._send_status_required = fake_send
    return watchdog


def _set_status(redis_client, status):
    redis_client.hset(f"agent:{AGENT}", "status", status)


def _inject(redis_client, event, ts, task_id="t1"):
    """Événement WAL avec ts contrôlé (wal.emit force ts=now)."""
    redis_client.xadd(wal.stream(),
                      {"event": event, "agent_id": AGENT,
                       "task_id": task_id, "ts": int(ts)})


def _alerts(redis_client):
    return [d for _, d in redis_client.xrange("monitoring:alerts")]


@pytest.fixture(autouse=True)
def _env(redis_client, monkeypatch):
    keys = [wal.stream(), f"agent:{AGENT}",
            f"agent:{AGENT}:inbox", f"agent:{AGENT}:control",
            "monitoring:alerts"]
    redis_client.delete(*keys)
    yield
    redis_client.delete(*keys)


class TestCheckStall:
    def test_not_busy_no_stall_and_state_reset(self, redis_client):
        wd = _watchdog(redis_client)
        wd._nudged[AGENT] = "nudged"
        _set_status(redis_client, "idle")
        assert wd._check_stall(AGENT) is None
        assert AGENT not in wd._nudged

    def test_busy_recent_activity_no_stall(self, redis_client):
        wd = _watchdog(redis_client)
        _set_status(redis_client, "busy")
        _inject(redis_client, "task_assigned", time.time())
        assert wd._check_stall(AGENT) is None

    def test_busy_no_wal_no_false_positive(self, redis_client):
        """Bridge v2 (sans WAL) : jamais de nudge intempestif."""
        wd = _watchdog(redis_client)
        _set_status(redis_client, "busy")
        assert wd._check_stall(AGENT) is None

    def test_first_stall_is_observed_without_model_nudge(self, redis_client):
        wd = _watchdog(redis_client)
        _set_status(redis_client, "busy")
        _inject(redis_client, "task_assigned", time.time() - 700)

        assert wd._check_stall(AGENT) == "stalled"
        assert wd._nudged[AGENT] == "observed"
        # alerte warning publiée
        alerts = _alerts(redis_client)
        assert len(alerts) == 1
        assert alerts[0]["type"] == "alert:warning"
        assert redis_client.xrange(f"agent:{AGENT}:inbox") == []
        control = redis_client.xrange(f"agent:{AGENT}:control")
        assert len(control) == 1
        assert control[0][1]["event"] == "TERMINAL_PENDING"
        assert "prompt" not in control[0][1]
        last = wal.last_event(redis_client, None, AGENT)
        assert last[1]["event"] == "terminal_pending"

    def test_first_stall_informs_requester_without_model_wake(self, redis_client):
        """Le demandeur en WAITING constate le silence de sa cible : même
        TERMINAL_PENDING sur SON stream control (drainé au prochain vrai
        tour), jamais dans son inbox — aucun réveil modèle."""
        wd = _watchdog(redis_client)
        redis_client.hset(f"agent:{AGENT}", mapping={
            "status": "busy",
            "current_correlation": "corr-1",
            "current_task_id": "task-1",
            "current_cycle": "3",
            "current_requester": "100",
        })
        _inject(redis_client, "task_assigned", time.time() - 700)

        assert wd._check_stall(AGENT) == "stalled"
        requester_control = redis_client.xrange("agent:100:control")
        assert len(requester_control) == 1
        assert requester_control[0][1]["event"] == "TERMINAL_PENDING"
        assert requester_control[0][1]["owner"] == AGENT
        assert "prompt" not in requester_control[0][1]
        assert redis_client.xrange("agent:100:inbox") == []
        event = redis_client.xrevrange(
            f"agent:{AGENT}:control", count=1)[0][1]
        assert event["event"] == "TERMINAL_PENDING"
        assert event["correlation_id"] == "corr-1"
        assert event["owner"] == AGENT
        assert "prompt" not in event

    def test_after_nudge_window_not_elapsed_stays_silent(self, redis_client):
        """Le nudge vient d'être émis → age < seuil → aucune nouvelle
        alerte, mais l'état 'nudged' est CONSERVÉ (pas réarmé par le
        nudge lui-même)."""
        wd = _watchdog(redis_client)
        _set_status(redis_client, "busy")
        _inject(redis_client, "task_assigned", time.time() - 700)
        wd._check_stall(AGENT)  # nudge

        assert wd._check_stall(AGENT) is None
        assert wd._nudged[AGENT] == "observed"
        assert len(_alerts(redis_client)) == 1  # pas de nouvelle alerte

    def test_repeated_old_observation_does_not_escalate(self, redis_client):
        wd = _watchdog(redis_client)
        wd._nudged[AGENT] = "observed"
        _set_status(redis_client, "busy")
        _inject(redis_client, "terminal_pending", time.time() - 700, task_id="-")

        assert wd._check_stall(AGENT) == "stalled"
        assert wd._nudged[AGENT] == "observed"
        assert _alerts(redis_client) == []

    def test_observed_state_no_alert_spam(self, redis_client):
        wd = _watchdog(redis_client)
        wd._nudged[AGENT] = "observed"
        _set_status(redis_client, "busy")
        _inject(redis_client, "terminal_pending", time.time() - 700, task_id="-")

        assert wd._check_stall(AGENT) == "stalled"
        assert _alerts(redis_client) == []  # silence total

    def test_real_activity_rearms_state_machine(self, redis_client):
        wd = _watchdog(redis_client)
        wd._nudged[AGENT] = "nudged"
        _set_status(redis_client, "busy")
        _inject(redis_client, "verify_red", time.time())  # activité réelle

        assert wd._check_stall(AGENT) is None
        assert AGENT not in wd._nudged

    def test_redis_error_never_breaks_watchdog(self, redis_client):
        wd = _watchdog(redis_client)

        class _Broken:
            def hget(self, *a, **kw):
                raise ConnectionError("boom")

        wd.redis = _Broken()
        assert wd._check_stall(AGENT) is None


class TestProcessAgentIntegration:
    def test_runtime_auth_failure_makes_agent_unavailable(
            self, redis_client, monkeypatch):
        wd = _watchdog(redis_client)
        monkeypatch.setattr(wd, "check_health", lambda a: {
            "status": "degraded",
            "auth_blocked": True,
            "listeners": {
                "redis_listener": {"state": "up"},
                "legacy_listener": {"state": "up"},
            },
        })

        assert wd.process_agent(AGENT) == "auth_blocked"

    def test_live_process_with_dead_consumer_is_not_healthy(
            self, redis_client, monkeypatch):
        wd = _watchdog(redis_client)
        monkeypatch.setattr(wd, "check_health", lambda a: {
            "status": "degraded",
            "listeners": {
                "redis_listener": {"state": "down"},
                "legacy_listener": {"state": "up"},
            },
        })

        assert wd.process_agent(AGENT) == "consumer_down"

    def test_healthy_process_but_stalled_agent(self, redis_client, monkeypatch):
        """Le process répond au /health mais l'agent n'avance plus →
        process_agent remonte 'stalled' au lieu de 'healthy'."""
        wd = _watchdog(redis_client)
        monkeypatch.setattr(wd, "check_health",
                            lambda a: {"status": "healthy"})
        _set_status(redis_client, "busy")
        _inject(redis_client, "task_assigned", time.time() - 700)

        assert wd.process_agent(AGENT) == "stalled"

    def test_healthy_and_active_agent_stays_healthy(self, redis_client, monkeypatch):
        wd = _watchdog(redis_client)
        monkeypatch.setattr(wd, "check_health",
                            lambda a: {"status": "healthy"})
        _set_status(redis_client, "busy")
        _inject(redis_client, "task_assigned", time.time())

        assert wd.process_agent(AGENT) == "healthy"
