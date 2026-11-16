#!/usr/bin/env python3
"""Migration idempotente des lettres d'effort (décision opérateur, 2026-10-09).

Les lettres suivent désormais les noms réels des CLI, et Ultracode devient un
interrupteur séparé (claude uniquement) :

    avant : L=medium  M=high    H=xhigh  X=max   U=ultracode
    après : L=low     M=medium  H=high   X=xhigh MAX=max  (+ .ultracode on|off)

Conversion (le niveau réel ne change pas) : L→M, M→H, H→X, X→MAX, U→MAX avec
un fichier voisin <id>.ultracode = on.

Le témoin prompts/.effort-letters-v2 marque une installation déjà convertie
(ou livrée avec les nouvelles lettres) : la migration ne s'applique qu'une
fois. Les originaux sont sauvegardés sous removed/<horodatage>_effort-letters/.
Les liens symboliques ne sont pas réécrits : leur cible, un fichier régulier
de prompts/, est convertie elle-même.

Usage :
    python3 patch/migrate-effort-letters.py --base ~/multi-agent --check
    python3 patch/migrate-effort-letters.py --base ~/multi-agent --apply
"""

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

OLD_TO_NEW = {"L": "M", "M": "H", "H": "X", "X": "MAX", "U": "MAX"}
STAMP = ".effort-letters-v2"


def plan(prompts_dir):
    """Liste (fichier, ancienne valeur, nouvelle valeur, ultracode_on)."""
    changes = []
    for path in sorted(prompts_dir.rglob("*.effort")):
        if path.is_symlink() or not path.is_file():
            continue
        old = path.read_text(errors="replace").strip().upper()
        new = OLD_TO_NEW.get(old)
        if new:
            changes.append((path, old, new, old == "U"))
    return changes


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default=str(Path(__file__).resolve().parent.parent))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="rapport sans écriture (défaut)")
    mode.add_argument("--apply", action="store_true", help="convertir et poser le témoin")
    args = parser.parse_args()

    base = Path(args.base).expanduser().resolve()
    prompts_dir = base / "prompts"
    if not prompts_dir.is_dir():
        print("updated=0 (pas de prompts/)")
        return 0
    stamp = prompts_dir / STAMP
    if stamp.exists():
        print("updated=0 (lettres d'effort déjà converties)")
        return 0

    changes = plan(prompts_dir)
    for path, old, new, ultracode in changes:
        extra = " + ultracode on" if ultracode else ""
        print(f"{path.relative_to(base)}: {old} → {new}{extra}")

    if not args.apply:
        print(f"updated={len(changes)} (check — rien écrit)")
        return 0

    stamp_time = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup = base / "removed" / f"{stamp_time}_effort-letters"
    for path, old, new, ultracode in changes:
        saved = backup / path.relative_to(base)
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, saved)
        path.write_text(new + "\n")
        if ultracode:
            sibling = path.with_suffix(".ultracode")
            if not sibling.exists():
                sibling.write_text("on\n")
    stamp.write_text(
        "Lettres d'effort L=low M=medium H=high X=xhigh MAX=max "
        f"(converties le {stamp_time} UTC ; sauvegarde : "
        f"{backup.relative_to(base) if changes else 'aucune'})\n")
    print(f"updated={len(changes)}" + (f" (sauvegarde : {backup.relative_to(base)})" if changes else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
