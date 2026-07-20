#!/usr/bin/env python3
"""Collecte bornée et envoi déterministe pour un Contradictor 2XX."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import re
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
MAX_TEXT = 200_000
MAX_FILES = 30
MAX_FIELD = 8_000


def timestamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def validate_triangle(value):
    if len(value) != 3 or not value.isdigit():
        raise SystemExit("triangle attendu au format NNN")
    return value


def prompt_directory(triangle):
    matches = []
    for directory in (BASE / "prompts").glob(f"{triangle}*"):
        if directory.is_dir() and list(directory.glob(f"{triangle}-1??-system.md")):
            matches.append(directory)
    if len(matches) != 1:
        raise SystemExit(f"impossible de résoudre un répertoire unique pour {triangle}: {matches}")
    return matches[0]


def role_id(directory, triangle, hundreds):
    matches = sorted(directory.glob(f"{triangle}-{hundreds}??-system.md"))
    if len(matches) != 1:
        raise SystemExit(f"rôle {hundreds}XX ambigu ou absent dans {directory}")
    return matches[0].name.removesuffix("-system.md")


def tail(path, lines):
    if not path.is_file():
        return []
    try:
        return path.read_text(errors="replace").splitlines()[-lines:]
    except OSError:
        return []


def bounded_text(path):
    try:
        return path.read_text(errors="replace")[:MAX_TEXT]
    except OSError:
        return ""


def run(command, timeout=10):
    try:
        result = subprocess.run(command, cwd=BASE, text=True, capture_output=True,
                                timeout=timeout, check=False)
        return {"returncode": result.returncode,
                "stdout": result.stdout[-MAX_TEXT:],
                "stderr": result.stderr[-4000:]}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"returncode": 124, "stdout": "", "stderr": str(error)}


def redis_entries(stream, count=200):
    result = run([str(BASE / "scripts" / "redis.sh"), "--json", "XREVRANGE",
                  stream, "+", "-", "COUNT", str(count)])
    if result["returncode"] != 0:
        return {"available": False, "error": result["stderr"], "entries": []}
    try:
        raw = json.loads(result["stdout"] or "[]")
        entries = []
        for message_id, flat in raw:
            fields = {}
            for index in range(0, len(flat) - 1, 2):
                key = str(flat[index])
                limit = 4_000 if key in {"response", "prompt"} else MAX_FIELD
                fields[key] = str(flat[index + 1])[:limit]
            entries.append({"id": str(message_id), "fields": fields})
        return {"available": True, "error": "", "entries": entries}
    except (TypeError, ValueError) as error:
        return {"available": False, "error": f"JSON Redis invalide: {error}",
                "entries": []}


def declared_path(prompt_text, pattern):
    match = re.search(pattern, prompt_text)
    if not match:
        return None
    candidate = (BASE / match.group(1).rstrip("/`" )).resolve()
    try:
        candidate.relative_to(BASE.resolve())
    except ValueError:
        return None
    return candidate


def active_tasks(plan_root):
    if not plan_root or not plan_root.is_dir():
        return []
    tasks = []
    for category in sorted(path for path in plan_root.iterdir() if path.is_dir()):
        for task in sorted(path for path in category.iterdir() if path.is_dir()):
            files = sorted(path for path in task.rglob("*") if path.is_file())
            tasks.append({"id": task.name, "category": category.name,
                          "path": str(task.relative_to(BASE)),
                          "files": [str(path.relative_to(BASE)) for path in files[:MAX_FILES]]})
    return tasks


def related(entry, triangle, target, contradictor, task_ids):
    fields = entry["fields"]
    agents = {fields.get("agent_id", ""), fields.get("from_agent", ""),
              fields.get("to_agent", "")}
    if any(agent in {target, contradictor} or agent.startswith(f"{triangle}-")
           for agent in agents if agent):
        return True
    return fields.get("task_id", "") in task_ids


def analysis_view(target, task_list, memory_text, streams):
    active = task_list[0] if len(task_list) == 1 else None
    task_ids = {task["id"] for task in task_list}
    wal = streams["wal"]["entries"]
    dispatches = []
    terminals = []
    for entry in reversed(wal):
        fields = entry["fields"]
        event = fields.get("event", "")
        if event == "task_assigned" and fields.get("from_agent") == target:
            dispatches.append(entry)
        if event.lower() in {"done", "score", "error", "blocked", "artifact_ready",
                            "verify_green", "verify_red"} or "terminal" in event.lower():
            terminals.append(entry)
    groups = {}
    for entry in dispatches:
        fields = entry["fields"]
        key = (fields.get("agent_id", ""), fields.get("task_id", ""),
               fields.get("cycle", ""), fields.get("step", ""))
        groups.setdefault(key, []).append(entry)
    duplicates = [{"agent_id": key[0], "task_id": key[1], "cycle": key[2],
                   "step": key[3], "count": len(values), "events": values}
                  for key, values in groups.items() if len(values) > 1]
    memory_line = next((line.strip() for line in memory_text.splitlines()
                        if re.search(r"t[aâ]che active", line, re.I)), "")
    conflicts = []
    if task_ids and re.search(r"aucune|vide|none", memory_line, re.I):
        conflicts.append({"type": "active_task_vs_memory", "physical": sorted(task_ids),
                          "memory": memory_line})
    inbox_terminals = []
    for entry in reversed(streams["inbox"]["entries"]):
        fields = entry["fields"]
        prompt = fields.get("prompt", "")
        match = re.search(r"(?:EVENT:|\|)(DONE|SCORE|ERROR|BLOCKED|ARTIFACT_READY|INFO_REQUIRED)\b",
                          prompt)
        if match:
            inbox_terminals.append({"id": entry["id"], "event": match.group(1),
                                    "from_agent": fields.get("from_agent", ""),
                                    "task_id": fields.get("task_id", ""),
                                    "cycle": fields.get("cycle", ""),
                                    "correlation_id": fields.get("correlation_id", ""),
                                    "prompt": prompt})
    terminals.extend(inbox_terminals)
    correlations = sorted({entry["fields"].get("correlation_id", "")
                           for source in streams.values() for entry in source["entries"]
                           if entry["fields"].get("correlation_id")})
    return {"target": target, "active_task": active,
            "active_task_candidates": task_list,
            "memory_active_task_declaration": memory_line,
            "memory_conflicts": conflicts, "dispatches": dispatches,
            "duplicate_dispatches": duplicates, "terminal_events": terminals,
            "correlation_ids": correlations}


def recent_files(roots):
    candidates = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.is_file() and not path.is_symlink():
                try:
                    candidates.append((path.stat().st_mtime, path))
                except OSError:
                    continue
    result = []
    for _, path in sorted(candidates, reverse=True)[:MAX_FILES]:
        item = {"path": str(path.relative_to(BASE)), "size": path.stat().st_size}
        if path.suffix.lower() in {".md", ".json", ".jsonl", ".txt", ".yaml", ".yml"}:
            item["text"] = bounded_text(path)
        result.append(item)
    return result


def archive_current(path, archive_dir):
    if not path.exists():
        return
    archive_dir.mkdir(parents=True, exist_ok=True)
    path.replace(archive_dir / f"{timestamp()}-{path.name}")


def collect(triangle):
    directory = prompt_directory(triangle)
    target = role_id(directory, triangle, "1")
    contradictor = role_id(directory, triangle, "2")
    output = BASE / "pool-requests" / "knowledge" / "contradictor" / contradictor
    output.mkdir(parents=True, exist_ok=True)

    prompt_evidence = {}
    for kind in ("system", "memory", "methodology"):
        path = directory / f"{target}-{kind}.md"
        prompt_evidence[kind] = {"path": str(path.relative_to(BASE)),
                                 "text": bounded_text(path)}

    pane = run(["tmux", "capture-pane", "-p", "-t", f"agent-{target}:0",
                "-S", "-1000"])
    combined_prompts = "\n".join(value["text"] for value in prompt_evidence.values())
    plan_root = declared_path(combined_prompts, r"\$BASE/(plans/[^\s`]+/plan-DOING)/?")
    artifact_root = declared_path(combined_prompts, r"\$BASE/(pipeline/[^\s`/]+)")
    task_list = active_tasks(plan_root)
    task_ids = {task["id"] for task in task_list}
    streams = {
        "inbox": redis_entries(f"agent:{target}:inbox"),
        "outbox": redis_entries(f"agent:{target}:outbox"),
        "wal": redis_entries("wal"),
    }
    if task_ids:
        streams["inbox"]["entries"] = [
            entry for entry in streams["inbox"]["entries"]
            if entry["fields"].get("task_id") in task_ids]
        correlations = {entry["fields"].get("correlation_id", "")
                        for entry in streams["inbox"]["entries"]}
        streams["outbox"]["entries"] = [
            entry for entry in streams["outbox"]["entries"]
            if entry["fields"].get("correlation_id", "") in correlations]
        streams["wal"]["entries"] = [
            entry for entry in streams["wal"]["entries"]
            if entry["fields"].get("task_id") in task_ids]
    else:
        streams["wal"]["entries"] = [
            entry for entry in streams["wal"]["entries"]
            if related(entry, triangle, target, contradictor, task_ids)]
    payload = {
        "schema": "multi-agent.contradictor.snapshot.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "triangle": triangle,
        "contradictor": contradictor,
        "target": target,
        "limits": {"pane_lines": 1000, "history_lines": 500,
                   "log_lines": 1000, "stream_entries": 200,
                   "recent_files": MAX_FILES, "text_chars": MAX_TEXT},
        "evidence": {
            "prompts": prompt_evidence,
            "history": tail(directory / f"{target}.history", 500),
            "pane": pane,
            "logs": {
                "events": tail(BASE / "logs" / target / "events.jsonl", 1000),
                "bridge": tail(BASE / "logs" / target / "bridge.log", 1000),
            },
            "streams": streams,
            "active_tasks": task_list,
            "recent_artifacts": recent_files([artifact_root] if artifact_root else []),
        },
        "exclusions": ["setup/secrets.cfg", "login/**", "bench/oracle/**",
                       "bench/heldout.txt"],
    }
    payload["analysis_view"] = analysis_view(
        target, task_list, prompt_evidence["memory"]["text"], streams)
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    snapshots = output / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    immutable = snapshots / f"{timestamp()}-snapshot.json"
    immutable.write_bytes(encoded)
    destination = output / "snapshot.json"
    temporary = output / f".{timestamp()}-snapshot.tmp"
    temporary.write_bytes(encoded)
    temporary.replace(destination)
    digest = hashlib.sha256(encoded).hexdigest()
    state = {"triangle": triangle, "contradictor": contradictor, "target": target,
             "snapshot": str(immutable.relative_to(BASE)),
             "latest_snapshot": str(destination.relative_to(BASE)),
             "snapshot_sha256": digest,
             "collected_at": payload["created_at"]}
    (output / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(state, ensure_ascii=False))


def send(triangle):
    directory = prompt_directory(triangle)
    target = role_id(directory, triangle, "1")
    contradictor = role_id(directory, triangle, "2")
    output = BASE / "pool-requests" / "knowledge" / "contradictor" / contradictor
    conclusion = output / "conclusion.md"
    if not conclusion.is_file() or not conclusion.read_text().strip():
        raise SystemExit(f"conclusion absente: {conclusion}")
    message = conclusion.read_text()
    required = (f"Cible : {target}", "Verdict :", "Constat :",
                "Correction demandée :", "Résultat attendu :")
    missing = [field for field in required if field not in message]
    if missing:
        raise SystemExit(f"conclusion invalide, champs absents: {missing}")
    env = os.environ.copy()
    env["FROM_AGENT"] = contradictor
    try:
        result = subprocess.run([str(BASE / "scripts" / "send.sh"), target], cwd=BASE,
                                input=message, text=True, capture_output=True, env=env,
                                timeout=20, check=False)
    except subprocess.TimeoutExpired as error:
        raise SystemExit(f"envoi expiré: {error}") from error
    queued = "orphan queue" in (result.stderr or "")
    if result.returncode != 0 and not queued:
        sys.stderr.write(result.stderr or result.stdout)
        raise SystemExit(result.returncode)
    sent = output / "sent"
    sent.mkdir(parents=True, exist_ok=True)
    copy = sent / f"{timestamp()}-conclusion.md"
    shutil.copy2(conclusion, copy)
    proof = {"target": target, "source": str(conclusion.relative_to(BASE)),
             "copy": str(copy.relative_to(BASE)),
             "sha256": hashlib.sha256(message.encode()).hexdigest(),
             "sent_at": datetime.now(timezone.utc).isoformat(),
             "delivery": "queued" if queued else "delivered",
             "snapshot_sha256": "", "transport": (result.stdout + result.stderr).strip()}
    state_path = output / "state.json"
    if state_path.is_file():
        try:
            proof["snapshot_sha256"] = json.loads(state_path.read_text()).get(
                "snapshot_sha256", "")
        except (OSError, ValueError):
            pass
    (sent / f"{copy.stem}.json").write_text(
        json.dumps(proof, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(proof, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("collect", "send"))
    parser.add_argument("triangle", type=validate_triangle)
    args = parser.parse_args()
    (collect if args.action == "collect" else send)(args.triangle)


if __name__ == "__main__":
    main()
