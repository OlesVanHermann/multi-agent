"""Vérification JWT Keycloak + pont freemium pour l'agent-chat (B1)."""

import logging
import time
from typing import Optional

import httpx
from fastapi import HTTPException, Request

from . import config as cfg

logger = logging.getLogger(__name__)

# Public paths that don't require auth
_PUBLIC_PATHS = {"/api/agent-chat/health", "/api/agent-chat/spec"}
_PUBLIC_PREFIXES = ("/auth/", "/assets/", "/favicon")

_jwks_cache = {"keys": None, "fetched": 0}


async def _get_jwks():
    """Fetch and cache Keycloak JWKS (public keys for JWT verification)."""
    now = time.time()
    if _jwks_cache["keys"] and now - _jwks_cache["fetched"] < 3600:
        return _jwks_cache["keys"]
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(cfg.KEYCLOAK_JWKS_URL, timeout=10)
            if resp.status_code == 200:
                _jwks_cache["keys"] = resp.json()
                _jwks_cache["fetched"] = now
                return _jwks_cache["keys"]
    except Exception:
        pass
    return _jwks_cache["keys"]  # return stale if fetch fails


def _verify_jwt_minimal(token: str) -> bool:
    """JWT verification: RS256 signature via Keycloak JWKS, strict issuer, audience (aud or azp)."""
    try:
        import jwt as pyjwt
        from jwt import PyJWKClient
        jwks_client = PyJWKClient(cfg.KEYCLOAK_JWKS_URL, cache_keys=True, lifespan=3600)
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        payload = pyjwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=cfg._EXPECTED_ISSUER,
            options={"verify_aud": False, "verify_iss": True, "verify_exp": True},
        )
        # Keycloak public clients without an audience mapper put the client ID
        # in azp (aud is "account"); accept either aud or azp matching.
        aud = payload.get("aud", [])
        if isinstance(aud, str):
            aud = [aud]
        if cfg._EXPECTED_AUDIENCE not in aud and payload.get("azp") != cfg._EXPECTED_AUDIENCE:
            logger.warning("JWT rejected: audience/azp mismatch (aud=%s azp=%s)", aud, payload.get("azp"))
            return False
        return True
    except Exception as e:
        logger.warning("JWT verification failed: %s", e)
        return False


def _extract_username_from_jwt(auth_header: str) -> Optional[str]:
    """Extract preferred_username from a dashboard JWT with full signature verification."""
    try:
        token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else auth_header
        import jwt as pyjwt
        from jwt import PyJWKClient
        jwks_client = PyJWKClient(cfg.KEYCLOAK_JWKS_URL, cache_keys=True, lifespan=3600)
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        payload = pyjwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={"verify_aud": False, "verify_iss": False, "verify_exp": True},
        )
        iss = payload.get("iss", "")
        if not iss.endswith(f"/realms/{cfg.KEYCLOAK_REALM}"):
            return None
        return payload.get("preferred_username")
    except Exception:
        return None


def _get_jwt_username(request: Request) -> str:
    auth_header = request.headers.get("authorization", "")
    username = _extract_username_from_jwt(auth_header)
    if not username:
        raise HTTPException(status_code=401, detail="Authentication required")
    return username


# Cache: {username: (token_str, expiry_timestamp)}
_freemium_token_cache: dict[str, tuple[str, float]] = {}


async def _get_freemium_token(username: str) -> Optional[str]:
    """Get a freemium Keycloak JWT via password grant. Caches until near-expiry."""
    cached = _freemium_token_cache.get(username)
    if cached and cached[1] > time.time():
        return cached[0]
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                cfg.AGENT_FREEMIUM_TOKEN_URL,
                data={
                    "grant_type": "password",
                    "client_id": cfg.AGENT_FREEMIUM_CLIENT_ID,
                    "username": username,
                    "password": username,  # convention: password = username
                },
                timeout=10.0,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            token = data["access_token"]
            expires_in = data.get("expires_in", 300)
            _freemium_token_cache[username] = (token, time.time() + expires_in - 60)
            return token
    except Exception:
        return None
