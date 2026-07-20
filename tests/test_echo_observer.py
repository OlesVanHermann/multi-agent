import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from web.backend.multi_agent import config as cfg
from web.backend.multi_agent import echo as echo_core
from web.backend.multi_agent import state
from web.backend.multi_agent.models import EchoObservationRequest
from web.backend.multi_agent.routers.echo import observe


class FakeRedis:
    def __init__(self):
        self.writes = []

    async def xrevrange(self, name, count):
        return [("1-0", {"event": "verify_green", "agent_id": "345-300"})]

    async def xadd(self, name, fields, **kwargs):
        self.writes.append((name, fields, kwargs))
        return "2-0"


@pytest.fixture
def echo_tree(tmp_path, monkeypatch):
    agent = tmp_path / "prompts" / "345"
    agent.mkdir(parents=True)
    (agent / "345-300.md").write_text("intention\n")
    (agent / "345-300.history").write_text("one\ntwo\nthree\n")
    logs = tmp_path / "logs" / "345-300"
    logs.mkdir(parents=True)
    (logs / "events.jsonl").write_text("event-one\nevent-two\n")
    (logs / "bridge.log").write_text("bridge-one\n")
    monkeypatch.setattr(cfg, "BASE_DIR", tmp_path)
    monkeypatch.setattr(cfg, "ECHO_OBSERVER_ENABLED", True)
    monkeypatch.setattr(
        echo_core, "_capture_agent_pane",
        lambda *args, **kwargs: asyncio.sleep(
            0, result=SimpleNamespace(returncode=0, stdout="pane evidence")
        ),
    )
    fake = FakeRedis()
    monkeypatch.setattr(state, "redis_pool", fake)
    return tmp_path, fake


def test_tail_lines_is_bounded(tmp_path):
    path = tmp_path / "history"
    path.write_text("1\n2\n3\n")
    assert echo_core._tail_lines(path, 2) == ["2", "3"]


def test_prompt_evidence_rejects_symlink_outside_prompts(tmp_path, monkeypatch):
    prompts = tmp_path / "prompts" / "345"
    prompts.mkdir(parents=True)
    secret = tmp_path / "setup" / "secrets.cfg"
    secret.parent.mkdir()
    secret.write_text("do-not-read")
    (prompts / "345-300.md").symlink_to(secret)
    monkeypatch.setattr(cfg, "BASE_DIR", tmp_path)
    assert echo_core._prompt_evidence("345-300") == []


def test_observe_writes_only_echo_artifact_and_never_dispatches(echo_tree):
    root, fake = echo_tree
    result = asyncio.run(
        observe(
            "345-200",
            EchoObservationRequest(
                target_agent="345-300", pane_lines=99999, history_lines=2,
                log_lines=2, stream_entries=2,
            ),
        )
    )
    artifact = root / result["artifact"]
    payload = json.loads(artifact.read_text())
    assert artifact.is_relative_to(root / "pool-requests" / "knowledge" / "echo")
    assert result["dispatched"] is False
    assert result["workflow_transition"] is False
    assert payload["limits"]["pane_lines"] == echo_core.MAX_PANE_LINES
    assert payload["evidence"]["inputs"]["history"] == ["two", "three"]
    assert payload["authority"]["rank"] == 5
    assert [item[1]["event"] for item in fake.writes] == [
        "echo_requested", "echo_snapshot_ready"
    ]


def test_observe_rejects_cross_triangle(echo_tree):
    with pytest.raises(HTTPException) as error:
        asyncio.run(observe("345-200", EchoObservationRequest(target_agent="346-300")))
    assert error.value.status_code == 400


def test_observe_accepts_any_2xx_slot(echo_tree):
    result = asyncio.run(observe("345-217", EchoObservationRequest(target_agent="345-300")))
    assert result["status"] == "snapshot_ready"


def test_observe_is_hidden_when_disabled(echo_tree, monkeypatch):
    monkeypatch.setattr(cfg, "ECHO_OBSERVER_ENABLED", False)
    with pytest.raises(HTTPException) as error:
        asyncio.run(observe("345-200", EchoObservationRequest(target_agent="345-300")))
    assert error.value.status_code == 404
