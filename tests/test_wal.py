"""
V3/C2 — wal.py : write-ahead log d'orchestration.

emit / last_event / open_task sur un redis-server éphémère (fixture
conftest redis_client). Le WAL est un outil d'audit et de diagnostic :
le state_file du workflow_engine reste la source de vérité de reprise.
"""
import time

import pytest

import wal

PREFIX = "TWAL"


@pytest.fixture(autouse=True)
def _clean(redis_client):
    redis_client.delete(wal.stream(PREFIX))
    yield
    redis_client.delete(wal.stream(PREFIX))


class TestEmit:
    def test_emit_writes_event(self, redis_client):
        wal.emit(redis_client, PREFIX, "task_assigned", "300",
                 "t1", source="redis")
        entries = redis_client.xrange(wal.stream(PREFIX))
        assert len(entries) == 1
        _, data = entries[0]
        assert data["event"] == "task_assigned"
        assert data["agent_id"] == "300"
        assert data["task_id"] == "t1"
        assert data["source"] == "redis"
        assert abs(int(data["ts"]) - time.time()) < 5

    def test_emit_defaults_task_id_dash(self, redis_client):
        wal.emit(redis_client, PREFIX, "nudge", "300")
        _, data = redis_client.xrange(wal.stream(PREFIX))[0]
        assert data["task_id"] == "-"

    def test_emit_truncates_long_fields(self, redis_client):
        wal.emit(redis_client, PREFIX, "verify_red", "300", "t1",
                 rapport="x" * 2000)
        _, data = redis_client.xrange(wal.stream(PREFIX))[0]
        assert len(data["rapport"]) == 500


class TestLastEvent:
    def test_returns_most_recent_for_agent(self, redis_client):
        wal.emit(redis_client, PREFIX, "task_assigned", "300", "t1")
        wal.emit(redis_client, PREFIX, "task_assigned", "301", "tX")
        wal.emit(redis_client, PREFIX, "verify_red", "300", "t1", retry=1)
        found = wal.last_event(redis_client, PREFIX, "300")
        assert found is not None
        _, data = found
        assert data["event"] == "verify_red"

    def test_filtered_by_event_types(self, redis_client):
        wal.emit(redis_client, PREFIX, "task_assigned", "300", "t1")
        wal.emit(redis_client, PREFIX, "verify_red", "300", "t1")
        found = wal.last_event(redis_client, PREFIX, "300",
                               events=("task_assigned",))
        assert found[1]["event"] == "task_assigned"

    def test_none_for_unknown_agent(self, redis_client):
        wal.emit(redis_client, PREFIX, "task_assigned", "300", "t1")
        assert wal.last_event(redis_client, PREFIX, "999") is None

    def test_pagination_past_batch_boundary(self, redis_client, monkeypatch):
        monkeypatch.setattr(wal, "_BATCH", 2)
        wal.emit(redis_client, PREFIX, "task_assigned", "300", "vieux")
        for i in range(5):
            wal.emit(redis_client, PREFIX, "verify_red", "301", f"t{i}")
        found = wal.last_event(redis_client, PREFIX, "300")
        assert found is not None
        assert found[1]["task_id"] == "vieux"


class TestOpenTask:
    """Diagnostic post-crash : tâche assignée jamais clôturée (green ou
    escalation). Le consumer group redélivre de toute façon (A4) — ce
    helper alimente le log de reprise du bridge."""

    def test_unclosed_task_is_open(self, redis_client):
        wal.emit(redis_client, PREFIX, "task_assigned", "300", "t42")
        assert wal.open_task(redis_client, PREFIX, "300") == "t42"

    def test_green_closes(self, redis_client):
        wal.emit(redis_client, PREFIX, "task_assigned", "300", "t42")
        wal.emit(redis_client, PREFIX, "verify_green", "300", "t42")
        assert wal.open_task(redis_client, PREFIX, "300") is None

    def test_escalation_closes(self, redis_client):
        wal.emit(redis_client, PREFIX, "task_assigned", "300", "t42")
        wal.emit(redis_client, PREFIX, "verify_escalation", "300", "t42",
                 motif="budget_retries")
        assert wal.open_task(redis_client, PREFIX, "300") is None

    def test_reassignment_reopens(self, redis_client):
        """Crash simulé : t1 clôturée, t2 assignée puis plus rien."""
        wal.emit(redis_client, PREFIX, "task_assigned", "300", "t1")
        wal.emit(redis_client, PREFIX, "verify_green", "300", "t1")
        wal.emit(redis_client, PREFIX, "task_assigned", "300", "t2")
        wal.emit(redis_client, PREFIX, "verify_red", "300", "t2", retry=1)
        assert wal.open_task(redis_client, PREFIX, "300") == "t2"

    def test_v2_task_without_id_not_reported(self, redis_client):
        wal.emit(redis_client, PREFIX, "task_assigned", "300")  # task_id="-"
        assert wal.open_task(redis_client, PREFIX, "300") is None

    def test_other_agents_ignored(self, redis_client):
        wal.emit(redis_client, PREFIX, "task_assigned", "301", "tX")
        assert wal.open_task(redis_client, PREFIX, "300") is None

    def test_pagination_past_batch_boundary(self, redis_client, monkeypatch):
        monkeypatch.setattr(wal, "_BATCH", 2)
        for i in range(5):
            wal.emit(redis_client, PREFIX, "task_assigned", "300", f"t{i}")
            wal.emit(redis_client, PREFIX, "verify_green", "300", f"t{i}")
        wal.emit(redis_client, PREFIX, "task_assigned", "300", "ouverte")
        assert wal.open_task(redis_client, PREFIX, "300") == "ouverte"
