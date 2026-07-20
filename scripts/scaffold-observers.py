#!/usr/bin/env python3
"""Installe le Contradictor 2XX et le workflow v3.2 dans un triangle."""

import argparse
import shutil
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


def archive_existing(path, removed):
    if not path.exists() and not path.is_symlink():
        return
    removed.mkdir(parents=True, exist_ok=True)
    destination = removed / f"{int(time.time() * 1000)}-{path.name}"
    path.replace(destination)


def write_from_template(source, destination, replacements, removed):
    archive_existing(destination, removed)
    text = source.read_text()
    for old, new in replacements.items():
        text = text.replace(old, new)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text)


def write_value(destination, value, removed):
    archive_existing(destination, removed)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(value)


def scaffold(base, triangle, directory_name, contradictor_login,
             contradictor_suffix="200", create_workflow=True):
    prompts_root = base / "prompts"
    target = prompts_root / (directory_name or triangle)
    target.mkdir(parents=True, exist_ok=True)
    removed = base / "removed" / "scaffold-observers"
    templates = base / "templates" / "x45" / "prompts"
    agent_id = f"{triangle}-{contradictor_suffix}"
    tail = triangle[1:]
    target_id = f"{triangle}-1{tail}"
    for kind in ("system", "memory", "methodology"):
        write_from_template(
            templates / "echo-200" / f"{kind}.md",
            target / f"{agent_id}-{kind}.md",
            {"Contradictor 200": f"Contradictor {agent_id}",
             "NNN-2XX": agent_id, "NNN-1XX": target_id,
             "NNN-200": agent_id, "NNN": triangle}, removed)
    entry = target / f"{agent_id}.md"
    archive_existing(entry, removed)
    entry.symlink_to(Path("..") / "AGENT.md")

    assignments = {
        agent_id: ("gpt-5-6-sol.model", f"{contradictor_login}.login", "H"),
    }
    for agent_id, (model, login, effort) in assignments.items():
        for ext, source in (("model", model), ("login", login)):
            link = target / f"{agent_id}.{ext}"
            archive_existing(link, removed)
            link.symlink_to(Path("..") / source)
        write_value(target / f"{agent_id}.effort", effort + "\n", removed)

    workflow = None
    if create_workflow:
        workflow_template = base / "templates" / "x45" / "workflows" / "x45-cycle.yaml.template"
        workflow = base / "scripts" / "agent-bridge" / "workflows" / f"x45-cycle-{triangle}.yaml"
        write_from_template(workflow_template, workflow,
                            {f"__TRIANGLE__-{hundreds}00":
                             (f"{triangle}-{triangle}" if hundreds == "3" else f"{triangle}-{hundreds}{tail}")
                             for hundreds in ("1", "3", "5", "7", "8", "9")} |
                            {"__TRIANGLE__": triangle,
                             "__MEMORY__": str(target / f"{triangle}-{triangle}-memory.md"),
                             "__VERIFY__": "pytest -q"}, removed)
    return target, workflow


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("triangle", help="préfixe NNN")
    parser.add_argument("--base", type=Path, default=BASE)
    parser.add_argument("--directory-name")
    parser.add_argument("--contradictor-login", "--echo-login", dest="echo_login",
                        default="login3a")
    parser.add_argument("--contradictor-suffix", "--echo-suffix", dest="echo_suffix",
                        default="200", help="slot Contradictor 2XX")
    parser.add_argument("--skip-workflow", action="store_true")
    args = parser.parse_args()
    if len(args.triangle) != 3 or not args.triangle.isdigit():
        parser.error("triangle doit être NNN")
    if (len(args.echo_suffix) != 3 or not args.echo_suffix.isdigit()
            or not 200 <= int(args.echo_suffix) <= 299):
        parser.error("contradictor-suffix doit appartenir à 2XX")
    target, workflow = scaffold(args.base.resolve(), args.triangle,
                                args.directory_name, args.echo_login,
                                args.echo_suffix, not args.skip_workflow)
    print(f"Prompts: {target}")
    if workflow:
        print(f"Workflow: {workflow}")
    print("Profils à authentifier séparément; aucun service n'a été démarré.")


if __name__ == "__main__":
    main()
