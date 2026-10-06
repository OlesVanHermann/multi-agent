#!/usr/bin/env python3
"""
V3/C0 — Agrège les runs d'un label ; compare à une baseline en deltas
APPARIÉS par tâche + IC bootstrap 95 % (plan §4 : « comparaison appariée
par tâche, deltas + IC »). Stdlib uniquement.

Usage: aggregate.py <label> [baseline_label]

Lit  bench/results/<label>.jsonl (une ligne = un run, produit par collect.py)
Écrit bench/results/aggregate-<label>[-vs-<baseline>].json
"""
import json
import os
import random
import statistics
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(BASE, "bench", "results")
N_BOOTSTRAP = int(os.environ.get("BENCH_BOOTSTRAP", 10000))


def load_runs(label):
    path = os.path.join(RESULTS, f"{label}.jsonl")
    if not os.path.exists(path):
        print(f"Error: {path} introuvable")
        sys.exit(1)
    runs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                runs.append(json.loads(line))
    return runs


def per_task(runs):
    """Moyennes par tâche — l'unité d'appariement du plan."""
    tasks = {}
    for run in runs:
        tasks.setdefault(run["task"], []).append(run)
    stats = {}
    for tid, rs in sorted(tasks.items()):
        judged = [r for r in rs if r.get("success") is not None]
        cycles = [r["cycles_to_green"] for r in rs
                  if r.get("cycles_to_green") is not None]
        stats[tid] = {
            "runs": len(rs),
            "success_rate": (statistics.mean(1 if r["success"] else 0
                                             for r in judged)
                             if judged else None),
            "cycles_to_green": statistics.mean(cycles) if cycles else None,
            "wall_s": statistics.mean(r["wall_s"] for r in rs),
            "retries": statistics.mean(r.get("retries", 0) for r in rs),
            "interventions": sum(r.get("interventions", 0) for r in rs),
            "hacking": any(r.get("hacking_detected") for r in rs),
            "tokens_in": _optional_mean(rs, "tokens_in"),
            "tokens_out": _optional_mean(rs, "tokens_out"),
            "tokens_cached": _optional_mean(rs, "tokens_cached"),
            "usd_est": _optional_mean(rs, "usd_est"),
            "verify_wall_s": _optional_mean(rs, "verify_wall_s"),
            "cost_per_green": _optional_mean(rs, "cost_per_green"),
            "help_requests": sum(r.get("help_requests", 0) for r in rs),
            "help_resolved": sum(r.get("help_resolved", 0) for r in rs),
            "help_notfound": sum(r.get("help_notfound", 0) for r in rs),
            "critic_followed": sum(r.get("critic_followed", 0) for r in rs),
            "critic_ignored": sum(r.get("critic_ignored", 0) for r in rs),
        }
    return stats


def _optional_mean(runs, key):
    values = [run.get(key) for run in runs if run.get(key) is not None]
    return statistics.mean(values) if values else None


def bootstrap_ci(deltas, n=N_BOOTSTRAP):
    """IC 95 % (percentiles) de la moyenne des deltas par tâche."""
    if not deltas:
        return None
    rng = random.Random(42)
    means = sorted(statistics.mean(rng.choices(deltas, k=len(deltas)))
                   for _ in range(n))
    return {"mean": statistics.mean(deltas),
            "ci95": [means[int(0.025 * n)], means[int(0.975 * n)]],
            "n_tasks": len(deltas)}


def paired_deltas(stats, base_stats):
    common = sorted(set(stats) & set(base_stats))
    out = {"common_tasks": common, "metrics": {}}
    for metric in ("success_rate", "cycles_to_green", "wall_s", "retries",
                   "tokens_in", "tokens_out", "tokens_cached", "usd_est",
                   "verify_wall_s", "cost_per_green"):
        deltas = []
        for tid in common:
            a, b = stats[tid].get(metric), base_stats[tid].get(metric)
            if a is not None and b is not None:
                deltas.append(a - b)
        out["metrics"][metric] = bootstrap_ci(deltas)
    return out


def main():
    if len(sys.argv) not in (2, 3):
        print(__doc__)
        sys.exit(1)
    label = sys.argv[1]
    baseline = sys.argv[2] if len(sys.argv) == 3 else None

    runs = load_runs(label)
    stats = per_task(runs)
    report = {"label": label, "per_task": stats}

    print(f"\n=== Banc {label} — {len(stats)} tâche(s) ===")
    for tid, s in stats.items():
        rate = (f"{s['success_rate']:.0%}" if s["success_rate"] is not None
                else "n/a")
        cyc = (f"{s['cycles_to_green']:.1f}" if s["cycles_to_green"] is not None
               else "n/a")
        print(f"  {tid:<24} runs={s['runs']} success={rate:<5} "
              f"cycles={cyc:<5} wall={s['wall_s']:.0f}s "
              f"interv={s['interventions']} hack={s['hacking']}")

    suffix = f"-vs-{baseline}" if baseline else ""
    if baseline:
        base_runs = load_runs(baseline)
        harnesses = {json.dumps(run.get("harness"), sort_keys=True) for run in runs}
        base_harnesses = {json.dumps(run.get("harness"), sort_keys=True) for run in base_runs}
        if harnesses != base_harnesses:
            print("Error: configurations de harnais différentes; comparaison refusée")
            sys.exit(2)
        base_stats = per_task(base_runs)
        report["baseline"] = baseline
        report["paired"] = paired_deltas(stats, base_stats)
        print(f"\n=== Deltas appariés vs {baseline} "
              f"({len(report['paired']['common_tasks'])} tâches communes) ===")
        for metric, ci in report["paired"]["metrics"].items():
            if ci is None:
                print(f"  {metric:<16} n/a")
                continue
            lo, hi = ci["ci95"]
            signif = "*" if lo > 0 or hi < 0 else " "
            print(f"  {metric:<16} Δ={ci['mean']:+.3f}  "
                  f"IC95=[{lo:+.3f}, {hi:+.3f}] {signif}")
        print("  (* : IC95 exclut 0)")

    out = os.path.join(RESULTS, f"aggregate-{label}{suffix}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n→ {out}")


if __name__ == "__main__":
    main()
