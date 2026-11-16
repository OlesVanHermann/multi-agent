"""Banc d'essai sur CLI RÉELS : identifiant de session relevé au démarrage.

Opt-in (lance les vrais Claude Code et Codex) :

    MA_REAL_CLI_BENCH=1 python3 -m pytest tests/test_session_id_real_cli.py -v

Serveur tmux ISOLÉ (TMUX_TMPDIR temporaire) : les sessions des agents ne sont
jamais touchées. Pour chaque moteur :
1. démarrage → engine_status_session_id (commande de statut du CLI) ;
2. /exit → engine_exit_session_id : même identifiant ;
3. reprise de cet identifiant → statut : même identifiant ; session_record_at_start
   écrit <id>.session (profil du process, moteur, identifiant).

Coût : Claude, aucun prompt (une session vide se reprend) ; Codex, un prompt
minimal sur le modèle le moins cher (une session Codex sans échange n'est pas
persistée, sa reprise échouerait). Profils : MA_BENCH_CLAUDE_PROFILE
(claude1a), MA_BENCH_CODEX_PROFILE (codex1a, « Sign in with ChatGPT » exigé
par le préflight de facturation).
"""
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]
ENGINES_PY = BASE / "scripts" / "agent-bridge" / "engines.py"

pytestmark = pytest.mark.skipif(
    os.environ.get("MA_REAL_CLI_BENCH") != "1",
    reason="banc CLI réels : MA_REAL_CLI_BENCH=1")

ENGINE_CASES = (
    ("claude", os.environ.get("MA_BENCH_CLAUDE_PROFILE", "claude1a"), "", "", False),
    ("codex", os.environ.get("MA_BENCH_CODEX_PROFILE", "codex1a"),
     "gpt-5.6-luna", "L", True),
)


@pytest.fixture
def bench():
    root = Path(tempfile.mkdtemp(prefix="sb", dir="/tmp"))   # socket : chemin court
    env = {k: v for k, v in os.environ.items() if k not in ("TMUX", "TMUX_PANE")}
    env["TMUX_TMPDIR"] = str(root)
    (root / "prompts" / "999-bench").mkdir(parents=True)
    (root / "prompts" / "999-bench" / "999-999.md").write_text("# banc\n")
    yield root, env
    subprocess.run(["tmux", "kill-server"], env=env, capture_output=True)
    shutil.rmtree(root, ignore_errors=True)


def sh(env, snippet, timeout=120):
    r = subprocess.run(
        ["bash", "-c", f'cd "{BASE}"; source scripts/engines.sh; '
                       f'source scripts/lib.sh\n{snippet}'],
        capture_output=True, text=True, timeout=timeout, env=env)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def tmux(env, *args):
    return subprocess.run(["tmux", *args], capture_output=True, text=True, env=env)


def marker(cli, key):
    return subprocess.run(["python3", str(ENGINES_PY), "get", key, "--cli", cli],
                          capture_output=True, text=True).stdout.splitlines()


def wait_ready(env, session, cli, timeout=60):
    ready = [m for m in marker(cli, "ready_markers") if m.strip()]
    deadline = time.time() + timeout
    while time.time() < deadline:
        pane = tmux(env, "capture-pane", "-p", "-t", session).stdout
        if any(m in pane for m in ready):
            time.sleep(2)
            return
        time.sleep(0.5)
    raise AssertionError(f"{cli} pas prêt :\n{pane}")


def wait_idle(env, session, cli, timeout=180):
    busy = [m for m in marker(cli, "busy_markers") if m.strip()]
    time.sleep(3)
    deadline = time.time() + timeout
    while time.time() < deadline:
        pane = tmux(env, "capture-pane", "-p", "-t", session).stdout
        if not any(m in pane for m in busy):
            time.sleep(2)
            return
        time.sleep(1)
    raise AssertionError(f"{cli} toujours occupé :\n{pane}")


def launch(env, session, cli, profile, model, effort, resume_id=""):
    rc, cmd, err = sh(env, f'engine_launch_cmd {cli} "$PWD/login" {profile} '
                           f'"{model}" "{effort}" bench-status "{resume_id}"')
    assert rc == 0 and cmd, err
    tmux(env, "send-keys", "-t", session,
         f"cd '{BASE}' && unset CLAUDECODE && {cmd}", "Enter")
    wait_ready(env, session, cli)


@pytest.mark.parametrize("cli,profile,model,effort,needs_exchange", ENGINE_CASES)
def test_session_id_read_at_start_matches_exit_and_resume(
        bench, cli, profile, model, effort, needs_exchange):
    root, env = bench
    if cli == "codex":
        rc, _, err = sh(env, f'engine_codex_preflight "$PWD/login" {profile}')
        assert rc == 0, f"préflight facturation refusé : {err}"
    session = f"bench-{cli}"
    tmux(env, "new-session", "-d", "-s", session, "-x", "140", "-y", "50",
         "bash --norc --noprofile")

    # 1. Démarrage : identifiant lu par la commande de statut.
    launch(env, session, cli, profile, model, effort)
    rc, at_start, err = sh(env, f"engine_status_session_id {session} {cli}")
    assert rc == 0 and at_start, f"statut illisible au démarrage : {err}"

    if needs_exchange:
        tmux(env, "send-keys", "-t", f"{session}:0.0", "-l", "Réponds uniquement OK.")
        time.sleep(0.6)
        tmux(env, "send-keys", "-t", f"{session}:0.0", "Enter")
        wait_idle(env, session, cli)

    # 2. Sortie : même identifiant.
    rc, at_exit, err = sh(env, f"engine_exit_session_id {session} {cli}")
    assert rc == 0 and at_exit == at_start, (at_start, at_exit, err)

    # 3. Reprise : statut identique, fichier écrit avec le profil du process.
    launch(env, session, cli, profile, model, effort, resume_id=at_start)
    rc, recorded, err = sh(
        env, f'session_record_at_start 999-999 {session} {cli} "{root}/prompts"')
    assert rc == 0 and recorded == at_start, (at_start, recorded, err)
    saved = (root / "prompts" / "999-bench" / "999-999.session").read_text()
    assert saved == f"{profile}\n{cli}\n{at_start}\n"
    sh(env, f"engine_exit_cli {session} {cli}")
