#!/usr/bin/env python3
"""F4/F5 — matérialise une affectation bi-moteur dans un triangle quelconque."""

import argparse
import re
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent

ROLE_DEFAULTS = {
    "master": ("100", "fable-5", "login3a", "H"),
    "contradictor": ("200", "gpt-5-6-sol", "login3a", "H"),
    "developer": ("300", "gpt-5-6-sol", "login1a", "H"),
    "observer": ("500", "fable-5", "login2a", "H"),
    "curator": ("700", "fable-5", "login4a", "H"),
    "coach": ("800", "gpt-5-6-sol", "login2a", "H"),
    "architect": ("900", "fable-5", "login4a", "H"),
}

ROLE_BY_HUNDRED = {
    "1": "master", "2": "contradictor", "3": "developer",
    "5": "observer", "7": "curator", "8": "coach", "9": "architect",
}


def archive(path, removed):
    if path.exists() or path.is_symlink():
        removed.mkdir(parents=True, exist_ok=True)
        path.replace(removed / f"{int(time.time() * 1000)}-{path.name}")


def configure(base, triangle, prompt_dir, assignments):
    root = base / "prompts"
    target = root / prompt_dir
    if not target.is_dir():
        raise FileNotFoundError(target)
    removed = base / "removed" / "model-assignment"
    for role, (suffix, model, login, effort) in assignments.items():
        for source in (root / f"{model}.model", root / f"{login}.login"):
            if not source.exists():
                raise FileNotFoundError(f"{role}: configuration absente: {source}")
        agent = f"{triangle}-{suffix}"
        for ext, source in (("model", f"{model}.model"), ("login", f"{login}.login")):
            destination = target / f"{agent}.{ext}"
            archive(destination, removed)
            destination.symlink_to(Path("..") / source)
        effort_path = target / f"{agent}.effort"
        archive(effort_path, removed)
        effort_path.write_text(effort + "\n")


def suffix_for_triangle(role_suffix, triangle):
    """Décline le rôle X00 avec les deux derniers chiffres du triangle."""
    return role_suffix[0] + triangle[1:]


def topology_assignments(directory, triangle):
    """Construit la matrice depuis les rôles réellement présents."""
    assignments = {}
    pattern = re.compile(rf"^{re.escape(triangle)}-(\d{{3}})-system\.md$")
    for path in sorted(directory.glob("*-system.md")):
        match = pattern.match(path.name)
        if not match:
            continue
        suffix = match.group(1)
        role = ROLE_BY_HUNDRED.get(suffix[0])
        if role is None and suffix == triangle:
            role = "developer"
        if role is None:
            continue
        _default_suffix, model, login, effort = ROLE_DEFAULTS[role]
        assignments[f"{role}:{suffix}"] = (suffix, model, login, effort)
    return assignments


def configure_all(base, check=False):
    changed = []
    prompts = base / "prompts"
    for directory in sorted(path for path in prompts.iterdir() if path.is_dir()):
        match = re.match(r"^(\d{3})(?:-|$)", directory.name)
        marker = directory / "agent.type"
        if not match or not marker.is_symlink():
            continue
        if marker.readlink().name not in {"agent_x45.type", "agent_z21.type"}:
            continue
        triangle = match.group(1)
        assignments = topology_assignments(directory, triangle)
        for _role, (suffix, model, login, effort) in assignments.items():
            agent = f"{triangle}-{suffix}"
            expected = {
                "model": Path("..") / f"{model}.model",
                "login": Path("..") / f"{login}.login",
            }
            effort_path = directory / f"{agent}.effort"
            mismatch = any(
                not (directory / f"{agent}.{ext}").is_symlink()
                or (directory / f"{agent}.{ext}").readlink() != target
                for ext, target in expected.items()
            ) or not effort_path.is_file() or effort_path.read_text(errors="replace") != effort + "\n"
            if mismatch:
                changed.append(agent)
        if not check and any(item.startswith(f"{triangle}-") for item in changed):
            configure(base, triangle, directory.name, assignments)
    return changed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("triangle", nargs="?")
    parser.add_argument("--base", type=Path, default=BASE)
    parser.add_argument("--prompt-dir")
    parser.add_argument("--all", action="store_true", help="configure tous les x45/z21 existants")
    parser.add_argument("--check", action="store_true", help="lister sans modifier")
    for role, (suffix, model, login, effort) in ROLE_DEFAULTS.items():
        parser.add_argument(f"--{role}-suffix")
        parser.add_argument(f"--{role}-model", default=model)
        parser.add_argument(f"--{role}-login", default=login)
        parser.add_argument(f"--{role}-effort", default=effort, choices=("L", "M", "H"))
    args = parser.parse_args()
    if args.all:
        changed = configure_all(args.base.resolve(), check=args.check)
        for agent in changed:
            print(agent)
        print(f"updated={len(changed)}")
        return
    if not args.triangle:
        parser.error("triangle requis sauf avec --all")
    if len(args.triangle) != 3 or not args.triangle.isdigit():
        parser.error("triangle doit être NNN")
    assignments = {}
    for role, (role_suffix, _model, _login, _effort) in ROLE_DEFAULTS.items():
        suffix = getattr(args, f"{role}_suffix")
        if not suffix:
            suffix = args.triangle if role == "developer" else suffix_for_triangle(role_suffix, args.triangle)
        assignments[role] = (suffix,
                             getattr(args, f"{role}_model"),
                             getattr(args, f"{role}_login"),
                             getattr(args, f"{role}_effort"))
    configure(args.base.resolve(), args.triangle, args.prompt_dir or args.triangle,
              assignments)
    print("Affectation matérialisée sans démarrer les agents.")
    print("Les profils Codex doivent être authentifiés via Sign in with ChatGPT.")


if __name__ == "__main__":
    main()
