#!/usr/bin/env python3
"""
chrome-bridge.py -- Chrome Extension CDP Bridge Client
======================================================

DROP-IN REPLACEMENT for chrome-shared.py

Same CLI interface, same commands, same Redis integration.
The only difference: instead of connecting directly to Chrome via CDP WebSocket
on port 9222, this script sends commands to the Native Messaging Host HTTP server
which relays them to the Chrome Extension.

WHY:
  - Chrome launched with --remote-debugging-port=9222 is detected by Google
    as automation → login is blocked or requires extra verification
  - The Chrome Extension uses chrome.debugger API internally, which provides
    the same CDP capabilities but from INSIDE a normal Chrome instance
  - Google does not detect the extension as automation → login works normally

ARCHITECTURE:
  This script (HTTP) → Native Host (port 9222) → Extension → Chrome engine

MIGRATION FROM chrome-shared.py:
  Just replace 'chrome-shared.py' with 'chrome-bridge.py' in your commands.
  Everything else is identical.

USAGE:
  Same as chrome-shared.py — see that file's docstring for full command list.
  python3 chrome-bridge.py tab https://google.com
  python3 chrome-bridge.py screenshot out.png
  python3 chrome-bridge.py click "#login-button"
  etc.
"""

import subprocess
import sys
import time
import json
import urllib.request
import urllib.parse
import os
import base64
from pathlib import Path

# --- Optional: Redis ---
try:
    import redis
except ImportError:
    redis = None

# --- Optional: Pillow for image resizing ---
try:
    from PIL import Image
    import io
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# =============================================================================
# CONSTANTS
# =============================================================================

MAX_IMAGE_DIM = 1800
BRIDGE_PORT = int(os.environ.get("CDP_BRIDGE_PORT", "9222"))
BRIDGE_HOST = os.environ.get("CDP_BRIDGE_HOST", "127.0.0.1")
BRIDGE_URL = f"http://{BRIDGE_HOST}:{BRIDGE_PORT}"

REDIS_PREFIX = "ma:chrome:tab:"
BASE = str(Path.home() / "multi-agent")

# Exit codes (same as chrome-shared.py)
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CHROME_NOT_RUNNING = 100
EXIT_TARGET_STALE = 101
EXIT_WEBSOCKET_FAILED = 102

# =============================================================================
# REDIS CONNECTION
# =============================================================================

r = None
if redis:
    try:
        r = redis.Redis(host='localhost', port=6379, decode_responses=True)
        r.ping()
    except:
        r = None

# =============================================================================
# AGENT IDENTIFICATION (identical to chrome-shared.py)
# =============================================================================

def get_my_agent_id():
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
    except:
        pass
    return None

# =============================================================================
# REDIS TAB MAPPING (identical to chrome-shared.py)
# =============================================================================

def get_agent_tab(agent_id):
    if r:
        return r.get(f"{REDIS_PREFIX}{agent_id}")
    return None

def set_agent_tab(agent_id, tab_id):
    if r:
        r.set(f"{REDIS_PREFIX}{agent_id}", str(tab_id))
        return True
    return False

def del_agent_tab(agent_id):
    if r:
        r.delete(f"{REDIS_PREFIX}{agent_id}")

# =============================================================================
# BRIDGE HTTP CLIENT
# =============================================================================

class BridgeError(Exception):
    """Error communicating with the CDP Bridge."""
    pass


def bridge_request(method, path, data=None, timeout=60):
    """
    Send an HTTP request to the Native Host bridge server.

    Args:
        method: HTTP method ("GET" or "POST")
        path: URL path (e.g. "/command", "/json")
        data: Optional dict to send as JSON body (for POST)
        timeout: Request timeout in seconds

    Returns:
        Parsed JSON response

    Raises:
        BridgeError: If the request fails
    """
    url = f"{BRIDGE_URL}{path}"
    req_data = None
    if data is not None:
        req_data = json.dumps(data).encode("utf-8")

    max_retries = 3
    for attempt in range(max_retries):
        req = urllib.request.Request(
            url,
            data=req_data,
            method=method,
            headers={"Content-Type": "application/json"} if req_data else {}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                content_type = resp.headers.get("Content-Type", "")
                if "application/json" in content_type:
                    return json.loads(body.decode("utf-8"))
                else:
                    return body  # Raw binary (for screenshots, PDFs)
        except urllib.error.HTTPError as e:
            if e.code in (500, 502, 503) and attempt < max_retries - 1:
                time.sleep(1 + attempt)  # 1s, 2s backoff
                continue
            raise BridgeError(f"Bridge not reachable at {url}: {e}")
        except urllib.error.URLError as e:
            if attempt < max_retries - 1:
                time.sleep(1 + attempt)
                continue
            raise BridgeError(f"Bridge not reachable at {url}: {e}")
        except Exception as e:
            raise BridgeError(f"Bridge request failed: {e}")


def send_command(action, params=None, timeout=60):
    """
    Send a command to the extension via the bridge.

    Args:
        action: Command name (e.g. "navigate", "screenshot", "click")
        params: Optional dict of parameters

    Returns:
        The result from the extension

    Raises:
        BridgeError: If the command fails
    """
    resp = bridge_request("POST", "/command", {
        "action": action,
        "params": params or {}
    }, timeout=timeout)

    if isinstance(resp, dict):
        if resp.get("success"):
            return resp.get("result")
        else:
            raise BridgeError(resp.get("error", "Unknown error"))
    return resp

# =============================================================================
# BRIDGE-AWARE TAB QUERIES
# =============================================================================

def get_tabs():
    """List all open tabs via the bridge."""
    try:
        return bridge_request("GET", "/json")
    except:
        return []

def count_page_tabs():
    """Count open page-type tabs."""
    return len([t for t in get_tabs() if t.get("type") == "page"])

def check_chrome_running(port=BRIDGE_PORT):
    """Check if the bridge (and thus Chrome+extension) is reachable."""
    try:
        bridge_request("GET", "/health", timeout=3)
        return True
    except:
        return False

def validate_target(target_id, port=BRIDGE_PORT):
    """Check if a tab ID still exists."""
    try:
        tabs = get_tabs()
        return any(str(t.get("id")) == str(target_id) for t in tabs)
    except:
        return False

def cleanup_stale_target(agent_id):
    if r:
        old = r.get(f"{REDIS_PREFIX}{agent_id}")
        if old:
            r.delete(f"{REDIS_PREFIX}{agent_id}")
            print(f"⚠ Target {str(old)[:8]}... obsolète, mapping supprimé", file=sys.stderr)

def require_chrome_running():
    if not check_chrome_running():
        print("", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print("❌ ERREUR CRITIQUE: CDP Bridge non accessible sur port", BRIDGE_PORT, file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print("", file=sys.stderr)
        print("  Vérifier que:", file=sys.stderr)
        print("  1. Chrome est lancé normalement (PAS avec --remote-debugging-port)", file=sys.stderr)
        print("  2. L'extension CDP Bridge est installée et active", file=sys.stderr)
        print("  3. Le native host est installé (./install.sh)", file=sys.stderr)
        print("", file=sys.stderr)
        print("  Tester: curl http://127.0.0.1:9222/health", file=sys.stderr)
        print("", file=sys.stderr)
        sys.exit(EXIT_CHROME_NOT_RUNNING)

# =============================================================================
# TAB LIFECYCLE
# =============================================================================

def create_tab(target_url="about:blank"):
    """Create a new tab via the bridge."""
    try:
        result = send_command("new_tab", {"url": target_url})
        return str(result.get("tabId"))
    except Exception as e:
        print(f"Erreur création onglet: {e}", file=sys.stderr)
        return None

def close_tab_by_id(tab_id):
    """Close a tab via the bridge."""
    try:
        send_command("close_tab", {"tabId": int(tab_id)})
        return True
    except:
        return False

# =============================================================================
# CDP CLASS — Bridge-backed replacement
# =============================================================================

class CDP:
    """
    CDP client that sends commands through the Chrome Extension bridge.

    Drop-in replacement for the WebSocket-based CDP class in chrome-shared.py.
    Same methods, same signatures, same behavior — different transport.
    """

    def __init__(self, tab_id):
        self.tab_id = int(tab_id)

    def connect(self):
        """No-op — HTTP is connectionless. Kept for API compatibility."""
        return self

    def close(self):
        """No-op — HTTP is connectionless. Kept for API compatibility."""
        pass

    def send(self, method, params=None, timeout=30):
        """
        Send a CDP command via the bridge.
        Equivalent to the WebSocket-based send() in chrome-shared.py.
        """
        result = send_command("raw_cdp", {
            "tabId": self.tab_id,
            "method": method,
            "cdpParams": params or {}
        }, timeout=timeout)
        return result

    def evaluate(self, expression, timeout=60):
        """Execute JavaScript and return the result value."""
        result = send_command("evaluate", {
            "tabId": self.tab_id,
            "expression": expression
        }, timeout=timeout)
        return result.get("value") if isinstance(result, dict) else result

    # ─── Navigation ───────────────────────────────────────────────────

    def navigate(self, url):
        send_command("navigate", {"tabId": self.tab_id, "url": url})

    def reload(self):
        send_command("reload", {"tabId": self.tab_id})

    def go_back(self):
        self.evaluate("history.back()")
        time.sleep(1)

    def go_forward(self):
        self.evaluate("history.forward()")
        time.sleep(1)

    def get_url(self):
        return self.evaluate("window.location.href")

    def get_title(self):
        return self.evaluate("document.title")

    # ─── Page Content ─────────────────────────────────────────────────

    def get_html(self):
        """Get full page HTML. Uses chunked transfer for large pages (>800KB)."""
        # First check size to decide if chunking is needed
        size = self.evaluate("document.documentElement.outerHTML.length")
        if not size or int(size) < 800_000:
            return self.evaluate("document.documentElement.outerHTML", timeout=120)
        # Large page — store in window._html and transfer in 500KB chunks
        # Use IIFE to avoid returning the 2MB+ string as assignment result
        self.evaluate("void(window._html = document.documentElement.outerHTML)")
        total = int(self.evaluate("window._html.length"))
        chunk_size = 500_000
        parts = []
        for offset in range(0, total, chunk_size):
            chunk = self.evaluate(f"window._html.substring({offset}, {offset + chunk_size})")
            if chunk:
                parts.append(chunk)
        self.evaluate("delete window._html")
        return "".join(parts)

    def get_text(self):
        return self.evaluate("document.body.innerText")

    def get_element_html(self, selector):
        return self.evaluate(f"document.querySelector('{_esc(selector)}')?.outerHTML || null")

    def get_attribute(self, selector, attr):
        return self.evaluate(
            f"document.querySelector('{_esc(selector)}')?.getAttribute('{_esc(attr)}') || null")

    def get_links(self):
        return self.evaluate("""
            [...document.querySelectorAll('a[href]')].map(a => ({
                href: a.href, text: a.textContent.trim().substring(0, 100)
            }))
        """) or []

    # ─── Click / Mouse ────────────────────────────────────────────────

    def click(self, selector):
        send_command("click", {"tabId": self.tab_id, "selector": selector})
        time.sleep(0.5)

    def click_text(self, text, tag="*"):
        send_command("click_text", {"tabId": self.tab_id, "text": text, "tag": tag})
        time.sleep(0.5)

    def dblclick(self, selector):
        send_command("dblclick", {"tabId": self.tab_id, "selector": selector})
        time.sleep(0.5)

    def hover(self, selector):
        send_command("hover", {"tabId": self.tab_id, "selector": selector})

    def _mouse_click(self, x, y, click_count=1):
        # Low-level: use raw CDP
        self.send("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": x, "y": y,
            "button": "left", "clickCount": click_count
        })
        self.send("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": x, "y": y,
            "button": "left", "clickCount": click_count
        })
        time.sleep(0.5)

    # ─── Keyboard / Input ─────────────────────────────────────────────

    def type_text(self, selector, text, clear=True):
        send_command("type", {
            "tabId": self.tab_id,
            "selector": selector,
            "text": text,
            "clear": clear
        })

    def clear_field(self, selector):
        self.evaluate(f"document.querySelector('{_esc(selector)}').value = ''")

    def press_key(self, key):
        send_command("press", {"tabId": self.tab_id, "key": key})

    # ─── Forms ────────────────────────────────────────────────────────

    def select_option(self, selector, value):
        send_command("select", {"tabId": self.tab_id, "selector": selector, "value": value})

    def check(self, selector):
        send_command("check", {"tabId": self.tab_id, "selector": selector})

    def uncheck(self, selector):
        send_command("uncheck", {"tabId": self.tab_id, "selector": selector})

    def submit_form(self):
        self.evaluate("document.activeElement?.form?.submit()")
        time.sleep(1)

    # ─── Scroll ───────────────────────────────────────────────────────

    def scroll(self, direction):
        send_command("scroll", {"tabId": self.tab_id, "direction": direction})

    def scroll_to(self, selector):
        send_command("scroll_to", {"tabId": self.tab_id, "selector": selector})

    # ─── Wait / Poll ──────────────────────────────────────────────────

    def wait(self, seconds):
        time.sleep(float(seconds))

    def wait_element(self, selector, timeout=30):
        send_command("wait_element", {
            "tabId": self.tab_id, "selector": selector, "timeout": timeout
        }, timeout=timeout + 5)
        return True

    def wait_hidden(self, selector, timeout=30):
        send_command("wait_hidden", {
            "tabId": self.tab_id, "selector": selector, "timeout": timeout
        }, timeout=timeout + 5)
        return True

    def wait_text(self, text, timeout=30):
        send_command("wait_text", {
            "tabId": self.tab_id, "text": text, "timeout": timeout
        }, timeout=timeout + 5)
        return True

    # ─── Screenshot / PDF ─────────────────────────────────────────────

    def screenshot(self, full_page=False, max_dim=None):
        if max_dim is None:
            max_dim = MAX_IMAGE_DIM

        action = "screenshot_full" if full_page else "screenshot"
        result = send_command(action, {"tabId": self.tab_id}, timeout=30)
        png_data = base64.b64decode(result.get("data", ""))

        # Resize if needed (same logic as chrome-shared.py)
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

    def pdf(self):
        result = send_command("pdf", {"tabId": self.tab_id}, timeout=30)
        return base64.b64decode(result.get("data", ""))

    # ─── Images ───────────────────────────────────────────────────────

    def get_images(self):
        return send_command("get_images", {"tabId": self.tab_id})

    def get_element_as_image(self, selector, max_dim=None):
        if max_dim is None:
            max_dim = MAX_IMAGE_DIM

        result = send_command("capture_element", {
            "tabId": self.tab_id, "selector": selector
        })
        if not result or not result.get("data"):
            return None
        png_data = base64.b64decode(result["data"])

        if PIL_AVAILABLE and max_dim:
            try:
                img = Image.open(io.BytesIO(png_data))
                w, h = img.size
                if w > max_dim or h > max_dim:
                    if w > h:
                        new_w, new_h = max_dim, int(h * max_dim / w)
                    else:
                        new_h, new_w = max_dim, int(w * max_dim / h)
                    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                    buf = io.BytesIO()
                    img.save(buf, format='PNG')
                    png_data = buf.getvalue()
            except Exception as e:
                print(f"⚠️  Resize failed: {e}", file=sys.stderr)

        return png_data


# =============================================================================
# HELPER
# =============================================================================

def _esc(s):
    """Escape single quotes for JS injection."""
    if not s:
        return ""
    return s.replace("\\", "\\\\").replace("'", "\\'")


# =============================================================================
# CDP CONNECTION FACTORY (compatible with chrome-shared.py)
# =============================================================================

def get_cdp(agent_id=None):
    """
    Create a validated CDP connection for the current agent.
    Same interface as chrome-shared.py's get_cdp().
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
        print(f"  → Utiliser: chrome-bridge.py tab <url>", file=sys.stderr)
        sys.exit(EXIT_ERROR)

    return CDP(tab_id).connect(), agent_id


# =============================================================================
# MAIN COMMAND DISPATCHER
# =============================================================================
# Identical structure to chrome-shared.py main() — same commands, same args.
# =============================================================================

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1].lower()
    args = sys.argv[2:]

    # =====================================================================
    # TAB MANAGEMENT
    # =====================================================================

    if cmd == "status":
        if check_chrome_running():
            try:
                info = bridge_request("GET", "/health")
                tabs = get_tabs()
                print(f"✓ CDP Bridge actif sur port {BRIDGE_PORT}")
                print(f"  Extension connectée: {info.get('extensionConnected', '?')}")
                print(f"  Onglets: {len(tabs)}")
                print(f"  Uptime: {info.get('uptime', 0):.0f}s")
            except Exception as e:
                print(f"✓ Bridge actif mais erreur: {e}")
        else:
            print(f"✗ CDP Bridge non actif sur port {BRIDGE_PORT}")
            sys.exit(EXIT_CHROME_NOT_RUNNING)

    elif cmd == "list":
        if r:
            keys = r.keys(f"{REDIS_PREFIX}*")
            if keys:
                print(f"{'Agent':<10} TabId")
                print("-" * 50)
                for key in sorted(keys):
                    agent = key.replace(REDIS_PREFIX, "")
                    print(f"{agent:<10} {r.get(key)}")
            else:
                print("Aucun mapping")
        else:
            # Without Redis, list tabs directly
            tabs = get_tabs()
            for t in tabs:
                print(f"  [{t.get('id')}] {t.get('title', '')} — {t.get('url', '')}")

    elif cmd == "tab":
        require_chrome_running()

        if len(args) >= 2 and not args[0].startswith("http"):
            agent_id, url = args[0], args[1]
        elif len(args) >= 1:
            agent_id, url = get_my_agent_id(), args[0]
        else:
            agent_id, url = get_my_agent_id(), "about:blank"

        if not agent_id:
            print("Erreur: agent_id non détectable", file=sys.stderr)
            sys.exit(EXIT_ERROR)

        existing = get_agent_tab(agent_id)
        if existing:
            if validate_target(existing):
                try:
                    cdp = CDP(existing).connect()
                    cdp.navigate(url)
                    cdp.close()
                    print(existing)
                except Exception as e:
                    print(f"⚠ Target zombie, création nouveau tab...", file=sys.stderr)
                    cleanup_stale_target(agent_id)
                    existing = None
            else:
                cleanup_stale_target(agent_id)
                existing = None

        if not existing:
            tab_id = create_tab(url)
            if tab_id:
                set_agent_tab(agent_id, tab_id)
                print(tab_id)
            else:
                sys.exit(EXIT_ERROR)

    elif cmd == "get":
        agent_id = args[0] if args else get_my_agent_id()
        tab_id = get_agent_tab(agent_id)
        if tab_id:
            print(tab_id)
        else:
            print(f"Pas d'onglet pour agent {agent_id}", file=sys.stderr)
            sys.exit(1)

    elif cmd == "close":
        require_chrome_running()
        agent_id = args[0] if args else get_my_agent_id()
        if not agent_id:
            print("Erreur: agent_id non détectable", file=sys.stderr)
            sys.exit(EXIT_ERROR)

        tab_id = get_agent_tab(agent_id)
        if not tab_id:
            print(f"Agent {agent_id} n'a pas d'onglet", file=sys.stderr)
            sys.exit(EXIT_ERROR)

        if count_page_tabs() <= 1:
            print("⛔ Impossible: dernier onglet", file=sys.stderr)
            sys.exit(1)

        close_tab_by_id(tab_id)
        del_agent_tab(agent_id)
        print(f"✓ Onglet fermé pour agent {agent_id}")

    # =====================================================================
    # NAVIGATION
    # =====================================================================

    elif cmd == "goto":
        if not args:
            print("Usage: goto <url>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.navigate(args[0])
        cdp.close()
        print(f"✓ Navigation → {args[0]}")

    elif cmd == "reload":
        cdp, _ = get_cdp()
        cdp.reload()
        cdp.close()
        print("✓ Page rechargée")

    elif cmd == "back":
        cdp, _ = get_cdp()
        cdp.go_back()
        cdp.close()
        print("✓ ← Retour")

    elif cmd == "forward":
        cdp, _ = get_cdp()
        cdp.go_forward()
        cdp.close()
        print("✓ → Avance")

    elif cmd == "url":
        cdp, _ = get_cdp()
        print(cdp.get_url())
        cdp.close()

    elif cmd == "title":
        cdp, _ = get_cdp()
        print(cdp.get_title())
        cdp.close()

    # =====================================================================
    # READING
    # =====================================================================

    elif cmd == "read":
        if not args:
            print("Usage: read <fichier>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        html = cdp.get_html()
        cdp.close()
        with open(args[0], 'w', encoding='utf-8') as f:
            f.write(html or "")
        print(f"✓ HTML → {args[0]}")

    elif cmd == "read-text":
        if not args:
            print("Usage: read-text <fichier>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        text = cdp.get_text()
        cdp.close()
        with open(args[0], 'w', encoding='utf-8') as f:
            f.write(text or "")
        print(f"✓ Text → {args[0]}")

    elif cmd == "read-element":
        if len(args) < 2:
            print("Usage: read-element <selector> <fichier>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        html = cdp.get_element_html(args[0])
        cdp.close()
        if html:
            with open(args[1], 'w', encoding='utf-8') as f:
                f.write(html)
            print(f"✓ Element → {args[1]}")
        else:
            print(f"✗ Element non trouvé: {args[0]}", file=sys.stderr)
            sys.exit(1)

    elif cmd == "read-attr":
        if len(args) < 2:
            print("Usage: read-attr <selector> <attribut>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        val = cdp.get_attribute(args[0], args[1])
        cdp.close()
        if val is not None:
            print(val)
        else:
            print(f"✗ Attribut non trouvé", file=sys.stderr)
            sys.exit(1)

    elif cmd == "read-links":
        cdp, _ = get_cdp()
        links = cdp.get_links()
        cdp.close()
        for link in (links or []):
            print(f"  {link.get('text', '')[:60]:<60} {link.get('href', '')}")

    elif cmd == "eval":
        if not args:
            print("Usage: eval <expression>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        result = cdp.evaluate(" ".join(args))
        cdp.close()
        if result is not None:
            if isinstance(result, (dict, list)):
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                print(result)

    # =====================================================================
    # CLICKING
    # =====================================================================

    elif cmd == "click":
        if not args:
            print("Usage: click <selector>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.click(args[0])
        cdp.close()
        print(f"✓ Click: {args[0]}")

    elif cmd == "click-text":
        if not args:
            print("Usage: click-text <texte>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.click_text(" ".join(args))
        cdp.close()
        print(f"✓ Click text: {' '.join(args)}")

    elif cmd == "dblclick":
        if not args:
            print("Usage: dblclick <selector>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.dblclick(args[0])
        cdp.close()
        print(f"✓ Double-click: {args[0]}")

    elif cmd == "hover":
        if not args:
            print("Usage: hover <selector>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.hover(args[0])
        cdp.close()
        print(f"✓ Hover: {args[0]}")

    # =====================================================================
    # TYPING
    # =====================================================================

    elif cmd in ("type", "fill"):
        if len(args) < 2:
            print("Usage: type <selector> <texte>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.type_text(args[0], " ".join(args[1:]))
        cdp.close()
        print(f"✓ Tapé dans {args[0]}")

    elif cmd == "clear":
        if not args:
            print("Usage: clear <selector>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.clear_field(args[0])
        cdp.close()
        print(f"✓ Champ vidé: {args[0]}")

    elif cmd == "press":
        if not args:
            print("Usage: press <touche>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.press_key(args[0])
        cdp.close()
        print(f"✓ Touche: {args[0]}")

    # =====================================================================
    # FORMS
    # =====================================================================

    elif cmd == "select":
        if len(args) < 2:
            print("Usage: select <selector> <valeur>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.select_option(args[0], args[1])
        cdp.close()
        print(f"✓ Sélectionné: {args[1]}")

    elif cmd == "check":
        if not args:
            print("Usage: check <selector>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.check(args[0])
        cdp.close()
        print(f"✓ Coché: {args[0]}")

    elif cmd == "uncheck":
        if not args:
            print("Usage: uncheck <selector>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.uncheck(args[0])
        cdp.close()
        print(f"✓ Décoché: {args[0]}")

    elif cmd == "submit":
        cdp, _ = get_cdp()
        cdp.submit_form()
        cdp.close()
        print("✓ Formulaire soumis")

    # =====================================================================
    # SCROLLING
    # =====================================================================

    elif cmd == "scroll":
        if not args:
            print("Usage: scroll <down|up|bottom|top>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.scroll(args[0])
        cdp.close()
        print(f"✓ Scroll {args[0]}")

    elif cmd == "scroll-to":
        if not args:
            print("Usage: scroll-to <selector>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.scroll_to(args[0])
        cdp.close()
        print(f"✓ Scroll vers {args[0]}")

    # =====================================================================
    # WAITING
    # =====================================================================

    elif cmd == "wait":
        if not args:
            print("Usage: wait <secondes>", file=sys.stderr)
            sys.exit(1)
        time.sleep(float(args[0]))
        print(f"✓ Attendu {args[0]}s")

    elif cmd == "wait-element":
        if not args:
            print("Usage: wait-element <selector>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.wait_element(args[0])
        cdp.close()
        print(f"✓ Element trouvé: {args[0]}")

    elif cmd == "wait-hidden":
        if not args:
            print("Usage: wait-hidden <selector>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.wait_hidden(args[0])
        cdp.close()
        print(f"✓ Element disparu: {args[0]}")

    elif cmd == "wait-text":
        if not args:
            print("Usage: wait-text <texte>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.wait_text(" ".join(args))
        cdp.close()
        print(f"✓ Texte trouvé")

    # =====================================================================
    # SCREENSHOT & PDF
    # =====================================================================

    elif cmd == "screenshot":
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
        if not args:
            print("Usage: pdf <fichier.pdf>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        data = cdp.pdf()
        cdp.close()
        with open(args[0], 'wb') as f:
            f.write(data)
        print(f"✓ PDF → {args[0]}")

    # =====================================================================
    # IMAGES
    # =====================================================================

    elif cmd == "read-images":
        cdp, _ = get_cdp()
        images = cdp.get_images()
        cdp.close()
        if args:
            with open(args[0], 'w') as f:
                json.dump(images, f, indent=2, ensure_ascii=False)
            print(f"✓ {len(images)} images → {args[0]}")
        else:
            print(json.dumps(images, indent=2, ensure_ascii=False))

    elif cmd == "capture-element":
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
        if not args:
            print("Usage: download-images <dossier>", file=sys.stderr)
            sys.exit(1)
        dossier = args[0]
        os.makedirs(dossier, exist_ok=True)
        cdp, _ = get_cdp()
        images = cdp.get_images()
        cdp.close()

        downloaded = 0
        for i, img in enumerate(images or []):
            src = img.get('src', '')
            img_type = img.get('type', 'img')
            try:
                if src.startswith('data:'):
                    header, b64data = src.split(',', 1)
                    ext = 'png' if 'png' in header else 'svg' if 'svg' in header else 'jpg'
                    data = base64.b64decode(b64data)
                    filename = f"{img_type}_{i:03d}.{ext}"
                    with open(os.path.join(dossier, filename), 'wb') as f:
                        f.write(data)
                    downloaded += 1
                elif src.startswith('http'):
                    ext = src.split('.')[-1].split('?')[0][:4]
                    if ext not in ['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp']:
                        ext = 'png'
                    filename = f"{img_type}_{i:03d}.{ext}"
                    urllib.request.urlretrieve(src, os.path.join(dossier, filename))
                    downloaded += 1
            except Exception as e:
                print(f"  ⚠ Skip: {src[:50]}... ({e})", file=sys.stderr)

        print(f"✓ {downloaded}/{len(images or [])} images → {dossier}/")

    # =====================================================================
    # BLOCKED
    # =====================================================================

    elif cmd == "stop":
        print("⛔ INTERDIT: Chrome ne doit JAMAIS être arrêté", file=sys.stderr)
        sys.exit(1)

    # =====================================================================
    # UNKNOWN
    # =====================================================================

    else:
        print(f"Commande inconnue: {cmd}", file=sys.stderr)
        print("Commandes: status, list, tab, get, close, goto, reload, back, forward,")
        print("  url, title, read, read-text, read-element, read-attr, read-links, eval,")
        print("  click, click-text, dblclick, hover, type, fill, clear, press,")
        print("  select, check, uncheck, submit, scroll, scroll-to,")
        print("  wait, wait-element, wait-hidden, wait-text,")
        print("  screenshot, screenshot-full, pdf, read-images, capture-element, download-images")
        sys.exit(1)


if __name__ == "__main__":
    main()
