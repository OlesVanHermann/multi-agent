"""Rapport obligatoire de fin de tour au coordinateur du triangle."""

import importlib.util
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def shell(command):
    return subprocess.run(
        ["bash", "-c", command], cwd=ROOT, capture_output=True, text=True)


def test_triangle_master_is_derived_without_hardcoded_examples():
    result = shell(
        "source scripts/lib.sh; triangle_master_id 712-845")
    assert result.returncode == 0
    assert result.stdout.strip() == "712-145"


def test_triangle_master_rejects_self_and_global_ids():
    assert shell("source scripts/lib.sh; triangle_master_id 712-145").returncode
    assert shell("source scripts/lib.sh; triangle_master_id 712").returncode


def test_report_script_uses_non_interactive_supervision_stream():
    source = (ROOT / "scripts" / "report-master.sh").read_text()
    assert 'DELIVERY_STATE="STORED"' in source
    assert 'agent:${MASTER_ID}:reports' in source
    assert 'event "MASTER_REPORT"' in source
    assert '\n    prompt ' not in source
    assert "last_master_report_id" in source


def test_upgrade_merges_hook_without_replacing_existing_hooks(tmp_path):
    target = tmp_path / "settings.json"
    target.write_text(json.dumps({
        "hooks": {"Stop": [{"hooks": [{
            "type": "command", "command": "existing-check"
        }]}]},
        "env": {"KEPT": "yes"},
    }))
    path = ROOT / "patch" / "merge-communication-hooks.py"
    first = subprocess.run(
        ["python3", str(path), str(target)], capture_output=True, text=True)
    second = subprocess.run(
        ["python3", str(path), str(target)], capture_output=True, text=True)
    assert first.returncode == second.returncode == 0
    data = json.loads(target.read_text())
    commands = [
        hook["command"]
        for group in data["hooks"]["Stop"]
        for hook in group["hooks"]
    ]
    assert "existing-check" in commands
    assert sum("claude-stop-guard.py" in command for command in commands) == 1
    assert data["env"]["KEPT"] == "yes"
