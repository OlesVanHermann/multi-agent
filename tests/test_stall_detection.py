"""
V3/C2 — Détection de stall (healthcheck.AgentWatchdog._check_stall).

Machine à états : busy + WAL silencieux > seuil → nudge (warning + message
inbox, le nudge WAL réarme le compteur pour une fenêtre COMPLÈTE) →
toujours silencieux → alerte critique + WAL escalation, puis silence
(état 'escalated', pas de spam). Toute activité réelle réarme.
"""
import time

import pytest

import healthcheck
import wal

PREFIX = "TSTALL"
MON_PREFIX = "TSTALLMON"
AGENT = "300"


def _watchdog(redis_client):
    return healthcheck.AgentWatchdog(redis_client, prefix=MON_PREFIX,
                                     stall_threshold=100)


def _set_status(redis_client, status):
    redis_client.hset(f"{PREFIX}:agent:{AGENT}", "status", status)


def _inject(redis_client, event, ts, task_id="t1"):
    """Événement WAL avec ts contrôlé (wal.emit force ts=now)."""
    redis_client.xadd(wal.stream(PREFIX),
                      {"event": event, "agent_id": AGENT,
                       "task_id": task_id, "ts": int(ts)})


def _alerts(redis_client):
    return [d for _, d in redis_client.xrange(f"{MON_PREFIX}:monitoring:alerts")]


@pytest.fixture(autouse=True)
def _env(redis_client, monkeypatch):
    monkeypatch.setattr(healthcheck, "MA_PREFIX", PREFIX)
    keys = [wal.stream(PREFIX), f"{PREFIX}:agent:{AGENT}",
            f"{PREFIX}:agent:{AGENT}:inbox",
            f"{MON_PREFIX}:monitoring:alerts"]
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

    def test_first_stall_nudges(self, redis_client):
        wd = _watchdog(redis_client)
        _set_status(redis_client, "busy")
        _inject(redis_client, "task_assigned", time.time() - 700)

        assert wd._check_stall(AGENT) == "stalled"
        assert wd._nudged[AGENT] == "nudged"
        # alerte warning publiée
        alerts = _alerts(redis_client)
        assert len(alerts) == 1
        assert alerts[0]["type"] == "alert:warning"
        # message de nudge dans l'inbox
        inbox = redis_client.xrange(f"{PREFIX}:agent:{AGENT}:inbox")
        assert len(inbox) == 1
        assert inbox[0][1]["from_agent"] == "watchdog"
        assert inbox[0][1]["prompt"].startswith("FROM:watchdog|")
        # le nudge est journalisé dans le WAL (réarme le compteur)
        last = wal.last_event(redis_client, PREFIX, AGENT)
        assert last[1]["event"] == "nudge"

    def test_after_nudge_window_not_elapsed_stays_silent(self, redis_client):
        """Le nudge vient d'être émis → age < seuil → aucune nouvelle
        alerte, mais l'état 'nudged' est CONSERVÉ (pas réarmé par le
        nudge lui-même)."""
        wd = _watchdog(redis_client)
        _set_status(redis_client, "busy")
        _inject(redis_client, "task_assigned", time.time() - 700)
        wd._check_stall(AGENT)  # nudge

        assert wd._check_stall(AGENT) is None
        assert wd._nudged[AGENT] == "nudged"
        assert len(_alerts(redis_client)) == 1  # pas de nouvelle alerte

    def test_full_window_after_nudge_escalates(self, redis_client):
        wd = _watchdog(redis_client)
        wd._nudged[AGENT] = "nudged"
        _set_status(redis_client, "busy")
        _inject(redis_client, "nudge", time.time() - 700, task_id="-")

        assert wd._check_stall(AGENT) == "stalled"
        assert wd._nudged[AGENT] == "escalated"
        alerts = _alerts(redis_client)
        assert len(alerts) == 1
        assert alerts[0]["type"] == "alert:critical"
        # escalade journalisée dans le WAL
        last = wal.last_event(redis_client, PREFIX, AGENT,
                              events=("escalation",))
        assert last[1]["motif"] == "stall"

    def test_escalated_state_no_alert_spam(self, redis_client):
        wd = _watchdog(redis_client)
        wd._nudged[AGENT] = "escalated"
        _set_status(redis_client, "busy")
        _inject(redis_client, "escalation", time.time() - 700, task_id="-")

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
