#!/usr/bin/env python3
"""
chrome-shared.py -- Shared Chrome Browser Controller for Multi-Agent System
=============================================================================

ARCHITECTURE OVERVIEW
---------------------
This module provides a **single shared Chrome instance** that is used by ALL agents
in the multi-agent system. Each agent gets its own dedicated Chrome **tab** (target),
and the mapping between agent IDs and Chrome tab IDs is persisted in Redis.

The design ensures that:
  - Only ONE Chrome process runs, started manually with --remote-debugging-port=9222
  - Each agent (identified by a numeric ID like 300, 301, etc.) owns exactly one tab
  - Agents never interfere with each other's tabs
  - Chrome is NEVER stopped or restarted automatically (to preserve logged-in sessions
    on sites like Ahrefs, SimilarWeb, etc.)

COMMUNICATION MODEL
-------------------
All interaction with Chrome happens via CDP (Chrome DevTools Protocol) over WebSocket.
This is a synchronous, request-response protocol:
  1. Connect to ws://127.0.0.1:9222/devtools/page/{tab_id}
  2. Send a JSON command with a unique message ID
  3. Wait for a JSON response with the matching ID
  4. Disconnect when done

No Playwright, no Puppeteer, no MCP chrome-devtools -- just raw CDP over websockets.

AGENT IDENTIFICATION
--------------------
Each agent is identified by a numeric string (e.g. "300", "001", "500").
The agent ID is resolved in this priority order:
  1. AGENT_ID environment variable (set by the agent runner)
  2. Tmux session name parsing:
     - "{MA_PREFIX}-agent-{id}" format (e.g. "ma-agent-300")
     - "agent-{id}" format (e.g. "agent-300")
  MA_PREFIX is an env var (default "ma") that allows multiple multi-agent instances
  to coexist on the same machine without Redis key collisions.

REDIS STORAGE
-------------
The mapping from agent_id to Chrome tab_id is stored in Redis as simple key-value:
  Key:   ma:chrome:tab:{agent_id}   (e.g. "ma:chrome:tab:300")
  Value: Chrome target ID            (e.g. "E3F2A1B4C5D6...")
This allows any agent to reconnect to its tab even after the Python process restarts.

SECURITY MODEL
--------------
Hard rules enforced by this script:
  - NEVER close the last remaining Chrome tab (would effectively kill Chrome)
  - NEVER stop Chrome (the "stop" command is explicitly blocked)
  - NEVER restart Chrome automatically (exit code 100 = "go fix it manually")
  - NEVER use Playwright or MCP chrome-devtools

EXIT CODES
----------
  0   = Success
  1   = Generic error (bad arguments, element not found, etc.)
  100 = CRITICAL: Chrome is not running on port 9222 (manual intervention required)
  101 = Stale target: the tab ID in Redis no longer exists in Chrome (auto-cleaned)
  102 = WebSocket connection failed (transient, retry may help)

STALE TARGET CLEANUP
--------------------
When Chrome is restarted (manually), all previously-stored tab IDs become invalid
because Chrome assigns new IDs to new tabs. This script detects stale targets by
querying Chrome's /json endpoint and comparing against the stored tab ID. If the
tab ID no longer exists, the Redis mapping is deleted and the agent must create a
new tab via the "tab" command.

IMAGE HANDLING
--------------
Screenshots are automatically resized to fit within MAX_IMAGE_DIM (1800px) on their
longest side, preserving aspect ratio. This is necessary because the Claude API has
limits on image dimensions in multi-image requests. Resizing uses PIL/Pillow with
LANCZOS resampling for high quality downscaling.

The get_images() method extracts images from 5 different sources on a web page:
  1. <img> tags (standard images)
  2. Inline <svg> elements (serialized to data URIs)
  3. <canvas> elements (converted to PNG data URIs)
  4. CSS background-image properties (extracted from computed styles)
  5. <picture>/<source> elements (responsive images with srcset)
Results are deduplicated by source URL.

USAGE
-----
    python3 chrome-shared.py <command> [args...]

    # Tab management
    python3 chrome-shared.py tab <url>                 # Create tab or navigate existing
    python3 chrome-shared.py tab <agent_id> <url>      # Create tab for specific agent
    python3 chrome-shared.py get                       # Show my tab ID
    python3 chrome-shared.py close                     # Close my tab
    python3 chrome-shared.py list                      # List all agent->tab mappings
    python3 chrome-shared.py status                    # Show Chrome status

    # Navigation
    python3 chrome-shared.py goto <url>                # Navigate in existing tab
    python3 chrome-shared.py reload                    # Refresh page
    python3 chrome-shared.py back / forward            # History navigation
    python3 chrome-shared.py url / title               # Get current URL or title

    # Reading page content
    python3 chrome-shared.py read <file>               # Full HTML -> file
    python3 chrome-shared.py read-text <file>          # Text only -> file
    python3 chrome-shared.py read-element <sel> <file> # Element HTML -> file
    python3 chrome-shared.py read-attr <sel> <attr>    # Attribute value
    python3 chrome-shared.py read-links                # List all links
    python3 chrome-shared.py eval <expression>         # Execute JS, return result

    # Clicking
    python3 chrome-shared.py click <selector>          # Click by CSS selector
    python3 chrome-shared.py click-text <text>         # Click by visible text
    python3 chrome-shared.py dblclick <selector>       # Double-click
    python3 chrome-shared.py hover <selector>          # Hover (mouseover)

    # Typing
    python3 chrome-shared.py type <selector> <text>    # Type into input field
    python3 chrome-shared.py clear <selector>          # Clear input field
    python3 chrome-shared.py press <key>               # Press key (enter, tab, etc.)

    # Forms
    python3 chrome-shared.py fill <selector> <value>   # Alias for type
    python3 chrome-shared.py select <selector> <val>   # Select dropdown option
    python3 chrome-shared.py check <selector>          # Check checkbox
    python3 chrome-shared.py uncheck <selector>        # Uncheck checkbox
    python3 chrome-shared.py submit                    # Submit active form

    # Scrolling
    python3 chrome-shared.py scroll <direction>        # down, up, bottom, top
    python3 chrome-shared.py scroll-to <selector>      # Scroll element into view

    # Waiting
    python3 chrome-shared.py wait <seconds>            # Sleep N seconds
    python3 chrome-shared.py wait-element <selector>   # Wait for element to appear
    python3 chrome-shared.py wait-hidden <selector>    # Wait for element to disappear
    python3 chrome-shared.py wait-text <text>          # Wait for text on page

    # Screenshots & PDF
    python3 chrome-shared.py screenshot <file.png>     # Viewport screenshot
    python3 chrome-shared.py screenshot-full <file.png># Full-page screenshot
    python3 chrome-shared.py pdf <file.pdf>            # Export page as PDF

    # Images
    python3 chrome-shared.py read-images               # List all images (JSON to stdout)
    python3 chrome-shared.py read-images <file>        # Save image list as JSON file
    python3 chrome-shared.py capture-element <sel> <f> # Capture element as PNG
    python3 chrome-shared.py download-images <dir>     # Download all images to directory

SECURITY RULES
--------------
  - NEVER close the last tab
  - NEVER stop Chrome
  - NEVER restart Chrome automatically
  - NEVER use Playwright or MCP

EXIT CODES
----------
  0   = Success
  1   = Generic error
  100 = CRITICAL: Chrome not running (DO NOT auto-restart!)
  101 = Stale target (auto-cleanup performed)
  102 = WebSocket timeout (retry possible)
"""

# =============================================================================
# IMPORTS
# =============================================================================

import subprocess      # For running tmux commands to detect agent ID
import sys             # For argv, exit codes, stderr
import time            # For sleeps and timeouts
import json            # For CDP message serialization and JSON output
import urllib.request  # For HTTP calls to Chrome's /json endpoints
import urllib.parse    # For URL encoding when creating new tabs
import os              # For environment variables and file paths
import base64          # For decoding screenshot data and data URIs
from pathlib import Path  # For dynamic home directory resolution

# --- Optional dependency: redis ---
# Redis is used to persist the agent_id -> tab_id mapping.
# Without Redis, each agent would lose track of its tab on restart.
try:
    import redis
except ImportError:
    redis = None

# --- Optional dependency: websocket-client ---
# This is the core communication library for CDP (Chrome DevTools Protocol).
# Without it, no Chrome interaction is possible.
try:
    import websocket
except ImportError:
    websocket = None
    print("⚠️  pip install websocket-client", file=sys.stderr)

# --- Optional dependency: Pillow (PIL) ---
# Used to resize screenshots before sending to Claude API.
# Without PIL, screenshots are sent at original resolution (may exceed API limits).
try:
    from PIL import Image
    import io
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# =============================================================================
# CONSTANTS
# =============================================================================

# Maximum image dimension (width or height) for screenshots sent to Claude API.
# When using multi-image requests, Claude API recommends images no larger than
# 1800px on their longest side. Images exceeding this are downscaled with
# aspect ratio preserved using LANCZOS resampling.
MAX_IMAGE_DIM = 1800

# Port where Chrome listens for DevTools Protocol connections.
# Chrome must be started manually with: --remote-debugging-port=9222
CHROME_PORT = 9222

# Directory where Chrome stores its user profile data for the multi-agent system.
# This keeps the multi-agent Chrome profile separate from the user's normal Chrome.
CHROME_USER_DATA = os.path.expanduser("~/.chrome-multi-agent")

# Redis key prefix for storing agent-to-tab mappings.
# Full key format: "ma:chrome:tab:{agent_id}" -> "{chrome_tab_id}"
# Example: "ma:chrome:tab:300" -> "E3F2A1B4C5D6E7F8A9B0C1D2E3F4A5B6"
REDIS_PREFIX = "ma:chrome:tab:"

# Base directory of the multi-agent system installation.
# Resolved dynamically from the user's home directory so it works on any machine.
BASE = str(Path.home() / "multi-agent")


# =============================================================================
# REDIS CONNECTION
# =============================================================================

# Global Redis client. Initialized at module load time.
# If Redis is unavailable, the script falls back to stateless mode (no tab persistence).
r = None
if redis:
    try:
        r = redis.Redis(host='localhost', port=6379, decode_responses=True)
        r.ping()  # Verify the connection is alive
    except:
        # Redis not reachable -- continue without persistence.
        # Tab mappings won't survive process restarts.
        r = None


# =============================================================================
# AGENT IDENTIFICATION
# =============================================================================
# These functions determine which agent is running this script, so the correct
# Chrome tab can be looked up (or created) in Redis.
# =============================================================================

def get_my_agent_id():
    """
    Detect the current agent's numeric ID.

    Resolution order:
      1. AGENT_ID environment variable -- set by the agent runner (agent.py)
         when it spawns the Claude process. This is the most reliable method.
      2. Tmux session name -- if running inside a tmux session, the session
         name follows the convention "{prefix}-agent-{id}" or "agent-{id}".
         The MA_PREFIX env var (default "ma") determines the prefix, allowing
         multiple multi-agent instances to coexist on one machine.

    Returns:
        str: The agent ID (e.g. "300", "001") or None if undetectable.
    """
    # Method 1: Check the AGENT_ID environment variable (most reliable)
    agent_id = os.environ.get("AGENT_ID")
    if agent_id:
        return agent_id

    # Method 2: Parse the tmux session name
    try:
        # Ask tmux for the current session name using the #S format string
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#S"],
            capture_output=True, text=True, timeout=2
        )
        session_name = result.stdout.strip()

        # Support both "ma-agent-XXX" and "agent-XXX" session naming
        if session_name.startswith("ma-agent-"):
            return session_name.split("ma-agent-")[1]

        if session_name.startswith("agent-"):
            return session_name.replace("agent-", "")
    except:
        # Not in a tmux session, or tmux not installed
        pass

    return None


# =============================================================================
# REDIS TAB MAPPING
# =============================================================================
# These functions manage the persistent mapping between agent IDs and Chrome
# tab (target) IDs. Each agent owns exactly one tab. The mapping is stored
# in Redis so it survives Python process restarts.
#
# Redis key format: "ma:chrome:tab:{agent_id}"
# Redis value:      Chrome target ID string (e.g. "E3F2A1B4...")
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


# =============================================================================
# CHROME TAB QUERIES
# =============================================================================
# These functions query Chrome's HTTP debug endpoints (not CDP WebSocket)
# to get metadata about open tabs without needing a WebSocket connection.
# =============================================================================

def get_tabs():
    """
    List all open tabs/targets in Chrome by querying the /json HTTP endpoint.

    Chrome's debug port exposes a REST-like API at http://127.0.0.1:9222/json
    that returns a JSON array of all open targets (tabs, service workers, etc.).

    Returns:
        list[dict]: Array of tab metadata dicts, each containing:
            - id: The target ID (used for WebSocket connections)
            - type: "page", "service_worker", "background_page", etc.
            - url: The tab's current URL
            - title: The tab's title
            - webSocketDebuggerUrl: The WebSocket URL for CDP
        Returns empty list if Chrome is not reachable.
    """
    try:
        url = f"http://127.0.0.1:{CHROME_PORT}/json"
        with urllib.request.urlopen(url, timeout=2) as response:
            return json.loads(response.read().decode())
    except:
        return []


def count_page_tabs():
    """
    Count the number of open tabs of type 'page' (regular browser tabs).

    Filters out non-page targets like service workers, devtools, extensions, etc.
    Used by the safety check that prevents closing the last tab.

    Returns:
        int: Number of open page-type tabs.
    """
    return len([t for t in get_tabs() if t.get("type") == "page"])


# =============================================================================
# CHROME SECURITY & VALIDATION
# =============================================================================
# These functions enforce the security model: Chrome must be running, targets
# must be valid, and stale mappings must be cleaned up gracefully.
# =============================================================================

# --- Exit code constants ---
# These are used throughout the script and by callers to determine what happened.
EXIT_OK = 0                      # Everything worked
EXIT_ERROR = 1                   # Generic error (bad args, element not found, etc.)
EXIT_CHROME_NOT_RUNNING = 100    # CRITICAL: Chrome is not listening on port 9222.
                                 # Manual intervention required -- NEVER auto-restart.
EXIT_TARGET_STALE = 101          # The stored tab ID no longer exists in Chrome.
                                 # Typically happens after Chrome restart. Auto-cleaned.
EXIT_WEBSOCKET_FAILED = 102      # WebSocket connection to the target failed.
                                 # May be transient; retry is possible.


def check_chrome_running(port=CHROME_PORT):
    """
    Check if Chrome is listening on the CDP debug port.

    Makes an HTTP request to Chrome's /json/version endpoint, which returns
    version metadata if Chrome is running with --remote-debugging-port.

    Args:
        port: The port to check (default: 9222).

    Returns:
        bool: True if Chrome is reachable, False otherwise.
    """
    try:
        url = f"http://127.0.0.1:{port}/json/version"
        with urllib.request.urlopen(url, timeout=3) as resp:
            return True
    except urllib.error.URLError:
        return False
    except Exception:
        return False


def validate_target(target_id, port=CHROME_PORT):
    """
    Check if a specific target (tab) ID still exists in Chrome.

    After a Chrome restart, all old target IDs become invalid because Chrome
    assigns new UUIDs to every new tab. This function checks the current list
    of targets to see if the given ID is still present.

    Args:
        target_id: The Chrome target ID to validate.
        port: The Chrome debug port (default: 9222).

    Returns:
        bool: True if the target exists in Chrome's tab list, False if stale.
    """
    try:
        tabs = get_tabs()
        return any(t.get('id') == target_id for t in tabs)
    except:
        return False


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
            # Show a truncated target ID for debugging (first 8 chars)
            print(f"⚠ Target {old_target[:8]}... obsolète, mapping supprimé", file=sys.stderr)


def require_chrome_running():
    """
    Assert that Chrome is running. If not, print an error and exit(100).

    This is a hard gate: if Chrome is not running, there's nothing this script
    can do. The exit code 100 signals to the calling agent that Chrome must be
    started MANUALLY. We NEVER restart Chrome automatically because:
      - Logged-in sessions (Ahrefs, SimilarWeb, etc.) would be lost
      - Other agents' tabs would be destroyed
      - Chrome profile state could be corrupted

    Exit:
        Calls sys.exit(100) if Chrome is not running.
    """
    if not check_chrome_running():
        print("", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print("❌ ERREUR CRITIQUE: Chrome n'est pas actif sur port 9222", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print("", file=sys.stderr)
        print("  Chrome doit être lancé MANUELLEMENT avec:", file=sys.stderr)
        print("  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\", file=sys.stderr)
        print("    --remote-debugging-port=9222 &", file=sys.stderr)
        print("", file=sys.stderr)
        print("  ⛔ NE JAMAIS relancer Chrome automatiquement", file=sys.stderr)
        print("     (les sessions Ahrefs, SimilarWeb, etc. seraient perdues)", file=sys.stderr)
        print("", file=sys.stderr)
        sys.exit(EXIT_CHROME_NOT_RUNNING)


# =============================================================================
# TAB LIFECYCLE (CREATE / CLOSE)
# =============================================================================
# These functions manage the creation and destruction of Chrome tabs using
# Chrome's HTTP debug endpoints (not CDP WebSocket).
# =============================================================================

def create_tab(target_url="about:blank"):
    """
    Create a new Chrome tab and optionally navigate it to a URL.

    Uses Chrome's /json/new HTTP endpoint which accepts a URL parameter.
    The PUT method is required by Chrome's debug protocol for tab creation.

    Args:
        target_url: The URL to open in the new tab (default: about:blank).

    Returns:
        str: The new tab's target ID, or None on failure.
    """
    try:
        # URL-encode the target to handle special characters safely
        encoded_url = urllib.parse.quote(target_url, safe='')
        url = f"http://127.0.0.1:{CHROME_PORT}/json/new?{encoded_url}"
        req = urllib.request.Request(url, method='PUT')
        with urllib.request.urlopen(req, timeout=10) as response:
            # Chrome returns JSON metadata for the newly created tab
            return json.loads(response.read().decode()).get("id")
    except Exception as e:
        print(f"Erreur création onglet: {e}", file=sys.stderr)
        return None


def close_tab_by_id(tab_id):
    """
    Close a Chrome tab by its target ID.

    Uses Chrome's /json/close/{id} HTTP endpoint. Note: the caller must
    check that this is NOT the last tab before calling (safety rule).

    Args:
        tab_id: The Chrome target ID of the tab to close.

    Returns:
        bool: True if closed successfully, False on error.
    """
    try:
        url = f"http://127.0.0.1:{CHROME_PORT}/json/close/{tab_id}"
        urllib.request.urlopen(url, timeout=5)
        return True
    except:
        return False


# =============================================================================
# CDP WebSocket CLIENT
# =============================================================================
# The CDP class implements a synchronous Chrome DevTools Protocol client.
#
# CDP is a JSON-RPC-like protocol over WebSocket. Each command is sent as:
#   {"id": N, "method": "Domain.method", "params": {...}}
# And Chrome responds with:
#   {"id": N, "result": {...}}  -- on success
#   {"id": N, "error": {"message": "..."}} -- on failure
#
# The WebSocket URL for a specific tab is:
#   ws://127.0.0.1:9222/devtools/page/{target_id}
#
# Only one WebSocket connection can be open to a given tab at a time.
# The CDP class manages:
#   - Connection lifecycle (connect/close)
#   - Message ID auto-increment for request/response correlation
#   - Timeout handling (default 30s per command)
#   - Response filtering (ignoring async events, waiting for matching ID)
# =============================================================================

class CDP:
    """
    Synchronous Chrome DevTools Protocol client.

    Provides high-level methods for common browser operations (navigate, click,
    type, screenshot, etc.) built on top of low-level CDP commands.

    Usage:
        cdp = CDP(tab_id).connect()
        cdp.navigate("https://example.com")
        title = cdp.get_title()
        cdp.close()
    """

    def __init__(self, tab_id):
        """
        Initialize CDP client for a specific Chrome tab.

        Args:
            tab_id: The Chrome target ID (from Redis mapping or /json endpoint).
        """
        self.tab_id = tab_id   # Chrome target ID for WebSocket URL construction
        self.ws = None          # WebSocket connection (set by connect())
        self.msg_id = 0         # Auto-incrementing message ID for request/response matching

    def connect(self):
        """
        Open a WebSocket connection to Chrome for this tab.

        The WebSocket URL is constructed from the tab_id:
          ws://127.0.0.1:9222/devtools/page/{tab_id}

        The 30-second timeout applies to the initial WebSocket handshake.

        Returns:
            self: For method chaining (e.g. CDP(tab_id).connect().navigate(...))

        Raises:
            Exception: If websocket-client is not installed.
            WebSocketException: If the connection fails (stale target, network error, etc.)
        """
        if not websocket:
            raise Exception("pip install websocket-client")
        ws_url = f"ws://127.0.0.1:{CHROME_PORT}/devtools/page/{self.tab_id}"
        self.ws = websocket.create_connection(ws_url, timeout=30)
        return self

    def close(self):
        """
        Close the WebSocket connection.

        Should always be called when done with CDP operations to free the
        WebSocket slot. Only one connection per tab is allowed by Chrome.
        """
        if self.ws:
            self.ws.close()

    def send(self, method, params=None, timeout=30):
        """
        Send a CDP command and wait for its response.

        This is the core low-level method. It:
          1. Assigns a unique auto-incrementing message ID
          2. Sends the JSON-encoded command over WebSocket
          3. Reads messages in a loop until it finds the response with matching ID
          4. Ignores async CDP events (messages without matching ID) that Chrome
             may send at any time (e.g. Network.requestWillBeSent, Console.messageAdded)

        Args:
            method:  CDP method name (e.g. "Page.navigate", "Runtime.evaluate")
            params:  Optional dict of method parameters
            timeout: Max seconds to wait for a response (default 30)

        Returns:
            dict: The "result" field from Chrome's response, or empty dict.

        Raises:
            Exception: If Chrome returns an error or if the timeout is exceeded.
        """
        # Auto-increment message ID for request/response correlation
        self.msg_id += 1
        cmd = {"id": self.msg_id, "method": method}
        if params:
            cmd["params"] = params

        # Send the command as JSON
        self.ws.send(json.dumps(cmd))

        # Wait for the matching response, ignoring async events
        start = time.time()
        while time.time() - start < timeout:
            try:
                # Set a 1-second recv timeout so we can check the overall timeout
                self.ws.settimeout(1)
                response = json.loads(self.ws.recv())

                # Only process responses with our message ID; ignore async events
                if response.get("id") == self.msg_id:
                    if "error" in response:
                        raise Exception(response["error"].get("message", "CDP error"))
                    return response.get("result", {})
            except websocket.WebSocketTimeoutException:
                # recv() timed out after 1s -- loop back and check overall timeout
                continue

        raise Exception("CDP timeout")

    def evaluate(self, expression):
        """
        Execute a JavaScript expression in the page context and return its value.

        Uses Runtime.evaluate with returnByValue=True so that the result is
        serialized and transferred as a JSON value rather than a remote object
        reference. This means complex objects (arrays, nested dicts) are fully
        transferred but DOM nodes cannot be returned directly.

        Args:
            expression: JavaScript code to execute (string).

        Returns:
            The JavaScript return value (str, int, float, bool, list, dict, or None).
        """
        result = self.send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True  # Serialize the result as JSON, not an object reference
        })
        return result.get("result", {}).get("value")

    # =========================================================================
    # NAVIGATION METHODS
    # =========================================================================
    # These methods control page navigation (URL changes, history, reload).
    # Each navigation includes a sleep to allow basic page loading.
    # =========================================================================

    def navigate(self, url):
        """
        Navigate the tab to a new URL.

        Enables the Page domain first (required for Page.navigate), then
        navigates and waits 2 seconds for basic page load. Note: this does
        NOT wait for full page load (DOMContentLoaded or load events) --
        use wait_element() or wait_text() for that.

        Args:
            url: The URL to navigate to.
        """
        self.send("Page.enable")   # Enable Page domain events (required before navigate)
        self.send("Page.navigate", {"url": url})
        time.sleep(2)              # Basic wait for initial page load

    def reload(self):
        """
        Reload the current page (equivalent to pressing F5).
        Waits 2 seconds after reload for basic page load.
        """
        self.send("Page.reload")
        time.sleep(2)

    def go_back(self):
        """
        Navigate back in browser history (equivalent to clicking the back button).
        Uses JavaScript history.back() rather than CDP's Page.navigateToHistoryEntry
        for simplicity. Waits 1 second for page transition.
        """
        self.evaluate("history.back()")
        time.sleep(1)

    def go_forward(self):
        """
        Navigate forward in browser history.
        Uses JavaScript history.forward(). Waits 1 second for page transition.
        """
        self.evaluate("history.forward()")
        time.sleep(1)

    def get_url(self):
        """
        Get the current page URL.

        Returns:
            str: The current URL (e.g. "https://example.com/page").
        """
        return self.evaluate("window.location.href")

    def get_title(self):
        """
        Get the current page title.

        Returns:
            str: The page title from <title> tag.
        """
        return self.evaluate("document.title")

    # =========================================================================
    # PAGE CONTENT READING METHODS
    # =========================================================================
    # These methods extract content from the page: full HTML, text, individual
    # elements, attributes, and links.
    # =========================================================================

    def get_html(self):
        """
        Get the full HTML source of the page (including <html> tag).

        Returns:
            str: The complete outerHTML of the document element.
        """
        return self.evaluate("document.documentElement.outerHTML")

    def get_text(self):
        """
        Get the visible text content of the page (no HTML tags).

        Returns:
            str: The innerText of document.body.
        """
        return self.evaluate("document.body.innerText")

    def get_element_html(self, selector):
        """
        Get the HTML of a specific element matched by CSS selector.

        Args:
            selector: CSS selector string (e.g. "#main", ".content", "div.article").

        Returns:
            str: The outerHTML of the first matching element, or empty string if not found.
        """
        return self.evaluate(f"document.querySelector('{selector}')?.outerHTML || ''")

    def get_attribute(self, selector, attr):
        """
        Get the value of a specific attribute on an element.

        Args:
            selector: CSS selector for the target element.
            attr: Attribute name (e.g. "href", "src", "data-id").

        Returns:
            str: The attribute value, or None if element/attribute not found.
        """
        return self.evaluate(f"document.querySelector('{selector}')?.getAttribute('{attr}')")

    def get_links(self):
        """
        Get all hyperlinks (<a href="...">) on the page.

        Returns:
            list[str]: Array of absolute URLs from all anchor elements.
        """
        return self.evaluate("[...document.querySelectorAll('a[href]')].map(a => a.href)")

    # =========================================================================
    # CLICK METHODS
    # =========================================================================
    # Clicks are performed using CDP's Input.dispatchMouseEvent rather than
    # JavaScript click() to better simulate real user interaction. The flow:
    #   1. Find the element via JavaScript
    #   2. Scroll it into view (so coordinates are within the viewport)
    #   3. Calculate the center point of its bounding rectangle
    #   4. Dispatch mousePressed + mouseReleased events at those coordinates
    # =========================================================================

    def click(self, selector):
        """
        Click on an element identified by CSS selector.

        The element is first scrolled into view, then its center coordinates
        are calculated, and a mouse click is dispatched at those coordinates
        via CDP Input.dispatchMouseEvent (not JavaScript .click()).

        Args:
            selector: CSS selector for the element to click.

        Raises:
            Exception: If the element is not found in the DOM.
        """
        # Execute JS to find element, scroll it into view, and return center coordinates
        coords = self.evaluate(f"""
            (() => {{
                const el = document.querySelector('{selector}');
                if (!el) return null;
                el.scrollIntoView({{block: 'center'}});
                const rect = el.getBoundingClientRect();
                return {{x: rect.x + rect.width/2, y: rect.y + rect.height/2}};
            }})()
        """)
        if not coords:
            raise Exception(f"Element not found: {selector}")

        # Dispatch the actual mouse click at the element's center
        self._mouse_click(coords["x"], coords["y"])

    def click_text(self, text, tag="*"):
        """
        Click on an element that contains the specified visible text.

        Searches all elements matching the given tag (default: any tag "*")
        for one whose textContent includes the search text. Useful when
        elements don't have stable CSS selectors but have known text labels.

        Args:
            text: The text to search for within elements.
            tag:  Optional HTML tag filter (e.g. "button", "a"). Default "*" = any.

        Raises:
            Exception: If no element with the specified text is found.
        """
        # Escape quotes in the search text to prevent JS injection
        text_escaped = text.replace("'", "\\'").replace('"', '\\"')
        coords = self.evaluate(f"""
            (() => {{
                const els = [...document.querySelectorAll('{tag}')];
                const el = els.find(e => e.textContent.includes('{text_escaped}'));
                if (!el) return null;
                el.scrollIntoView({{block: 'center'}});
                const rect = el.getBoundingClientRect();
                return {{x: rect.x + rect.width/2, y: rect.y + rect.height/2}};
            }})()
        """)
        if not coords:
            raise Exception(f"Element with text '{text}' not found")

        self._mouse_click(coords["x"], coords["y"])

    def dblclick(self, selector):
        """
        Double-click on an element identified by CSS selector.

        Same approach as click() but with clickCount=2 in the mouse events.

        Args:
            selector: CSS selector for the element to double-click.

        Raises:
            Exception: If the element is not found.
        """
        coords = self.evaluate(f"""
            (() => {{
                const el = document.querySelector('{selector}');
                if (!el) return null;
                el.scrollIntoView({{block: 'center'}});
                const rect = el.getBoundingClientRect();
                return {{x: rect.x + rect.width/2, y: rect.y + rect.height/2}};
            }})()
        """)
        if not coords:
            raise Exception(f"Element not found: {selector}")

        # clickCount=2 tells Chrome this is a double-click
        self._mouse_click(coords["x"], coords["y"], click_count=2)

    def hover(self, selector):
        """
        Hover (move mouse) over an element without clicking.

        Dispatches a mouseMoved event at the element's center, which triggers
        CSS :hover styles and JavaScript mouseenter/mouseover event handlers.

        Args:
            selector: CSS selector for the element to hover.

        Raises:
            Exception: If the element is not found.
        """
        coords = self.evaluate(f"""
            (() => {{
                const el = document.querySelector('{selector}');
                if (!el) return null;
                el.scrollIntoView({{block: 'center'}});
                const rect = el.getBoundingClientRect();
                return {{x: rect.x + rect.width/2, y: rect.y + rect.height/2}};
            }})()
        """)
        if not coords:
            raise Exception(f"Element not found: {selector}")

        # Only mouseMoved -- no press/release (that would be a click)
        self.send("Input.dispatchMouseEvent", {
            "type": "mouseMoved", "x": coords["x"], "y": coords["y"]
        })

    def _mouse_click(self, x, y, click_count=1):
        """
        Low-level mouse click helper: dispatches mousePressed + mouseReleased.

        CDP requires both events to simulate a complete click. The 0.5s sleep
        after the click allows the page to process the event (animations,
        navigation, AJAX requests, etc.).

        Args:
            x: Horizontal coordinate (pixels from left edge of viewport).
            y: Vertical coordinate (pixels from top edge of viewport).
            click_count: 1 for single click, 2 for double-click.
        """
        # Mouse button down at (x, y)
        self.send("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": x, "y": y,
            "button": "left", "clickCount": click_count
        })
        # Mouse button up at (x, y) -- completes the click
        self.send("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": x, "y": y,
            "button": "left", "clickCount": click_count
        })
        # Wait for page to process the click event
        time.sleep(0.5)

    # =========================================================================
    # TEXT INPUT METHODS
    # =========================================================================
    # These methods handle keyboard interaction: typing text into fields,
    # clearing fields, and pressing special keys.
    # =========================================================================

    def type_text(self, selector, text, clear=True):
        """
        Type text into an input field identified by CSS selector.

        The approach:
          1. Focus the element via JavaScript (.focus())
          2. Optionally clear existing content by setting .value = ''
          3. Insert text using CDP Input.insertText (simulates keyboard input)

        Input.insertText is used instead of individual keyDown/keyUp events
        because it's much faster and more reliable for multi-character strings.

        Args:
            selector: CSS selector for the input/textarea element.
            text: The text to type.
            clear: If True (default), clear the field before typing.
        """
        # Focus the element so it receives keyboard input
        self.evaluate(f"document.querySelector('{selector}')?.focus()")
        time.sleep(0.1)  # Brief pause to ensure focus is applied

        if clear:
            # Clear existing content by resetting the value property
            self.evaluate(f"document.querySelector('{selector}').value = ''")

        # Insert the text as if typed by the user
        self.send("Input.insertText", {"text": text})
        time.sleep(0.1)  # Brief pause to let input event handlers fire

    def clear_field(self, selector):
        """
        Clear an input field by setting its value to empty string.

        Args:
            selector: CSS selector for the input/textarea element.
        """
        self.evaluate(f"document.querySelector('{selector}').value = ''")

    def press_key(self, key):
        """
        Press a keyboard key (special key or character).

        Dispatches a keyDown + keyUp event pair via CDP Input.dispatchKeyEvent.
        Supports named keys (enter, tab, escape, etc.) and single characters.

        The key_map translates friendly names to CDP key parameters:
          - key: The key value (e.g. "Enter", "Tab")
          - code: The physical key code (e.g. "Enter", "Tab")
          - keycode: The numeric virtual key code (e.g. 13 for Enter)

        Args:
            key: Key name (case-insensitive). Supported: enter, tab, escape,
                 backspace, delete, arrowup, arrowdown, arrowleft, arrowright,
                 or any single character.
        """
        # Map of friendly key names to (key, code, virtualKeyCode) tuples
        key_map = {
            "enter": ("Enter", "Enter", 13),
            "tab": ("Tab", "Tab", 9),
            "escape": ("Escape", "Escape", 27),
            "backspace": ("Backspace", "Backspace", 8),
            "delete": ("Delete", "Delete", 46),
            "arrowup": ("ArrowUp", "ArrowUp", 38),
            "arrowdown": ("ArrowDown", "ArrowDown", 40),
            "arrowleft": ("ArrowLeft", "ArrowLeft", 37),
            "arrowright": ("ArrowRight", "ArrowRight", 39),
        }

        key_lower = key.lower()
        if key_lower in key_map:
            key_name, code, keycode = key_map[key_lower]
        else:
            # For single characters, use the character itself as key/code
            key_name = key
            code = key
            keycode = ord(key[0].upper()) if len(key) == 1 else 0

        # keyDown event (key press)
        self.send("Input.dispatchKeyEvent", {
            "type": "keyDown", "key": key_name, "code": code,
            "windowsVirtualKeyCode": keycode, "nativeVirtualKeyCode": keycode
        })
        # keyUp event (key release)
        self.send("Input.dispatchKeyEvent", {
            "type": "keyUp", "key": key_name, "code": code,
            "windowsVirtualKeyCode": keycode, "nativeVirtualKeyCode": keycode
        })
        # Brief pause to let the keystroke be processed
        time.sleep(0.2)

    # =========================================================================
    # FORM INTERACTION METHODS
    # =========================================================================
    # Higher-level methods for interacting with HTML forms: dropdowns,
    # checkboxes, and form submission.
    # =========================================================================

    def select_option(self, selector, value):
        """
        Select an option in a <select> dropdown.

        Finds the option by matching either its value attribute or its visible
        text. After setting the value, dispatches a 'change' event (with
        bubbles:true) so that any listening JavaScript handlers are triggered.

        Args:
            selector: CSS selector for the <select> element.
            value: The option value or visible text to select.
        """
        self.evaluate(f"""
            (() => {{
                const sel = document.querySelector('{selector}');
                if (!sel) return;
                const opt = [...sel.options].find(o => o.value === '{value}' || o.text === '{value}');
                if (opt) sel.value = opt.value;
                sel.dispatchEvent(new Event('change', {{bubbles: true}}));
            }})()
        """)

    def check(self, selector):
        """
        Check a checkbox (only if currently unchecked).

        Uses JavaScript .click() on the element, but only if it's not already
        checked. This avoids toggling an already-checked box.

        Args:
            selector: CSS selector for the checkbox input element.
        """
        self.evaluate(f"""
            const el = document.querySelector('{selector}');
            if (el && !el.checked) el.click();
        """)

    def uncheck(self, selector):
        """
        Uncheck a checkbox (only if currently checked).

        Args:
            selector: CSS selector for the checkbox input element.
        """
        self.evaluate(f"""
            const el = document.querySelector('{selector}');
            if (el && el.checked) el.click();
        """)

    def submit_form(self):
        """
        Submit the form that contains the currently focused element.

        Uses the activeElement's form reference to call .submit(). This works
        when the user has just typed into a form field and wants to submit.
        Waits 1 second for the form submission to process.
        """
        self.evaluate("document.activeElement?.form?.submit()")
        time.sleep(1)

    # =========================================================================
    # SCROLL METHODS
    # =========================================================================

    def scroll(self, direction):
        """
        Scroll the page in a given direction.

        Args:
            direction: One of:
                - "down":   Scroll down by 500px
                - "up":     Scroll up by 500px
                - "bottom": Scroll to the very bottom of the page
                - "top":    Scroll to the very top of the page
        """
        if direction == "down":
            self.evaluate("window.scrollBy(0, 500)")
        elif direction == "up":
            self.evaluate("window.scrollBy(0, -500)")
        elif direction == "bottom":
            self.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        elif direction == "top":
            self.evaluate("window.scrollTo(0, 0)")
        time.sleep(0.3)  # Brief pause for scroll animation

    def scroll_to(self, selector):
        """
        Scroll a specific element into the center of the viewport.

        Args:
            selector: CSS selector for the target element.
        """
        self.evaluate(f"document.querySelector('{selector}')?.scrollIntoView({{block: 'center'}})")
        time.sleep(0.3)

    # =========================================================================
    # WAIT / POLLING METHODS
    # =========================================================================
    # These methods poll the page at 0.5s intervals until a condition is met
    # or the timeout expires.
    # =========================================================================

    def wait(self, seconds):
        """
        Wait (sleep) for a fixed number of seconds.

        Args:
            seconds: Number of seconds to wait (can be a float).
        """
        time.sleep(float(seconds))

    def wait_element(self, selector, timeout=30):
        """
        Wait until an element matching the CSS selector exists in the DOM.

        Polls every 0.5 seconds until the element is found or timeout expires.

        Args:
            selector: CSS selector to wait for.
            timeout: Maximum seconds to wait (default 30).

        Returns:
            True when the element is found.

        Raises:
            Exception: If the element is not found within the timeout.
        """
        start = time.time()
        while time.time() - start < timeout:
            if self.evaluate(f"!!document.querySelector('{selector}')"):
                return True
            time.sleep(0.5)  # Poll interval
        raise Exception(f"Timeout waiting for: {selector}")

    def wait_hidden(self, selector, timeout=30):
        """
        Wait until an element matching the CSS selector is no longer in the DOM.

        Polls every 0.5 seconds until the element disappears or timeout expires.

        Args:
            selector: CSS selector to wait for disappearance.
            timeout: Maximum seconds to wait (default 30).

        Returns:
            True when the element has disappeared.

        Raises:
            Exception: If the element is still present after the timeout.
        """
        start = time.time()
        while time.time() - start < timeout:
            if not self.evaluate(f"!!document.querySelector('{selector}')"):
                return True
            time.sleep(0.5)
        raise Exception(f"Timeout waiting for hidden: {selector}")

    def wait_text(self, text, timeout=30):
        """
        Wait until the specified text appears anywhere on the page.

        Uses document.body.innerText.includes() which searches all visible text.
        Polls every 0.5 seconds.

        Args:
            text: The text to search for.
            timeout: Maximum seconds to wait (default 30).

        Returns:
            True when the text is found.

        Raises:
            Exception: If the text is not found within the timeout.
        """
        # Escape single quotes to prevent JS syntax errors
        text_escaped = text.replace("'", "\\'")
        start = time.time()
        while time.time() - start < timeout:
            if self.evaluate(f"document.body.innerText.includes('{text_escaped}')"):
                return True
            time.sleep(0.5)
        raise Exception(f"Timeout waiting for text: {text}")

    # =========================================================================
    # SCREENSHOT & PDF METHODS
    # =========================================================================
    # Screenshots are captured via CDP's Page.captureScreenshot command.
    # Full-page screenshots temporarily override the device metrics to capture
    # the entire scrollable area. All screenshots are optionally resized to
    # fit within MAX_IMAGE_DIM (1800px) for Claude API compatibility.
    # =========================================================================

    def screenshot(self, full_page=False, max_dim=None):
        """
        Capture a screenshot of the current page.

        For viewport screenshots (full_page=False): captures only what's visible.
        For full-page screenshots (full_page=True): temporarily overrides the
        device metrics to match the full document dimensions, captures, then
        restores original metrics.

        The resulting PNG is optionally downsized if either dimension exceeds
        max_dim (default MAX_IMAGE_DIM=1800px). This is required because the
        Claude API has limits on image dimensions in multi-image requests.
        Resizing uses LANCZOS resampling for high-quality downscaling and
        preserves the original aspect ratio.

        Args:
            full_page: If True, capture the entire scrollable page.
            max_dim: Maximum allowed dimension in pixels. None uses MAX_IMAGE_DIM.

        Returns:
            bytes: PNG image data.
        """
        if max_dim is None:
            max_dim = MAX_IMAGE_DIM

        params = {"format": "png"}
        if full_page:
            params["captureBeyondViewport"] = True
            # Measure the full document dimensions (may be much larger than viewport)
            metrics = self.evaluate("""
                ({
                    width: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
                    height: Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)
                })
            """)
            if metrics:
                # Temporarily override device metrics to capture the full page
                self.send("Emulation.setDeviceMetricsOverride", {
                    "width": metrics["width"],
                    "height": metrics["height"],
                    "deviceScaleFactor": 1,
                    "mobile": False
                })

        # Capture the screenshot via CDP
        result = self.send("Page.captureScreenshot", params)

        if full_page:
            # Restore original device metrics after full-page capture
            self.send("Emulation.clearDeviceMetricsOverride")

        # Decode the base64-encoded PNG data from Chrome's response
        png_data = base64.b64decode(result.get("data", ""))

        # --- Resize if needed (for Claude API multi-image compatibility) ---
        # The Claude API recommends images no larger than 1800px on their longest
        # side when sending multiple images. This block downsizes if necessary.
        if PIL_AVAILABLE and max_dim:
            try:
                img = Image.open(io.BytesIO(png_data))
                w, h = img.size
                if w > max_dim or h > max_dim:
                    # Calculate new dimensions preserving aspect ratio
                    if w > h:
                        # Landscape: constrain width to max_dim
                        new_w = max_dim
                        new_h = int(h * max_dim / w)
                    else:
                        # Portrait: constrain height to max_dim
                        new_h = max_dim
                        new_w = int(w * max_dim / h)
                    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                    buf = io.BytesIO()
                    img.save(buf, format='PNG')
                    png_data = buf.getvalue()
            except Exception as e:
                print(f"⚠️  Resize failed: {e}", file=sys.stderr)

        return png_data

    def pdf(self):
        """
        Export the current page as a PDF document.

        Uses CDP's Page.printToPDF command with background printing enabled
        and CSS page size preferences respected.

        Returns:
            bytes: PDF document data.
        """
        result = self.send("Page.printToPDF", {
            "printBackground": True,       # Include background colors/images
            "preferCSSPageSize": True       # Use @page CSS rules if present
        })
        return base64.b64decode(result.get("data", ""))

    # =========================================================================
    # IMAGE EXTRACTION METHODS
    # =========================================================================
    # These methods extract images from 5 different sources on a web page.
    # Modern web pages can embed images in many ways beyond simple <img> tags:
    # inline SVGs, canvas elements, CSS backgrounds, and responsive <picture>
    # elements. These methods handle all of them.
    # =========================================================================

    def get_images(self):
        """
        Extract all images from the current page.

        Collects images from 5 sources:
          1. <img> tags -- standard image elements with src attribute.
             Returns: type, src URL, alt text, natural dimensions, CSS selector.
          2. Inline <svg> -- SVG elements serialized to base64 data URIs.
             Returns: type, data URI, dimensions from viewBox/attributes, selector.
          3. <canvas> -- canvas elements converted to PNG data URIs via toDataURL().
             Skips cross-origin canvases (SecurityError from tainted canvas).
             Returns: type, data URI, canvas dimensions, selector.
          4. CSS background-image -- any element with a non-empty background-image.
             Extracts the URL from url("...") syntax, skips SVG data URIs.
             Returns: type, URL, selector.
          5. <picture>/<source> -- responsive image sources with srcset attribute.
             Parses the srcset to extract individual image URLs (strips size descriptors).
             Returns: type, URL, media query, selector.

        All results are deduplicated by source URL using a Set.

        Returns:
            list[dict]: Array of image descriptor dicts. Empty list if no images found.
        """
        return self.evaluate("""
            (() => {
                const images = [];

                // --- Source 1: <img> tags ---
                // Standard image elements. Uses naturalWidth/naturalHeight for true
                // image dimensions (not CSS-scaled dimensions).
                document.querySelectorAll('img').forEach((img, i) => {
                    if (img.src) {
                        images.push({
                            type: 'img',
                            src: img.src,
                            alt: img.alt || '',
                            width: img.naturalWidth || img.width,
                            height: img.naturalHeight || img.height,
                            selector: img.id ? '#' + img.id : `img:nth-of-type(${i+1})`
                        });
                    }
                });

                // --- Source 2: Inline <svg> elements ---
                // SVGs are serialized to XML string, then base64-encoded as data URIs.
                // encodeURIComponent + unescape handles Unicode characters in SVG content.
                document.querySelectorAll('svg').forEach((svg, i) => {
                    const serializer = new XMLSerializer();
                    const svgStr = serializer.serializeToString(svg);
                    const dataUri = 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(svgStr)));
                    images.push({
                        type: 'svg',
                        src: dataUri,
                        width: svg.width?.baseVal?.value || svg.viewBox?.baseVal?.width || 0,
                        height: svg.height?.baseVal?.value || svg.viewBox?.baseVal?.height || 0,
                        selector: svg.id ? '#' + svg.id : `svg:nth-of-type(${i+1})`
                    });
                });

                // --- Source 3: <canvas> elements ---
                // Converts canvas content to PNG data URI. This captures dynamically-drawn
                // charts, graphs, and other canvas-rendered content.
                // Cross-origin canvases throw SecurityError (tainted canvas), so we skip them.
                document.querySelectorAll('canvas').forEach((canvas, i) => {
                    try {
                        const dataUri = canvas.toDataURL('image/png');
                        images.push({
                            type: 'canvas',
                            src: dataUri,
                            width: canvas.width,
                            height: canvas.height,
                            selector: canvas.id ? '#' + canvas.id : `canvas:nth-of-type(${i+1})`
                        });
                    } catch(e) {
                        // Cross-origin canvas, skip (SecurityError: tainted canvas)
                    }
                });

                // --- Source 4: CSS background-image ---
                // Scans ALL elements on the page for computed background-image CSS property.
                // Extracts the URL from url("...") or url('...') syntax.
                // Skips SVG data URIs (already captured in source 2).
                document.querySelectorAll('*').forEach((el, i) => {
                    const bg = getComputedStyle(el).backgroundImage;
                    if (bg && bg !== 'none' && bg.startsWith('url(')) {
                        const match = bg.match(/url\\(["']?(.+?)["']?\\)/);
                        if (match && match[1] && !match[1].startsWith('data:image/svg')) {
                            images.push({
                                type: 'background',
                                src: match[1],
                                selector: el.id ? '#' + el.id : el.className ? '.' + el.className.split(' ')[0] : el.tagName.toLowerCase()
                            });
                        }
                    }
                });

                // --- Source 5: <picture>/<source> responsive images ---
                // Parses the srcset attribute which contains comma-separated entries like:
                //   "image-300.jpg 300w, image-600.jpg 600w, image-1200.jpg 1200w"
                // Extracts just the URLs (stripping size descriptors).
                document.querySelectorAll('picture source').forEach((source, i) => {
                    if (source.srcset) {
                        const srcs = source.srcset.split(',').map(s => s.trim().split(' ')[0]);
                        srcs.forEach(src => {
                            images.push({
                                type: 'picture',
                                src: src,
                                media: source.media || '',
                                selector: `picture:nth-of-type(${i+1}) source`
                            });
                        });
                    }
                });

                // --- Deduplication ---
                // Remove duplicate entries that have the same src URL.
                // This commonly happens with CSS backgrounds on nested elements
                // or responsive images that share the same URL.
                const seen = new Set();
                return images.filter(img => {
                    if (seen.has(img.src)) return false;
                    seen.add(img.src);
                    return true;
                });
            })()
        """) or []

    def get_canvas_as_image(self, selector):
        """
        Convert a specific canvas element to a PNG data URI.

        Args:
            selector: CSS selector for the canvas element.

        Returns:
            str: PNG data URI (data:image/png;base64,...) or None if not found
                 or cross-origin restricted.
        """
        return self.evaluate(f"""
            (() => {{
                const canvas = document.querySelector('{selector}');
                if (!canvas) return null;
                try {{
                    return canvas.toDataURL('image/png');
                }} catch(e) {{
                    return null;
                }}
            }})()
        """)

    def get_svg_as_image(self, selector):
        """
        Serialize a specific SVG element to a base64 data URI.

        Args:
            selector: CSS selector for the SVG element.

        Returns:
            str: SVG data URI (data:image/svg+xml;base64,...) or None if not found.
        """
        return self.evaluate(f"""
            (() => {{
                const svg = document.querySelector('{selector}');
                if (!svg) return null;
                const serializer = new XMLSerializer();
                const svgStr = serializer.serializeToString(svg);
                return 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(svgStr)));
            }})()
        """)

    def get_element_as_image(self, selector, max_dim=None):
        """
        Capture a specific DOM element as a PNG screenshot.

        Unlike get_canvas_as_image (which reads canvas pixel data), this method
        uses CDP's screenshot with a clip region to capture any visible element
        as it appears on screen -- including its styling, children, etc.

        The captured image is optionally resized to fit within max_dim, same as
        the screenshot() method.

        Args:
            selector: CSS selector for the element to capture.
            max_dim: Maximum dimension in pixels. None uses MAX_IMAGE_DIM.

        Returns:
            bytes: PNG image data, or None if the element is not found.
        """
        if max_dim is None:
            max_dim = MAX_IMAGE_DIM

        # Get the element's bounding box (including scroll offset for absolute positioning)
        bounds = self.evaluate(f"""
            (() => {{
                const el = document.querySelector('{selector}');
                if (!el) return null;
                const rect = el.getBoundingClientRect();
                return {{
                    x: rect.x + window.scrollX,
                    y: rect.y + window.scrollY,
                    width: rect.width,
                    height: rect.height
                }};
            }})()
        """)
        if not bounds:
            return None

        # Use CDP's clip parameter to capture only the element's region
        result = self.send("Page.captureScreenshot", {
            "format": "png",
            "clip": {
                "x": bounds["x"],
                "y": bounds["y"],
                "width": bounds["width"],
                "height": bounds["height"],
                "scale": 1  # 1:1 pixel ratio
            }
        })
        png_data = base64.b64decode(result.get("data", ""))

        # Resize if needed (same logic as screenshot())
        if PIL_AVAILABLE and max_dim:
            try:
                img = Image.open(io.BytesIO(png_data))
                w, h = img.size
                if w > max_dim or h > max_dim:
                    if w > h:
                        new_w = max_dim
                        new_h = int(h * max_dim / w)
                    else:
                        new_h = max_dim
                        new_w = int(w * max_dim / h)
                    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                    buf = io.BytesIO()
                    img.save(buf, format='PNG')
                    png_data = buf.getvalue()
            except Exception as e:
                print(f"⚠️  Resize failed: {e}", file=sys.stderr)

        return png_data


# =============================================================================
# CDP CONNECTION FACTORY
# =============================================================================
# get_cdp() is the main entry point for commands that need a WebSocket
# connection to a Chrome tab. It performs a 3-step validation:
#   1. Is Chrome running? (exit 100 if not)
#   2. Does the agent have a valid tab? (cleanup stale + error if not)
#   3. Can we open a WebSocket? (cleanup + exit 102 if not)
# =============================================================================

def get_cdp(agent_id=None):
    """
    Create a validated CDP connection for the current agent.

    This is the standard way to get a CDP client. It performs safety checks:
      Step 1: Verify Chrome is running (exit 100 if not -- manual intervention needed)
      Step 2: Look up the agent's tab ID in Redis and validate it still exists
              in Chrome. If stale (e.g. Chrome was restarted), clean up the Redis
              mapping and ask the agent to create a new tab.
      Step 3: Open a WebSocket connection to the tab. If this fails (zombie target),
              clean up and exit with code 102 (retryable).

    Args:
        agent_id: Optional agent ID override. If None, auto-detected from env/tmux.

    Returns:
        tuple: (CDP instance, agent_id string)

    Exit:
        100 if Chrome not running, 1 if no tab mapping, 102 if WebSocket fails.
    """
    # STEP 1: Verify Chrome is running on the debug port
    require_chrome_running()

    # Auto-detect agent ID if not provided
    if not agent_id:
        agent_id = get_my_agent_id()
    if not agent_id:
        print("Erreur: agent_id non détectable", file=sys.stderr)
        sys.exit(EXIT_ERROR)

    # Look up this agent's tab ID in Redis
    tab_id = get_agent_tab(agent_id)

    # STEP 2: Validate the tab still exists in Chrome
    # After a Chrome restart, old tab IDs become invalid
    if tab_id and not validate_target(tab_id):
        cleanup_stale_target(agent_id)
        tab_id = None

    # If no valid tab, the agent needs to create one first with "tab <url>"
    if not tab_id:
        print(f"Erreur: pas d'onglet pour agent {agent_id}", file=sys.stderr)
        print(f"  → Utiliser: chrome-shared.py tab <url>", file=sys.stderr)
        sys.exit(EXIT_ERROR)

    # STEP 3: Open WebSocket connection to the tab
    try:
        return CDP(tab_id).connect(), agent_id
    except Exception as e:
        # WebSocket failed -- the target might be a zombie (exists in /json but
        # doesn't accept WebSocket connections). Clean up and report.
        print(f"⚠ WebSocket failed: {e}", file=sys.stderr)
        cleanup_stale_target(agent_id)
        print(f"  → Réessayer: chrome-shared.py tab <url>", file=sys.stderr)
        sys.exit(EXIT_WEBSOCKET_FAILED)


# =============================================================================
# MAIN COMMAND DISPATCHER
# =============================================================================
# The main() function parses the CLI command and dispatches to the appropriate
# handler. Commands are organized into categories:
#
#   TAB MANAGEMENT (no CDP needed):
#     status, list, tab, get, close
#
#   NAVIGATION (needs CDP):
#     goto, reload, back, forward, url, title
#
#   READING (needs CDP):
#     read, read-text, read-element, read-attr, read-links, eval
#
#   CLICKING (needs CDP):
#     click, click-text, dblclick, hover
#
#   TYPING (needs CDP):
#     type, fill, clear, press
#
#   FORMS (needs CDP):
#     select, check, uncheck, submit
#
#   SCROLLING (needs CDP):
#     scroll, scroll-to
#
#   WAITING (needs CDP for element/text waits):
#     wait, wait-element, wait-hidden, wait-text
#
#   SCREENSHOTS (needs CDP):
#     screenshot, screenshot-full, pdf
#
#   IMAGES (needs CDP):
#     read-images, capture-element, download-images
#
#   BLOCKED COMMANDS:
#     stop -- explicitly forbidden (security rule)
# =============================================================================

def main():
    # Show usage if no command given
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    # Parse command and arguments (case-insensitive command matching)
    cmd = sys.argv[1].lower()
    args = sys.argv[2:]

    # =========================================================================
    # TAB MANAGEMENT COMMANDS
    # =========================================================================
    # These commands manage Chrome tabs without needing a CDP WebSocket
    # connection. They use Chrome's HTTP /json endpoints and Redis directly.
    # =========================================================================

    if cmd == "status":
        # --- STATUS: Show Chrome running status and version info ---
        if check_chrome_running():
            try:
                url = f"http://127.0.0.1:{CHROME_PORT}/json/version"
                with urllib.request.urlopen(url, timeout=2) as resp:
                    version = json.loads(resp.read().decode())
                    print(f"✓ Chrome actif sur port {CHROME_PORT}")
                    print(f"  Version: {version.get('Browser', '?')}")
                    print(f"  Onglets: {count_page_tabs()}")
            except Exception as e:
                print(f"✓ Chrome actif mais erreur version: {e}")
        else:
            print(f"✗ Chrome non actif sur port {CHROME_PORT}")
            print(f"  → Lancer manuellement (NE JAMAIS automatiser)")
            sys.exit(EXIT_CHROME_NOT_RUNNING)

    elif cmd == "list":
        # --- LIST: Show all agent -> tab ID mappings stored in Redis ---
        if r:
            # Get all keys matching the Redis prefix pattern
            keys = r.keys(f"{REDIS_PREFIX}*")
            if keys:
                print(f"{'Agent':<10} TabId")
                print("-" * 50)
                for key in sorted(keys):
                    # Extract agent ID from the key by removing the prefix
                    agent = key.replace(REDIS_PREFIX, "")
                    print(f"{agent:<10} {r.get(key)}")
            else:
                print("Aucun mapping")
        else:
            print("Redis non disponible")

    elif cmd == "tab":
        # --- TAB: Create a new tab for an agent, or navigate an existing one ---
        # This is the primary way agents get their Chrome tab.
        #
        # Usage patterns:
        #   tab <url>              -- auto-detect agent ID, open URL
        #   tab <agent_id> <url>   -- explicit agent ID, open URL
        #   tab                    -- auto-detect agent ID, open about:blank
        #
        # Behavior:
        #   1. Check if agent already has a valid tab in Redis
        #   2. If yes: navigate the existing tab to the URL (reuse tab)
        #   3. If no (or stale): create a new tab and store the mapping

        # SAFETY: Verify Chrome is running before any tab operations
        require_chrome_running()

        # Parse arguments: determine agent_id and target URL
        if len(args) >= 2 and not args[0].startswith("http"):
            # Explicit agent ID provided: tab 300 https://example.com
            agent_id, url = args[0], args[1]
        elif len(args) >= 1:
            # Auto-detect agent ID: tab https://example.com
            agent_id, url = get_my_agent_id(), args[0]
        else:
            # No arguments: auto-detect agent ID, default URL
            agent_id, url = get_my_agent_id(), "about:blank"

        if not agent_id:
            print("Erreur: agent_id non détectable", file=sys.stderr)
            sys.exit(EXIT_ERROR)

        # Check if this agent already has a tab assigned in Redis
        existing = get_agent_tab(agent_id)
        if existing:
            if validate_target(existing):
                # Tab exists in Chrome and is valid -- reuse it by navigating
                try:
                    cdp = CDP(existing).connect()
                    cdp.navigate(url)
                    cdp.close()
                    # Print the tab ID to stdout (for callers to capture)
                    print(existing)
                except Exception as e:
                    # WebSocket failed even though target exists in /json list.
                    # This is a "zombie" target -- clean up and create a new tab.
                    print(f"⚠ Target zombie, création nouveau tab...", file=sys.stderr)
                    cleanup_stale_target(agent_id)
                    existing = None
            else:
                # Target ID no longer exists in Chrome (Chrome was restarted)
                cleanup_stale_target(agent_id)
                existing = None

        # If no valid existing tab, create a fresh one
        if not existing:
            tab_id = create_tab(url)
            if tab_id:
                # Store the new mapping in Redis
                set_agent_tab(agent_id, tab_id)
                # Print the tab ID to stdout (for callers to capture)
                print(tab_id)
            else:
                sys.exit(EXIT_ERROR)

    elif cmd == "get":
        # --- GET: Retrieve and display the current agent's tab ID ---
        # Optionally accepts an explicit agent ID as argument.
        agent_id = args[0] if args else get_my_agent_id()
        tab_id = get_agent_tab(agent_id)
        if tab_id:
            print(tab_id)
        else:
            print(f"Pas d'onglet pour agent {agent_id}", file=sys.stderr)
            sys.exit(1)

    elif cmd == "close":
        # --- CLOSE: Close the current agent's Chrome tab ---
        # Safety rules:
        #   - NEVER close the last remaining tab (would effectively kill Chrome)
        #   - Clean up Redis mapping after closing
        #   - Handle already-stale targets gracefully

        require_chrome_running()

        agent_id = args[0] if args else get_my_agent_id()
        if not agent_id:
            print("Erreur: agent_id non détectable", file=sys.stderr)
            sys.exit(EXIT_ERROR)

        tab_id = get_agent_tab(agent_id)
        if not tab_id:
            print(f"Agent {agent_id} n'a pas d'onglet", file=sys.stderr)
            sys.exit(EXIT_ERROR)

        # Check if the target still exists before trying to close it
        if not validate_target(tab_id):
            # Already gone -- just clean up the Redis mapping
            cleanup_stale_target(agent_id)
            print(f"⚠ Target déjà fermé, mapping nettoyé")
            sys.exit(EXIT_OK)

        # CRITICAL SAFETY CHECK: Never close the last tab
        if count_page_tabs() <= 1:
            print("⚠️  REFUSÉ: Impossible de fermer le dernier tab", file=sys.stderr)
            sys.exit(EXIT_ERROR)

        # Close the tab and remove the Redis mapping
        if close_tab_by_id(tab_id):
            del_agent_tab(agent_id)
            print(f"✓ Onglet fermé")
        else:
            sys.exit(EXIT_ERROR)

    # =========================================================================
    # NAVIGATION COMMANDS
    # =========================================================================
    # These commands require a CDP WebSocket connection to the agent's tab.
    # get_cdp() handles all validation (Chrome running, tab valid, WS connected).
    # =========================================================================

    elif cmd == "goto":
        # Navigate to a URL in the agent's existing tab
        if not args:
            print("Usage: goto <url>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.navigate(args[0])
        cdp.close()
        print(f"✓ Navigué vers {args[0]}")

    elif cmd == "reload":
        # Refresh the current page
        cdp, _ = get_cdp()
        cdp.reload()
        cdp.close()
        print("✓ Page rafraîchie")

    elif cmd == "back":
        # Go back in browser history
        cdp, _ = get_cdp()
        cdp.go_back()
        cdp.close()
        print("✓ Page précédente")

    elif cmd == "forward":
        # Go forward in browser history
        cdp, _ = get_cdp()
        cdp.go_forward()
        cdp.close()
        print("✓ Page suivante")

    elif cmd == "url":
        # Print the current page URL to stdout
        cdp, _ = get_cdp()
        print(cdp.get_url())
        cdp.close()

    elif cmd == "title":
        # Print the current page title to stdout
        cdp, _ = get_cdp()
        print(cdp.get_title())
        cdp.close()

    # =========================================================================
    # PAGE CONTENT READING COMMANDS
    # =========================================================================

    elif cmd == "read":
        # Save the full page HTML to a file
        if not args:
            print("Usage: read <fichier>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        html = cdp.get_html()
        cdp.close()
        with open(args[0], 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"✓ HTML → {args[0]} ({len(html)} bytes)")

    elif cmd == "read-text":
        # Save the visible text content (no HTML tags) to a file
        if not args:
            print("Usage: read-text <fichier>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        text = cdp.get_text()
        cdp.close()
        with open(args[0], 'w', encoding='utf-8') as f:
            f.write(text)
        print(f"✓ Texte → {args[0]} ({len(text)} bytes)")

    elif cmd == "read-element":
        # Save the HTML of a specific element to a file
        if len(args) < 2:
            print("Usage: read-element <selector> <fichier>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        html = cdp.get_element_html(args[0])
        cdp.close()
        with open(args[1], 'w', encoding='utf-8') as f:
            f.write(html or "")
        print(f"✓ Element → {args[1]}")

    elif cmd == "read-attr":
        # Print the value of a specific attribute on an element
        if len(args) < 2:
            print("Usage: read-attr <selector> <attribut>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        val = cdp.get_attribute(args[0], args[1])
        cdp.close()
        print(val or "")

    elif cmd == "read-links":
        # Print all hyperlinks on the page, one per line
        cdp, _ = get_cdp()
        links = cdp.get_links()
        cdp.close()
        for link in (links or []):
            print(link)

    elif cmd == "eval":
        # Execute arbitrary JavaScript and print the result
        if not args:
            print("Usage: eval <expression>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        # Join all args to support expressions with spaces
        result = cdp.evaluate(" ".join(args))
        cdp.close()
        # Format output: JSON for complex types, plain string otherwise
        print(json.dumps(result) if isinstance(result, (dict, list)) else result)

    # =========================================================================
    # CLICK COMMANDS
    # =========================================================================

    elif cmd == "click":
        # Click an element by CSS selector
        if not args:
            print("Usage: click <selector>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.click(args[0])
        cdp.close()
        print(f"✓ Cliqué sur {args[0]}")

    elif cmd == "click-text":
        # Click an element by its visible text content
        if not args:
            print("Usage: click-text <texte>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        # Join all args to support multi-word text
        cdp.click_text(" ".join(args))
        cdp.close()
        print(f"✓ Cliqué sur texte '{' '.join(args)}'")

    elif cmd == "dblclick":
        # Double-click an element by CSS selector
        if not args:
            print("Usage: dblclick <selector>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.dblclick(args[0])
        cdp.close()
        print(f"✓ Double-cliqué sur {args[0]}")

    elif cmd == "hover":
        # Hover over an element (triggers :hover CSS and JS events)
        if not args:
            print("Usage: hover <selector>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.hover(args[0])
        cdp.close()
        print(f"✓ Hover sur {args[0]}")

    # =========================================================================
    # TEXT INPUT COMMANDS
    # =========================================================================

    elif cmd in ("type", "fill"):
        # Type text into an input field ("fill" is an alias for "type")
        if len(args) < 2:
            print(f"Usage: {cmd} <selector> <texte>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        # Join remaining args to support text with spaces
        cdp.type_text(args[0], " ".join(args[1:]))
        cdp.close()
        print(f"✓ Tapé dans {args[0]}")

    elif cmd == "clear":
        # Clear an input field
        if not args:
            print("Usage: clear <selector>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.clear_field(args[0])
        cdp.close()
        print(f"✓ Champ vidé")

    elif cmd == "press":
        # Press a keyboard key
        if not args:
            print("Usage: press <key>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.press_key(args[0])
        cdp.close()
        print(f"✓ Touche {args[0]}")

    # =========================================================================
    # FORM COMMANDS
    # =========================================================================

    elif cmd == "select":
        # Select a value in a dropdown (<select> element)
        if len(args) < 2:
            print("Usage: select <selector> <valeur>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.select_option(args[0], args[1])
        cdp.close()
        print(f"✓ Sélectionné {args[1]}")

    elif cmd == "check":
        # Check a checkbox
        if not args:
            print("Usage: check <selector>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.check(args[0])
        cdp.close()
        print("✓ Coché")

    elif cmd == "uncheck":
        # Uncheck a checkbox
        if not args:
            print("Usage: uncheck <selector>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.uncheck(args[0])
        cdp.close()
        print("✓ Décoché")

    elif cmd == "submit":
        # Submit the form that contains the currently focused element
        cdp, _ = get_cdp()
        cdp.submit_form()
        cdp.close()
        print("✓ Formulaire soumis")

    # =========================================================================
    # SCROLL COMMANDS
    # =========================================================================

    elif cmd == "scroll":
        # Scroll the page in a direction
        if not args:
            print("Usage: scroll <down|up|bottom|top>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.scroll(args[0])
        cdp.close()
        print(f"✓ Scroll {args[0]}")

    elif cmd == "scroll-to":
        # Scroll a specific element into view
        if not args:
            print("Usage: scroll-to <selector>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.scroll_to(args[0])
        cdp.close()
        print(f"✓ Scroll vers {args[0]}")

    # =========================================================================
    # WAIT / POLLING COMMANDS
    # =========================================================================

    elif cmd == "wait":
        # Simple sleep (no CDP needed)
        if not args:
            print("Usage: wait <secondes>", file=sys.stderr)
            sys.exit(1)
        time.sleep(float(args[0]))
        print(f"✓ Attendu {args[0]}s")

    elif cmd == "wait-element":
        # Wait for a CSS-selected element to appear in the DOM
        if not args:
            print("Usage: wait-element <selector>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.wait_element(args[0])
        cdp.close()
        print(f"✓ Element trouvé: {args[0]}")

    elif cmd == "wait-hidden":
        # Wait for a CSS-selected element to disappear from the DOM
        if not args:
            print("Usage: wait-hidden <selector>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.wait_hidden(args[0])
        cdp.close()
        print(f"✓ Element disparu: {args[0]}")

    elif cmd == "wait-text":
        # Wait for specific text to appear on the page
        if not args:
            print("Usage: wait-text <texte>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.wait_text(" ".join(args))
        cdp.close()
        print(f"✓ Texte trouvé")

    # =========================================================================
    # SCREENSHOT & PDF COMMANDS
    # =========================================================================

    elif cmd == "screenshot":
        # Capture a viewport screenshot (only what's visible)
        if not args:
            print("Usage: screenshot <fichier.png>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        data = cdp.screenshot(full_page=False)
        cdp.close()
        with open(args[0], 'wb') as f:
            f.write(data)
        print(f"✓ Screenshot → {args[0]}")

    elif cmd == "screenshot-full":
        # Capture a full-page screenshot (entire scrollable area)
        if not args:
            print("Usage: screenshot-full <fichier.png>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        data = cdp.screenshot(full_page=True)
        cdp.close()
        with open(args[0], 'wb') as f:
            f.write(data)
        print(f"✓ Screenshot full → {args[0]}")

    elif cmd == "pdf":
        # Export the current page as a PDF document
        if not args:
            print("Usage: pdf <fichier.pdf>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        data = cdp.pdf()
        cdp.close()
        with open(args[0], 'wb') as f:
            f.write(data)
        print(f"✓ PDF → {args[0]}")

    # =========================================================================
    # IMAGE COMMANDS
    # =========================================================================

    elif cmd == "read-images":
        # Extract all images from the page (5 sources: img, svg, canvas, bg, picture)
        cdp, _ = get_cdp()
        images = cdp.get_images()
        cdp.close()
        if args:
            # Save to file as JSON
            with open(args[0], 'w') as f:
                json.dump(images, f, indent=2, ensure_ascii=False)
            print(f"✓ {len(images)} images → {args[0]}")
        else:
            # Print JSON to stdout for piping
            print(json.dumps(images, indent=2, ensure_ascii=False))

    elif cmd == "capture-element":
        # Capture a specific DOM element as a PNG screenshot
        if len(args) < 2:
            print("Usage: capture-element <selector> <fichier.png>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        data = cdp.get_element_as_image(args[0])
        cdp.close()
        if data:
            with open(args[1], 'wb') as f:
                f.write(data)
            print(f"✓ Element {args[0]} → {args[1]}")
        else:
            print(f"✗ Element non trouvé: {args[0]}", file=sys.stderr)
            sys.exit(1)

    elif cmd == "download-images":
        # Download all images from the page to a local directory.
        # Handles both data URIs (base64-decode locally) and HTTP URLs (download).
        if not args:
            print("Usage: download-images <dossier>", file=sys.stderr)
            sys.exit(1)
        # urllib.request is already imported at the top of the file

        dossier = args[0]
        os.makedirs(dossier, exist_ok=True)

        # Extract all image metadata from the page
        cdp, _ = get_cdp()
        images = cdp.get_images()
        cdp.close()

        downloaded = 0
        for i, img in enumerate(images):
            src = img.get('src', '')
            img_type = img.get('type', 'img')  # img, svg, canvas, background, picture

            try:
                if src.startswith('data:'):
                    # --- Data URI: decode the base64 payload locally ---
                    # Format: "data:image/png;base64,iVBORw0KGgo..."
                    header, b64data = src.split(',', 1)
                    # Determine file extension from the MIME type in the header
                    ext = 'png' if 'png' in header else 'svg' if 'svg' in header else 'jpg'
                    data = base64.b64decode(b64data)
                    filename = f"{img_type}_{i:03d}.{ext}"
                    with open(os.path.join(dossier, filename), 'wb') as f:
                        f.write(data)
                    downloaded += 1
                elif src.startswith('http'):
                    # --- HTTP URL: download the image file ---
                    # Extract extension from URL, falling back to png
                    ext = src.split('.')[-1].split('?')[0][:4]  # Truncate to 4 chars
                    if ext not in ['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp']:
                        ext = 'png'
                    filename = f"{img_type}_{i:03d}.{ext}"
                    urllib.request.urlretrieve(src, os.path.join(dossier, filename))
                    downloaded += 1
            except Exception as e:
                # Skip failed downloads (network errors, invalid data URIs, etc.)
                print(f"  ⚠ Skip: {src[:50]}... ({e})", file=sys.stderr)

        print(f"✓ {downloaded}/{len(images)} images → {dossier}/")

    # =========================================================================
    # BLOCKED COMMANDS (SECURITY)
    # =========================================================================

    elif cmd == "stop":
        # EXPLICITLY FORBIDDEN: Chrome must NEVER be stopped by agents.
        # Stopping Chrome would destroy all agents' tabs and logged-in sessions.
        print("⛔ INTERDIT: Chrome ne doit JAMAIS être arrêté", file=sys.stderr)
        sys.exit(1)

    # =========================================================================
    # UNKNOWN COMMAND
    # =========================================================================

    else:
        print(f"Commande inconnue: {cmd}", file=sys.stderr)
        print("Voir --help pour la liste des commandes")
        sys.exit(1)


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    main()
