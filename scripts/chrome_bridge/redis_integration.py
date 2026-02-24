"""
redis_integration.py — Interface Redis pour le mapping agent→tab Chrome
EF-005 — Module 4/4 : Gestion persistante des associations agent/onglet

Responsabilités :
  - Connexion Redis (fallback stateless si indisponible)
  - CRUD mapping agent_id → Chrome tab_id
  - Nettoyage des targets obsolètes (après restart Chrome)

Réf spec 342 : CT-003 (port 9222 inchangé), CT-004 (pas de nouvelle dépendance)
"""

import sys

try:
    import redis
except ImportError:
    redis = None


# =============================================================================
# CONSTANTS
# =============================================================================

# Redis key prefix for agent→tab mappings.
# Full key: "{REDIS_PREFIX}{agent_id}" → "{chrome_tab_id}"
# Example: "ma:chrome:tab:300" → "E3F2A1B4C5D6E7F8A9B0C1D2E3F4A5B6"
REDIS_PREFIX = "ma:chrome:tab:"


# =============================================================================
# REDIS CONNECTION
# =============================================================================

def get_redis_client():
    """
    Create and validate a Redis connection.

    Returns:
        redis.Redis instance if connection succeeds, None otherwise.
        Falling back to None means the script runs in stateless mode:
        tab mappings won't survive process restarts.
    """
    if not redis:
        return None
    try:
        client = redis.Redis(host='localhost', port=6379, decode_responses=True)
        client.ping()
        return client
    except Exception:
        return None


# Global Redis client — initialized at module import time.
r = get_redis_client()


# =============================================================================
# TAB MAPPING CRUD
# =============================================================================

def get_agent_tab(agent_id):
    """
    Retrieve the Chrome tab ID (target ID) for the given agent from Redis.

    Args:
        agent_id: The agent's numeric ID (e.g. "300").

    Returns:
        str: The Chrome target ID, or None if no mapping exists or Redis unavailable.
    """
    if r:
        return r.get(f"{REDIS_PREFIX}{agent_id}")
    return None


def set_agent_tab(agent_id, tab_id):
    """
    Store the Chrome tab ID for the given agent in Redis.

    Args:
        agent_id: The agent's numeric ID (e.g. "300").
        tab_id:   The Chrome target ID to associate.

    Returns:
        bool: True if stored successfully, False if Redis unavailable.
    """
    if r:
        r.set(f"{REDIS_PREFIX}{agent_id}", tab_id)
        return True
    return False


def del_agent_tab(agent_id):
    """
    Delete the Redis mapping for the given agent.
    Called when an agent's tab is closed or when cleaning up stale targets.

    Args:
        agent_id: The agent's numeric ID (e.g. "300").
    """
    if r:
        r.delete(f"{REDIS_PREFIX}{agent_id}")


def list_all_mappings():
    """
    List all agent→tab mappings stored in Redis.

    Returns:
        dict: {agent_id: tab_id} for all stored mappings. Empty dict if Redis unavailable.
    """
    if not r:
        return {}
    keys = r.keys(f"{REDIS_PREFIX}*")
    result = {}
    for key in sorted(keys):
        agent = key.replace(REDIS_PREFIX, "")
        result[agent] = r.get(key)
    return result


# =============================================================================
# STALE TARGET CLEANUP
# =============================================================================

def cleanup_stale_target(agent_id):
    """
    Remove a stale (invalid) target mapping from Redis.

    Called when we detect that the stored tab ID no longer exists in Chrome
    (typically after Chrome was restarted). Deletes the Redis key so the
    agent can create a fresh tab.

    Args:
        agent_id: The agent whose mapping should be cleaned up.
    """
    if r:
        old_target = r.get(f"{REDIS_PREFIX}{agent_id}")
        if old_target:
            r.delete(f"{REDIS_PREFIX}{agent_id}")
            print(f"⚠ Target {old_target[:8]}... obsolète, mapping supprimé",
                  file=sys.stderr)
