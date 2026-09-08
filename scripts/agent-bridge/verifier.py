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
import sys
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
LITERAL_MIN_LEN = 4
LITERAL_SUSPECT_THRESHOLD = int(os.environ.get("VERIFY_LITERAL_THRESHOLD", 3))
PLACEHOLDERS = ("__A_RENSEIGNER__", "TODO", "TBD", "FIXME", "(vide)")


def _git(args, cwd):
    return subprocess.run(["git"] + args, cwd=cwd, capture_output=True,
                          text=True, timeout=60)


def _added_string_literals(diff):
    literals = set()
    for line in diff.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        literals.update(re.findall(rf'"([^"\n]{{{LITERAL_MIN_LEN},}})"', line))
        literals.update(re.findall(rf"'([^'\n]{{{LITERAL_MIN_LEN},}})'", line))
    return literals


def literal_specialization(diff, oracle_dir):
    """R4: literals newly added and repeated verbatim in the sealed oracle."""
    base = Path(oracle_dir)
    if not base.is_dir():
        return []
    oracle = []
    for path in base.rglob("*"):
        if path.is_file():
            try:
                oracle.append(path.read_text(errors="ignore"))
            except OSError:
                continue
    joined = "\n".join(oracle)
    suspects = sorted(item for item in _added_string_literals(diff) if item in joined)
    return suspects if len(suspects) >= LITERAL_SUSPECT_THRESHOLD else []


def hacking_rules(cwd=None, oracle_dir=None):
    """Retourne (hacked: bool, raisons: list[str]) sur le diff non commité."""
    cwd = cwd or PROJECT_DIR
    reasons = []
    diff = _git(["diff", "HEAD", "--unified=0"], cwd).stdout
    names = _git(["diff", "HEAD", "--name-only"], cwd).stdout.splitlines()
    untracked = _git(["ls-files", "--others", "--exclude-standard"], cwd).stdout.splitlines()
    names += untracked
    # `git diff HEAD` omet les fichiers non suivis : sans leur contenu R4 se
    # contourne simplement en créant un nouveau fichier spécialisé.
    root = Path(cwd)
    for relative in untracked:
        path = root / relative
        if not path.is_file() or path.stat().st_size > 1_000_000:
            continue
        try:
            diff += "\n" + "\n".join("+" + line for line in path.read_text(
                errors="ignore").splitlines())
        except OSError:
            continue
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
    if oracle_dir:
        suspects = literal_specialization(diff, oracle_dir)
        if suspects:
            preview = ", ".join(repr(item)[:60] for item in suspects[:3])
            reasons.append(f"{len(suspects)} littéraux de l'oracle recopiés: {preview}")
    return (len(reasons) > 0, reasons)


def _contract_text(path):
    return Path(path).read_text(encoding="utf-8", errors="ignore")


def contract_spec(path, project_dir=None):
    candidate = Path(path)
    if not candidate.is_file() or candidate.stat().st_size == 0:
        return False, "fichier absent ou vide"
    text = _contract_text(candidate)
    missing = [h for h in ("## Contexte", "## Critères", "## Hors périmètre") if h not in text]
    placeholders = [p for p in PLACEHOLDERS if p in text]
    return (not missing and not placeholders,
            f"sections_absentes={missing} placeholders={placeholders}")


def contract_inventory(path, project_dir=None):
    candidate = Path(path)
    if not candidate.is_file():
        return False, "fichier absent"
    root = Path(project_dir or PROJECT_DIR).resolve()
    cited = re.findall(r'`([^`]+\.(?:py|md|sh|js|jsx|ts|tsx|yaml|yml|json))`',
                       _contract_text(candidate))
    missing = []
    for item in cited:
        referenced = Path(item)
        referenced = referenced if referenced.is_absolute() else root / referenced
        if not referenced.exists():
            missing.append(item)
    return (bool(cited) and not missing,
            f"citations={len(cited)} absentes={missing[:20]}")


def contract_memory(path, project_dir=None):
    candidate = Path(path)
    if not candidate.is_file():
        return False, "fichier absent"
    text = _contract_text(candidate)
    required = ("**ID**", "**Fichier source**", "**Critères de succès**")
    missing = [field for field in required if field not in text]
    placeholders = [p for p in PLACEHOLDERS if p in text]
    return (not missing and not placeholders,
            f"champs_absents={missing} placeholders={placeholders}")


CONTRACT_VERIFIERS = {
    "spec": contract_spec,
    "inventory": contract_inventory,
    "memory": contract_memory,
}


def run_contract(kind, path, project_dir=None):
    verifier_fn = CONTRACT_VERIFIERS.get(kind)
    if not verifier_fn:
        return False, f"contrat inconnu: {kind}"
    try:
        return verifier_fn(path, project_dir)
    except OSError as exc:
        return False, str(exc)


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
    verify_cmd = task.get("verify_cmd", "")
    oracle_dir = None
    match = re.search(r"(?:^|\s)([^\s;|&]*bench/oracle/[^\s/;|&]+)", verify_cmd)
    if match:
        candidate = Path(match.group(1))
        oracle_dir = candidate if candidate.is_dir() else candidate.parent
    hacked, reasons = hacking_rules(cwd, oracle_dir=oracle_dir)
    if hacked:
        audit(redis_cli, agent_id, task.get("task_id"), "HACK_DETECTED")
        return (False, True, "[verify] anti-hacking:\n- " + "\n- ".join(reasons))
    green, rapport = run_cmd(task["verify_cmd"], cwd)
    if green:
        checkpoint(task.get("task_id", "?"), cwd)
        audit(redis_cli, agent_id, task.get("task_id"), "SCORE 100")
    return (green, False, rapport)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) == 3 and argv[0] == "contract":
        green, detail = run_contract(argv[1], argv[2])
        print(f"[contract] {'GREEN' if green else 'RED'} {argv[1]} {argv[2]} — {detail}")
        return 0 if green else 1
    print("usage: verifier.py contract <spec|inventory|memory> <path>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
