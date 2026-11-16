"""TMPDIR privé des moteurs qui nettoient leur propre répertoire temporaire.

Constat mx81 (2026-10-10) : neuf Codex démarrés ensemble avec TMPDIR=/tmp ont
supprimé les répertoires d'outils $TMPDIR/arg0/* les uns des autres
(apply_patch, wrapper sandbox). Chaque agent ou session keepalive Codex reçoit
donc son propre TMPDIR ; Claude est inchangé.
"""
import os
import subprocess
import sys

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ENGINES_SH = os.path.join(BASE, "scripts", "engines.sh")
sys.path.insert(0, os.path.join(BASE, "scripts", "agent-bridge"))

import engines  # noqa: E402


def sh(snippet):
    env = {k: v for k, v in os.environ.items()
           if k not in ("OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ALLOW_API_KEY")}
    r = subprocess.run(["bash", "-c", f'source "{ENGINES_SH}"\n{snippet}'],
                       capture_output=True, text=True, timeout=20, env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_codex_agent_gets_a_private_tmpdir():
    out = sh("engine_launch_cmd codex /L codex1a gpt-5.6-sol M 348-248")
    assert "TMPDIR=/tmp/codex-348-248 " in out
    # Répertoire créé par la commande lancée elle-même, puis exec du CLI.
    assert """sh -c 'mkdir -p "$TMPDIR" && exec "$0" "$@"' codex """ in out
    # Les verrous de facturation restent en place.
    assert out.startswith("env -u OPENAI_API_KEY -u CODEX_API_KEY ")
    assert "forced_login_method=chatgpt" in out


def test_wrapper_prefix_covers_the_cli():
    """agent.sh préfixe la commande par CLAUDE_WRAPPER (confinement OS, cf.
    README) : un `&&` de premier niveau (`mkdir … && codex`) ne confinerait que
    mkdir. Aucun `&&` hors de la chaîne entre apostrophes du `sh -c`."""
    out = sh("engine_launch_cmd codex /L codex1a gpt-5.6-sol M 348-248")
    unquoted = out.split("'")[0::2]
    assert not any("&&" in part or ";" in part for part in unquoted), out


def test_resumed_codex_keeps_its_private_tmpdir():
    sid = "01a1c626-0661-78b1-8b9e-c786c964e58b"
    out = sh(f'engine_launch_cmd codex /L codex1a "" "" 300-301 {sid}')
    assert "TMPDIR=/tmp/codex-300-301 " in out
    assert f"""exec "$0" "$@"' codex resume {sid} """ in out


def test_claude_and_legacy_calls_are_unchanged():
    assert "TMPDIR" not in sh("engine_launch_cmd claude /L claude1a claude-opus-5 M 000")
    legacy = sh("engine_launch_cmd codex /L codex1a gpt-5.6-sol")
    assert "TMPDIR" not in legacy and legacy.startswith("env -u ")


def test_unsafe_owner_is_ignored():
    for owner in ("../x", "a b", "a;rm", ""):
        assert sh(f"engine_private_tmpdir codex '{owner}'") == ""
        assert engines.private_tmpdir("codex", owner) == ""


def test_shell_and_python_layers_agree():
    for cli, owner in (("codex", "300"), ("codex", "keepalive-codex1a"),
                       ("claude", "300")):
        assert sh(f"engine_private_tmpdir {cli} {owner}") == \
            engines.private_tmpdir(cli, owner)
