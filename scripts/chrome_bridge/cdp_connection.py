"""
cdp_connection.py — Gestion de la connexion WebSocket CDP (Chrome DevTools Protocol)
EF-005 — Module 1/4 : Connexion, envoi de commandes, évaluation JS

Responsabilités :
  - Classe CDP de base : connect(), close(), send(), evaluate()
  - Vérification que Chrome tourne sur le port 9222
  - Validation des targets (onglets)
  - Factory get_cdp() pour obtenir une connexion validée

Réf spec 342 : CT-003 (port 9222 inchangé), CT-004 (pas de nouvelle dépendance)
"""

import sys
import time
import json
import urllib.request
import urllib.error

try:
    import websocket
except ImportError:
    websocket = None
    print("⚠️  pip install websocket-client", file=sys.stderr)

try:
    from .redis_integration import get_agent_tab, cleanup_stale_target
    from .tab_manager import get_my_agent_id, get_tabs
except ImportError:
    from redis_integration import get_agent_tab, cleanup_stale_target
    from tab_manager import get_my_agent_id, get_tabs


# =============================================================================
# CONSTANTS
# =============================================================================

CHROME_PORT = 9222

# Exit codes used by callers to determine what happened
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CHROME_NOT_RUNNING = 100
EXIT_TARGET_STALE = 101
EXIT_WEBSOCKET_FAILED = 102


# =============================================================================
# CHROME VALIDATION
# =============================================================================

def check_chrome_running(port=CHROME_PORT):
    """
    Check if Chrome is listening on the CDP debug port.

    Makes an HTTP request to Chrome's /json/version endpoint.

    Args:
        port: The port to check (default: 9222).

    Returns:
        bool: True if Chrome is reachable, False otherwise.
    """
    try:
        url = f"http://127.0.0.1:{port}/json/version"
        with urllib.request.urlopen(url, timeout=3):
            return True
    except urllib.error.URLError:
        return False
    except Exception:
        return False


def validate_target(target_id, port=CHROME_PORT):
    """
    Check if a specific target (tab) ID still exists in Chrome.

    After a Chrome restart, all old target IDs become invalid.

    Args:
        target_id: The Chrome target ID to validate.
        port: The Chrome debug port (default: 9222).

    Returns:
        bool: True if the target exists, False if stale.
    """
    try:
        tabs = get_tabs()
        return any(t.get('id') == target_id for t in tabs)
    except Exception:
        return False


def require_chrome_running():
    """
    Assert that Chrome is running. If not, print an error and exit(100).

    This is a hard gate: Chrome must be started MANUALLY. We NEVER restart
    Chrome automatically because logged-in sessions would be lost.

    Exit:
        Calls sys.exit(100) if Chrome is not running.
    """
    if not check_chrome_running():
        print("", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print("❌ ERREUR CRITIQUE: Chrome n'est pas actif sur port 9222",
              file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print("", file=sys.stderr)
        print("  Chrome doit être lancé MANUELLEMENT avec:", file=sys.stderr)
        print("  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\",
              file=sys.stderr)
        print("    --remote-debugging-port=9222 &", file=sys.stderr)
        print("", file=sys.stderr)
        print("  ⛔ NE JAMAIS relancer Chrome automatiquement", file=sys.stderr)
        print("     (les sessions Ahrefs, SimilarWeb, etc. seraient perdues)",
              file=sys.stderr)
        print("", file=sys.stderr)
        sys.exit(EXIT_CHROME_NOT_RUNNING)


# =============================================================================
# CDP CLASS — CORE CONNECTION
# =============================================================================

class CDP:
    """
    Synchronous Chrome DevTools Protocol client (base connection layer).

    Provides low-level methods:
      - connect(): Open WebSocket to Chrome tab
      - close(): Close WebSocket
      - send(): Send CDP command and wait for response
      - evaluate(): Execute JavaScript and return value

    Higher-level commands (navigate, click, screenshot, etc.) are in
    cdp_commands.py which extends this class.

    Usage:
        cdp = CDP(tab_id).connect()
        result = cdp.evaluate("document.title")
        cdp.close()
    """

    def __init__(self, tab_id):
        """
        Initialize CDP client for a specific Chrome tab.

        Args:
            tab_id: The Chrome target ID (from Redis mapping or /json endpoint).
        """
        self.tab_id = tab_id
        self.ws = None
        self.msg_id = 0

    def connect(self):
        """
        Open a WebSocket connection to Chrome for this tab.

        Returns:
            self: For method chaining.

        Raises:
            Exception: If websocket-client is not installed.
            WebSocketException: If the connection fails.
        """
        if not websocket:
            raise Exception("pip install websocket-client")
        ws_url = f"ws://127.0.0.1:{CHROME_PORT}/devtools/page/{self.tab_id}"
        self.ws = websocket.create_connection(ws_url, timeout=30)
        return self

    def close(self):
        """Close the WebSocket connection."""
        if self.ws:
            self.ws.close()

    def send(self, method, params=None, timeout=30):
        """
        Send a CDP command and wait for its response.

        Args:
            method:  CDP method name (e.g. "Page.navigate").
            params:  Optional dict of method parameters.
            timeout: Max seconds to wait for response (default 30).

        Returns:
            dict: The "result" field from Chrome's response, or empty dict.

        Raises:
            Exception: If Chrome returns an error or timeout is exceeded.
        """
        self.msg_id += 1
        cmd = {"id": self.msg_id, "method": method}
        if params:
            cmd["params"] = params

        self.ws.send(json.dumps(cmd))

        start = time.time()
        while time.time() - start < timeout:
            try:
                self.ws.settimeout(1)
                response = json.loads(self.ws.recv())
                if response.get("id") == self.msg_id:
                    if "error" in response:
                        raise Exception(response["error"].get("message", "CDP error"))
                    return response.get("result", {})
            except websocket.WebSocketTimeoutException:
                continue

        raise Exception("CDP timeout")

    def evaluate(self, expression):
        """
        Execute a JavaScript expression in the page context and return its value.

        Args:
            expression: JavaScript code to execute (string).

        Returns:
            The JavaScript return value (str, int, float, bool, list, dict, or None).
        """
        result = self.send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True
        })
        return result.get("result", {}).get("value")


# =============================================================================
# CDP CONNECTION FACTORY
# =============================================================================

def get_cdp(agent_id=None):
    """
    Create a validated CDP connection for the current agent.

    Performs safety checks:
      1. Chrome is running (exit 100 if not)
      2. Agent has a valid tab in Redis (exit 1 if not)
      3. WebSocket connection succeeds (exit 102 if not)

    Args:
        agent_id: Optional agent ID override. If None, auto-detected.

    Returns:
        tuple: (CDP instance, agent_id string)

    Exit:
        100 if Chrome not running, 1 if no tab, 102 if WebSocket fails.
    """
    require_chrome_running()

    if not agent_id:
        agent_id = get_my_agent_id()
    if not agent_id:
        print("Erreur: agent_id non détectable", file=sys.stderr)
        sys.exit(EXIT_ERROR)

    tab_id = get_agent_tab(agent_id)

    if tab_id and not validate_target(tab_id):
        cleanup_stale_target(agent_id)
        tab_id = None

    if not tab_id:
        print(f"Erreur: pas d'onglet pour agent {agent_id}", file=sys.stderr)
        print(f"  → Utiliser: chrome-shared.py tab <url>", file=sys.stderr)
        sys.exit(EXIT_ERROR)

    try:
        return CDP(tab_id).connect(), agent_id
    except Exception as e:
        print(f"⚠ WebSocket failed: {e}", file=sys.stderr)
        cleanup_stale_target(agent_id)
        print(f"  → Réessayer: chrome-shared.py tab <url>", file=sys.stderr)
        sys.exit(EXIT_WEBSOCKET_FAILED)
