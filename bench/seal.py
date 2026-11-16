#!/usr/bin/env python3
"""D3 — crée un clone shallow scellé et son manifeste de harnais."""

import argparse
import json
import subprocess
import time
from pathlib import Path


def seal(source, destination, tag, run, mode, network):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists():
        archived = destination.parents[2] / "removed" / "bench-sandbox"
        archived.mkdir(parents=True, exist_ok=True)
        destination.replace(archived / f"{int(time.time() * 1000)}-{destination.name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "--depth", "1", "--branch", tag,
                    f"file://{source}", str(destination)], check=True)
    harness = {"sealed_git": True, "sealed_net": bool(network),
               "base_tag": tag, "run": run, "mode": mode}
    (destination / ".harness.json").write_text(json.dumps(harness, indent=2) + "\n")
    return harness


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("tag")
    parser.add_argument("--run", type=int, required=True)
    parser.add_argument("--mode", required=True)
    parser.add_argument("--network", action="store_true")
    args = parser.parse_args()
    seal(args.source, args.destination, args.tag, args.run, args.mode, args.network)
    print(args.destination.resolve())


if __name__ == "__main__":
    main()
