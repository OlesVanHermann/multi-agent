"""Routes système : health, lecture de fichiers, upload, logs frontend, proxy Keycloak (B1)."""

import json
import logging
import os
import re
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import Response

from .. import config as cfg
from .. import state
from ..prompts import _resolve_prompts_dir

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/health")
async def health():
    """Health check — reads from background cache"""
    return state._cache["health"]


@router.get("/api/file")
async def read_prompt_file(path: str = "", reverse: bool = False):
    """Read a file from allowed directories (prompts/, logs/).
    Resolves named directories: prompts/345/file → prompts/345-name/file.
    reverse=true returns lines in reverse order (newest first for LOGS.md).
    """
    if not path:
        raise HTTPException(status_code=400, detail="path required")
    # Block path traversal attempts
    if ".." in path or "\x00" in path:
        raise HTTPException(status_code=403, detail="forbidden")
    full = (cfg.BASE_DIR / path).resolve()
    allowed_roots = [
        (cfg.BASE_DIR / "prompts").resolve(),
        (cfg.BASE_DIR / "logs").resolve(),
    ]
    if not any(str(full) == str(root) or str(full).startswith(str(root) + os.sep) for root in allowed_roots):
        raise HTTPException(status_code=403, detail="forbidden")
    # Reject symlinks pointing outside allowed directories
    if full.is_symlink():
        target = full.resolve()
        if not any(str(target) == str(root) or str(target).startswith(str(root) + os.sep) for root in allowed_roots):
            raise HTTPException(status_code=403, detail="forbidden")
    # If not found, try resolving named directory (345 → 345-develop-fonction-beta)
    if not full.exists():
        parts = Path(path).parts  # e.g. ('prompts', '345', '345-system.md')
        if len(parts) >= 2 and parts[0] == 'prompts' and re.match(r'^\d{3}$', parts[1]):
            resolved_dir = _resolve_prompts_dir(cfg.BASE_DIR / "prompts", parts[1])
            if resolved_dir:
                full = (resolved_dir / Path(*parts[2:])).resolve()
                if not any(str(full) == str(root) or str(full).startswith(str(root) + os.sep) for root in allowed_roots):
                    raise HTTPException(status_code=403, detail="forbidden")
    if not full.exists() or not full.is_file():
        raise HTTPException(status_code=404, detail="not found")
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
    if full.stat().st_size > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="file too large")
    try:
        content = full.read_text(encoding="utf-8")
        if reverse:
            lines = content.splitlines()
            content = "\n".join(reversed(lines))
    except Exception:
        raise HTTPException(status_code=500, detail="read error")
    return {"path": path, "content": content}


MAX_UPLOAD_SIZE = 5 * 1024 * 1024 * 1024  # 5 GB


@router.post("/api/upload")
async def upload_file(file: UploadFile):
    """Upload a file to /tmp and return its path."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="no filename")
    # Sanitize: strip path components, replace spaces, remove ..
    safe_name = os.path.basename(file.filename).replace(" ", "_")
    safe_name = re.sub(r'[^\w.\-]', '_', safe_name)
    if not safe_name or safe_name.startswith('.'):
        safe_name = f"upload_{int(time.time())}"
    ts = time.strftime("%Y%m%d_%H%M%S")
    dest = Path("/tmp") / f"{ts}_{safe_name}"
    counter = 1
    while dest.exists():
        dest = Path("/tmp") / f"{ts}_{counter}_{safe_name}"
        counter += 1
    size = 0
    try:
        with open(dest, "wb") as f:
            while chunk := await file.read(8192):
                size += len(chunk)
                if size > MAX_UPLOAD_SIZE:
                    dest.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail="file too large (max 5GB)")
                f.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("upload failed: %s", e)
        raise HTTPException(status_code=500, detail="upload failed")
    return {"path": str(dest), "name": safe_name, "size": size}


@router.post("/api/logs/frontend")
async def post_frontend_logs(request: Request):
    """Receive frontend log events and append them as JSONL to logs/frontend/."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    events = body.get("events", [])
    if not events:
        return {"ok": True, "written": 0}
    if not isinstance(events, list) or len(events) > 20:
        raise HTTPException(status_code=400, detail="events must be a list of max 20 items")

    cfg.FRONTEND_LOG_DIR.mkdir(parents=True, exist_ok=True)

    date_str = time.strftime("%Y-%m-%d", time.gmtime())
    log_path = cfg.FRONTEND_LOG_DIR / f"frontend-{date_str}.jsonl"

    if log_path.exists() and log_path.stat().st_size > 50_000_000:
        return {"ok": True, "written": 0, "capped": True}

    lines = "\n".join(json.dumps(e, separators=(",", ":"))[:10000] for e in events) + "\n"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(lines)

    return {"ok": True, "written": len(events)}


@router.api_route("/auth/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy_keycloak(request: Request, path: str):
    """Auth endpoint: proxy to Keycloak. Returns 503 if Keycloak is unavailable."""

    normalized_path = os.path.normpath(path)
    if "/admin" in normalized_path or ".." in normalized_path or not any(path.startswith(p) for p in cfg._KEYCLOAK_ALLOWED_PREFIXES):
        return Response(content=json.dumps({"error": "forbidden", "error_description": "Path not allowed"}),
                        status_code=403, headers={"Content-Type": "application/json"})

    url = f"{cfg.KEYCLOAK_URL}/{path}"
    body = await request.body()
    if len(body) > 1_000_000:
        return Response(content=json.dumps({"error": "request too large"}), status_code=413,
                        media_type="application/json")
    _PROXY_ALLOWED_REQ_HEADERS = {"content-type", "accept", "authorization", "accept-language"}
    headers = {k: v for k, v in request.headers.items() if k.lower() in _PROXY_ALLOWED_REQ_HEADERS}

    _HOP_BY_HOP = {"transfer-encoding", "connection", "keep-alive", "proxy-authenticate",
                    "proxy-authorization", "te", "trailers", "upgrade", "content-length"}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.request(
                method=request.method, url=url, headers=headers, content=body,
                params=request.query_params, timeout=30.0
            )
            safe_headers = {k: v for k, v in response.headers.items() if k.lower() not in _HOP_BY_HOP}
            return Response(content=response.content, status_code=response.status_code,
                            headers=safe_headers)
        except Exception:
            return Response(
                content=json.dumps({"error": "service_unavailable", "error_description": "Keycloak is not reachable. Start Keycloak first."}),
                status_code=503,
                headers={"Content-Type": "application/json"},
            )
