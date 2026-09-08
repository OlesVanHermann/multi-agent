#!/usr/bin/env python3
"""C5 — exécute les quatre bras d'ablation sans muter les prompts actifs."""

import argparse
import json
import os
import subprocess
import time
from pathlib import Path


def run_arm(command, memory, methodology, cwd, timeout):
    env = os.environ.copy()
    env["MA_ABLATION_MEMORY"] = str(Path(memory).resolve())
    env["MA_ABLATION_METHODOLOGY"] = str(Path(methodology).resolve())
    started = time.monotonic()
    result = subprocess.run(command, shell=True, cwd=cwd, env=env,
                            capture_output=True, text=True, timeout=timeout)
    return {"green": result.returncode == 0, "returncode": result.returncode,
            "wall_s": round(time.monotonic() - started, 6),
            "output": (result.stdout + "\n" + result.stderr)[-4000:]}


def attribute(arms):
    if arms["B"]["green"] and not arms["C"]["green"]:
        return "curator"
    if arms["C"]["green"] and not arms["B"]["green"]:
        return "coach"
    if not any(arm["green"] for arm in arms.values()):
        return "contract"
    return "non_conclusive"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--memory-current", required=True)
    parser.add_argument("--memory-previous", required=True)
    parser.add_argument("--method-current", required=True)
    parser.add_argument("--method-previous", required=True)
    parser.add_argument("--verify", required=True)
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    combinations = {
        "A": (args.memory_current, args.method_current),
        "B": (args.memory_previous, args.method_current),
        "C": (args.memory_current, args.method_previous),
        "D": (args.memory_previous, args.method_previous),
    }
    arms = {name: run_arm(args.verify, memory, method, args.cwd, args.timeout)
            for name, (memory, method) in combinations.items()}
    report = {"schema": "multi-agent.ablation.v1", "arms": arms,
              "attribution": attribute(arms)}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"attribution": report["attribution"], "output": str(output)}))


if __name__ == "__main__":
    main()
