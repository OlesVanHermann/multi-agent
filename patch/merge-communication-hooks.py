#!/usr/bin/env python3
"""Ajoute idempotemment le Stop hook de communication aux profils Claude.

Ne lit ni ne modifie aucun credential. Les hooks existants sont conservés.
"""

import argparse
import json
from pathlib import Path


HOOK = {
    "type": "command",
    "command": "\"${CLAUDE_PROJECT_DIR:-$PWD}/scripts/claude-stop-guard.py\"",
    "timeout": 10,
}


def merge(path, check=False):
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"[WARN] {path}: profil illisible, ignoré ({exc})")
        return False
    hooks = data.setdefault("hooks", {})
    stop_groups = hooks.setdefault("Stop", [])
    if not isinstance(stop_groups, list):
        print(f"[WARN] {path}: hooks.Stop n'est pas une liste, ignoré")
        return False
    for group in stop_groups:
        for hook in group.get("hooks", []) if isinstance(group, dict) else []:
            if (isinstance(hook, dict)
                    and "claude-stop-guard.py" in hook.get("command", "")):
                if hook == HOOK:
                    print(f"[OK] {path}: hook de communication à jour")
                    return False
                if check:
                    print(f"[MERGE] {path}: hook de communication à actualiser")
                    return True
                hook.clear()
                hook.update(HOOK)
                path.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
                print(f"[OK] {path}: hook de communication actualisé")
                return True
    if check:
        print(f"[MERGE] {path}: hook de communication à ajouter")
        return True
    stop_groups.append({"hooks": [dict(HOOK)]})
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(f"[OK] {path}: hook de communication ajouté")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("targets", nargs="+")
    args = parser.parse_args()
    for target in args.targets:
        merge(target, args.check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
