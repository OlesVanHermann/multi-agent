"""Suivi d'usage des forfaits : une seule présentation, des seuils de couleur.

Claude Code affiche « N% used » (0 → 100), Codex « N% left » (100 → 0). Le
dashboard présente tout en % UTILISÉ (le collecteur convertit Codex en 100-N)
et colore selon la consigne opérateur du 2026-11-16 : orange à partir de 2/3
utilisés, rouge à partir de 9/10 utilisés.
"""
import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "web" / "frontend"
COMPONENTS = (
    FRONTEND / "src" / "components" / "terminal" / "UsageBars.jsx",
    FRONTEND / "src" / "components" / "KeepAliveSplit.jsx",
)


def _node(expr):
    """Évalue une expression sur le module partagé lib/usage.js (ESM)."""
    script = ("import * as u from './src/lib/usage.js';"
              f"console.log(JSON.stringify({expr}))")
    r = subprocess.run(["node", "--input-type=module", "-e", script],
                       cwd=FRONTEND, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node absent")


@needs_node
@pytest.mark.parametrize("percent,level", [
    (0, "ok"), (66, "ok"), (67, "warn"), (89, "warn"), (90, "crit"), (100, "crit"),
    (66.7, "warn"), (89.5, "crit"), (150, "crit"), (-5, "ok"), ("x", "ok"),
])
def test_thresholds_two_thirds_orange_nine_tenths_red(percent, level):
    assert _node(f"u.usageLevel({json.dumps(percent)})") == level


@needs_node
def test_colors_and_clamped_value():
    assert _node("[u.usageColor(10), u.usageColor(67), u.usageColor(90)]") == [
        "var(--green)", "var(--orange)", "var(--red)"]
    assert _node("[u.usageUsed(150), u.usageUsed(-3), u.usageUsed(40.4)]") == [100, 0, 40]


@needs_node
def test_one_wording_for_claude_and_codex():
    title = _node("u.usageTitle({label: 'Weekly limit', percent: 40, resets: '22:29 on 21 Nov'})")
    assert title == "Weekly limit : 40 % utilisé, 60 % restant — reset 22:29 on 21 Nov"


@pytest.mark.parametrize("path", COMPONENTS, ids=lambda p: p.name)
def test_components_use_the_shared_helper_only(path):
    src = path.read_text()
    assert "from '" in src and "lib/usage'" in src
    for name in ("usageColor(b.percent)", "usageTitle(b)", "usageUsed(b.percent)"):
        assert name in src, name
    # Aucun seuil ni libellé propre au composant : une seule source de vérité.
    assert not re.search(r"percent\s*[<>]=?\s*\d", src)
    assert "% used" not in src


def _load_scheduler():
    path = ROOT / "scripts" / "crontab-scheduler.py"
    spec = importlib.util.spec_from_file_location("crontab_scheduler_usage", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sweep_reads_usage_of_suspended_profiles_with_an_open_session(tmp_path, monkeypatch):
    """Suspendu = ni hello ni session démarrée ; une session keepalive déjà
    ouverte est relevée, sinon les barres restent figées (codex3a au 26/07)."""
    sched = _load_scheduler()
    login, keepalive = tmp_path / "login", tmp_path / "keepalive"
    for profile in ("claude1b", "codex3a", "codex4b"):
        (login / profile).mkdir(parents=True)
    keepalive.mkdir()
    for profile in ("codex3a", "codex4b"):
        (keepalive / f"{profile}.suspended").write_text("")
    monkeypatch.setattr(sched, "LOGIN_DIR", str(login))
    monkeypatch.setattr(sched, "KEEPALIVE_DIR", str(keepalive))
    monkeypatch.setattr(sched, "_cleanup_legacy_keepalive_sessions", lambda: [])
    monkeypatch.setattr(sched, "_cloned_refresh_token_profiles", lambda profiles: set())
    swept, collected = [], []
    monkeypatch.setattr(sched, "_sweep_profile",
                        lambda p: swept.append(p) or {"profile": p, "status": "ok"})

    def collect(profile, wait_timeout=90):
        collected.append(profile)
        return {"status": "ok", "bars": [{"label": "Weekly limit", "percent": 40}]}
    monkeypatch.setattr(sched, "_collect_profile_status", collect)
    open_sessions = {"agent-002-codex3a"}          # codex4b : suspendu, sans session
    monkeypatch.setattr(sched.subprocess, "run", lambda cmd, **kw: SimpleNamespace(
        returncode=0 if cmd[-1] in open_sessions else 1))

    sched._run_sweep()

    assert swept == ["claude1b"]                   # hello seulement hors suspension
    assert collected == ["codex3a"]                # relevé sans hello
    report = json.loads((keepalive / "sweep_report.json").read_text())
    assert report["profiles"]["codex3a"]["suspended"] is True
    assert "codex4b" not in report["profiles"]
