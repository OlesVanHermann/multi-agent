"""patch/retire-models.py : retrait des modèles du catalogue pendant l'upgrade.

Jamais de suppression (déplacement dans la sauvegarde), jamais de retrait d'un
modèle encore référencé par un lien : l'agent démarrerait sans erreur sur le
modèle par défaut du CLI.
"""
import os
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
SCRIPT = BASE / "patch" / "retire-models.py"
UPGRADE = BASE / "patch" / "upgrade.sh"


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                          capture_output=True, text=True, timeout=30)


def _catalog(tmp_path):
    prompts = tmp_path / "prompts"
    agent = prompts / "300-demo"
    agent.mkdir(parents=True)
    for name, ident in (("opus-4-8", "claude-opus-4-8"), ("fable-5", "claude-fable-5"),
                        ("gpt-5-5", "gpt-5.5"), ("opus-5-5", "claude-opus-5-5")):
        (prompts / f"{name}.model").write_text(ident + "\n")
    # default.model garde opus-4-8 en vie, un agent garde fable-5.
    (prompts / "default.model").symlink_to("./opus-4-8.model")
    (agent / "300-300.model").symlink_to("../fable-5.model")
    return prompts


def test_check_moves_nothing(tmp_path):
    prompts = _catalog(tmp_path)
    r = run("--check", prompts)
    assert r.returncode == 0
    assert "[RETIRE] prompts/gpt-5-5.model" in r.stdout
    assert "retired=1 manual=2" in r.stdout
    assert (prompts / "gpt-5-5.model").exists()


def test_apply_moves_unreferenced_and_keeps_referenced(tmp_path):
    prompts = _catalog(tmp_path)
    backup = tmp_path / "backup"
    r = run("--backup", backup, prompts)
    assert r.returncode == 0
    assert not (prompts / "gpt-5-5.model").exists()
    assert (backup / "gpt-5-5.model").read_text() == "gpt-5.5\n", "déplacé, jamais supprimé"
    assert (prompts / "opus-4-8.model").exists(), "référencé par default.model"
    assert (prompts / "fable-5.model").exists(), "référencé par un agent"
    assert "[MANUAL] prompts/opus-4-8.model" in r.stdout and "default.model" in r.stdout
    assert "300-demo/300-300.model" in r.stdout
    assert (prompts / "default.model").read_text() == "claude-opus-4-8\n"
    assert (prompts / "opus-5-5.model").exists(), "modèle non retiré intact"
    # Idempotent.
    again = run("--backup", backup, prompts)
    assert "retired=0 manual=2" in again.stdout


def test_apply_requires_backup_dir(tmp_path):
    prompts = _catalog(tmp_path)
    assert run(prompts).returncode == 2
    assert (prompts / "gpt-5-5.model").exists()


def test_upgrade_runs_retirement_in_plan_and_apply():
    source = UPGRADE.read_text()
    assert source.count('MODEL_RETIRE="$TEMP_DIR/patch/retire-models.py"') == 2
    assert '"$MODEL_RETIRE" --check ./prompts' in source
    assert '"$MODEL_RETIRE" --backup "$BACKUP_DIR/prompts-retired" ./prompts' in source
    # Le retrait suit la copie du catalogue (6b.2) : rien ne le recrée ensuite.
    assert source.index('log_ok "configurations modèles/logins v3.2"') < \
        source.index('"$MODEL_RETIRE" --backup')


# ── Fable 5.1 remplacé par Fable 5.2 (décision opérateur, 2026-11-10) ──

def _fable_catalog(tmp_path, with_successor=True):
    prompts = tmp_path / "prompts"
    agent = prompts / "300-demo"
    agent.mkdir(parents=True)
    names = [("fable-5-1", "claude-fable-5-1"), ("opus-5-5", "claude-opus-5-5")]
    if with_successor:
        names.append(("fable-5-2", "claude-fable-5-2"))
    for name, ident in names:
        (prompts / f"{name}.model").write_text(ident + "\n")
        (prompts / f"{name}.advisor").symlink_to(f"{name}.model")
    (prompts / "default.advisor").symlink_to("fable-5-1.advisor")
    (agent / "300-300.model").symlink_to("../fable-5-1.model")
    (agent / "300-300.advisor").symlink_to("../fable-5-1.advisor")
    (prompts / "301.model").symlink_to("./fable-5-1.model")
    (prompts / "302.model").write_text("claude-fable-5-1\n")   # copie texte
    (prompts / "303.advisor").write_text("fable-5-1\n")        # ancien format
    (prompts / "304.model").symlink_to("opus-5-5.model")       # non concerné
    return prompts


def test_replacement_dry_run_plans_everything_and_changes_nothing(tmp_path):
    # Dry-run d'upgrade : fable-5-2 n'est pas encore copié dans prompts/ (6b.2).
    prompts = _fable_catalog(tmp_path, with_successor=False)
    r = run("--check", prompts)
    assert r.returncode == 0
    assert "replaced=6 retired=2 manual=0" in r.stdout, r.stdout
    assert "[REPLACE] prompts/300-demo/300-300.advisor → ../fable-5-2.advisor" in r.stdout
    assert "[RETIRE] prompts/fable-5-1.model" in r.stdout
    assert os.readlink(prompts / "300-demo" / "300-300.model") == "../fable-5-1.model"
    assert (prompts / "fable-5-1.model").exists()


def test_replacement_repoints_links_rewrites_text_and_retires_old(tmp_path):
    prompts = _fable_catalog(tmp_path)
    backup = tmp_path / "backup"
    r = run("--backup", backup, prompts)
    assert r.returncode == 0, r.stderr
    assert "replaced=6 retired=2 manual=0" in r.stdout, r.stdout
    assert os.readlink(prompts / "default.advisor") == "fable-5-2.advisor"
    assert os.readlink(prompts / "300-demo" / "300-300.model") == "../fable-5-2.model"
    assert os.readlink(prompts / "300-demo" / "300-300.advisor") == "../fable-5-2.advisor"
    assert os.readlink(prompts / "301.model") == "./fable-5-2.model"
    assert (prompts / "302.model").read_text() == "claude-fable-5-2\n"
    assert (prompts / "303.advisor").read_text() == "fable-5-2\n"
    assert os.readlink(prompts / "304.model") == "opus-5-5.model"
    assert (prompts / "300-demo" / "300-300.model").read_text() == "claude-fable-5-2\n"
    # L'ancien catalogue est déplacé, jamais supprimé ; les originaux sauvegardés.
    assert not os.path.lexists(prompts / "fable-5-1.model")
    assert not os.path.lexists(prompts / "fable-5-1.advisor")
    assert (backup / "fable-5-1.model").read_text() == "claude-fable-5-1\n"
    assert os.readlink(backup / "replaced" / "300-demo" / "300-300.model") == "../fable-5-1.model"
    assert (backup / "replaced" / "302.model").read_text() == "claude-fable-5-1\n"
    # Idempotent.
    again = run("--backup", backup, prompts)
    assert "replaced=0 retired=0 manual=0" in again.stdout, again.stdout


def test_replacement_without_successor_keeps_old_model(tmp_path):
    """Sans fable-5-2 dans prompts/, rien n'est repointé ni retiré : l'agent
    démarrerait sans erreur sur le modèle par défaut du CLI."""
    prompts = _fable_catalog(tmp_path, with_successor=False)
    r = run("--backup", tmp_path / "backup", prompts)
    assert r.returncode == 0
    assert "replaced=0" in r.stdout and "[MANUAL]" in r.stdout
    assert os.readlink(prompts / "300-demo" / "300-300.model") == "../fable-5-1.model"
    assert (prompts / "fable-5-1.model").exists()
    assert (prompts / "302.model").read_text() == "claude-fable-5-1\n"
