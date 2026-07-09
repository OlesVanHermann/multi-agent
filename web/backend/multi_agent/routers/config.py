"""Routes /api/config : logins/modèles, effort, favoris, tmux, panel, keepalive (B1)."""

import json
import logging
import os
import re
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from .. import config as cfg
from .. import state
from ..auth import _get_jwt_username
from ..models import EffortUpdate, LoginModelUpdate, PanelConfigUpdate
from ..prompts import (
    _favoris_file,
    _find_agent_config,
    _read_panel_config,
    _resolve_prompts_dir,
    _write_panel_config,
)
from ..tmuxio import _run_subprocess

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/config/logins-models")
async def get_logins_models():
    """Return available logins, models, defaults, and per-agent assignments."""
    prompts_dir = cfg.BASE_DIR / "prompts"

    # Collect non-symlink .login and .model files
    logins = sorted(
        f.stem for f in prompts_dir.glob("*.login")
        if not f.is_symlink() and f.stem != "default"
    )
    models = sorted(
        f.stem for f in prompts_dir.glob("*.model")
        if not f.is_symlink() and f.stem != "default"
    )

    # Read default effort
    default_effort = "H"
    de = prompts_dir / "default.effort"
    if de.exists():
        default_effort = de.read_text().strip() or "H"

    # Resolve default symlinks
    default_login = ""
    dl = prompts_dir / "default.login"
    if dl.is_symlink():
        target = os.readlink(dl)
        default_login = Path(target).stem  # "claude1a.login" -> "claude1a"
    elif dl.exists():
        default_login = logins[0] if logins else ""

    default_model = ""
    dm = prompts_dir / "default.model"
    if dm.is_symlink():
        target = os.readlink(dm)
        default_model = Path(target).stem
    elif dm.exists():
        default_model = models[0] if models else ""

    # Gather agent IDs from cache + directory scan
    agent_ids = set()
    x45_base_ids = set()  # bare IDs that are x45/z21 groups (not standalone agents)
    for a in state._cache.get("agents", []):
        agent_ids.add(a["id"])
    # Scan prompts/ directories — detect type from agent.type symlink
    for f in prompts_dir.iterdir():
        if not f.is_dir() or not re.match(r'^\d{3}', f.name):
            continue
        base_id = f.name[:3]
        # Read agent.type to determine kind
        type_link = f / "agent.type"
        agent_type = ""
        if type_link.is_symlink():
            agent_type = Path(os.readlink(type_link)).stem.replace("agent_", "")
        if agent_type == "mono":
            agent_ids.add(base_id)
        elif agent_type in ("x45", "z21"):
            x45_base_ids.add(base_id)
            for sf in f.iterdir():
                sm = re.match(r'^(\d{3}-\d{3})-system\.md$', sf.name)
                if sm:
                    agent_ids.add(sm.group(1))
                # Remote agents: .remote files (e.g. 390-190.remote)
                rm = re.match(r'^(\d{3}-\d{3})\.remote$', sf.name)
                if rm:
                    agent_ids.add(rm.group(1))
        else:
            # Legacy: no agent.type — check for compound system.md files
            has_compound = any(re.match(r'^\d{3}-\d{3}-system\.md$', sf.name) for sf in f.iterdir())
            if has_compound:
                x45_base_ids.add(base_id)
                for sf in f.iterdir():
                    sm = re.match(r'^(\d{3}-\d{3})-system\.md$', sf.name)
                    if sm:
                        agent_ids.add(sm.group(1))
            else:
                agent_ids.add(base_id)
    # Remove bare IDs that are x45/z21 groups (they use compound format)
    agent_ids -= x45_base_ids

    # Build per-agent config
    agents = []
    for aid in sorted(agent_ids, key=lambda x: tuple(int(p) for p in x.split("-"))):
        # For compound IDs (301-101), try x45 dir first, then prompts/, then parent (301)
        parent_id = aid.split("-")[0] if "-" in aid else None
        login_file = _find_agent_config(prompts_dir, aid, "login")
        model_file = _find_agent_config(prompts_dir, aid, "model")

        if login_file and login_file.is_symlink():
            agent_login = Path(os.readlink(login_file)).stem
            login_source = "override"
        elif parent_id and (prompts_dir / f"{parent_id}.login").is_symlink():
            agent_login = Path(os.readlink(prompts_dir / f"{parent_id}.login")).stem
            login_source = "default"
        else:
            agent_login = default_login
            login_source = "default"

        if model_file and model_file.is_symlink():
            agent_model = Path(os.readlink(model_file)).stem
            model_source = "override"
        elif parent_id and (prompts_dir / f"{parent_id}.model").is_symlink():
            agent_model = Path(os.readlink(prompts_dir / f"{parent_id}.model")).stem
            model_source = "default"
        else:
            agent_model = default_model
            model_source = "default"

        effort_file = _find_agent_config(prompts_dir, aid, "effort") or prompts_dir / f"{aid}.effort"
        if effort_file.exists():
            agent_effort = effort_file.read_text().strip()
            effort_source = "override"
        elif parent_id and (prompts_dir / f"{parent_id}.effort").exists():
            agent_effort = (prompts_dir / f"{parent_id}.effort").read_text().strip()
            effort_source = "default"
        else:
            agent_effort = default_effort
            effort_source = "default"

        agents.append({
            "id": aid,
            "login": agent_login,
            "login_source": login_source,
            "model": agent_model,
            "model_source": model_source,
            "effort": agent_effort,
            "effort_source": effort_source,
        })

    # Detect group types from agent.type symlink
    groups = []
    for base_id in sorted(x45_base_ids, key=int):
        x45_dir = _resolve_prompts_dir(prompts_dir, base_id)
        if not x45_dir:
            continue
        type_link = x45_dir / "agent.type"
        if type_link.is_symlink():
            group_type = Path(os.readlink(type_link)).stem.replace("agent_", "")
        else:
            group_type = "x45"
        # Collect agent IDs belonging to this group
        group_agents = [a["id"] for a in agents if a["id"].startswith(f"{base_id}-")]
        groups.append({
            "id": base_id,
            "type": group_type,
            "name": x45_dir.name,
            "agents": group_agents,
        })

    return {
        "logins": logins,
        "models": models,
        "default_login": default_login,
        "default_model": default_model,
        "default_effort": default_effort,
        "agents": agents,
        "groups": groups,
    }


@router.post("/api/config/logins-models")
async def update_login_model(data: LoginModelUpdate):
    """Create or remove a login/model symlink override for an agent."""
    prompts_dir = cfg.BASE_DIR / "prompts"

    if data.type not in ("login", "model"):
        raise HTTPException(status_code=400, detail="type must be 'login' or 'model'")

    # Validate agent_id format
    if data.agent_id != "default" and not cfg.is_valid_agent_id(data.agent_id):
        raise HTTPException(status_code=400, detail="invalid agent_id")

    # Validate data.value (prevent path traversal)
    if data.value and not re.match(r'^[a-zA-Z0-9_.-]+$', data.value):
        raise HTTPException(status_code=400, detail="invalid value")

    # For compound x45 IDs, resolve to x45 directory; otherwise prompts/
    if data.agent_id != "default" and "-" in data.agent_id:
        base_id = data.agent_id.split("-")[0]
        x45_dir = _resolve_prompts_dir(prompts_dir, base_id)
        if x45_dir:
            link_path = x45_dir / f"{data.agent_id}.{data.type}"
            symlink_target = f"../{data.value}.{data.type}" if data.value else ""
        else:
            link_path = prompts_dir / f"{data.agent_id}.{data.type}"
            symlink_target = f"{data.value}.{data.type}" if data.value else ""
    else:
        link_path = prompts_dir / f"{data.agent_id}.{data.type}"
        symlink_target = f"{data.value}.{data.type}" if data.value else ""

    if data.value == "":
        # Remove override (only for non-default)
        if data.agent_id == "default":
            raise HTTPException(status_code=400, detail="cannot remove default")
        # Also check old location in prompts/ for cleanup
        old_path = prompts_dir / f"{data.agent_id}.{data.type}"
        if old_path.is_symlink() or old_path.exists():
            old_path.unlink()
        if link_path.is_symlink() or link_path.exists():
            link_path.unlink()
        return {"status": "removed", "agent_id": data.agent_id, "type": data.type}

    # Validate target exists
    target_file = prompts_dir / f"{data.value}.{data.type}"
    if not target_file.exists() or target_file.is_symlink():
        raise HTTPException(status_code=400, detail=f"target {data.value}.{data.type} not found")

    # Create/replace symlink
    if link_path.is_symlink() or link_path.exists():
        link_path.unlink()
    link_path.symlink_to(symlink_target)

    return {"status": "updated", "agent_id": data.agent_id, "type": data.type, "value": data.value}


@router.post("/api/config/effort")
async def update_effort(data: EffortUpdate):
    """Create, update, or remove an effort override for an agent.

    Compound x45 IDs (e.g. 011-911) write to the x45 subdir when present,
    mirroring /api/config/logins-models. Remove cleans both locations so
    no ghost file ever shadows the GET lookup.
    """
    prompts_dir = cfg.BASE_DIR / "prompts"

    # Validate agent_id format
    if data.agent_id != "default" and not cfg.is_valid_agent_id(data.agent_id):
        raise HTTPException(status_code=400, detail="invalid agent_id")

    # Resolve write path: x45 subdir for compounds when it exists, else root
    root_path = prompts_dir / f"{data.agent_id}.effort"
    if data.agent_id != "default" and "-" in data.agent_id:
        base_id = data.agent_id.split("-")[0]
        x45_dir = _resolve_prompts_dir(prompts_dir, base_id)
        effort_path = (x45_dir / f"{data.agent_id}.effort") if x45_dir else root_path
    else:
        effort_path = root_path

    if data.level == "":
        # Remove override (only for non-default) — clean BOTH locations
        if data.agent_id == "default":
            raise HTTPException(status_code=400, detail="cannot remove default effort")
        for p in {effort_path, root_path}:
            if p.exists() or p.is_symlink():
                p.unlink()
        return {"status": "removed", "agent_id": data.agent_id}

    if data.level not in ("L", "M", "H"):
        raise HTTPException(status_code=400, detail="level must be L, M, or H")

    # Write to canonical location, and remove any ghost in the other to keep GET deterministic
    effort_path.parent.mkdir(parents=True, exist_ok=True)
    effort_path.write_text(data.level + "\n")
    if effort_path != root_path and (root_path.exists() or root_path.is_symlink()):
        root_path.unlink()
    return {"status": "updated", "agent_id": data.agent_id, "level": data.level}


# --- Favoris (persisted JSON per user per project) ---

@router.get("/api/config/favoris")
async def get_favoris(request: Request, project: str = "default"):
    """Get agent favoris config for the authenticated user+project."""
    user = _get_jwt_username(request)
    f = _favoris_file(user, project)
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception:
            pass
    return {}


@router.post("/api/config/favoris")
async def set_favoris(request: Request, data: dict):
    """Save agent favoris config. Body: {project, favoris: {agent_id: position (1-6)}}."""
    user = _get_jwt_username(request)
    project = data.get("project", "default")
    favoris = data.get("favoris", {})
    clean = {}
    for k, v in favoris.items():
        if isinstance(v, int) and 1 <= v <= 6:
            clean[k] = v
    _favoris_file(user, project).write_text(json.dumps(clean, indent=2) + "\n")
    return {"status": "ok", "user": user, "project": project, "favoris": clean}


@router.get("/api/config/favoris/projects")
async def get_favoris_projects(request: Request):
    """List all projects for the authenticated user."""
    user = _get_jwt_username(request)
    import glob as g
    safe_user = "".join(c for c in user if c.isalnum() or c in "-_")[:30].strip() or "default"
    pattern = str(cfg.BASE_DIR / "prompts" / f"favoris-{safe_user}-*.json")
    prefix = f"favoris-{safe_user}-"
    projects = []
    for path in sorted(g.glob(pattern)):
        name = Path(path).stem
        if name.startswith(prefix):
            proj = name[len(prefix):]
            if proj:
                projects.append(proj)
    return {"projects": projects}


@router.post("/api/config/favoris/rename")
async def rename_favoris_project(request: Request, data: dict):
    """Rename a favoris project. Body: {old_project, new_project}."""
    user = _get_jwt_username(request)
    old_project = data.get("old_project", "")
    new_project = data.get("new_project", "")
    if not old_project or not new_project:
        raise HTTPException(400, "old_project and new_project required")
    old_f = _favoris_file(user, old_project)
    new_f = _favoris_file(user, new_project)
    if old_f == new_f:
        favoris = {}
        if old_f.exists():
            try:
                favoris = json.loads(old_f.read_text())
            except Exception:
                pass
        return {"status": "ok", "project": new_project, "favoris": favoris}
    if new_f.exists():
        try:
            favoris = json.loads(new_f.read_text())
        except Exception:
            favoris = {}
        return {"status": "switched", "project": new_project, "favoris": favoris}
    favoris = {}
    if old_f.exists():
        old_f.rename(new_f)
        try:
            favoris = json.loads(new_f.read_text())
        except Exception:
            pass
    else:
        new_f.write_text("{}\n")
    return {"status": "renamed", "project": new_project, "favoris": favoris}


@router.post("/api/config/favoris/delete")
async def delete_favoris_project(request: Request, data: dict):
    """Delete a favoris project file. Body: {project}."""
    user = _get_jwt_username(request)
    project = data.get("project", "")
    if not project:
        raise HTTPException(400, "project required")
    f = _favoris_file(user, project)
    removed_dir = cfg.BASE_DIR / "removed"
    removed_dir.mkdir(exist_ok=True)
    if f.exists():
        import shutil
        import datetime
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.move(str(f), str(removed_dir / f"{ts}_{f.name}"))
    return {"status": "deleted", "project": project}


@router.get("/api/config/tmux-width")
async def get_tmux_width():
    """Get tmux width from persisted file, fallback to live sessions."""
    width_file = cfg.BASE_DIR / "prompts" / "tmux.width"
    if width_file.exists():
        try:
            return {"width": int(width_file.read_text().strip())}
        except Exception:
            pass
    try:
        result = await _run_subprocess(
            ["tmux", "list-sessions", "-F", "#{window_width}"],
            text=True, capture_output=True, timeout=5
        )
        widths = [int(w) for w in result.stdout.strip().split('\n') if w.strip().isdigit()]
        return {"width": widths[0] if widths else 220}
    except Exception:
        return {"width": 220}


@router.post("/api/config/tmux-width")
async def set_tmux_width(data: dict):
    """Resize all tmux windows to the given width."""
    width = data.get("width")
    if not isinstance(width, int) or width < 80 or width > 400:
        raise HTTPException(status_code=400, detail="width must be 80-400")
    try:
        result = await _run_subprocess(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            text=True, capture_output=True, timeout=5
        )
        sessions = [s.strip() for s in result.stdout.strip().split('\n') if s.strip()]
        resized = 0
        for s in sessions:
            await _run_subprocess(
                ["tmux", "resize-window", "-t", s, "-x", str(width), "-y", "50"],
                text=True, capture_output=True, timeout=5
            )
            resized += 1
        # Persist for new agent sessions
        (cfg.BASE_DIR / "prompts" / "tmux.width").write_text(str(width) + "\n")
        return {"status": "ok", "width": width, "sessions": resized}
    except Exception as e:
        logger.error("resize failed: %s", e)
        raise HTTPException(status_code=500, detail="operation failed")


@router.get("/api/config/panel")
async def get_panel_config():
    """Return panel overrides and current mode."""
    pcfg = _read_panel_config()
    return {"overrides": pcfg.get("overrides", {}), "mode": state._cache.get("mode", "pipeline")}


@router.post("/api/config/panel")
async def update_panel_config(data: PanelConfigUpdate):
    """Set or remove a panel override for an agent."""
    if not cfg.is_valid_agent_id(data.agent_id):
        raise HTTPException(status_code=400, detail="invalid agent_id")
    if data.panel not in ("control", "agent", ""):
        raise HTTPException(status_code=400, detail="panel must be 'control', 'agent', or ''")

    pcfg = _read_panel_config()
    overrides = pcfg.get("overrides", {})

    if data.panel == "":
        overrides.pop(data.agent_id, None)
    else:
        overrides[data.agent_id] = data.panel

    pcfg["overrides"] = overrides
    _write_panel_config(pcfg)
    return {"status": "ok", "overrides": overrides}


# === Keep Alive Config ===

@router.get("/api/config/keepalive")
async def get_keepalive():
    """List all login profiles with their keepalive and tmux status."""
    cfg.KEEPALIVE_DIR.mkdir(parents=True, exist_ok=True)

    # List profiles from login/ directory
    profiles = []
    if cfg.PROFILES_DIR.exists():
        for d in sorted(cfg.PROFILES_DIR.iterdir()):
            if d.is_dir() and d.name.startswith("claude"):
                profiles.append(d.name)

    # Check tmux sessions
    running_sessions = set()
    try:
        result = await _run_subprocess(
            ["tmux", "list-sessions", "-F", "#{session_name}"], text=True
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if line.startswith(f"{cfg.MA_PREFIX}-agent-002-"):
                    running_sessions.add(line.replace(f"{cfg.MA_PREFIX}-agent-002-", ""))
    except Exception:
        pass

    # Build entries
    entries = []
    for profile in profiles:
        active_file = cfg.KEEPALIVE_DIR / f"{profile}.active"
        suspended_file = cfg.KEEPALIVE_DIR / f"{profile}.suspended"
        is_active = active_file.exists()
        is_suspended = suspended_file.exists()
        is_running = profile in running_sessions

        entries.append({
            "profile": profile,
            "running": is_running,
            "keepalive": is_active,
            "suspended": is_suspended,
            "session": f"002-{profile}",
        })

    return {"entries": entries}


@router.post("/api/config/keepalive/start")
async def start_keepalive(data: dict):
    """Start a Claude login session with keepalive."""
    profile = data.get("profile", "")
    if not re.match(r'^claude\d[a-b]$', profile):
        raise HTTPException(status_code=400, detail="invalid profile")

    profile_dir = cfg.PROFILES_DIR / profile
    if not profile_dir.exists():
        raise HTTPException(status_code=404, detail="profile directory not found")

    session = f"{cfg.MA_PREFIX}-agent-002-{profile}"

    # Check if already running
    result = await _run_subprocess(["tmux", "has-session", "-t", session], text=True)
    if result.returncode == 0:
        raise HTTPException(status_code=409, detail="session already running")

    # Create tmux session with Claude
    cmd = f"cd '{cfg.BASE_DIR}' && CLAUDE_CONFIG_DIR='{profile_dir}' claude --dangerously-skip-permissions"
    await _run_subprocess([
        "tmux", "new-session", "-d", "-s", session, cmd
    ], text=True)

    # Create keepalive file
    cfg.KEEPALIVE_DIR.mkdir(parents=True, exist_ok=True)
    keepalive_file = cfg.KEEPALIVE_DIR / f"{profile}.active"
    if not keepalive_file.exists():
        keepalive_file.write_text("toujours en vie ?\n")

    return {"status": "started", "session": session}


@router.post("/api/config/keepalive/stop")
async def stop_keepalive(data: dict):
    """Stop a Claude login session."""
    profile = data.get("profile", "")
    if not re.match(r'^claude\d[a-b]$', profile):
        raise HTTPException(status_code=400, detail="invalid profile")

    session = f"{cfg.MA_PREFIX}-agent-002-{profile}"
    await _run_subprocess(["tmux", "kill-session", "-t", session], text=True)

    # Move keepalive file to suspended
    active = cfg.KEEPALIVE_DIR / f"{profile}.active"
    suspended = cfg.KEEPALIVE_DIR / f"{profile}.suspended"
    if active.exists():
        active.rename(suspended)

    return {"status": "stopped"}


@router.post("/api/config/keepalive/probe")
async def probe_keepalive(data: dict):
    """Read cached profile info from static JSON file."""
    profile = data.get("profile", "")
    if not re.match(r'^claude\d[a-b]$', profile):
        raise HTTPException(status_code=400, detail="invalid profile")

    info_file = cfg.KEEPALIVE_DIR / f"info_{profile}.json"
    if info_file.exists():
        try:
            info = json.loads(info_file.read_text())
        except Exception:
            info = {}
    else:
        info = {}

    return {"profile": profile, "info": info}
