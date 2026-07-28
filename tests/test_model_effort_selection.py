"""Model/effort selection regressions for duplicate numeric prompt directories."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

import engines
from web.backend.multi_agent.models import EffortUpdate
from web.backend.multi_agent.prompts import _find_agent_config
from web.backend.multi_agent.routers import config as config_router
from web.backend.multi_agent.routers.config import (
    _config_owner_dir,
    _effort_levels_for_model,
    _link_path_for,
)


def _fixture_dirs(tmp_path: Path) -> tuple[Path, Path, Path]:
    prompts = tmp_path / "prompts"
    hub = prompts / "000-hub-master"
    active = prompts / "000-super-master"
    hub.mkdir(parents=True)
    active.mkdir()
    (prompts / "fable-5.model").write_text("claude-fable-5\n")
    (active / "000.model").symlink_to("../fable-5.model")
    return prompts, hub, active


def test_config_resolver_selects_directory_that_owns_override(tmp_path):
    prompts, _hub, active = _fixture_dirs(tmp_path)

    assert _find_agent_config(prompts, "000", "model") == active / "000.model"
    assert engines.resolve_agent_config(
        prompts, "000", "model") == "claude-fable-5"
    assert engines.agent_engine(prompts, "000") == "claude"
    assert _config_owner_dir(prompts, "000") == active
    assert _link_path_for(prompts, "000", "effort") == (
        active / "000.effort",
        "../",
    )


def test_config_resolver_rejects_two_exact_overrides(tmp_path):
    prompts, hub, _active = _fixture_dirs(tmp_path)
    (hub / "000.model").symlink_to("../fable-5.model")

    with pytest.raises(RuntimeError, match="multiple .model overrides"):
        _find_agent_config(prompts, "000", "model")
    with pytest.raises(RuntimeError, match="multiple .model overrides"):
        engines.resolve_agent_config(prompts, "000", "model")


@pytest.mark.parametrize(
    "model,levels",
    [
        ("claude-fable-5", ["L", "M", "H", "X", "U"]),
        ("claude-opus-5", ["L", "M", "H", "X", "U"]),
        ("claude-sonnet-5", ["L", "M", "H", "X", "U"]),
        ("gpt-5.6-sol", ["L", "M", "H", "X", "U"]),
        ("claude-opus-4-8", ["L", "M", "H"]),
    ],
)
def test_effort_levels_follow_model_capabilities(model, levels):
    assert _effort_levels_for_model(model) == levels


def test_removing_effort_override_reapplies_inherited_level(tmp_path, monkeypatch):
    prompts = tmp_path / "prompts"
    agent_dir = prompts / "334-dev-voip"
    agent_dir.mkdir(parents=True)
    (prompts / "334.effort").write_text("X\n")
    override = agent_dir / "334-234.effort"
    override.write_text("H\n")

    async def no_live_session(*_args, **_kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    monkeypatch.setattr(config_router.cfg, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config_router, "_run_subprocess", no_live_session)

    result = asyncio.run(config_router.update_effort(
        EffortUpdate(agent_id="334-234", level="")))

    assert not override.exists()
    assert result["status"] == "removed"
    assert result["level"] == "X"
    assert result["configured_level"] is None
    assert result["applied"] is False
    assert result["reason"] == "session absente"
