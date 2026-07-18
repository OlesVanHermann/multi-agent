"""Routes agents : liste, détail, cycle de vie, IO tmux, historique, notes (B1)."""

import asyncio
import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from .. import config as cfg
from .. import state
from ..deps import ValidAgentId
from ..events import _events_dir
from ..models import AgentStatus, SendKeys, SendMessage, UpdateInput
from ..prompts import (
    _find_agent_config,
    _log_prompt_history,
    _resolve_prompts_dir,
)
from ..tmuxio import (
    TMUX_SERVER_ABSENT_DETAIL,
    _agent_session_exists,
    _capture_agent_pane,
    _extract_current_input,
    _run_subprocess,
    _tmux_server_alive,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/agent/{base_id}/contexts")
async def get_z21_contexts(base_id: str):
    """List z21 sub-context directories for a group."""
    if not re.match(r'^\d{3}$', base_id):
        raise HTTPException(status_code=400, detail="invalid base_id")
    prompts_dir = cfg.BASE_DIR / "prompts"
    agent_dir = _resolve_prompts_dir(prompts_dir, base_id)
    if not agent_dir:
        raise HTTPException(status_code=404, detail="agent dir not found")
    contexts = []
    for child in sorted(agent_dir.iterdir(), key=lambda c: c.name):
        if not child.is_dir():
            continue
        archi = child / "archi.md"
        if not archi.exists():
            continue
        # Read first non-empty line of archi.md as description
        desc = ""
        try:
            for line in archi.read_text(encoding="utf-8").splitlines():
                stripped = line.strip().lstrip("#").strip()
                if stripped:
                    desc = stripped
                    break
        except Exception:
            pass
        rel = f"prompts/{agent_dir.name}/{child.name}"
        contexts.append({
            "name": child.name,
            "description": desc,
            "path": rel,
            "files": {
                "archi": f"{rel}/archi.md",
                "memory": f"{rel}/memory.md",
                "methodology": f"{rel}/methodology.md",
            }
        })
    return {"base_id": base_id, "contexts": contexts}


@router.get("/api/agents")
async def list_agents():
    """List all agents — reads from background cache (instant)"""
    # 000 (Architect) apparaît dans la liste comme tout agent — seules les
    # opérations de contrôle (send/input/lifecycle) restent protégées (403).
    agents = list(state._cache["agents"])
    result = {
        "agents": agents,
        "count": len(agents),
        "timestamp": state._cache["timestamp"],
    }
    if state._cache.get("mode"):
        result["mode"] = state._cache["mode"]
    if state._cache.get("triangles"):
        result["triangles"] = state._cache["triangles"]
    if state._cache.get("agent_names"):
        result["agent_names"] = state._cache["agent_names"]
    return result


@router.get("/api/usage")
async def get_usage():
    """Return Claude Code token usage from Redis (updated every 30min)."""
    if not state.redis_pool:
        return {"global": {}, "sessions": []}

    # Global totals
    g = await state.redis_pool.hgetall("mi:usage:global")

    # Active session IDs
    sids = await state.redis_pool.smembers("mi:usage:sessions")

    # Per-session details
    sessions = []
    for sid in sorted(sids):
        data = await state.redis_pool.hgetall(f"mi:usage:session:{sid}")
        if data:
            data["id"] = sid
            sessions.append(data)

    # Plan usage bars — read per-profile JSON files
    import json as _json
    import glob as _glob
    profiles = {}
    usage_glob = str(cfg.BASE_DIR / "keepalive" / "usage_*.json")
    for fpath in _glob.glob(usage_glob):
        try:
            with open(fpath) as _f:
                pdata = _json.load(_f)
                pname = pdata.get("profile", "")
                if pname and pdata.get("bars"):
                    profiles[pname] = pdata
        except Exception:
            pass

    # Enrich profiles with static info from info_*.json
    info_glob = str(cfg.BASE_DIR / "keepalive" / "info_*.json")
    for fpath in _glob.glob(info_glob):
        try:
            with open(fpath) as _f:
                idata = _json.load(_f)
                # Extract profile name from filename: info_claude1a.json -> claude1a
                pname = Path(fpath).stem.replace("info_", "", 1)
                if pname not in profiles:
                    profiles[pname] = {"profile": pname, "bars": []}
                profiles[pname]["info"] = idata
        except Exception:
            pass

    # Aggregate: take max % per bar label across profiles
    plan = None
    if profiles:
        agg = {}
        for pdata in profiles.values():
            for b in pdata.get("bars", []):
                lbl = b["label"]
                if lbl not in agg or b["percent"] > agg[lbl]["percent"]:
                    agg[lbl] = b
        plan = {
            "bars": list(agg.values()),
            "profiles": profiles,
            "last_scan": max((p.get("last_scan", 0) for p in profiles.values()), default=0),
        }

    return {"global": g, "sessions": sessions, "plan": plan}


@router.get("/api/usage/{agent_id}")
async def get_usage_for_agent(agent_id: str = ValidAgentId):
    """Return plan usage bars for the login associated with this agent."""
    import json as _json
    prompts_dir = cfg.BASE_DIR / "prompts"

    # Resolve login
    login = None

    # Special case: keepalive agents 002-{profile} → login is the profile
    if agent_id.startswith("002-"):
        login = agent_id[4:]  # "002-claude2a" -> "claude2a"
    else:
        # agent_id.login (x45 dir > prompts/) -> parent_id.login -> default.login
        for candidate in [agent_id, agent_id.split("-")[0]]:
            lf = _find_agent_config(prompts_dir, candidate, "login") or prompts_dir / f"{candidate}.login"
            if lf.exists():
                try:
                    if lf.is_symlink():
                        login = Path(os.readlink(lf)).stem
                    else:
                        login = lf.read_text().strip()
                except Exception:
                    pass
                if login:
                    break
        if not login:
            dl = prompts_dir / "default.login"
            if dl.exists():
                try:
                    login = Path(os.readlink(dl)).stem if dl.is_symlink() else dl.read_text().strip()
                except Exception:
                    login = "claude1a"

    # Read keepalive/usage_{login}.json — no fallback, show only exact profile
    usage_file = cfg.BASE_DIR / "keepalive" / f"usage_{login}.json"
    if usage_file and usage_file.exists():
        try:
            with open(usage_file) as f:
                data = _json.load(f)
                data["login"] = login
                return data
        except Exception:
            pass

    return {"login": login, "bars": [], "last_scan": 0}


@router.get("/api/agent/{agent_id}")
async def get_agent(agent_id: str = ValidAgentId):
    """Get single agent details"""
    if not state.redis_pool:
        raise HTTPException(status_code=503, detail="Redis not available")

    key = f"{cfg.MA_PREFIX}:agent:{agent_id}"
    data = await state.redis_pool.hgetall(key)

    if not data:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    return AgentStatus(
        id=agent_id,
        status=data.get("status", "unknown"),
        last_seen=int(data.get("last_seen", 0)),
        queue_size=int(data.get("queue_size", 0)),
        tasks_completed=int(data.get("tasks_completed", 0)),
        mode=data.get("mode", "unknown")
    ).model_dump()


async def _agent_lifecycle(agent_id: str, action: str):
    """Start, stop, or restart an agent via ./scripts/agent.sh."""
    if not cfg.is_valid_agent_id(agent_id):
        raise HTTPException(status_code=400, detail="invalid agent_id")
    base_id = agent_id.split("-")[0] if "-" in agent_id else agent_id
    # La protection CLI de 000 reste active pour les opérateurs. Seul cet
    # endpoint authentifié l'ouvre explicitement, sans arrêter le reste de
    # l'infrastructure comme le ferait ``infra.sh stop``.

    script = cfg.BASE_DIR / "scripts" / "agent.sh"
    if not script.exists():
        raise HTTPException(status_code=500, detail="agent.sh not found")

    # start/restart créent des sessions : jamais spawner le serveur tmux
    # depuis le backend (namespace sandboxé, /home read-only hérité).
    if action in ("start", "restart") and not await _tmux_server_alive():
        raise HTTPException(status_code=503, detail=TMUX_SERVER_ABSENT_DETAIL)

    try:
        command = ["bash", str(script), action, agent_id]
        if base_id == "000":
            command = ["env", "ALLOW_PROTECTED_000=1", *command]
        # agent.sh est synchrone (attente TUI prêt + application modèle/effort) :
        # 120 s de marge — le picker codex ajoute ~10-15 s au démarrage.
        result = await _run_subprocess(
            command,
            text=True, timeout=120
        )
        output = result.stdout.strip()
        print(f"[{action}] agent {agent_id}: {output}")

        # Rendre la main sur l'ÉTAT RÉEL, pas sur un délai : la session tmux
        # doit exister (start/restart) ou avoir disparu (stop). Le front
        # réactive les boutons à la réponse — jamais sur un compte à rebours.
        session = f"{cfg.MA_PREFIX}-agent-{agent_id}"
        want_alive = action in ("start", "restart")
        alive = not want_alive
        verified = False
        for _ in range(20):
            alive = (await _run_subprocess(
                ["tmux", "has-session", "-t", session]
            )).returncode == 0
            if alive == want_alive:
                verified = True
                break
            await asyncio.sleep(0.5)

        return {
            "status": action if verified else f"{action}_unverified",
            "agent_id": agent_id,
            "running": alive,
            "verified": verified,
            "output": output,
        }
    except Exception as e:
        logger.warning("%s failed for agent %s: %s", action, agent_id, e)
        raise HTTPException(status_code=500, detail=f"{action} failed")


@router.post("/api/agent/{agent_id}/start")
async def start_agent(agent_id: str):
    return await _agent_lifecycle(agent_id, "start")


@router.post("/api/agent/{agent_id}/stop")
async def stop_agent(agent_id: str):
    return await _agent_lifecycle(agent_id, "stop")


@router.post("/api/agent/{agent_id}/restart")
async def restart_agent(agent_id: str):
    return await _agent_lifecycle(agent_id, "restart")


@router.get("/api/agent/{agent_id}/events")
async def get_agent_events(agent_id: str = ValidAgentId, all: int = 0):
    """Get event log for an agent. ?all=1 includes archived (rotated) files."""
    base_id = agent_id.split("-")[0] if "-" in agent_id else agent_id
    d = _events_dir(agent_id)

    def _read_jsonl(path: Path) -> list:
        if not path.exists():
            return []
        lines = []
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        lines.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return lines

    events = _read_jsonl(d / "events.jsonl")

    if all:
        archived = []
        for f in sorted(d.glob("events.*.jsonl")):
            archived.extend(_read_jsonl(f))
        return {"agent_id": agent_id, "events": events, "archived": archived}

    return {"agent_id": agent_id, "events": events}


_SEND_MAX_LENGTH = 5000


@router.post("/api/agent/{agent_id}/send")
async def send_to_agent(msg: SendMessage, agent_id: str = ValidAgentId):
    """Send message to an agent via tmux send-keys (with Enter)"""
    base_id = agent_id.split("-")[0] if "-" in agent_id else agent_id
    if len(msg.message) > _SEND_MAX_LENGTH:
        raise HTTPException(status_code=400, detail=f"Message too long (max {_SEND_MAX_LENGTH})")
    session_name = f"{cfg.MA_PREFIX}-agent-{agent_id}"
    target = f"{session_name}:0.0"

    try:
        # Check if session exists
        result = await _run_subprocess(["tmux", "has-session", "-t", session_name])
        if result.returncode != 0:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} session not found")

        # Send message via tmux send-keys (-l = literal, prevents C-c/C-d injection)
        await _run_subprocess(
            ["tmux", "send-keys", "-t", target, "-l", msg.message], check=True
        )
        await _run_subprocess(
            ["tmux", "send-keys", "-t", target, "Enter"], check=True
        )

        return {
            "status": "sent",
            "agent_id": agent_id,
            "message_length": len(msg.message),
            "timestamp": int(time.time())
        }
    except subprocess.CalledProcessError as e:
        logger.warning("Failed to send to agent %s: %s", agent_id, e)
        raise HTTPException(status_code=500, detail="Failed to send")


@router.post("/api/agent/{agent_id}/input")
async def update_agent_input(agent_id: str, data: UpdateInput):
    """Update the current input line in tmux (co-editing)"""
    if not cfg.is_valid_agent_id(agent_id):
        raise HTTPException(status_code=400, detail="invalid agent_id")
    base_id = agent_id.split("-")[0] if "-" in agent_id else agent_id
    # Normaliser plutot que rejeter : les copier-coller reels contiennent des \r
    # (CRLF) et parfois d'autres caracteres de controle — on les retire. La
    # protection anti-injection tmux est conservee : aucun char < 32 hors \t\n
    # n'atteint send-keys.
    def _sanitize(t: str) -> str:
        t = (t or "").replace("\r\n", "\n").replace("\r", "\n")
        return "".join(c for c in t if ord(c) >= 32 or c in ("\t", "\n"))
    if data.text:
        data.text = _sanitize(data.text)
    if data.previous:
        data.previous = _sanitize(data.previous)
    max_length = 1_000_000 if data.submit else 20_000
    if data.text and len(data.text) > max_length:
        raise HTTPException(status_code=400, detail=f"input too long (max {max_length})")
    session_name = f"{cfg.MA_PREFIX}-agent-{agent_id}"
    target = f"{session_name}:0.0"

    try:
        # Check if session exists
        result = await _run_subprocess(["tmux", "has-session", "-t", session_name])
        if result.returncode != 0:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} session not found")

        if data.submit:
            # Soumission atomique : ne pas dependre d'une co-edition encore en
            # vol. Le bracketed-paste preserve les prompts Markdown longs et la
            # pause separe l'Enter de la rafale de collage detectee par Codex.
            text = (data.text or "").strip("\n")
            await _run_subprocess(["tmux", "send-keys", "-t", target, "C-u"], check=True)
            buffer_name = f"ma-web-{agent_id}-{time.time_ns()}"
            await _run_subprocess(
                ["tmux", "load-buffer", "-b", buffer_name, "-"],
                input=text, text=True, check=True,
            )
            await _run_subprocess(
                ["tmux", "paste-buffer", "-p", "-d", "-b", buffer_name, "-t", target],
                check=True,
            )
            await asyncio.sleep(0.75)
            await _run_subprocess(["tmux", "send-keys", "-t", target, "Enter"], check=True)

            tail = " ".join(text.splitlines()[-2:]).strip()
            snippet = tail[-16:]
            for delay in (0.75, 1.5, 3.0):
                if not snippet:
                    break
                await asyncio.sleep(delay)
                try:
                    pane = (await _run_subprocess(
                        ["tmux", "capture-pane", "-t", target, "-p"], text=True,
                    )).stdout
                except Exception:
                    break
                if snippet not in pane:
                    break
                await _run_subprocess(
                    ["tmux", "send-keys", "-t", target, "Enter"], check=True
                )
            _log_prompt_history(agent_id, data.text)
        else:
            # Incremental diff: only send backspaces + new chars
            prev = (data.previous or "").rstrip()
            new = (data.text or "").rstrip().replace("\n", " ").replace("\r", "")

            i = 0
            while i < len(prev) and i < len(new) and prev[i] == new[i]:
                i += 1

            bs = len(prev) - i
            if bs > 0:
                await _run_subprocess(
                    ["tmux", "send-keys", "-t", target] + ["BSpace"] * bs, check=True
                )

            new_chars = new[i:]
            if new_chars:
                await _run_subprocess(
                    ["tmux", "send-keys", "-t", target, "-l", new_chars], check=True
                )

        return {
            "status": "updated",
            "agent_id": agent_id,
            "text": data.text,
            "submitted": data.submit,
            "timestamp": int(time.time())
        }
    except subprocess.CalledProcessError as e:
        logger.warning("Failed to update input for agent %s: %s", agent_id, e)
        raise HTTPException(status_code=500, detail="Failed to update input")


@router.get("/api/agent/{agent_id}/history")
async def get_agent_history(agent_id: str = ValidAgentId):
    """Read prompt history file for an agent."""
    base_id = agent_id.split("-")[0] if "-" in agent_id else agent_id
    prompts_dir = cfg.BASE_DIR / "prompts"
    parent_id = agent_id.split('-')[0] if '-' in agent_id else agent_id
    parent_dir = _resolve_prompts_dir(prompts_dir, parent_id)
    if parent_dir:
        history_file = parent_dir / f"{agent_id}.history"
    else:
        history_file = prompts_dir / f"{agent_id}.history"
    if not history_file.exists():
        return {"lines": []}
    text = history_file.read_text(errors="replace")
    lines = [l for l in text.splitlines() if l.strip()]
    return {"lines": lines}


@router.get("/api/agent/{agent_id}/notes")
async def get_agent_notes(agent_id: str = ValidAgentId):
    """Read notes file for an agent."""
    prompts_dir = cfg.BASE_DIR / "prompts"
    parent_id = agent_id.split('-')[0] if '-' in agent_id else agent_id
    parent_dir = _resolve_prompts_dir(prompts_dir, parent_id)
    notes_file = (parent_dir / f"{agent_id}.notes") if parent_dir else (prompts_dir / f"{agent_id}.notes")
    if not notes_file.exists():
        return {"content": ""}
    return {"content": notes_file.read_text(errors="replace")}


_NOTES_MAX_SIZE = 1_000_000


@router.post("/api/agent/{agent_id}/notes")
async def save_agent_notes(req: Request, agent_id: str = ValidAgentId):
    """Save notes file for an agent."""
    body = await req.json()
    content = body.get("content", "")
    if len(content) > _NOTES_MAX_SIZE:
        raise HTTPException(status_code=400, detail=f"Content too large (max {_NOTES_MAX_SIZE} bytes)")
    prompts_dir = cfg.BASE_DIR / "prompts"
    parent_id = agent_id.split('-')[0] if '-' in agent_id else agent_id
    parent_dir = _resolve_prompts_dir(prompts_dir, parent_id)
    notes_file = (parent_dir / f"{agent_id}.notes") if parent_dir else (prompts_dir / f"{agent_id}.notes")
    notes_file.write_text(content)
    return {"ok": True}


@router.get("/api/history/recent")
async def get_recent_history(n: int = 10):
    """Return last N prompts (all agents) from Redis stream."""
    n = max(1, min(n, 100))
    if not state.redis_pool:
        return {"entries": []}
    try:
        raw = await state.redis_pool.xrevrange(cfg.PROMPT_HISTORY_STREAM, count=n)
        entries = []
        for _msg_id, data in reversed(raw):
            entries.append({
                "time": data.get("time", ""),
                "agent": data.get("agent", ""),
                "text": data.get("text", ""),
            })
        return {"entries": entries}
    except Exception:
        return {"entries": []}


ALLOWED_KEYS = {"Enter", "C-c", "Escape", "C-u", "C-d", "C-l", "C-z", "Up", "Down", "Left", "Right", "Tab", "S-Tab", "Space", "y", "n"}

_SEND_KEYS_MAX = 20


@router.post("/api/agent/{agent_id}/keys")
async def send_keys_to_agent(data: SendKeys, agent_id: str = ValidAgentId):
    """Send raw tmux keys to an agent (Enter, Ctrl+C, Escape, etc.)"""
    base_id = agent_id.split("-")[0] if "-" in agent_id else agent_id
    if len(data.keys) > _SEND_KEYS_MAX:
        raise HTTPException(status_code=400, detail=f"Too many keys (max {_SEND_KEYS_MAX})")
    session_name = f"{cfg.MA_PREFIX}-agent-{agent_id}"
    target = f"{session_name}:0.0"

    try:
        result = await _run_subprocess(["tmux", "has-session", "-t", session_name])
        if result.returncode != 0:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} session not found")

        for key in data.keys:
            if key not in ALLOWED_KEYS:
                raise HTTPException(status_code=400, detail=f"Key not allowed: {key}")
            await _run_subprocess(
                ["tmux", "send-keys", "-t", target, key], check=True
            )

        return {
            "status": "sent",
            "agent_id": agent_id,
            "keys": data.keys,
            "timestamp": int(time.time())
        }
    except subprocess.CalledProcessError as e:
        logger.warning("Failed to send keys to agent %s: %s", agent_id, e)
        raise HTTPException(status_code=500, detail="Failed to send keys")


@router.get("/api/agent/{agent_id}/output")
async def get_agent_output(agent_id: str = ValidAgentId, lines: int = 3000):
    """Capture tmux pane output for an agent (remote-aware via SSH)."""
    base_id = agent_id.split("-")[0] if "-" in agent_id else agent_id
    lines = max(1, min(lines, 5000))
    try:
        # Check if session exists (remote via SSH if applicable)
        if not await _agent_session_exists(agent_id):
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} session not found")

        # Capture pane content (plain for display)
        result = await _capture_agent_pane(agent_id, lines=lines, ansi=False)
        output = result.stdout.rstrip('\n ')

        # Capture with ANSI codes for input detection (suggestion vs typed)
        result_ansi = await _capture_agent_pane(agent_id, ansi=True)
        current_input = _extract_current_input(result_ansi.stdout)

        return {
            "agent_id": agent_id,
            "output": output,
            "current_input": current_input,
            "lines": lines,
            "timestamp": int(time.time())
        }
    except subprocess.CalledProcessError as e:
        logger.warning("Failed to capture output for agent %s: %s", agent_id, e)
        raise HTTPException(status_code=500, detail="Failed to capture output")
