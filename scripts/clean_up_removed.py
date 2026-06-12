#!/usr/bin/env python3
"""
clean_up_removed.py - Supprime les entrées de removed/ plus vieilles que 6h
Usage: python3 scripts/clean_up_removed.py [--hours N]
"""

import os
import sys
import shutil
import argparse
import time
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REMOVED_DIR = os.path.join(BASE, "removed")


def human_size(path):
    total = 0
    if os.path.isfile(path):
        return os.path.getsize(path)
    for dirpath, dirnames, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total


def fmt_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def fmt_age(mtime):
    delta = timedelta(seconds=time.time() - mtime)
    h, rem = divmod(int(delta.total_seconds()), 3600)
    m = rem // 60
    if h >= 24:
        return f"{h // 24}j {h % 24}h"
    return f"{h}h{m:02d}m"


def collect_old_entries(removed_dir, max_age_hours):
    cutoff = time.time() - max_age_hours * 3600
    entries = []
    try:
        names = sorted(os.listdir(removed_dir))
    except FileNotFoundError:
        return entries
    for name in names:
        path = os.path.join(removed_dir, name)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if mtime < cutoff:
            entries.append({
                "name": name,
                "path": path,
                "mtime": mtime,
                "is_dir": os.path.isdir(path),
                "size": human_size(path),
            })
    return entries


def main():
    parser = argparse.ArgumentParser(description="Nettoyer removed/ des entrées obsolètes")
    parser.add_argument("--hours", type=float, default=6.0,
                        help="Age minimum en heures (défaut: 6)")
    args = parser.parse_args()

    if not os.path.isdir(REMOVED_DIR):
        print(f"Répertoire absent : {REMOVED_DIR}")
        sys.exit(0)

    entries = collect_old_entries(REMOVED_DIR, args.hours)

    if not entries:
        print(f"Rien à nettoyer (aucune entrée > {args.hours}h dans removed/).")
        sys.exit(0)

    total_size = sum(e["size"] for e in entries)
    print(f"{len(entries)} entrée(s) > {args.hours}h ({fmt_size(total_size)}) :")

    deleted = 0
    freed = 0
    errors = 0
    for e in entries:
        kind = "DIR " if e["is_dir"] else "FILE"
        try:
            if os.path.isdir(e["path"]):
                shutil.rmtree(e["path"])
            else:
                os.remove(e["path"])
            print(f"  OK  {kind}  {fmt_age(e['mtime'])}  {fmt_size(e['size']):>9}  {e['name']}")
            deleted += 1
            freed += e["size"]
        except Exception as ex:
            print(f"  ERR {kind}  {e['name']} : {ex}")
            errors += 1

    print(f"{deleted} suppression(s), {fmt_size(freed)} libérés"
          + (f", {errors} erreur(s)" if errors else "") + ".")


if __name__ == "__main__":
    main()
