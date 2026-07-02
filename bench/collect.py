#!/usr/bin/env python3
"""
V3/C0 — Collecte les métriques d'UN run de banc → bench/results/<label>.jsonl.

Usage: collect.py <label> <task_id> <run_i> <t0_epoch> <t1_epoch> <v2|v3>

Sources (annexe §4.2) :
  - WAL {MA_PREFIX}:wal        : cycles_to_green (verify_red + 1), retries,
                                 interventions (escalations), hacking_detected
  - {MA_PREFIX}:completion     : done_declared (origin=agent — l'auto-
                                 déclaration, à confronter au verdict oracle)
  - oracle post-hoc            : success — bench/oracle/<tid>/verify.sh rejoué
                                 sur project/ APRÈS le run, pour v2 comme v3
                                 (verdict uniforme, jamais montré à l'agent)

La fenêtre [t0, t1] isole ce run des runs précédents (le WAL est append-only).
"""
import json
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "scripts", "agent-bridge"))

import redis

import wal

MA_PREFIX = os.environ.get("MA_PREFIX", "A")
PROJECT_DIR = os.environ.get("PROJECT_DIR", os.path.join(BASE, "project"))
ORACLE_TIMEOUT = int(os.environ.get("BENCH_ORACLE_TIMEOUT", 600))


def _redis():
    return redis.Redis(host=os.environ.get("REDIS_HOST", "localhost"),
                       port=int(os.environ.get("REDIS_PORT", 6379)),
                       password=os.environ.get("REDIS_PASSWORD") or None,
                       decode_responses=True)


def oracle_success(task_id):
    """Rejoue l'oracle post-hoc. Verdict de vérité du banc (O5)."""
    script = os.path.join(BASE, "bench", "oracle", task_id, "verify.sh")
    if not os.path.exists(script):
        return None
    try:
        res = subprocess.run(["bash", script], cwd=PROJECT_DIR,
                             capture_output=True, timeout=ORACLE_TIMEOUT)
        return res.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def wal_metrics(r, task_id, t0, t1):
    reds = greens = escalations = 0
    hacking = False
    for _, data in r.xrange(wal.stream(MA_PREFIX)):
        try:
            ts = int(data.get("ts", 0))
        except (TypeError, ValueError):
            continue
        if data.get("task_id") != task_id or not t0 <= ts <= t1:
            continue
        event = data.get("event")
        if event == "verify_red":
            reds += 1
        elif event == "verify_green":
            greens += 1
        elif event in ("verify_escalation", "escalation"):
            escalations += 1
            if data.get("motif") == "hacking":
                hacking = True
    return reds, greens, escalations, hacking


def completion_metrics(r, task_id, t0, t1):
    """done_declared : l'agent a émis DONE/SCORE (origin=agent) dans la
    fenêtre. Sans task_id côté done.sh, le filtre est temporel."""
    declared = False
    for _, data in r.xrange(f"{MA_PREFIX}:completion"):
        try:
            ts = int(data.get("timestamp", 0))
        except (TypeError, ValueError):
            continue
        if not t0 <= ts <= t1:
            continue
        if data.get("task_id") not in (None, task_id):
            continue
        if data.get("origin") == "agent":
            declared = True
    return declared


def main():
    if len(sys.argv) != 7:
        print(__doc__)
        sys.exit(1)
    label, task_id, run_i = sys.argv[1], sys.argv[2], int(sys.argv[3])
    t0, t1, mode = int(sys.argv[4]), int(sys.argv[5]), sys.argv[6]

    reds = greens = escalations = 0
    hacking = False
    declared = False
    try:
        r = _redis()
        reds, greens, escalations, hacking = wal_metrics(r, task_id, t0, t1)
        declared = completion_metrics(r, task_id, t0, t1)
    except redis.RedisError as exc:
        print(f"[collect] WARN: Redis indisponible ({exc}) — "
              f"métriques WAL absentes", file=sys.stderr)

    success = oracle_success(task_id)
    record = {
        "label": label,
        "task": task_id,
        "run": run_i,
        "mode": mode,
        "success": success,
        "done_declared": declared,
        "verify_green": greens > 0,
        "cycles_to_green": reds + 1 if greens else None,
        "retries": reds,
        "interventions": escalations,
        "hacking_detected": hacking,
        "wall_s": t1 - t0,
        "ts": int(time.time()),
    }

    out_dir = os.path.join(BASE, "bench", "results")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"{label}.jsonl")
    with open(out, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"[collect] {task_id} run {run_i}: success={success} "
          f"cycles={record['cycles_to_green']} → {out}")


if __name__ == "__main__":
    main()
