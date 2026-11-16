#!/usr/bin/env python3
"""C4 — admission non destructive d'une méthodologie candidate."""

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "scripts" / "agent-bridge"))
sys.path.insert(0, str(BASE / "bench"))

import aggregate
import redis
import wal


def decision(candidate_label, reference_label):
    candidate_runs = aggregate.load_runs(candidate_label)
    reference_runs = aggregate.load_runs(reference_label)
    candidate_harness = {json.dumps(r.get("harness"), sort_keys=True) for r in candidate_runs}
    reference_harness = {json.dumps(r.get("harness"), sort_keys=True) for r in reference_runs}
    if candidate_harness != reference_harness:
        raise ValueError("configurations de harnais différentes")
    paired = aggregate.paired_deltas(
        aggregate.per_task(candidate_runs), aggregate.per_task(reference_runs))
    success = paired["metrics"]["success_rate"]
    if not success:
        raise ValueError("aucune tâche appariée avec verdict")
    low, high = success["ci95"]
    if low > 0:
        verdict = "accepted"
    elif high < 0:
        verdict = "rejected"
    else:
        verdict = "archived"
    return verdict, paired


def _unique(directory, name):
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return directory / f"{stamp}-{name}"


def apply(verdict, active, candidate, metadata, removed_root=None):
    active = Path(active)
    candidate = Path(candidate)
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    archive = active.parent / ".archive"
    archive.mkdir(parents=True, exist_ok=True)
    candidate_copy = _unique(archive, candidate.name)
    shutil.copy2(candidate, candidate_copy)
    candidate_copy.with_suffix(candidate_copy.suffix + ".json").write_text(
        json.dumps(metadata, indent=2) + "\n")
    if verdict == "accepted":
        if active.exists() or active.is_symlink():
            shutil.copy2(active, _unique(archive, "previous-" + active.name),
                         follow_symlinks=True)
        candidate.replace(active)
    elif verdict == "rejected":
        removed = Path(removed_root or BASE / "removed") / "methodology-rejected"
        removed.mkdir(parents=True, exist_ok=True)
        candidate.replace(_unique(removed, candidate.name))
    return candidate_copy


def emit(event, agent_id, task_id, **fields):
    client = redis.Redis(host=os.environ.get("REDIS_HOST", "localhost"),
                         port=int(os.environ.get("REDIS_PORT", 6379)),
                         password=os.environ.get("REDIS_PASSWORD") or None,
                         decode_responses=True)
    try:
        wal.emit(client, None, event,
                 agent_id, task_id, **fields)
    except redis.RedisError:
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("active")
    parser.add_argument("candidate")
    parser.add_argument("reference_label")
    parser.add_argument("candidate_label")
    parser.add_argument("--agent", required=True)
    parser.add_argument("--task", default="methodology-gate")
    args = parser.parse_args()
    verdict, paired = decision(args.candidate_label, args.reference_label)
    metadata = {"verdict": verdict, "reference": args.reference_label,
                "candidate": args.candidate_label, "paired": paired}
    artifact = apply(verdict, args.active, args.candidate, metadata)
    event = {"accepted": "methodology_accepted", "archived": "methodology_archived",
             "rejected": "methodology_rejected"}[verdict]
    emit(event, args.agent, args.task, artifact=artifact)
    print(json.dumps({"verdict": verdict, "artifact": str(artifact)}))


if __name__ == "__main__":
    main()
