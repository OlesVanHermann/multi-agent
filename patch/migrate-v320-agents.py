#!/usr/bin/env python3
"""Migre les topologies projet vers v3.2 sans démarrer les agents.

- mono historique -> paire 1XX + Contradictor 2XX ;
- x45/z21 sans 2XX -> ajout du Contradictor local ;
- topologies déjà migrées -> no-op.

Les écritures sont déléguées aux scaffolders publics, qui archivent chaque
homonyme dans removed/. Les cas ambigus sont rapportés, jamais devinés.
"""

import argparse
import importlib.util
import json
import re
from pathlib import Path


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def directory_type(directory):
    marker = directory / "agent.type"
    if marker.is_symlink():
        target = marker.readlink().name
        for kind in ("mono", "x45", "z21"):
            if f"agent_{kind}.type" == target:
                return kind
    if (directory / "mono-pair.json").is_file():
        return "mono"
    systems = list(directory.glob("*-system.md"))
    # Sans marqueur, n'inférer un triangle que si sa structure minimale est
    # complète. Un ancien prompt Developer isolé n'est pas une topologie à
    # migrer et ne doit pas bloquer tout l'upgrade.
    prefix = group_prefix(directory)
    if (systems and prefix
            and list(directory.glob(f"{prefix}-1??-system.md"))
            and (directory / f"{prefix}-{prefix}-system.md").is_file()):
        return "x45"
    legacy = directory / f"{directory.name}.md"
    if legacy.is_file():
        return "mono"
    return None


def group_prefix(directory):
    match = re.match(r"^(\d{3})(?:-|$)", directory.name)
    return match.group(1) if match else None


def role_ids(directory, prefix, hundred):
    pattern = re.compile(rf"^{re.escape(prefix)}-({hundred}\d{{2}})-system\.md$")
    return sorted(match.group(1) for path in directory.glob("*-system.md")
                  if (match := pattern.match(path.name)))


def already_has_contradictor(directory, prefix):
    return bool(role_ids(directory, prefix, "2"))


def plan(base):
    actions = []
    manual = []
    prompts = base / "prompts"
    if not prompts.is_dir():
        return actions, ["prompts/: répertoire absent"]
    for directory in sorted(path for path in prompts.iterdir() if path.is_dir()):
        prefix = group_prefix(directory)
        if not prefix or prefix == "000":
            continue
        kind = directory_type(directory)
        if kind not in {"mono", "x45", "z21"}:
            continue
        if already_has_contradictor(directory, prefix):
            continue
        if kind == "mono":
            canonical = directory / f"{directory.name}.md"
            systems = list(directory.glob(f"{prefix}-1??-system.md"))
            if not canonical.is_file() and len(systems) != 1:
                manual.append(f"{directory.relative_to(base)}: principal mono ambigu")
                continue
            actions.append(("mono", prefix, directory.name, None, None))
            continue
        masters = role_ids(directory, prefix, "1")
        if len(masters) != 1:
            manual.append(f"{directory.relative_to(base)}: {len(masters)} Master 1XX détecté(s)")
            continue
        main_system = directory / f"{prefix}-{prefix}-system.md"
        if not main_system.is_file():
            manual.append(f"{directory.relative_to(base)}: Developer {prefix}-{prefix} absent")
            continue
        master_suffix = masters[0]
        contradictor_suffix = "2" + master_suffix[1:]
        actions.append((kind, prefix, directory.name, master_suffix, contradictor_suffix))
    return actions, manual


def apply(base, actions):
    mono = load_module(base / "scripts" / "scaffold-mono-pair.py", "scaffold_mono_pair")
    observers = load_module(base / "scripts" / "scaffold-observers.py", "scaffold_observers")
    completed = []
    for kind, prefix, directory_name, master_suffix, contradictor_suffix in actions:
        if kind == "mono":
            main_suffix, contra_suffix = mono.default_suffixes(prefix)
            mono.scaffold(base, prefix, main_suffix, contra_suffix, directory_name,
                          "gpt-5-6-sol", "codex3a", "fable-5", "login1a")
            completed.append(f"{directory_name}: mono -> {prefix}-{main_suffix}+{prefix}-{contra_suffix}")
        else:
            observers.scaffold(base, prefix, directory_name, "codex3a",
                               contradictor_suffix, create_workflow=False,
                               target_suffix=master_suffix)
            completed.append(f"{directory_name}: ajout {prefix}-{contradictor_suffix} ({kind})")
    return completed


def report(actions, manual):
    for kind, prefix, directory, master, contradictor in actions:
        if kind == "mono":
            tail = prefix[1:]
            print(f"MIGRATE mono {directory}: {prefix}-1{tail} + {prefix}-2{tail}")
        else:
            print(f"MIGRATE {kind} {directory}: add {prefix}-{contradictor} -> {prefix}-{master}")
    for item in manual:
        print(f"MANUAL {item}")
    print(json.dumps({"migrate": len(actions), "manual": len(manual)}, sort_keys=True))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    base = args.base.resolve()
    actions, manual = plan(base)
    report(actions, manual)
    if args.check:
        return
    if manual:
        raise SystemExit("migration interrompue: traiter les lignes MANUAL puis relancer")
    for line in apply(base, actions):
        print(f"DONE {line}")


if __name__ == "__main__":
    main()
