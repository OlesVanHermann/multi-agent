"""
tab_manager.py — Gestion des onglets Chrome et identification des agents
EF-005 — Module 2/4 : Cycle de vie des tabs et détection d'agent

Responsabilités :
  - Détection de l'agent ID courant (env var, tmux)
  - Requêtes HTTP au endpoint Chrome /json (liste des tabs)
  - Création et fermeture d'onglets Chrome
  - Comptage des tabs de type "page" (sécurité : ne jamais fermer le dernier)

Réf spec 342 : CT-003 (port 9222 inchangé), CT-005 (safe_rm uniquement)
"""

import subprocess
import sys
import os
import json
import urllib.request
import urllib.parse

# =============================================================================
# CONSTANTS
# =============================================================================

CHROME_PORT = 9222


# =============================================================================
# AGENT IDENTIFICATION
# =============================================================================

def get_my_agent_id():
    """
    Detect the current agent's numeric ID.

    Resolution order:
      1. AGENT_ID environment variable (set by agent runner)
      2. Tmux session name parsing ("{prefix}-agent-{id}" or "agent-{id}")

    Returns:
        str: The agent ID (e.g. "300") or None if undetectable.
    """
    agent_id = os.environ.get("AGENT_ID")
    if agent_id:
        return agent_id

    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#S"],
            capture_output=True, text=True, timeout=2
        )
        session_name = result.stdout.strip()

        if session_name.startswith("ma-agent-"):
            return session_name.split("ma-agent-")[1]
        if session_name.startswith("agent-"):
            return session_name.replace("agent-", "")
    except Exception:
        pass

    return None


# =============================================================================
# CHROME TAB QUERIES
# =============================================================================

def get_tabs():
    """
    List all open tabs/targets in Chrome via the /json HTTP endpoint.

    Returns:
        list[dict]: Array of tab metadata dicts with keys:
            id, type, url, title, webSocketDebuggerUrl.
        Returns empty list if Chrome is not reachable.
    """
    try:
        url = f"http://127.0.0.1:{CHROME_PORT}/json"
        with urllib.request.urlopen(url, timeout=2) as response:
            return json.loads(response.read().decode())
    except Exception:
        return []


def count_page_tabs():
    """
    Count the number of open tabs of type 'page' (regular browser tabs).

    Filters out service workers, devtools, extensions, etc.
    Used by the safety check that prevents closing the last tab.

    Returns:
        int: Number of open page-type tabs.
    """
    return len([t for t in get_tabs() if t.get("type") == "page"])


# =============================================================================
# TAB LIFECYCLE (CREATE / CLOSE)
# =============================================================================

def create_tab(target_url="about:blank"):
    """
    Create a new Chrome tab and optionally navigate it to a URL.

    Uses Chrome's /json/new HTTP endpoint.

    Args:
        target_url: The URL to open in the new tab (default: about:blank).

    Returns:
        str: The new tab's target ID, or None on failure.
    """
    try:
        encoded_url = urllib.parse.quote(target_url, safe='')
        url = f"http://127.0.0.1:{CHROME_PORT}/json/new?{encoded_url}"
        req = urllib.request.Request(url, method='PUT')
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode()).get("id")
    except Exception as e:
        print(f"Erreur création onglet: {e}", file=sys.stderr)
        return None


def close_tab_by_id(tab_id):
    """
    Close a Chrome tab by its target ID.

    Uses Chrome's /json/close/{id} HTTP endpoint.
    Caller must check this is NOT the last tab before calling (safety rule).

    Args:
        tab_id: The Chrome target ID of the tab to close.

    Returns:
        bool: True if closed successfully, False on error.
    """
    try:
        url = f"http://127.0.0.1:{CHROME_PORT}/json/close/{tab_id}"
        urllib.request.urlopen(url, timeout=5)
        return True
    except Exception:
        return False
