#!/usr/bin/env python3
"""Ajoute idempotemment le hook PreToolUse (Bash) anti-`rm` aux profils Claude.

Rend vérifiable l'interdiction de CLAUDE.md (`rm`/`rmdir`/`unlink`). Ne lit ni
ne modifie aucun credential ; les autres hooks (Stop de communication…) sont
conservés. Modèle : `patch/merge-communication-hooks.py`.

Usage : merge-rm-guard-hook.py [--check] TARGET...
"""

import argparse
import json
from pathlib import Path


HOOK = {
    "type": "command",
    "command": "\"${CLAUDE_PROJECT_DIR:-$PWD}/scripts/claude-rm-guard.py\"",
    "timeout": 10,
}
MARKER = "claude-rm-guard.py"


def merge(path, check=False):
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"[WARN] {path}: profil illisible, ignoré ({exc})")
        return False
    hooks = data.setdefault("hooks", {})
    pre_groups = hooks.setdefault("PreToolUse", [])
    if not isinstance(pre_groups, list):
        print(f"[WARN] {path}: hooks.PreToolUse n'est pas une liste, ignoré")
        return False
    for group in pre_groups:
        if not isinstance(group, dict):
            continue
        for hook in group.get("hooks", []):
            if isinstance(hook, dict) and MARKER in hook.get("command", ""):
                if hook == HOOK:
                    print(f"[OK] {path}: hook rm-guard à jour")
                    return False
                if check:
                    print(f"[MERGE] {path}: hook rm-guard à actualiser")
                    return True
                hook.clear()
                hook.update(HOOK)
                path.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
                print(f"[OK] {path}: hook rm-guard actualisé")
                return True
    if check:
        print(f"[MERGE] {path}: hook rm-guard à ajouter")
        return True
    pre_groups.append({"matcher": "Bash", "hooks": [dict(HOOK)]})
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(f"[OK] {path}: hook rm-guard ajouté")
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
