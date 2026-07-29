"""Model/effort selection regressions for duplicate numeric prompt directories."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

import engines
from web.backend.multi_agent.models import EffortUpdate, LoginModelUpdate
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


# ── Règle opérateur 2026-07-29 : le MOTEUR décide de l'application ──────
# Modèle à moteur constant et effort → à chaud, automatiquement.
# Changement de moteur (ou de login) → enregistré, redémarrage requis,
# JAMAIS automatique : c'est une décision de l'utilisateur.

def _model_fixture(tmp_path, model_file, model_id):
    prompts = tmp_path / "prompts"
    agent_dir = prompts / "334-dev-voip"
    agent_dir.mkdir(parents=True)
    for name, ident in (("opus-5", "claude-opus-5"),
                        ("sonnet-5", "claude-sonnet-5"),
                        ("gpt-5-6-sol", "gpt-5.6-sol")):
        (prompts / f"{name}.model").write_text(ident + "\n")
    (prompts / "default.model").symlink_to("opus-5.model")
    (agent_dir / "334-334.model").symlink_to(f"../{model_file}.model")
    (agent_dir / "334-334.effort").write_text("M\n")
    return prompts, agent_dir


def _record_calls(monkeypatch, tmp_path, alive=True):
    """Session vivante et libre ; enregistre les commandes lancées."""
    calls = []

    async def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        if cmd[:2] == ["tmux", "has-session"]:
            return SimpleNamespace(returncode=0 if alive else 1,
                                   stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(config_router.cfg, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config_router, "_run_subprocess", fake_run)
    monkeypatch.setattr(config_router.state, "redis_pool", None)
    return calls


def test_model_change_within_same_engine_is_applied_hot(tmp_path, monkeypatch):
    """claude-opus-5 → claude-sonnet-5 : même CLI, on change dans le TUI."""
    _model_fixture(tmp_path, "opus-5", "claude-opus-5")
    calls = _record_calls(monkeypatch, tmp_path)

    result = asyncio.run(config_router.update_login_model(
        LoginModelUpdate(agent_id="334-334", type="model", value="sonnet-5")))

    assert result["engine_changed"] is False
    assert result["restart_required"] is False
    assert result["applied"] is True
    assert result["deferred"] is False
    assert any("engine_apply_model_effort" in " ".join(c) for c in calls), (
        "le modèle doit être appliqué au TUI de la session en cours")


def test_engine_switch_is_deferred_and_never_restarts(tmp_path, monkeypatch):
    """claude-* → gpt-* : autre binaire, autre profil. On enregistre et on
    dit que le redémarrage appartient à l'utilisateur."""
    _model_fixture(tmp_path, "opus-5", "claude-opus-5")
    calls = _record_calls(monkeypatch, tmp_path)

    result = asyncio.run(config_router.update_login_model(
        LoginModelUpdate(agent_id="334-334", type="model",
                         value="gpt-5-6-sol")))

    assert result["engine_changed"] is True
    assert result["restart_required"] is True
    assert result["applied"] is False
    assert result["deferred"] is True
    assert "redémarrage requis" in result["reason"]
    assert not any("engine_apply_model_effort" in " ".join(c) for c in calls)
    assert not any("restart" in " ".join(c) for c in calls), (
        "aucun redémarrage ne doit jamais être déclenché automatiquement")


def test_login_change_requires_restart_too(tmp_path, monkeypatch):
    """Le profil est passé au CLI à son lancement : pas de bascule à chaud."""
    prompts, _agent_dir = _model_fixture(tmp_path, "opus-5", "claude-opus-5")
    (prompts / "login3a.login").write_text("login3a\n")
    calls = _record_calls(monkeypatch, tmp_path)

    result = asyncio.run(config_router.update_login_model(
        LoginModelUpdate(agent_id="334-334", type="login", value="login3a")))

    assert result["restart_required"] is True
    assert result["applied"] is False
    assert not any("engine_apply_model_effort" in " ".join(c) for c in calls)


def test_hot_apply_is_shared_between_model_and_effort_routes():
    """Une seule implémentation du chemin d'application à chaud."""
    source = (Path(config_router.__file__)).read_text()
    assert source.count("engine_apply_model_effort") == 1, (
        "le chemin d'application doit rester unique (_apply_to_live_tui)")
