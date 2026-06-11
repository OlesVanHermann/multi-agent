"""Multi-Agent Dashboard API — module d'assemblage FastAPI (B1).

Le code applicatif vit dans le package multi_agent/ :
  config.py    constantes et variables d'environnement
  state.py     état mutable partagé (redis_pool, cache)
  auth.py      vérification JWT Keycloak + pont freemium
  ratelimit.py rate limiter Redis + fallback local
  cache.py     boucle de rafraîchissement du cache agents
  routers/     routes HTTP et WebSocket par domaine

Ce module ne fait qu'assembler : lifespan, middlewares, routers, statiques.
Entrée uvicorn : multi_agent.backend:app (qui ré-exporte app d'ici).
"""

import asyncio
import json
import os
import shlex
import subprocess
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from multi_agent import config as cfg
from multi_agent import state
from multi_agent.auth import _PUBLIC_PATHS, _PUBLIC_PREFIXES, _verify_jwt_minimal
from multi_agent.cache import _cache_loop, _seed_prompt_history
from multi_agent.ratelimit import _check_rate_limit
from multi_agent.routers import agent_chat, agents, chat, crontab, system, ws
from multi_agent.routers import config as config_routes

# === Ré-exports compat tests (lecture seule) ===
from multi_agent.config import (  # noqa: F401
    BASE_DIR,
    MA_PREFIX,
    _EXPECTED_AUDIENCE,
    _EXPECTED_ISSUER,
)
from multi_agent.cache import PANE_STATE_TTL, _pane_states_from_redis  # noqa: F401
from multi_agent.ratelimit import _RATE_WINDOW, _check_rate_limit_local  # noqa: F401

__all__ = ["app"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown events"""
    state.redis_pool = redis.Redis(
        host=cfg.REDIS_HOST,
        port=cfg.REDIS_PORT,
        password=cfg.REDIS_PASSWORD or None,
        decode_responses=True
    )
    try:
        await state.redis_pool.ping()
        print(f"Connected to Redis at {cfg.REDIS_HOST}:{cfg.REDIS_PORT}")
    except Exception as e:
        print(f"WARNING: Redis connection failed: {e}")

    # Seed prompt history stream from existing .history files
    await _seed_prompt_history()

    # Start background cache refresh
    state._cache_task = asyncio.create_task(_cache_loop())
    print(f"Background cache started (refresh every {cfg.CACHE_REFRESH_INTERVAL}s)")

    # Start crontab-scheduler if not already running (one per MA_PREFIX)
    _crontab_session = f"{cfg.MA_PREFIX}-agent-001"
    _crontab_script = cfg.BASE_DIR / "scripts" / "crontab-scheduler.py"
    _crontab_log = cfg.BASE_DIR / "logs" / "crontab-scheduler.log"
    try:
        check = subprocess.run(
            ["tmux", "has-session", "-t", _crontab_session],
            capture_output=True, timeout=5
        )
        if check.returncode != 0 and _crontab_script.exists():
            os.makedirs(cfg.BASE_DIR / "logs", exist_ok=True)
            _env_file = cfg.BASE_DIR / "setup" / "secrets.cfg"
            _base = shlex.quote(str(cfg.BASE_DIR))
            _script = shlex.quote(str(_crontab_script))
            _log = shlex.quote(str(_crontab_log))
            _envf = shlex.quote(str(_env_file))
            _source_env = f"set -a; source {_envf} 2>/dev/null; set +a; " if _env_file.exists() else ""
            _prefix = shlex.quote(cfg.MA_PREFIX)
            subprocess.run([
                "tmux", "new-session", "-d", "-s", _crontab_session,
                f"cd {_base} && {_source_env}MA_PREFIX={_prefix} python3 -u {_script} 2>&1 | tee -a {_log}"
            ], timeout=5)
            print(f"Crontab scheduler started: {_crontab_session}")
        else:
            print(f"Crontab scheduler already running: {_crontab_session}")
    except Exception as e:
        print(f"WARNING: Could not start crontab scheduler: {e}")

    yield

    # Stop background cache
    if state._cache_task:
        state._cache_task.cancel()
        try:
            await state._cache_task
        except asyncio.CancelledError:
            pass

    if state.redis_pool:
        await state.redis_pool.close()


app = FastAPI(
    title="Multi-Agent Dashboard API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg._ALLOWED_ORIGINS + cfg._ALLOWED_ORIGINS_LOCAL_DEV,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# === Security Headers Middleware ===

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
    return response


# === JWT Auth Middleware ===
# Keycloak JWT verification on all /api/* routes (except paths publics et /auth/*)

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path

    # Rate limit all API requests
    if path.startswith("/api/"):
        client_ip = request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")
        if not await _check_rate_limit(client_ip):
            return Response(
                content=json.dumps({"detail": "Rate limit exceeded"}),
                status_code=429,
                media_type="application/json",
            )

    # Skip auth for public paths, static files, and WebSocket upgrades (handled separately)
    if path in _PUBLIC_PATHS or any(path.startswith(p) for p in _PUBLIC_PREFIXES):
        return await call_next(request)

    # Skip non-API paths (frontend static files served by StaticFiles mount)
    if not path.startswith("/api/") and not path.startswith("/ws/"):
        return await call_next(request)

    # Extract Bearer token
    auth_header = request.headers.get("authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    elif request.query_params.get("token"):
        token = request.query_params.get("token")  # WebSocket fallback

    if not token or not _verify_jwt_minimal(token):
        return Response(
            content=json.dumps({"detail": "Authentication required"}),
            status_code=401,
            media_type="application/json",
        )

    return await call_next(request)


# === Routers ===

app.include_router(system.router)
app.include_router(agents.router)
app.include_router(config_routes.router)
app.include_router(crontab.router)
app.include_router(chat.router)
app.include_router(agent_chat.router)
app.include_router(ws.router)


# === Static Files (Frontend) ===

# Serve static assets (JS, CSS, etc.)
frontend_path = os.path.join(os.path.dirname(__file__), cfg.FRONTEND_DIR)
if os.path.exists(frontend_path):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_path, "assets")), name="assets")

    @app.get("/")
    async def serve_index():
        """Serve frontend index.html (no-cache to pick up new builds)"""
        return FileResponse(
            os.path.join(frontend_path, "index.html"),
            headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"},
        )

    @app.get("/{path:path}")
    async def serve_spa(path: str):
        """Catch-all for SPA routing — path-traversal hardened"""
        if not path or path.startswith("/") or ".." in path or "\\" in path:
            return FileResponse(os.path.join(frontend_path, "index.html"))
        candidate = os.path.normpath(os.path.join(frontend_path, path))
        fp_abs = os.path.abspath(frontend_path)
        if not (candidate == fp_abs or candidate.startswith(fp_abs + os.sep)):
            return FileResponse(os.path.join(frontend_path, "index.html"))
        if os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(frontend_path, "index.html"))


# === Main ===

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8050)
