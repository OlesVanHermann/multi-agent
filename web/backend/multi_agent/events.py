"""Journal d'événements par agent : logs/{agent_id}/events.jsonl (B1)."""

import json
from pathlib import Path

from . import config as cfg


def _events_dir(agent_id: str) -> Path:
    """Return logs/{agent_id}/ directory, create if needed."""
    d = cfg.BASE_DIR / "logs" / agent_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _log_event(agent_id: str, event_type: str, detail: str = ""):
    """Append JSON line to logs/{agent_id}/events.jsonl."""
    from datetime import datetime
    entry = json.dumps({"ts": datetime.now().strftime("%Y%m%d_%H%M%S"), "type": event_type, "detail": detail})
    try:
        f = _events_dir(agent_id) / "events.jsonl"
        with open(f, "a") as fh:
            fh.write(entry + "\n")
        print(f"[event] agent={agent_id} type={event_type} detail={detail}")
    except Exception as e:
        print(f"[event] log error agent={agent_id}: {e}")


def _rotate_events(agent_id: str):
    """Rotate events on /clear: rename events.jsonl → events.{timestamp}.jsonl."""
    try:
        d = _events_dir(agent_id)
        current = d / "events.jsonl"
        if current.exists() and current.stat().st_size > 0:
            from datetime import datetime
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            archived = d / f"events.{ts}.jsonl"
            current.rename(archived)
            print(f"[event] rotated events for agent {agent_id} → {archived.name}")
        else:
            print(f"[event] nothing to rotate for agent {agent_id}")
    except Exception as e:
        print(f"[event] rotate error agent={agent_id}: {e}")
