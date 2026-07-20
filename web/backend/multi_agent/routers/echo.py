"""Endpoint opérateur du Contradictor NNN-2XX (route legacy /api/echo)."""

from fastapi import APIRouter, HTTPException

from .. import config as cfg
from ..echo import collect_snapshot, emit_echo_wal, persist_snapshot
from ..models import EchoObservationRequest

router = APIRouter()


def _is_compound_2xx(agent_id: str) -> bool:
    parts = agent_id.split("-")
    return (cfg.is_valid_agent_id(agent_id) and len(parts) == 2
            and 200 <= int(parts[1]) <= 299)


@router.get("/api/echo")
async def echo_status(limit: int = 50, echo_id: str | None = None):
    limit = max(1, min(limit, 200))
    if echo_id and not _is_compound_2xx(echo_id):
        raise HTTPException(status_code=400, detail="Observer ID must be NNN-2XX")
    root = cfg.BASE_DIR / "pool-requests" / "knowledge" / "echo"
    artifacts = []
    if root.is_dir():
        pattern = f"{echo_id}/*.snapshot.json" if echo_id else "*/*.snapshot.json"
        for path in sorted(root.glob(pattern), reverse=True)[:limit]:
            try:
                artifacts.append({"path": str(path.relative_to(cfg.BASE_DIR)),
                                  "size": path.stat().st_size,
                                  "mtime": int(path.stat().st_mtime)})
            except OSError:
                continue
    return {"enabled": cfg.ECHO_OBSERVER_ENABLED, "artifacts": artifacts}


@router.post("/api/echo/{echo_id}/observe")
async def observe(echo_id: str, request: EchoObservationRequest):
    if not cfg.ECHO_OBSERVER_ENABLED:
        raise HTTPException(status_code=404, detail="Contradictor is disabled")
    if not _is_compound_2xx(echo_id):
        raise HTTPException(status_code=400, detail="Observer ID must be NNN-2XX")
    if not cfg.is_valid_agent_id(request.target_agent):
        raise HTTPException(status_code=400, detail="Invalid target agent ID")
    if request.target_agent.split("-", 1)[0] != echo_id.split("-", 1)[0]:
        raise HTTPException(status_code=400, detail="Contradictor may only observe its own triangle")

    await emit_echo_wal("echo_requested", echo_id, request.task_id, target=request.target_agent)
    snapshot = await collect_snapshot(echo_id, request)
    path, digest = persist_snapshot(snapshot)
    relative = str(path.relative_to(cfg.BASE_DIR))
    await emit_echo_wal(
        "echo_snapshot_ready", echo_id, request.task_id,
        target=request.target_agent, artifact=relative, sha256=digest,
    )
    return {
        "status": "snapshot_ready",
        "artifact": relative,
        "sha256": digest,
        "dispatched": False,
        "workflow_transition": False,
    }
