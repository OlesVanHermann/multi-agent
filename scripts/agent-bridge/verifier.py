#!/usr/bin/env python3
"""
verifier.py — V3/C1 : la complétion se prouve, ne se déclare pas.

Appelé par le bridge (agent.py) quand une tâche porte un verify_cmd :
  1. règles déterministes anti-hacking sur le diff git (rapides, gratuites) ;
  2. exécution du verify_cmd (timeout, capture) ;
  3. vert  -> checkpoint git + audit stream completion (origin=verify)
     rouge -> rapport d'échec renvoyé au bridge (qui décide retry/escalade).

Une tâche SANS verify_cmd ne passe jamais ici (flux v2 inchangé).
Étage optionnel (hors v3-core) : juge LLM échantillonné — hook à brancher ici.
"""
import os
import re
import subprocess
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PROJECT_DIR = os.environ.get("PROJECT_DIR", str(BASE_DIR / "project"))
VERIFY_TIMEOUT = int(os.environ.get("VERIFY_TIMEOUT", 300))
RAPPORT_MAX = 4000

# Chemins que seul 945/l'humain peut modifier (défense complétée par les
# permissions.deny des profils workers — double barrière)
FORBIDDEN_PATHS = ("pool-requests/tests/", "bench/oracle/", "spec/acceptance/")
SKIP_MARKERS = (r"@pytest\.mark\.skip", r"@pytest\.mark\.xfail",
                r"unittest\.skip", r"\.skip\(", r"it\.skip", r"xdescribe")


def _git(args, cwd):
    return subprocess.run(["git"] + args, cwd=cwd, capture_output=True,
                          text=True, timeout=60)


def hacking_rules(cwd=None):
    """Retourne (hacked: bool, raisons: list[str]) sur le diff non commité."""
    cwd = cwd or PROJECT_DIR
    reasons = []
    diff = _git(["diff", "HEAD", "--unified=0"], cwd).stdout
    names = _git(["diff", "HEAD", "--name-only"], cwd).stdout.splitlines()
    names += _git(["ls-files", "--others", "--exclude-standard"], cwd).stdout.splitlines()
    for p in names:
        if any(p.startswith(f) or f.rstrip("/") + "/" in p for f in FORBIDDEN_PATHS):
            reasons.append(f"écriture interdite: {p}")
    removed_asserts = len(re.findall(r"^-.*\bassert\b", diff, re.M))
    added_asserts = len(re.findall(r"^\+.*\bassert\b", diff, re.M))
    if removed_asserts > 3 and added_asserts == 0:
        reasons.append(f"{removed_asserts} assertions supprimées, 0 ajoutée")
    for pat in SKIP_MARKERS:
        if re.search(rf"^\+.*{pat}", diff, re.M):
            reasons.append(f"marqueur de skip ajouté: {pat}")
    return (len(reasons) > 0, reasons)


def run_cmd(verify_cmd, cwd=None):
    """Exécute le harnais. Retourne (green: bool, rapport <= RAPPORT_MAX c)."""
    cwd = cwd or PROJECT_DIR
    try:
        p = subprocess.run(verify_cmd, shell=True, cwd=cwd,
                           capture_output=True, text=True,
                           timeout=VERIFY_TIMEOUT)
        out = (p.stdout + "\n" + p.stderr)[-RAPPORT_MAX:]
        return (p.returncode == 0, out)
    except subprocess.TimeoutExpired:
        return (False, f"[verify] timeout après {VERIFY_TIMEOUT}s")


def checkpoint(task_id, cwd=None):
    """Commit de checkpoint après verify vert (base des rollbacks). Best-effort."""
    cwd = cwd or PROJECT_DIR
    _git(["add", "-A"], cwd)
    _git(["commit", "-m",
          f"[v3-checkpoint] task={task_id} verify=green ts={int(time.time())}"],
         cwd)


def audit(redis_cli, agent_id, task_id, signal, origin="verify"):
    """Journalise dans le stream de complétion — seul origin=verify fait foi
    sur une tâche à verify_cmd (le SCORE origin=agent devient consultatif)."""
    redis_cli.xadd("completion",
                   {"from": str(agent_id), "to": "-", "signal": signal,
                    "task_id": str(task_id or "-"), "origin": origin,
                    "timestamp": int(time.time())},
                   maxlen=1000, approximate=True)


def run(task, redis_cli, agent_id, cwd=None):
    """Point d'entrée bridge. Retourne (green, hacked, rapport)."""
    cwd = cwd or PROJECT_DIR
    hacked, reasons = hacking_rules(cwd)
    if hacked:
        audit(redis_cli, agent_id, task.get("task_id"), "HACK_DETECTED")
        return (False, True, "[verify] anti-hacking:\n- " + "\n- ".join(reasons))
    green, rapport = run_cmd(task["verify_cmd"], cwd)
    if green:
        checkpoint(task.get("task_id", "?"), cwd)
        audit(redis_cli, agent_id, task.get("task_id"), "SCORE 100")
    return (green, False, rapport)
