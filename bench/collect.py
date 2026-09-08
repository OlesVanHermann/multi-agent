#!/usr/bin/env python3
"""
V3/C0 — Collecte les métriques d'UN run de banc → bench/results/<label>.jsonl.

Usage: collect.py <label> <task_id> <run_i> <t0_epoch> <t1_epoch> <v2|v3>

Sources (annexe §4.2) :
  - WAL wal                    : cycles_to_green (verify_red + 1), retries,
                                 interventions (escalations), hacking_detected
  - completion                 : done_declared (origin=agent — l'auto-
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
    totals = {"tokens_in": 0, "tokens_out": 0, "tokens_cached": 0,
              "usd_est": 0.0, "verify_wall_s": 0.0}
    observed = set()
    observation = {"help_requests": 0, "help_resolved": 0,
                   "help_notfound": 0, "critic_followed": 0,
                   "critic_ignored": 0}
    for _, data in r.xrange(wal.stream()):
        try:
            ts = int(data.get("ts", 0))
        except (TypeError, ValueError):
            continue
        if data.get("task_id") != task_id or not t0 <= ts <= t1:
            continue
        event = data.get("event")
        if event == "help_request":
            observation["help_requests"] += 1
        elif event in observation:
            observation[event] += 1
        if event in ("verify_red", "verify_green", "verify_escalation"):
            for key in totals:
                if data.get(key) not in (None, ""):
                    try:
                        totals[key] += float(data[key])
                        observed.add(key)
                    except (TypeError, ValueError):
                        pass
        if event == "verify_red":
            reds += 1
        elif event == "verify_green":
            greens += 1
        elif event in ("verify_escalation", "escalation"):
            escalations += 1
            if data.get("motif") == "hacking":
                hacking = True
    for key in ("tokens_in", "tokens_out", "tokens_cached"):
        if key in observed:
            totals[key] = int(totals[key])
    return reds, greens, escalations, hacking, totals, observed, observation


def completion_metrics(r, task_id, t0, t1):
    """done_declared : l'agent a émis DONE/SCORE (origin=agent) dans la
    fenêtre. Sans task_id côté done.sh, le filtre est temporel."""
    declared = False
    for _, data in r.xrange("completion"):
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
    totals = {"tokens_in": 0, "tokens_out": 0, "tokens_cached": 0,
              "usd_est": 0.0, "verify_wall_s": 0.0}
    observed = set()
    observation = {"help_requests": 0, "help_resolved": 0,
                   "help_notfound": 0, "critic_followed": 0,
                   "critic_ignored": 0}
    try:
        r = _redis()
        reds, greens, escalations, hacking, totals, observed, observation = wal_metrics(
            r, task_id, t0, t1)
        declared = completion_metrics(r, task_id, t0, t1)
    except redis.RedisError as exc:
        print(f"[collect] WARN: Redis indisponible ({exc}) — "
              f"métriques WAL absentes", file=sys.stderr)

    success = oracle_success(task_id)
    harness_path = os.path.join(PROJECT_DIR, ".harness.json")
    harness = None
    if os.path.isfile(harness_path):
        try:
            with open(harness_path, encoding="utf-8") as handle:
                harness = json.load(handle)
        except (OSError, ValueError):
            harness = {"invalid": True}
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
        "tokens_in": totals["tokens_in"] if "tokens_in" in observed else None,
        "tokens_out": totals["tokens_out"] if "tokens_out" in observed else None,
        "tokens_cached": totals["tokens_cached"] if "tokens_cached" in observed else None,
        "usd_est": totals["usd_est"] if "usd_est" in observed else None,
        "verify_wall_s": totals["verify_wall_s"],
        "cost_per_green": (totals["usd_est"] if success and "usd_est" in observed
                           else None),
        "harness": harness,
        **observation,
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
