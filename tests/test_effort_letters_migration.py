"""Migration des lettres d'effort (décision opérateur, 2026-10-09).

Avant : L=medium M=high H=xhigh X=max U=ultracode
Après : L=low M=medium H=high X=xhigh MAX=max (+ .ultracode on|off)
"""

import subprocess
import sys
from pathlib import Path

MIGRATOR = Path(__file__).resolve().parent.parent / "patch" / "migrate-effort-letters.py"


def _run(base, *args):
    return subprocess.run([sys.executable, str(MIGRATOR), "--base", str(base), *args],
                          capture_output=True, text=True, timeout=30)


def _tree(tmp_path):
    prompts = tmp_path / "prompts"
    agent = prompts / "300-dev"
    agent.mkdir(parents=True)
    for name, old in (("300-100", "L"), ("300-200", "M"), ("300-300", "H"),
                      ("300-400", "X"), ("300-500", "U")):
        (agent / f"{name}.effort").write_text(old + "\n")
    (prompts / "default.effort").write_text("M\n")
    (prompts / "301.effort").symlink_to("default.effort")
    return prompts, agent


def test_check_writes_nothing(tmp_path):
    prompts, agent = _tree(tmp_path)
    result = _run(tmp_path, "--check")
    assert "updated=6" in result.stdout
    assert (agent / "300-200.effort").read_text() == "M\n"
    assert not (prompts / ".effort-letters-v2").exists()


def test_apply_converts_keeps_real_level_and_is_idempotent(tmp_path):
    prompts, agent = _tree(tmp_path)
    result = _run(tmp_path, "--apply")
    assert result.returncode == 0, result.stderr
    expected = {"300-100": "M", "300-200": "H", "300-300": "X",
                "300-400": "MAX", "300-500": "MAX"}
    for name, new in expected.items():
        assert (agent / f"{name}.effort").read_text() == new + "\n"
    assert (agent / "300-500.ultracode").read_text() == "on\n"
    assert not (agent / "300-400.ultracode").exists()
    assert (prompts / "default.effort").read_text() == "H\n"
    # Le lien n'est pas réécrit : il suit sa cible convertie.
    assert (prompts / "301.effort").is_symlink()
    assert (prompts / "301.effort").read_text() == "H\n"
    backups = list((tmp_path / "removed").glob("*_effort-letters"))
    assert len(backups) == 1
    assert (backups[0] / "prompts" / "300-dev" / "300-200.effort").read_text() == "M\n"
    assert (prompts / ".effort-letters-v2").exists()

    again = _run(tmp_path, "--apply")
    assert "updated=0" in again.stdout
    assert (agent / "300-200.effort").read_text() == "H\n"


def test_upgrade_runs_migration_before_creators_and_topologies():
    source = (MIGRATOR.parent / "upgrade.sh").read_text()
    apply_part = source.split("# 6. Migrations", 1)[1]
    assert apply_part.index("migrate-effort-letters.py") < apply_part.index("# 6b.1 Créateurs")
    assert apply_part.index("migrate-effort-letters.py") < apply_part.index("# 6d. Topologies")
