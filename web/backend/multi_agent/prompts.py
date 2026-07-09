"""Résolution des fichiers prompts/, panel-config, favoris et historique (B1)."""

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Optional

from . import config as cfg
from . import state


def _read_panel_config() -> dict:
    """Read panel-config.json, return {"overrides": {}} if missing/corrupt."""
    try:
        return json.loads(cfg.PANEL_CONFIG_PATH.read_text())
    except Exception:
        return {"overrides": {}}


def _write_panel_config(data: dict):
    """Atomic write: .tmp + rename."""
    tmp = cfg.PANEL_CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.rename(cfg.PANEL_CONFIG_PATH)


def _resolve_prompts_dir(prompts_dir: Path, numeric_id: str) -> Optional[Path]:
    """Resolve a numeric agent ID to its prompts directory.
    Handles both plain (345/) and named (345-develop-fonction-beta/) directories.
    """
    # Exact match first
    exact = prompts_dir / numeric_id
    if exact.is_dir():
        return exact
    # Named directory: 345-*
    for d in prompts_dir.iterdir():
        if d.is_dir() and re.match(rf'^{re.escape(numeric_id)}-', d.name):
            return d
    return None


def _find_agent_config(prompts_dir: Path, agent_id: str, ext: str) -> Optional[Path]:
    """Find config file (.model, .login, .effort) for an agent.
    Check agent directory first (x45/z21/mono), then prompts/.
    """
    base_id = agent_id.split("-")[0] if "-" in agent_id else agent_id
    agent_dir = _resolve_prompts_dir(prompts_dir, base_id)
    if agent_dir:
        candidate = agent_dir / f"{agent_id}.{ext}"
        if candidate.exists() or candidate.is_symlink():
            return candidate
    candidate = prompts_dir / f"{agent_id}.{ext}"
    if candidate.exists() or candidate.is_symlink():
        return candidate
    return None


def _find_agent_prompt(prompts_dir: Path, agent_id: str) -> Optional[Path]:
    """Find prompt file for an agent. Supports:
    - x45 new: prompts/{parent}*/{id}.md (e.g. prompts/345/345-500.md)
    - x45 old: prompts/{id}/system.md
    - flat: prompts/{id}-*.md
    Handles named directories (345-develop-fonction-beta/).
    """
    parent_id = agent_id.split('-')[0] if '-' in agent_id else agent_id
    # x45: resolve named directory
    parent_dir = _resolve_prompts_dir(prompts_dir, parent_id)
    if parent_dir:
        entry = parent_dir / f"{agent_id}.md"
        if entry.exists():
            return entry
    # Flat format
    matches = sorted(prompts_dir.glob(f"{agent_id}-*.md"))
    if matches:
        return matches[0]
    return None


def _log_prompt_history(agent_id: str, text: str):
    """Append submitted prompt to agent history file + Redis stream.
    Flat agents: prompts/{agent_id}.history
    x45 agents:  prompts/{parent-dir}/{agent_id}.history
    """
    try:
        prompts_dir = cfg.BASE_DIR / "prompts"
        parent_id = agent_id.split('-')[0] if '-' in agent_id else agent_id
        # Try x45 directory first
        parent_dir = _resolve_prompts_dir(prompts_dir, parent_id)
        if parent_dir:
            history_file = parent_dir / f"{agent_id}.history"
        else:
            history_file = prompts_dir / f"{agent_id}.history"
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        line = text.replace("\n", " ").replace("\r", "")
        with open(history_file, "a") as f:
            f.write(f"{ts} | {line}\n")
        # Also push to Redis stream for real-time history
        if state.redis_pool:
            hm = time.strftime("%H:%M")
            short = line[:20]
            asyncio.get_event_loop().create_task(
                state.redis_pool.xadd(
                    cfg.PROMPT_HISTORY_STREAM,
                    {"time": hm, "agent": parent_id, "text": short},
                    maxlen=50,
                )
            )
    except Exception:
        pass  # never break the submit flow


def _favoris_file(user: str, project: str) -> Path:
    safe_user = "".join(c for c in user if c.isalnum() or c in "-_")[:30].strip() or "default"
    safe_proj = "".join(c for c in project if c.isalnum() or c in "-_ ")[:30].strip() or "default"
    return cfg.BASE_DIR / "prompts" / f"favoris-{safe_user}-{safe_proj}.json"
