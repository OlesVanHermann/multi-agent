#!/usr/bin/env python3
"""C3/C6 — règles delta traçables et promotion de compétences partagées."""

import json
import re
import shutil
import time
from pathlib import Path

RULE_RE = re.compile(
    r"^## (R-[0-9]+) \[helpful:(\d+) harmful:(\d+) born:([^ ]+) last_hit:([^\]]+)\]\n"
    r"(.*?)(?=^## R-[0-9]+ |\Z)", re.M | re.S)


def parse_rules(text):
    return [{"id": m.group(1), "helpful": int(m.group(2)),
             "harmful": int(m.group(3)), "born": m.group(4),
             "last_hit": m.group(5), "body": m.group(6).strip()}
            for m in RULE_RE.finditer(text)]


def render_rules(rules):
    return "\n\n".join(
        f"## {r['id']} [helpful:{r['helpful']} harmful:{r['harmful']} "
        f"born:{r['born']} last_hit:{r['last_hit']}]\n{r['body']}"
        for r in rules) + "\n"


def update_delta(path, rule_id, cycle, body=None, effect=None):
    path = Path(path)
    original = path.read_text() if path.exists() else ""
    rules = parse_rules(original)
    match = next((rule for rule in rules if rule["id"] == rule_id), None)
    if match is None:
        if not body:
            raise ValueError("body requis pour une nouvelle règle")
        match = {"id": rule_id, "helpful": 0, "harmful": 0,
                 "born": cycle, "last_hit": cycle, "body": body.strip()}
        rules.append(match)
    if effect not in (None, "helpful", "harmful"):
        raise ValueError("effect doit être helpful ou harmful")
    if effect:
        match[effect] += 1
        match["last_hit"] = cycle
    kept = [rule for rule in rules
            if not (rule["harmful"] >= 2 and rule["helpful"] == 0)]
    archive = path.parent / ".archive"
    archive.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, archive / f"delta-before-{int(time.time() * 1000)}-{path.name}")
    path.write_text(render_rules(kept))
    return {"kept": len(kept), "pruned": len(rules) - len(kept)}


def promote_skill(local_rule, skill_path, triangle, helpful, harmful):
    """Promote only after positive evidence from two independent triangles."""
    skill_path = Path(skill_path)
    meta_path = skill_path.with_suffix(skill_path.suffix + ".json")
    meta = {"triangles": {}, "promoted": False}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
    meta["triangles"][str(triangle)] = {"helpful": int(helpful), "harmful": int(harmful)}
    positive = [v for v in meta["triangles"].values()
                if v["helpful"] > 0 and v["harmful"] == 0]
    meta["promoted"] = len(positive) >= 2
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    if meta["promoted"]:
        skill_path.write_text(Path(local_rule).read_text())
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    return meta["promoted"]
