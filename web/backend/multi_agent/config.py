"""Configuration du dashboard : variables d'environnement et constantes (B1)."""

import os
import re
import sys
from pathlib import Path

# A6 : source unique du format d'ID agent (scripts/agent-bridge/ids.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts" / "agent-bridge"))
from ids import AGENT_ID_PATTERN, AGENT_ID_RE, is_valid_agent_id  # noqa: E402,F401

# Frontend static files path
FRONTEND_DIR = os.environ.get("FRONTEND_DIR", "../frontend/dist")

# Keycloak URL for auth proxy
KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://localhost:8080")
KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM", "multi-agent")
KEYCLOAK_JWKS_URL = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs"
_EXPECTED_AUDIENCE = os.environ.get("KEYCLOAK_CLIENT_ID", "multi-agent-web")
# Issuer attendu dans les JWT. Derrière un reverse proxy public (TLS),
# Keycloak émet l'issuer du domaine public (KC_HOSTNAME_URL) alors que
# KEYCLOAK_URL reste l'URL interne (JWKS, proxy /auth) : KEYCLOAK_PUBLIC_URL
# découple les deux ; KEYCLOAK_ISSUER = override explicite complet.
_KEYCLOAK_PUBLIC_URL = os.environ.get("KEYCLOAK_PUBLIC_URL", "").rstrip("/")
_EXPECTED_ISSUER = (
    os.environ.get("KEYCLOAK_ISSUER")
    or f"{_KEYCLOAK_PUBLIC_URL or KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}"
)

_KEYCLOAK_ALLOWED_PREFIXES = (
    f"realms/{KEYCLOAK_REALM}/protocol/openid-connect/",
    f"realms/{KEYCLOAK_REALM}/.well-known/",
)

# Redis
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "")
MA_PREFIX = os.environ.get("MA_PREFIX", "A")
if not re.match(r'^[A-Za-z0-9]+$', MA_PREFIX):
    raise ValueError(f"Invalid MA_PREFIX: {MA_PREFIX}")

BASE_DIR = Path(os.environ.get("MA_BASE", Path.home() / "multi-agent"))
# sessions/ est un repertoire PROJET (jamais touche par upgrade.sh) — l'ancien
# emplacement web/panel-config.json etait efface par le rsync --delete de web/
# a chaque upgrade (overrides M/D perdus). Migration lazy dans _read_panel_config.
PANEL_CONFIG_PATH = BASE_DIR / "sessions" / "panel-config.json"
PANEL_CONFIG_PATH_LEGACY = BASE_DIR / "web" / "panel-config.json"

PROMPT_HISTORY_STREAM = f"{MA_PREFIX}:prompt:history"
CHAT_STREAM = f"{MA_PREFIX}:devchat"

# Background cache
CACHE_REFRESH_INTERVAL = int(os.environ.get("CACHE_REFRESH_INTERVAL", "15"))  # seconds (normal)
CACHE_FAST_INTERVAL = 3  # seconds (when agent near compacting end)
COMPACTING_WAIT_SECS = 80  # wait this long before fast-polling for compacting end

# CORS
_ALLOWED_ORIGINS_ENV = os.environ.get("ALLOWED_ORIGINS", "")
_ALLOWED_ORIGINS = [o.strip() for o in _ALLOWED_ORIGINS_ENV.split(",") if o.strip()] if _ALLOWED_ORIGINS_ENV else ["*"]
_ALLOWED_ORIGINS_LOCAL_DEV = ["http://localhost:5173", "http://localhost:8050"]

# Domain directories
CRONTAB_DIR = BASE_DIR / "crontab"
VALID_CRONTAB_PERIODS = {10, 30, 60, 120}
KEEPALIVE_DIR = BASE_DIR / "keepalive"
PROFILES_DIR = BASE_DIR / "login"
FRONTEND_LOG_DIR = BASE_DIR / "logs" / "frontend"

# Upload (B7) : répertoire dédié, jamais servi statiquement, créé en 0700.
UPLOAD_DIR = Path(os.environ.get("MA_UPLOAD_DIR", str(BASE_DIR / "uploads")))
MAX_UPLOAD_BYTES = int(os.environ.get("MA_MAX_UPLOAD_MB", "5120")) * 1024 * 1024
# Extensions autorisées (liste blanche, vide = tout accepter : transfert
# générique vers les agents, le répertoire n'étant pas exposé par le web).
UPLOAD_ALLOWED_EXT = {
    e.strip().lower().lstrip(".")
    for e in os.environ.get("MA_UPLOAD_ALLOWED_EXT", "").split(",")
    if e.strip()
}

# Agent Chat (Robeke shim proxy)
AGENT_SHIM_URL = os.environ.get("AGENT_SHIM_URL", "http://127.0.0.1:8093")
AGENT_FREEMIUM_TOKEN_URL = os.environ.get(
    "AGENT_FREEMIUM_TOKEN_URL",
    "http://127.0.0.1:8040/realms/freemium/protocol/openid-connect/token",
)
AGENT_FREEMIUM_CLIENT_ID = os.environ.get("AGENT_FREEMIUM_CLIENT_ID", "freemium")
