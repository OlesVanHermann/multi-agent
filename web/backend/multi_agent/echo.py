"""Collecte bornée et non intrusive des preuves pour le Contradictor."""

import hashlib
import json
import os
import re
import tempfile
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from . import config as cfg
from . import state
from .prompts import _find_agent_prompt, _resolve_prompts_dir
from .tmuxio import _capture_agent_pane

MAX_PANE_LINES = 1000
MAX_HISTORY_LINES = 500
MAX_LOG_LINES = 1000
MAX_STREAM_ENTRIES = 500
MAX_TEXT_CHARS = 500_000
_SAFE_LABEL = re.compile(r"[^A-Za-z0-9_.-]+")


def _tail_lines(path: Path, limit: int) -> list[str]:
    if limit <= 0 or not path.is_file():
        return []
    try:
        with path.open("r", errors="replace") as handle:
            return [line.rstrip("\n") for line in deque(handle, maxlen=limit)]
    except OSError:
        return []


def _prompt_evidence(agent_id: str) -> list[dict]:
    """Return only declared agent prompts; never traverse secret/bench trees."""
    prompts_root = cfg.BASE_DIR / "prompts"
    parent = agent_id.split("-", 1)[0]
    agent_dir = _resolve_prompts_dir(prompts_root, parent) if prompts_root.is_dir() else None
    candidates: list[Path] = []
    flat = _find_agent_prompt(prompts_root, agent_id) if prompts_root.is_dir() else None
    if flat:
        candidates.append(flat)
    if agent_dir:
        candidates.extend(agent_dir / name for name in ("system.md", "memory.md", "methodology.md"))
    evidence = []
    for path in dict.fromkeys(candidates):
        if not path.is_file():
            continue
        try:
            path.resolve().relative_to(prompts_root.resolve())
        except (OSError, ValueError):
            continue
        try:
            text = path.read_text(errors="replace")[:MAX_TEXT_CHARS]
        except OSError:
            continue
        evidence.append({"path": str(path.relative_to(cfg.BASE_DIR)), "text": text})
    return evidence


def _history_path(agent_id: str) -> Path:
    prompts_root = cfg.BASE_DIR / "prompts"
    parent = agent_id.split("-", 1)[0]
    agent_dir = _resolve_prompts_dir(prompts_root, parent) if prompts_root.is_dir() else None
    return (agent_dir / f"{agent_id}.history") if agent_dir else (prompts_root / f"{agent_id}.history")


async def _stream_tail(name: str, limit: int) -> list[dict]:
    if not state.redis_pool or limit <= 0:
        return []
    try:
        raw = await state.redis_pool.xrevrange(name, count=limit)
    except Exception:
        return []
    result = []
    for message_id, fields in reversed(raw):
        if isinstance(message_id, bytes):
            message_id = message_id.decode(errors="replace")
        clean = {}
        for key, value in fields.items():
            if isinstance(key, bytes):
                key = key.decode(errors="replace")
            if isinstance(value, bytes):
                value = value.decode(errors="replace")
            clean[str(key)] = str(value)[:2000]
        result.append({"id": str(message_id), "fields": clean})
    return result


async def collect_snapshot(echo_id: str, request) -> dict:
    target = request.target_agent
    pane_limit = max(1, min(request.pane_lines, MAX_PANE_LINES))
    history_limit = max(1, min(request.history_lines, MAX_HISTORY_LINES))
    log_limit = max(1, min(request.log_lines, MAX_LOG_LINES))
    stream_limit = max(1, min(request.stream_entries, MAX_STREAM_ENTRIES))
    pane = await _capture_agent_pane(target, lines=pane_limit)
    pane_text = pane.stdout[-MAX_TEXT_CHARS:] if pane.returncode == 0 else ""
    log_dir = cfg.BASE_DIR / "logs" / target
    wal = await _stream_tail("wal", stream_limit)
    scoped_wal = []
    for item in wal:
        fields = item["fields"]
        same_agent = fields.get("agent_id") in {target, echo_id}
        same_task = request.task_id and fields.get("task_id") == request.task_id
        same_corr = request.correlation_id and fields.get("correlation_id") == request.correlation_id
        if same_agent or same_task or same_corr:
            scoped_wal.append(item)
    return {
        "schema": "multi-agent.echo.snapshot.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "observer": echo_id,
        "target": target,
        "scope": {
            "task_id": request.task_id,
            "correlation_id": request.correlation_id,
            "cycles": request.cycles,
        },
        "authority": {
            "rank": 5,
            "mode": "read_only_observer",
            "may_dispatch": False,
            "may_transition_workflow": False,
            "operator_injection_required": True,
        },
        "limits": {
            "pane_lines": pane_limit,
            "history_lines": history_limit,
            "log_lines": log_limit,
            "stream_entries": stream_limit,
        },
        "evidence": {
            "intention": _prompt_evidence(target),
            "inputs": {"history": _tail_lines(_history_path(target), history_limit)},
            "actions": {
                "pane": pane_text,
                "events": _tail_lines(log_dir / "events.jsonl", log_limit),
                "bridge": _tail_lines(log_dir / "bridge.log", log_limit),
            },
            "outputs": {
                "outbox": await _stream_tail(cfg.agent_outbox(target), stream_limit),
                "wal": scoped_wal,
            },
        },
        "exclusions": ["setup/secrets.cfg", "login/**", "bench/oracle/**", "bench/heldout.txt"],
    }


def persist_snapshot(snapshot: dict) -> tuple[Path, str]:
    payload = (json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n").encode()
    digest = hashlib.sha256(payload).hexdigest()
    root = cfg.BASE_DIR / "pool-requests" / "knowledge" / "echo" / snapshot["observer"]
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = _SAFE_LABEL.sub("-", snapshot["target"])
    destination = root / f"{stamp}-{target}.snapshot.json"
    fd, temporary = tempfile.mkstemp(prefix=".echo-", dir=root)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary).replace(destination)
    except Exception:
        # Conserver le temporaire pour diagnostic : la politique du framework
        # interdit toute suppression définitive, y compris en erreur.
        raise
    return destination, digest


async def emit_echo_wal(event: str, echo_id: str, task_id: str | None, **fields) -> None:
    if not state.redis_pool:
        return
    entry = {
        "event": event,
        "agent_id": echo_id,
        "task_id": task_id or "-",
        "ts": int(datetime.now(timezone.utc).timestamp()),
    }
    entry.update({key: str(value)[:500] for key, value in fields.items()})
    try:
        await state.redis_pool.xadd("wal", entry, maxlen=100000, approximate=True)
    except Exception:
        pass
