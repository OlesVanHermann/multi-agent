"""Routes /api/config/crontab : prompts périodiques par agent (B1)."""

import re
import time

from fastapi import APIRouter, HTTPException

from .. import config as cfg
from ..models import CrontabCreate, CrontabDelete, CrontabUpdate

router = APIRouter()

_CRONTAB_PROMPT_MAX = 2000


@router.get("/api/config/crontab")
async def get_crontab():
    """List all crontab entries (active + suspended)."""
    cfg.CRONTAB_DIR.mkdir(parents=True, exist_ok=True)
    entries = []
    for f in sorted(cfg.CRONTAB_DIR.iterdir()):
        if not f.is_file():
            continue
        name = f.name
        suspended = name.endswith(".prompt.suspended")
        if not suspended and not name.endswith(".prompt"):
            continue
        # Parse: {agent}-{period}.prompt[.suspended]
        base = name.replace(".suspended", "")
        m = re.match(rf'^({cfg.AGENT_ID_PATTERN})_(\d+)\.prompt$', base)
        if not m:
            continue
        try:
            prompt = f.read_text(errors="replace").strip()
        except Exception:
            prompt = ""
        entries.append({
            "agent_id": m.group(1),
            "period": int(m.group(2)),
            "prompt": prompt,
            "suspended": suspended,
        })
    return {"entries": entries}


@router.post("/api/config/crontab")
async def create_crontab(data: CrontabCreate):
    """Create a new crontab entry."""
    if not cfg.is_valid_agent_id(data.agent_id):
        raise HTTPException(status_code=400, detail="invalid agent_id")
    base_id = data.agent_id.split("-")[0] if "-" in data.agent_id else data.agent_id
    if base_id == "000":
        raise HTTPException(status_code=403, detail="Cannot schedule crontab for architect agent")
    if data.period not in cfg.VALID_CRONTAB_PERIODS:
        raise HTTPException(status_code=400, detail=f"period must be one of {sorted(cfg.VALID_CRONTAB_PERIODS)}")
    if not data.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt cannot be empty")
    if len(data.prompt) > _CRONTAB_PROMPT_MAX:
        raise HTTPException(status_code=400, detail=f"prompt too long (max {_CRONTAB_PROMPT_MAX})")

    cfg.CRONTAB_DIR.mkdir(parents=True, exist_ok=True)
    filepath = cfg.CRONTAB_DIR / f"{data.agent_id}_{data.period}.prompt"
    if filepath.exists() or filepath.with_suffix(".prompt.suspended").exists():
        raise HTTPException(status_code=409, detail="Entry already exists")
    filepath.write_text(data.prompt.strip() + "\n")
    return {"status": "created", "file": filepath.name}


@router.put("/api/config/crontab")
async def update_crontab(data: CrontabUpdate):
    """Update, suspend, or resume a crontab entry."""
    if not cfg.is_valid_agent_id(data.agent_id):
        raise HTTPException(status_code=400, detail="invalid agent_id")
    base_id = data.agent_id.split("-")[0] if "-" in data.agent_id else data.agent_id
    if base_id == "000":
        raise HTTPException(status_code=403, detail="Cannot modify crontab for architect agent")
    if data.period not in cfg.VALID_CRONTAB_PERIODS:
        raise HTTPException(status_code=400, detail=f"period must be one of {sorted(cfg.VALID_CRONTAB_PERIODS)}")
    if data.prompt is not None and len(data.prompt) > _CRONTAB_PROMPT_MAX:
        raise HTTPException(status_code=400, detail=f"prompt too long (max {_CRONTAB_PROMPT_MAX})")

    base = f"{data.agent_id}_{data.period}.prompt"
    active = cfg.CRONTAB_DIR / base
    suspended = cfg.CRONTAB_DIR / f"{base}.suspended"

    if data.action == "suspend":
        if not active.exists():
            raise HTTPException(status_code=404, detail="Active entry not found")
        active.rename(suspended)
        return {"status": "suspended", "file": suspended.name}

    elif data.action == "resume":
        if not suspended.exists():
            raise HTTPException(status_code=404, detail="Suspended entry not found")
        suspended.rename(active)
        return {"status": "resumed", "file": active.name}

    else:
        # Update prompt content
        target = active if active.exists() else suspended if suspended.exists() else None
        if not target:
            raise HTTPException(status_code=404, detail="Entry not found")
        if data.prompt is not None:
            target.write_text(data.prompt.strip() + "\n")
        return {"status": "updated", "file": target.name}


@router.delete("/api/config/crontab")
async def delete_crontab(data: CrontabDelete):
    """Delete a crontab entry (moves to removed/)."""
    if not cfg.is_valid_agent_id(data.agent_id):
        raise HTTPException(status_code=400, detail="invalid agent_id")

    base = f"{data.agent_id}_{data.period}.prompt"
    active = cfg.CRONTAB_DIR / base
    suspended = cfg.CRONTAB_DIR / f"{base}.suspended"

    target = active if active.exists() else suspended if suspended.exists() else None
    if not target:
        raise HTTPException(status_code=404, detail="Entry not found")

    # Safe remove: move to removed/
    removed_dir = cfg.BASE_DIR / "removed"
    removed_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    dest = removed_dir / f"{ts}_{target.name}"
    target.rename(dest)
    return {"status": "deleted", "moved_to": str(dest)}
