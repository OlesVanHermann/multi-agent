"""Routes de configuration : slots de login neutres et modèles."""

# E1 : la couche moteur est IMPORTÉE, pas recopiée. cfg a déjà inséré
# scripts/agent-bridge dans sys.path (même convention que ids.py / A6).
# Un miroir local aurait exactement le défaut qu'E1 corrige : une hypothèse
# dupliquée qui dérive.
import engines  # noqa: E402

ENGINES = engines.ENGINES
ENGINE_DEFAULT = engines.ENGINE_DEFAULT
ENGINE_MODEL_PREFIX = engines.ENGINE_MODEL_PREFIX
ENGINE_CONFIG_ENV = engines.ENGINE_CONFIG_ENV
ENGINE_BYPASS_FLAG = engines.ENGINE_BYPASS_FLAG
_model_matches_engine = engines.model_matches_engine

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
from ..tmuxio import _run_subprocess
from ..models import (
    AgentEngineUpdate,
    EffortUpdate,
    LoginModelUpdate,
    PanelConfigUpdate,
)
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
        if not f.is_symlink() and f.stem.startswith("login")
    )
    models = sorted(
        f.stem for f in prompts_dir.glob("*.model")
        if not f.is_symlink() and f.stem != "default"
    )
    clis = list(ENGINES)

    # Identifiant réel porté par chaque fichier *.model — sert au garde-fou
    # de compatibilité modèle↔moteur côté UI.
    model_ids = {}
    for name in models:
        try:
            model_ids[name] = (prompts_dir / f"{name}.model").read_text().strip()
        except OSError:
            model_ids[name] = ""

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

    # E1 : moteur par défaut. Absence de prompts/default.cli = installation
    # antérieure à E1 → `claude`, comportement historique strictement inchangé.
    default_cli = ENGINE_DEFAULT
    dc = prompts_dir / "default.cli"
    if dc.is_symlink():
        default_cli = Path(os.readlink(dc)).stem
    elif dc.exists():
        default_cli = dc.read_text().strip() or ENGINE_DEFAULT

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

        model_id = model_ids.get(agent_model, "")
        agent_cli = "codex" if model_id.startswith("gpt-") else "claude"
        cli_source = "model"

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
            "cli": agent_cli,
            "cli_source": cli_source,
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
        "clis": clis,
        "model_ids": model_ids,
        "engine_model_prefix": ENGINE_MODEL_PREFIX,
        "default_login": default_login,
        "default_model": default_model,
        "default_cli": default_cli,
        "default_effort": default_effort,
        "agents": agents,
        "groups": groups,
    }


def _effective_cli(prompts_dir: Path, agent_id: str) -> str:
    """Moteur effectif d'un agent (override > parent x45 > default)."""
    if agent_id != "default":
        f = _find_agent_config(prompts_dir, agent_id, "cli")
        if f and f.is_symlink():
            return Path(os.readlink(f)).stem
        if "-" in agent_id:
            parent = prompts_dir / f"{agent_id.split('-')[0]}.cli"
            if parent.is_symlink():
                return Path(os.readlink(parent)).stem
    dc = prompts_dir / "default.cli"
    if dc.is_symlink():
        return Path(os.readlink(dc)).stem
    if dc.exists():
        return dc.read_text().strip() or ENGINE_DEFAULT
    return ENGINE_DEFAULT


def _effective_model_id(prompts_dir: Path, agent_id: str) -> str:
    """ID de modèle effectif d'un agent, ou ''.

    Reproduit EXACTEMENT la cascade du GET /api/config/logins-models :
    override agent → override parent (x45/z21) → default. Une cascade
    divergente ferait valider une combinaison que agent.sh refuserait ensuite.
    """
    f = None
    if agent_id != "default":
        f = _find_agent_config(prompts_dir, agent_id, "model")
        if not (f and f.is_symlink()):
            f = None
            if "-" in agent_id:
                parent = prompts_dir / f"{agent_id.split('-')[0]}.model"
                if parent.is_symlink():
                    f = parent
    if f is None:
        f = prompts_dir / "default.model"
    try:
        return f.resolve().read_text().strip()
    except OSError:
        return ""


def _guard_engine_model_compat(prompts_dir: Path, data: LoginModelUpdate) -> None:
    """The model selects the engine; neutral login slots are always compatible."""
    return None


_profile_engine = engines.profile_engine
PROFILE_RE = re.compile(engines.PROFILE_RE)


def _link_path_for(prompts_dir: Path, agent_id: str, ext: str):
    """Chemin du symlink d'override + cible relative — MIROIR de
    _find_agent_config : le répertoire de l'agent (mono comme x45/z21) a
    priorité sur prompts/. Écrire à plat quand l'agent a un répertoire
    produirait un override FANTÔME : le lien du répertoire (ex.
    160-create-x45/160.model → ../default.model) le masque à la lecture
    ET au démarrage (resolve_config d'agent.sh a le même ordre)."""
    if agent_id != "default":
        base_id = agent_id.split("-")[0]
        agent_dir = _resolve_prompts_dir(prompts_dir, base_id)
        if agent_dir:
            return agent_dir / f"{agent_id}.{ext}", "../"
    return prompts_dir / f"{agent_id}.{ext}", ""


def _write_override(prompts_dir: Path, agent_id: str, ext: str, value: str):
    """Pose (ou remplace) le symlink d'override <agent_id>.<ext> → <value>.<ext>."""
    link_path, prefix = _link_path_for(prompts_dir, agent_id, ext)
    target = prompts_dir / f"{value}.{ext}"
    if not target.exists() or target.is_symlink():
        raise HTTPException(status_code=400, detail=f"target {value}.{ext} not found")
    if link_path.is_symlink() or link_path.exists():
        link_path.unlink()
    link_path.symlink_to(f"{prefix}{value}.{ext}")


@router.post("/api/config/engine")
async def update_agent_engine(data: AgentEngineUpdate):
    """E1 — Bascule ATOMIQUE moteur + modèle (+ profil) d'un agent.

    Sans cet endpoint, le garde-fou de compatibilité crée un interblocage :
    un agent `claude` + modèle `claude-*` ne peut passer à `codex` + `gpt-*`
    ni en changeant le moteur d'abord (moteur codex sur modèle claude → 400),
    ni le modèle d'abord (modèle gpt sur moteur claude → 400).

    Ici le TRIPLET est validé d'un bloc, puis écrit. Si une écriture échoue,
    les précédentes sont annulées (l'état partiel serait pire que l'échec :
    agent.sh refuserait de démarrer l'agent).
    """
    prompts_dir = cfg.BASE_DIR / "prompts"

    if data.agent_id != "default" and not cfg.is_valid_agent_id(data.agent_id):
        raise HTTPException(status_code=400, detail="invalid agent_id")
    if data.cli not in ENGINES:
        raise HTTPException(
            status_code=400,
            detail=f"unknown engine '{data.cli}' (expected: {', '.join(ENGINES)})",
        )
    for v in (data.model, data.login):
        if v is not None and not re.match(r"^[a-zA-Z0-9_.-]+$", v):
            raise HTTPException(status_code=400, detail="invalid value")

    # 1. Cohérence modèle ↔ moteur
    try:
        model_id = (prompts_dir / f"{data.model}.model").read_text().strip()
    except OSError:
        raise HTTPException(status_code=400, detail=f"target {data.model}.model not found")
    if not _model_matches_engine(model_id, data.cli):
        raise HTTPException(
            status_code=400,
            detail=(
                f"model '{model_id}' is incompatible with engine '{data.cli}' "
                f"(expected prefix '{ENGINE_MODEL_PREFIX.get(data.cli, '?')}')"
            ),
        )

    # 2. Cohérence profil ↔ moteur (un profil codex en CLAUDE_CONFIG_DIR = auth cassée)
    if data.login:
        if not PROFILE_RE.match(data.login):
            raise HTTPException(status_code=400, detail="invalid login profile name")
        if _profile_engine(data.login) != data.cli:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"login profile '{data.login}' does not belong to engine "
                    f"'{data.cli}' (expected a '{data.cli}*' profile)"
                ),
            )

    # 3. Écriture atomique (rollback des symlinks déjà posés en cas d'échec)
    written = []
    try:
        for ext, value in (("cli", data.cli), ("model", data.model), ("login", data.login)):
            if value is None:
                continue
            link_path, _ = _link_path_for(prompts_dir, data.agent_id, ext)
            previous = os.readlink(link_path) if link_path.is_symlink() else None
            _write_override(prompts_dir, data.agent_id, ext, value)
            written.append((link_path, previous))
    except Exception:
        for link_path, previous in reversed(written):
            if link_path.is_symlink() or link_path.exists():
                link_path.unlink()
            if previous is not None:
                link_path.symlink_to(previous)
        raise

    return {
        "status": "updated",
        "agent_id": data.agent_id,
        "cli": data.cli,
        "model": data.model,
        "login": data.login,
    }


@router.post("/api/config/logins-models")
async def update_login_model(data: LoginModelUpdate):
    """Create or remove a login/model symlink override for an agent."""
    prompts_dir = cfg.BASE_DIR / "prompts"

    if data.type not in ("login", "model"):
        raise HTTPException(status_code=400, detail="type must be 'login' or 'model'")

    # E1 : un moteur inconnu ne doit jamais atteindre agent.sh
    if data.type == "cli" and data.value and data.value not in ENGINES:
        raise HTTPException(
            status_code=400,
            detail=f"unknown engine '{data.value}' (expected: {', '.join(ENGINES)})",
        )

    # Validate agent_id format
    if data.agent_id != "default" and not cfg.is_valid_agent_id(data.agent_id):
        raise HTTPException(status_code=400, detail="invalid agent_id")

    # Validate data.value (prevent path traversal)
    if data.value and not re.match(r'^[a-zA-Z0-9_.-]+$', data.value):
        raise HTTPException(status_code=400, detail="invalid value")

    # Même résolution que la lecture (_find_agent_config) : répertoire de
    # l'agent d'abord (mono comme x45/z21), prompts/ sinon.
    link_path, _prefix = _link_path_for(prompts_dir, data.agent_id, data.type)
    symlink_target = f"{_prefix}{data.value}.{data.type}" if data.value else ""

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

    # E1 : garde-fou modèle ↔ moteur. Sans lui, l'UI laisse assigner un modèle
    # OpenAI à un agent Claude Code : la slash-command /model est alors ignorée
    # par le TUI, l'agent tourne SILENCIEUSEMENT sur son modèle par défaut.
    _guard_engine_model_compat(prompts_dir, data)

    # Create/replace symlink
    if link_path.is_symlink() or link_path.exists():
        link_path.unlink()
    link_path.symlink_to(symlink_target)

    # Nettoyer l'éventuel fantôme à plat (ancien emplacement d'écriture) : il
    # serait masqué par le lien du répertoire mais fausserait tout lecteur
    # qui ne regarde que prompts/.
    ghost = prompts_dir / f"{data.agent_id}.{data.type}"
    if ghost != link_path and (ghost.is_symlink() or ghost.exists()):
        ghost.unlink()

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

    # Même résolution que la lecture : répertoire de l'agent d'abord
    # (mono comme x45/z21), prompts/ sinon — cf. _link_path_for.
    root_path = prompts_dir / f"{data.agent_id}.effort"
    effort_path, _ = _link_path_for(prompts_dir, data.agent_id, "effort")

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

    # Application À CHAUD : si la session tourne et que l'agent est libre, la
    # commande du CLI est envoyée au TUI (claude: /effort <niveau> ; codex:
    # picker /model piloté). Une seule implémentation de la danse — celle de
    # scripts/engines.sh, partagée avec agent.sh/infra.sh. Agent occupé ou
    # session absente : le .effort prendra effet au prochain démarrage.
    applied = False
    reason = "session absente"
    if data.agent_id != "default":
        session = f"{cfg.MA_PREFIX}-agent-{data.agent_id}"
        alive = await _run_subprocess(["tmux", "has-session", "-t", session])
        if alive.returncode == 0:
            busy = False
            if state.redis_pool:
                try:
                    ps = await state.redis_pool.hget(f"{cfg.MA_PREFIX}:agent:{data.agent_id}", "pane_state")
                    busy = bool(json.loads(ps).get("busy")) if ps else False
                except Exception:
                    busy = False
            if busy:
                reason = "agent occupé — effectif au prochain démarrage"
            else:
                cli = engines.engine_for_model(_effective_model_id(prompts_dir, data.agent_id))
                model_arg = _effective_model_id(prompts_dir, data.agent_id) if cli == "codex" else ""
                res = await _run_subprocess(
                    ["bash", "-c",
                     'source "$1/scripts/engines.sh" && engine_apply_model_effort "$2" "$3" "$4" "$5"',
                     "_", str(cfg.BASE_DIR), session, cli, model_arg, data.level],
                    timeout=40,
                )
                applied = res.returncode == 0
                reason = "" if applied else "échec de la commande TUI (voir logs)"
    return {"status": "updated", "agent_id": data.agent_id, "level": data.level,
            "applied": applied, **({"reason": reason} if not applied else {})}


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

    # List profiles from login/ directory — E1 : tous les moteurs, pas que claude
    profiles = []
    if cfg.PROFILES_DIR.exists():
        for d in sorted(cfg.PROFILES_DIR.iterdir()):
            if d.is_dir() and _profile_engine(d.name):
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
            "engine": _profile_engine(profile),
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
    if not PROFILE_RE.match(profile):
        raise HTTPException(status_code=400, detail="invalid profile")

    profile_dir = cfg.PROFILES_DIR / profile
    if not profile_dir.exists():
        raise HTTPException(status_code=404, detail="profile directory not found")

    session = f"{cfg.MA_PREFIX}-agent-002-{profile}"

    # Check if already running
    result = await _run_subprocess(["tmux", "has-session", "-t", session], text=True)
    if result.returncode == 0:
        raise HTTPException(status_code=409, detail="session already running")

    # E1 : commande de lancement selon le moteur du profil — un profil codex
    # lancé avec `claude` + CLAUDE_CONFIG_DIR produirait une auth cassée.
    engine = _profile_engine(profile)
    if not engine:
        raise HTTPException(status_code=400, detail="cannot determine engine for profile")
    cmd = (
        f"cd '{cfg.BASE_DIR}' && {ENGINE_CONFIG_ENV[engine]}='{profile_dir}' "
        f"{engine} {ENGINE_BYPASS_FLAG[engine]}"
    )
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
    if not PROFILE_RE.match(profile):
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
    if not PROFILE_RE.match(profile):
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
