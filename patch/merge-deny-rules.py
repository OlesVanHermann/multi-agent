#!/usr/bin/env python3
"""Fusionne les règles permissions.deny d'un settings.json de référence
dans des profils login existants (union — ne touche à rien d'autre).

Usage: merge-deny-rules.py [--check] REFERENCE TARGET...

  --check : rapporte ce qui serait fusionné sans rien écrire (dry-run).

Codes retour : 0 = OK (profils invalides skippés avec WARN),
2 = usage / référence illisible.
"""
import json
import sys


def load_deny(path):
    with open(path, encoding="utf-8") as f:
        deny = json.load(f)["permissions"]["deny"]
    if not isinstance(deny, list) or not all(isinstance(r, str) for r in deny):
        raise ValueError("permissions.deny doit être une liste de chaînes")
    return deny


def merge_target(path, ref_deny, check):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        print(f"[WARN] {path} : illisible, profil sauté ({e})")
        return
    permissions = data.setdefault("permissions", {})
    deny = permissions.setdefault("deny", [])
    if not isinstance(deny, list):
        print(f"[WARN] {path} : permissions.deny n'est pas une liste, profil sauté")
        return
    missing = [r for r in ref_deny if r not in deny]
    if not missing:
        print(f"[OK]   {path} : à jour ({len(ref_deny)} règles de référence présentes)")
        return
    if check:
        print(f"[MERGE] {path} : {len(missing)} règle(s) deny à ajouter")
        for rule in missing:
            print(f"          + {rule}")
        return
    deny.extend(missing)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"[OK]   {path} : +{len(missing)} règle(s) deny")


def main(argv):
    check = "--check" in argv
    args = [a for a in argv if a != "--check"]
    if len(args) < 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    ref_path, targets = args[0], args[1:]
    try:
        ref_deny = load_deny(ref_path)
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"[ERROR] référence illisible : {ref_path} ({e})", file=sys.stderr)
        return 2
    for path in targets:
        merge_target(path, ref_deny, check)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
