#!/usr/bin/env python3
"""
Lit le contenu d'une page via CDP (Chrome DevTools Protocol)

Usage:
    python3 cdp-read.py                    # Utilise le tab de l'agent (auto-détecté)
    python3 cdp-read.py <tab_id>           # Utilise un tab spécifique
    python3 cdp-read.py --html             # Retourne le HTML complet
    python3 cdp-read.py --text             # Retourne le texte uniquement (défaut)
    python3 cdp-read.py --screenshot       # Sauvegarde un screenshot (base64)
"""

import json
import subprocess
import sys
import os

try:
    import websocket
except ImportError:
    sys.exit("pip install websocket-client")

CDP_PORT = 9222


def get_my_agent_id():
    """Détecte l'agent_id depuis tmux ou env."""
    agent_id = os.environ.get("AGENT_ID")
    if agent_id:
        return agent_id
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#S"],
            capture_output=True, text=True, timeout=2
        )
        session_name = result.stdout.strip()
        if session_name.startswith("agent-"):
            return session_name.replace("agent-", "")
    except:
        pass
    return None


def get_tab_id_from_redis(agent_id):
    """Récupère le tab_id depuis Redis."""
    try:
        result = subprocess.run(
            ["redis-cli", "GET", f"ma:chrome:tab:{agent_id}"],
            capture_output=True, text=True, timeout=2
        )
        tab_id = result.stdout.strip()
        if tab_id and tab_id != "(nil)":
            return tab_id
    except:
        pass
    return None


def get_ws_url(tab_id):
    """Construit l'URL WebSocket pour un tab."""
    return f"ws://127.0.0.1:{CDP_PORT}/devtools/page/{tab_id}"


def cdp_command(ws, method, params=None, msg_id=1):
    """Envoie une commande CDP et retourne le résultat."""
    cmd = {"id": msg_id, "method": method}
    if params:
        cmd["params"] = params
    ws.send(json.dumps(cmd))

    while True:
        response = json.loads(ws.recv())
        if response.get("id") == msg_id:
            return response.get("result", {})


def read_page(tab_id, mode="text"):
    """Lit le contenu d'une page."""
    ws_url = get_ws_url(tab_id)

    try:
        ws = websocket.create_connection(ws_url, timeout=10)
    except Exception as e:
        print(f"Erreur connexion WebSocket: {e}", file=sys.stderr)
        return None

    try:
        if mode == "html":
            result = cdp_command(ws, "Runtime.evaluate", {
                "expression": "document.documentElement.outerHTML",
                "returnByValue": True
            })
            return result.get("result", {}).get("value", "")

        elif mode == "text":
            result = cdp_command(ws, "Runtime.evaluate", {
                "expression": "document.body.innerText",
                "returnByValue": True
            })
            return result.get("result", {}).get("value", "")

        elif mode == "screenshot":
            result = cdp_command(ws, "Page.captureScreenshot", {
                "format": "png"
            })
            return result.get("data", "")

        elif mode == "url":
            result = cdp_command(ws, "Runtime.evaluate", {
                "expression": "window.location.href",
                "returnByValue": True
            })
            return result.get("result", {}).get("value", "")

        elif mode == "title":
            result = cdp_command(ws, "Runtime.evaluate", {
                "expression": "document.title",
                "returnByValue": True
            })
            return result.get("result", {}).get("value", "")

    finally:
        ws.close()


def navigate(tab_id, url):
    """Navigate vers une URL."""
    ws_url = get_ws_url(tab_id)

    try:
        ws = websocket.create_connection(ws_url, timeout=30)
    except Exception as e:
        print(f"Erreur connexion: {e}", file=sys.stderr)
        return False

    try:
        # Enable Page events
        cdp_command(ws, "Page.enable", msg_id=1)

        # Navigate
        cdp_command(ws, "Page.navigate", {"url": url}, msg_id=2)

        # Wait for load
        import time
        time.sleep(3)  # Simple wait

        return True
    finally:
        ws.close()


def main():
    # Parse arguments
    args = sys.argv[1:]
    mode = "text"
    tab_id = None
    url = None

    for arg in args:
        if arg == "--html":
            mode = "html"
        elif arg == "--text":
            mode = "text"
        elif arg == "--screenshot":
            mode = "screenshot"
        elif arg == "--url":
            mode = "url"
        elif arg == "--title":
            mode = "title"
        elif arg.startswith("--navigate="):
            url = arg.split("=", 1)[1]
        elif arg.startswith("http"):
            url = arg
        elif not arg.startswith("-"):
            tab_id = arg

    # Auto-detect tab_id if not provided
    if not tab_id:
        agent_id = get_my_agent_id()
        if agent_id:
            tab_id = get_tab_id_from_redis(agent_id)

    if not tab_id:
        print("Erreur: tab_id non fourni et non détectable", file=sys.stderr)
        print("Usage: cdp-read.py [tab_id] [--html|--text|--screenshot]", file=sys.stderr)
        sys.exit(1)

    # Navigate if URL provided
    if url:
        if not navigate(tab_id, url):
            sys.exit(1)

    # Read content
    content = read_page(tab_id, mode)
    if content:
        print(content)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
