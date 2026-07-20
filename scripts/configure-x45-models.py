#!/usr/bin/env python3
"""F4/F5 — matérialise une affectation bi-moteur dans un triangle quelconque."""

import argparse
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent

ROLE_DEFAULTS = {
    "developer": ("300", "gpt-5-6-sol", "login1a", "H"),
    "observer": ("500", "fable-5", "login2a", "H"),
    "coach": ("800", "gpt-5-6-sol", "login2a", "H"),
    "curator": ("700", "fable-5", "login4a", "H"),
    "master": ("100", "fable-5", "login3a", "H"),
    "architect": ("900", "fable-5", "login4a", "H"),
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("triangle")
    parser.add_argument("--base", type=Path, default=BASE)
    parser.add_argument("--prompt-dir")
    for role, (suffix, model, login, effort) in ROLE_DEFAULTS.items():
        parser.add_argument(f"--{role}-suffix")
        parser.add_argument(f"--{role}-model", default=model)
        parser.add_argument(f"--{role}-login", default=login)
        parser.add_argument(f"--{role}-effort", default=effort, choices=("L", "M", "H"))
    args = parser.parse_args()
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
