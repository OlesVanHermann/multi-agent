#!/usr/bin/env python3
"""
cdp-direct.py -- Chrome CDP Direct WebSocket Driver
===================================================

DROP-IN companion to chrome-bridge.py for RAW CDP Chrome instances.

Same CLI, same commands, same Redis tab mapping, same exit codes.
Transport: direct CDP WebSocket on the Chrome DevTools port (default 9222),
per the CLAUDE.md rule "Methode: CDP direct via websockets (port 9222)".

WHICH DRIVER WHEN:
  - chrome-bridge.py : GUI Chrome + extension cdp-bridge + native host
                       (Google-login safe; operator desktop machines)
  - cdp-direct.py    : headless/raw Chrome launched with
                       --remote-debugging-port=9222 (servers, live-walk)

ISOLATION (OBLIGATOIRE):
  Every agent tab is created inside its OWN BrowserContext
  (Target.createBrowserContext): separate cookies/session/storage.
  Operator tabs are NEVER listed as candidates, never navigated, never
  closed. `close` only closes the agent's own tab then disposes the
  agent's own context. The viewport of the isolated tab is set to
  1440x900 at creation for stable layouts in headless.

EXTRA COMMANDS (additive, absent from chrome-bridge.py):
  console <seconds> [file]   collect console/log/exception events (JSON lines)
  network <seconds> [file]   collect network request/response events (JSON lines)

USAGE:
  AGENT_ID=385-385 python3 cdp-direct.py tab https://example.com
  AGENT_ID=385-385 python3 cdp-direct.py click "#login-button"
  AGENT_ID=385-385 python3 cdp-direct.py read-text page.txt
  AGENT_ID=385-385 python3 cdp-direct.py close

Origin: decision operateur 2026-07-11 (escalation triangle 385, Option A).
The historical direct-ws driver (chrome-shared.py) was removed during the
extension-bridge migration (fev 2026); this file restores the sanctioned
transport as a versioned framework tool. WebSocket base: framework/crawl2.py.
"""

import sys
import time
import json
import urllib.request
import urllib.parse
import os
import base64
from pathlib import Path

try:
    from websockets.sync.client import connect as ws_connect
except ImportError:
    sys.exit("pip install websockets  (>= 11, sync client requis)")

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
CDP_PORT = int(os.environ.get("CDP_PORT", os.environ.get("CDP_BRIDGE_PORT", "9222")))
CDP_HOST = os.environ.get("CDP_HOST", os.environ.get("CDP_BRIDGE_HOST", "127.0.0.1"))
HTTP_BASE = f"http://{CDP_HOST}:{CDP_PORT}"

REDIS_PREFIX = "chrome:tab:"
CTX_PREFIX = "chrome:ctx:"
VIEWPORT = (1440, 900)

# Exit codes (same as chrome-bridge.py / chrome-shared.py)
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CHROME_NOT_RUNNING = 100
EXIT_TARGET_STALE = 101
EXIT_WEBSOCKET_FAILED = 102


def _safe_output_path(filepath: str) -> str:
    """Validate output path: reject absolute paths and traversal."""
    p = Path(filepath)
    if p.is_absolute():
        raise SystemExit(f"Error: absolute output path not allowed: {filepath}")
    resolved = Path.cwd().joinpath(p).resolve()
    if not str(resolved).startswith(str(Path.cwd().resolve())):
        raise SystemExit(f"Error: path traversal detected: {filepath}")
    return str(resolved)


def _is_safe_url(url: str) -> bool:
    """Block internal/private IPs and dangerous schemes (download-images only)."""
    import ipaddress
    import socket
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        return False
    host = (parsed.hostname or '').lower()
    if not host:
        return False
    try:
        resolved = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for _fam, _type, _proto, _canon, sockaddr in resolved:
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
    except (socket.gaierror, ValueError):
        return False
    return True

# =============================================================================
# REDIS CONNECTION (password from env, unlike chrome-bridge.py)
# =============================================================================

r = None
if redis:
    try:
        r = redis.Redis(
            host=os.environ.get("REDIS_HOST", "localhost"),
            port=int(os.environ.get("REDIS_PORT", "6379")),
            password=os.environ.get("REDIS_PASSWORD") or None,
            decode_responses=True,
        )
        r.ping()
    except Exception:
        r = None

# =============================================================================
# AGENT IDENTIFICATION
# =============================================================================

def get_my_agent_id():
    agent_id = os.environ.get("AGENT_ID")
    if agent_id:
        return agent_id
    try:
        import subprocess
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#S"],
            capture_output=True, text=True, timeout=2
        )
        session_name = result.stdout.strip()
        # Canonical session name: agent-XXX or agent-XXX-YYY.
        if "-agent-" in session_name:
            return session_name.split("-agent-", 1)[1]
        if session_name.startswith("agent-"):
            return session_name.replace("agent-", "")
    except Exception:
        pass
    return None

# =============================================================================
# REDIS TAB + CONTEXT MAPPING
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

def get_agent_ctx(agent_id):
    if r:
        return r.get(f"{CTX_PREFIX}{agent_id}")
    return None

def set_agent_ctx(agent_id, ctx_id):
    if r:
        r.set(f"{CTX_PREFIX}{agent_id}", str(ctx_id))

def del_agent_ctx(agent_id):
    if r:
        r.delete(f"{CTX_PREFIX}{agent_id}")

# =============================================================================
# CDP HTTP ENDPOINTS (raw Chrome)
# =============================================================================

class CDPError(Exception):
    """Error talking CDP to Chrome."""
    pass


def http_json(path, timeout=5):
    url = f"{HTTP_BASE}{path}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_tabs():
    """List all open targets via the raw CDP HTTP endpoint."""
    try:
        return http_json("/json")
    except Exception:
        return []


def count_page_tabs():
    return len([t for t in get_tabs() if t.get("type") == "page"])


def check_chrome_running():
    try:
        http_json("/json/version", timeout=3)
        return True
    except Exception:
        return False


def validate_target(target_id):
    try:
        return any(str(t.get("id")) == str(target_id) for t in get_tabs())
    except Exception:
        return False


def cleanup_stale_target(agent_id):
    if r:
        old = r.get(f"{REDIS_PREFIX}{agent_id}")
        if old:
            r.delete(f"{REDIS_PREFIX}{agent_id}")
            print(f"⚠ Target {str(old)[:8]}... obsolète, mapping supprimé", file=sys.stderr)
        # Context may survive a crashed tab: dispose it too
        old_ctx = get_agent_ctx(agent_id)
        if old_ctx:
            try:
                _dispose_context(old_ctx)
            except Exception:
                pass
            del_agent_ctx(agent_id)


def require_chrome_running():
    if not check_chrome_running():
        print("", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print("❌ ERREUR CRITIQUE: Chrome CDP non accessible sur port", CDP_PORT, file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print("", file=sys.stderr)
        print("  Vérifier que Chrome est lancé avec --remote-debugging-port", file=sys.stderr)
        print(f"  Tester: curl {HTTP_BASE}/json/version", file=sys.stderr)
        print("", file=sys.stderr)
        print("  ⛔ NE JAMAIS relancer Chrome automatiquement (sessions perdues)", file=sys.stderr)
        sys.exit(EXIT_CHROME_NOT_RUNNING)

# =============================================================================
# WEBSOCKET SESSION (transport layer — replaces bridge_request/send_command)
# =============================================================================

class WSSession:
    """One CDP WebSocket connection (browser-level or page-level)."""

    def __init__(self, ws_url):
        self.ws_url = ws_url
        self.ws = None
        self._id = 0
        self.events = []

    def connect(self):
        try:
            self.ws = ws_connect(self.ws_url, max_size=100_000_000, open_timeout=10)
        except Exception as e:
            print(f"✗ WebSocket CDP: {e}", file=sys.stderr)
            sys.exit(EXIT_WEBSOCKET_FAILED)
        return self

    def close(self):
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass

    def send(self, method, params=None, timeout=30):
        """Send a CDP command, buffer events, return the matching result."""
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise CDPError(f"timeout CDP: {method}")
            try:
                raw = self.ws.recv(timeout=remaining)
            except TimeoutError:
                raise CDPError(f"timeout CDP: {method}")
            msg = json.loads(raw)
            if msg.get("id") == mid:
                if "error" in msg:
                    raise CDPError(f"{method}: {msg['error'].get('message', '?')}")
                return msg.get("result", {})
            if "method" in msg:
                self.events.append(msg)

    def wait_cdp_event(self, name, timeout=15):
        """Wait for a CDP event (already buffered or incoming). None on timeout."""
        for ev in self.events:
            if ev.get("method") == name:
                return ev
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                return None
            try:
                raw = self.ws.recv(timeout=remaining)
            except TimeoutError:
                return None
            msg = json.loads(raw)
            if "method" in msg:
                self.events.append(msg)
                if msg["method"] == name:
                    return msg

    def collect_cdp_events(self, duration):
        """Buffer every incoming event for `duration` seconds, then return them."""
        deadline = time.time() + duration
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            try:
                raw = self.ws.recv(timeout=remaining)
            except TimeoutError:
                break
            msg = json.loads(raw)
            if "method" in msg:
                self.events.append(msg)
        return self.events

# =============================================================================
# BROWSER-LEVEL SESSION (context + target lifecycle — NEVER touches operator tabs)
# =============================================================================

def _browser_session():
    require_chrome_running()
    info = http_json("/json/version")
    ws_url = info.get("webSocketDebuggerUrl")
    if not ws_url:
        print("✗ Pas de webSocketDebuggerUrl navigateur", file=sys.stderr)
        sys.exit(EXIT_CHROME_NOT_RUNNING)
    return WSSession(ws_url).connect()


def create_tab(target_url="about:blank"):
    """Create a tab inside a FRESH isolated BrowserContext. Returns (tabId, ctxId)."""
    b = _browser_session()
    try:
        ctx = b.send("Target.createBrowserContext", {"disposeOnDetach": False})
        ctx_id = ctx.get("browserContextId")
        tgt = b.send("Target.createTarget", {
            "url": target_url or "about:blank",
            "browserContextId": ctx_id,
        })
        return str(tgt.get("targetId")), ctx_id
    except CDPError as e:
        print(f"Erreur création onglet: {e}", file=sys.stderr)
        return None, None
    finally:
        b.close()


def close_tab_by_id(tab_id):
    b = _browser_session()
    try:
        b.send("Target.closeTarget", {"targetId": str(tab_id)})
        return True
    except CDPError:
        return False
    finally:
        b.close()


def _dispose_context(ctx_id):
    b = _browser_session()
    try:
        b.send("Target.disposeBrowserContext", {"browserContextId": ctx_id})
        return True
    except CDPError:
        return False
    finally:
        b.close()

# =============================================================================
# CDP CLASS — page-level, direct WebSocket transport
# Same methods, same signatures, same behavior as chrome-bridge.py's CDP.
# =============================================================================

class CDP(WSSession):

    def __init__(self, tab_id):
        self.tab_id = str(tab_id)
        super().__init__(f"ws://{CDP_HOST}:{CDP_PORT}/devtools/page/{self.tab_id}")

    def evaluate(self, expression, timeout=60):
        """Execute JavaScript and return the result value."""
        res = self.send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        }, timeout=timeout)
        if res.get("exceptionDetails"):
            exc = res["exceptionDetails"]
            text = exc.get("exception", {}).get("description") or exc.get("text", "JS error")
            raise CDPError(text.split("\n")[0])
        return res.get("result", {}).get("value")

    # ─── Navigation ───────────────────────────────────────────────────

    def navigate(self, url, load_timeout=20):
        self.send("Page.enable")
        self.send("Page.navigate", {"url": url})
        self.wait_cdp_event("Page.loadEventFired", timeout=load_timeout)

    def reload(self):
        self.send("Page.enable")
        self.send("Page.reload")
        self.wait_cdp_event("Page.loadEventFired", timeout=20)

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
        size = self.evaluate("document.documentElement.outerHTML.length")
        if not size or int(size) < 800_000:
            return self.evaluate("document.documentElement.outerHTML", timeout=120)
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
        return self.evaluate(
            f"document.querySelector({json.dumps(selector)})?.outerHTML || null")

    def get_attribute(self, selector, attr):
        return self.evaluate(
            f"document.querySelector({json.dumps(selector)})"
            f"?.getAttribute({json.dumps(attr)}) || null")

    def get_links(self):
        return self.evaluate("""
            [...document.querySelectorAll('a[href]')].map(a => ({
                href: a.href, text: a.textContent.trim().substring(0, 100)
            }))
        """) or []

    # ─── Click / Mouse (real Input events, not el.click()) ───────────

    def _center(self, selector):
        return self.evaluate(
            "(() => {"
            f"  const el = document.querySelector({json.dumps(selector)});"
            "  if (!el) return null;"
            "  el.scrollIntoView({block: 'center', inline: 'center'});"
            "  const r = el.getBoundingClientRect();"
            "  return {x: r.left + r.width / 2, y: r.top + r.height / 2};"
            "})()")

    def _mouse_click(self, x, y, click_count=1):
        self.send("Input.dispatchMouseEvent", {
            "type": "mouseMoved", "x": x, "y": y, "button": "none"})
        self.send("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": x, "y": y,
            "button": "left", "clickCount": click_count})
        self.send("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": x, "y": y,
            "button": "left", "clickCount": click_count})
        time.sleep(0.5)

    def click(self, selector):
        c = self._center(selector)
        if not c:
            raise CDPError(f"element non trouve: {selector}")
        self._mouse_click(c["x"], c["y"])

    def click_text(self, text, tag="*"):
        c = self.evaluate(
            "(() => {"
            f"  const wanted = {json.dumps(text)};"
            f"  const nodes = [...document.querySelectorAll({json.dumps(tag)})];"
            "  const hits = nodes.filter(el => el.textContent"
            "    && el.textContent.trim().includes(wanted)"
            "    && el.getClientRects().length > 0);"
            "  if (!hits.length) return null;"
            "  let el = hits[hits.length - 1];"
            "  for (const m of hits) {"
            "    const deeper = [...m.querySelectorAll('*')].some(ch => ch.textContent"
            "      && ch.textContent.trim().includes(wanted) && ch.getClientRects().length > 0);"
            "    if (!deeper) { el = m; break; }"
            "  }"
            "  el.scrollIntoView({block: 'center', inline: 'center'});"
            "  const r = el.getBoundingClientRect();"
            "  return {x: r.left + r.width / 2, y: r.top + r.height / 2};"
            "})()")
        if not c:
            raise CDPError(f"texte non trouve: {text}")
        self._mouse_click(c["x"], c["y"])

    def dblclick(self, selector):
        c = self._center(selector)
        if not c:
            raise CDPError(f"element non trouve: {selector}")
        self._mouse_click(c["x"], c["y"], click_count=2)

    def hover(self, selector):
        c = self._center(selector)
        if not c:
            raise CDPError(f"element non trouve: {selector}")
        self.send("Input.dispatchMouseEvent", {
            "type": "mouseMoved", "x": c["x"], "y": c["y"], "button": "none"})

    # ─── Keyboard / Input ─────────────────────────────────────────────

    def type_text(self, selector, text, clear=True):
        ok = self.evaluate(
            "(() => {"
            f"  const el = document.querySelector({json.dumps(selector)});"
            "  if (!el) return false;"
            "  el.focus();"
            + ("  if ('value' in el) { el.value = '';"
               "    el.dispatchEvent(new Event('input', {bubbles: true})); }"
               if clear else "")
            + "  return true;"
            "})()")
        if not ok:
            raise CDPError(f"element non trouve: {selector}")
        # insertText fires native input events (React-compatible)
        self.send("Input.insertText", {"text": text})

    def clear_field(self, selector):
        self.evaluate(
            "(() => {"
            f"  const el = document.querySelector({json.dumps(selector)});"
            "  if (!el) return false;"
            "  el.value = '';"
            "  el.dispatchEvent(new Event('input', {bubbles: true}));"
            "  return true;"
            "})()")

    KEYMAP = {
        "enter":     ("Enter", "Enter", 13, "\r"),
        "tab":       ("Tab", "Tab", 9, None),
        "escape":    ("Escape", "Escape", 27, None),
        "backspace": ("Backspace", "Backspace", 8, None),
        "delete":    ("Delete", "Delete", 46, None),
        "space":     (" ", "Space", 32, " "),
        "up":        ("ArrowUp", "ArrowUp", 38, None),
        "down":      ("ArrowDown", "ArrowDown", 40, None),
        "left":      ("ArrowLeft", "ArrowLeft", 37, None),
        "right":     ("ArrowRight", "ArrowRight", 39, None),
        "pageup":    ("PageUp", "PageUp", 33, None),
        "pagedown":  ("PageDown", "PageDown", 34, None),
        "home":      ("Home", "Home", 36, None),
        "end":       ("End", "End", 35, None),
    }

    def press_key(self, key):
        k = key.lower()
        if k in self.KEYMAP:
            key_name, code, vk, text = self.KEYMAP[k]
            down = {"type": "rawKeyDown", "key": key_name, "code": code,
                    "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk}
            self.send("Input.dispatchKeyEvent", down)
            if text:
                self.send("Input.dispatchKeyEvent", {"type": "char", "text": text})
            self.send("Input.dispatchKeyEvent", {
                "type": "keyUp", "key": key_name, "code": code,
                "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk})
        elif len(key) == 1:
            self.send("Input.insertText", {"text": key})
        else:
            raise CDPError(f"touche inconnue: {key}")

    # ─── Forms ────────────────────────────────────────────────────────

    def select_option(self, selector, value):
        ok = self.evaluate(
            "(() => {"
            f"  const el = document.querySelector({json.dumps(selector)});"
            "  if (!el) return false;"
            f"  const v = {json.dumps(value)};"
            "  let opt = [...el.options].find(o => o.value === v)"
            "    || [...el.options].find(o => o.textContent.trim() === v);"
            "  if (!opt) return false;"
            "  el.value = opt.value;"
            "  el.dispatchEvent(new Event('input', {bubbles: true}));"
            "  el.dispatchEvent(new Event('change', {bubbles: true}));"
            "  return true;"
            "})()")
        if not ok:
            raise CDPError(f"option non trouvee: {value}")

    def _set_checked(self, selector, desired):
        ok = self.evaluate(
            "(() => {"
            f"  const el = document.querySelector({json.dumps(selector)});"
            "  if (!el) return false;"
            f"  if (el.checked !== {json.dumps(desired)}) el.click();"
            "  return true;"
            "})()")
        if not ok:
            raise CDPError(f"element non trouve: {selector}")

    def check(self, selector):
        self._set_checked(selector, True)

    def uncheck(self, selector):
        self._set_checked(selector, False)

    def submit_form(self):
        self.evaluate("document.activeElement?.form?.submit()")
        time.sleep(1)

    # ─── Scroll ───────────────────────────────────────────────────────

    def scroll(self, direction):
        js = {
            "down": "window.scrollBy(0, 500)",
            "up": "window.scrollBy(0, -500)",
            "bottom": "window.scrollTo(0, document.body.scrollHeight)",
            "top": "window.scrollTo(0, 0)",
        }.get(direction)
        if not js:
            raise CDPError(f"direction inconnue: {direction}")
        self.evaluate(js)

    def scroll_to(self, selector):
        ok = self.evaluate(
            f"(() => {{ const el = document.querySelector({json.dumps(selector)});"
            "  if (!el) return false;"
            "  el.scrollIntoView({block: 'center'}); return true; })()")
        if not ok:
            raise CDPError(f"element non trouve: {selector}")

    # ─── Wait / Poll (bounded, inside the tool) ───────────────────────

    def wait(self, seconds):
        time.sleep(float(seconds))

    def _wait_js(self, js_condition, timeout, label):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.evaluate(js_condition):
                return True
            time.sleep(0.5)
        raise CDPError(f"timeout: {label}")

    def wait_element(self, selector, timeout=30):
        return self._wait_js(
            f"!!document.querySelector({json.dumps(selector)})",
            timeout, f"wait-element {selector}")

    def wait_hidden(self, selector, timeout=30):
        return self._wait_js(
            "(() => {"
            f"  const el = document.querySelector({json.dumps(selector)});"
            "  return !el || el.getClientRects().length === 0; })()",
            timeout, f"wait-hidden {selector}")

    def wait_text(self, text, timeout=30):
        return self._wait_js(
            f"document.body.innerText.includes({json.dumps(text)})",
            timeout, f"wait-text {text}")

    # ─── Screenshot / PDF ─────────────────────────────────────────────

    @staticmethod
    def _resize_png(png_data, max_dim):
        if not (PIL_AVAILABLE and max_dim):
            return png_data
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
                return buf.getvalue()
        except Exception as e:
            print(f"⚠️  Resize failed: {e}", file=sys.stderr)
        return png_data

    def screenshot(self, full_page=False, max_dim=None):
        if max_dim is None:
            max_dim = MAX_IMAGE_DIM
        params = {"format": "png"}
        if full_page:
            params["captureBeyondViewport"] = True
        res = self.send("Page.captureScreenshot", params, timeout=60)
        png_data = base64.b64decode(res.get("data", ""))
        return self._resize_png(png_data, max_dim)

    def pdf(self):
        res = self.send("Page.printToPDF", {}, timeout=60)
        return base64.b64decode(res.get("data", ""))

    # ─── Images ───────────────────────────────────────────────────────

    def get_images(self):
        return self.evaluate("""
            (() => {
              const out = [];
              document.querySelectorAll('img[src]').forEach(el => out.push({
                type: 'img', src: el.src,
                width: el.naturalWidth || el.clientWidth,
                height: el.naturalHeight || el.clientHeight}));
              document.querySelectorAll('picture source[srcset]').forEach(el => out.push({
                type: 'picture', src: el.srcset.split(' ')[0],
                width: 0, height: 0}));
              document.querySelectorAll('canvas').forEach(el => {
                try { out.push({type: 'canvas', src: el.toDataURL('image/png'),
                                width: el.width, height: el.height}); } catch (e) {}});
              document.querySelectorAll('svg').forEach(el => {
                try {
                  const s = new XMLSerializer().serializeToString(el);
                  out.push({type: 'svg',
                    src: 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(s))),
                    width: el.clientWidth, height: el.clientHeight});
                } catch (e) {}});
              [...document.querySelectorAll('*')].forEach(el => {
                const bg = getComputedStyle(el).backgroundImage;
                const m = bg && bg.match(/url\\("?([^")]+)"?\\)/);
                if (m && m[1].startsWith('http')) out.push({
                  type: 'background', src: m[1],
                  width: el.clientWidth, height: el.clientHeight});
              });
              return out;
            })()
        """) or []

    def get_element_as_image(self, selector, max_dim=None):
        if max_dim is None:
            max_dim = MAX_IMAGE_DIM
        rect = self.evaluate(
            "(() => {"
            f"  const el = document.querySelector({json.dumps(selector)});"
            "  if (!el) return null;"
            "  el.scrollIntoView({block: 'center'});"
            "  const r = el.getBoundingClientRect();"
            "  return {x: r.left + window.scrollX, y: r.top + window.scrollY,"
            "          width: r.width, height: r.height};"
            "})()")
        if not rect or not rect.get("width") or not rect.get("height"):
            return None
        res = self.send("Page.captureScreenshot", {
            "format": "png",
            "captureBeyondViewport": True,
            "clip": {"x": rect["x"], "y": rect["y"],
                     "width": rect["width"], "height": rect["height"], "scale": 1},
        }, timeout=60)
        png_data = base64.b64decode(res.get("data", ""))
        return self._resize_png(png_data, max_dim)

    # ─── Event capture (console / network) ────────────────────────────

    def capture_console(self, duration):
        self.send("Runtime.enable")
        self.send("Log.enable")
        self.collect_cdp_events(duration)
        out = []
        for ev in self.events:
            m = ev.get("method")
            p = ev.get("params", {})
            if m == "Runtime.consoleAPICalled":
                out.append({
                    "kind": "console", "level": p.get("type"),
                    "text": " ".join(
                        str(a.get("value", a.get("description", "")))
                        for a in p.get("args", [])),
                    "ts": p.get("timestamp"),
                })
            elif m == "Runtime.exceptionThrown":
                d = p.get("exceptionDetails", {})
                out.append({
                    "kind": "exception",
                    "text": (d.get("exception", {}) or {}).get("description")
                            or d.get("text", ""),
                    "url": d.get("url"), "line": d.get("lineNumber"),
                    "ts": p.get("timestamp"),
                })
            elif m == "Log.entryAdded":
                e = p.get("entry", {})
                out.append({
                    "kind": "log", "level": e.get("level"),
                    "source": e.get("source"), "text": e.get("text"),
                    "url": e.get("url"), "ts": e.get("timestamp"),
                })
        return out

    def capture_network(self, duration):
        self.send("Network.enable")
        self.collect_cdp_events(duration)
        out = []
        for ev in self.events:
            m = ev.get("method")
            p = ev.get("params", {})
            if m == "Network.requestWillBeSent":
                req = p.get("request", {})
                out.append({"kind": "request", "method": req.get("method"),
                            "url": req.get("url"), "id": p.get("requestId")})
            elif m == "Network.responseReceived":
                resp = p.get("response", {})
                out.append({"kind": "response", "status": resp.get("status"),
                            "url": resp.get("url"),
                            "mimeType": resp.get("mimeType"), "id": p.get("requestId")})
            elif m == "Network.loadingFailed":
                out.append({"kind": "failed", "error": p.get("errorText"),
                            "id": p.get("requestId")})
        return out


# =============================================================================
# CDP CONNECTION FACTORY (compatible with chrome-bridge.py)
# =============================================================================

def get_cdp(agent_id=None):
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
        print(f"  → Utiliser: cdp-direct.py tab <url>", file=sys.stderr)
        sys.exit(EXIT_ERROR)

    return CDP(tab_id).connect(), agent_id


# =============================================================================
# MAIN COMMAND DISPATCHER
# Identical CLI to chrome-bridge.py (+ console / network, additive).
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
            info = http_json("/json/version")
            tabs = get_tabs()
            pages = [t for t in tabs if t.get("type") == "page"]
            print(f"✓ Chrome CDP direct actif sur port {CDP_PORT}")
            print(f"  Navigateur: {info.get('Browser', '?')}")
            print(f"  Protocole: {info.get('Protocol-Version', '?')}")
            print(f"  Targets: {len(tabs)} (pages: {len(pages)})")
        else:
            print(f"✗ Chrome CDP non actif sur port {CDP_PORT}")
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
            for t in get_tabs():
                if t.get("type") == "page":
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
                except Exception:
                    print(f"⚠ Target zombie, création nouveau tab...", file=sys.stderr)
                    cleanup_stale_target(agent_id)
                    existing = None
            else:
                cleanup_stale_target(agent_id)
                existing = None

        if not existing:
            tab_id, ctx_id = create_tab(url)
            if tab_id:
                set_agent_tab(agent_id, tab_id)
                if ctx_id:
                    set_agent_ctx(agent_id, ctx_id)
                # Stable viewport for headless layouts + wait initial load
                try:
                    cdp = CDP(tab_id).connect()
                    cdp.send("Emulation.setDeviceMetricsOverride", {
                        "width": VIEWPORT[0], "height": VIEWPORT[1],
                        "deviceScaleFactor": 1, "mobile": False})
                    if cdp.evaluate("document.readyState") != "complete":
                        cdp.send("Page.enable")
                        cdp.wait_cdp_event("Page.loadEventFired", timeout=15)
                    cdp.close()
                except Exception:
                    pass
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
        ctx_id = get_agent_ctx(agent_id)
        if ctx_id:
            _dispose_context(ctx_id)
            del_agent_ctx(agent_id)
        print(f"✓ Onglet fermé pour agent {agent_id} (contexte isolé libéré)")

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
        out = _safe_output_path(args[0])
        cdp, _ = get_cdp()
        html = cdp.get_html()
        cdp.close()
        with open(out, 'w', encoding='utf-8') as f:
            f.write(html or "")
        print(f"✓ HTML → {out}")

    elif cmd == "read-text":
        if not args:
            print("Usage: read-text <fichier>", file=sys.stderr)
            sys.exit(1)
        out = _safe_output_path(args[0])
        cdp, _ = get_cdp()
        text = cdp.get_text()
        cdp.close()
        with open(out, 'w', encoding='utf-8') as f:
            f.write(text or "")
        print(f"✓ Text → {out}")

    elif cmd == "read-element":
        if len(args) < 2:
            print("Usage: read-element <selector> <fichier>", file=sys.stderr)
            sys.exit(1)
        out = _safe_output_path(args[1])
        cdp, _ = get_cdp()
        html = cdp.get_element_html(args[0])
        cdp.close()
        if html:
            with open(out, 'w', encoding='utf-8') as f:
                f.write(html)
            print(f"✓ Element → {out}")
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
        out = _safe_output_path(args[0])
        cdp, _ = get_cdp()
        data = cdp.screenshot(full_page=False)
        cdp.close()
        with open(out, 'wb') as f:
            f.write(data)
        print(f"✓ Screenshot → {out}")

    elif cmd == "screenshot-full":
        if not args:
            print("Usage: screenshot-full <fichier.png>", file=sys.stderr)
            sys.exit(1)
        out = _safe_output_path(args[0])
        cdp, _ = get_cdp()
        data = cdp.screenshot(full_page=True)
        cdp.close()
        with open(out, 'wb') as f:
            f.write(data)
        print(f"✓ Screenshot full → {out}")

    elif cmd == "pdf":
        if not args:
            print("Usage: pdf <fichier.pdf>", file=sys.stderr)
            sys.exit(1)
        out = _safe_output_path(args[0])
        cdp, _ = get_cdp()
        data = cdp.pdf()
        cdp.close()
        with open(out, 'wb') as f:
            f.write(data)
        print(f"✓ PDF → {out}")

    # =====================================================================
    # IMAGES
    # =====================================================================

    elif cmd == "read-images":
        cdp, _ = get_cdp()
        images = cdp.get_images()
        cdp.close()
        if args:
            out = _safe_output_path(args[0])
            with open(out, 'w') as f:
                json.dump(images, f, indent=2, ensure_ascii=False)
            print(f"✓ {len(images)} images → {out}")
        else:
            print(json.dumps(images, indent=2, ensure_ascii=False))

    elif cmd == "capture-element":
        if len(args) < 2:
            print("Usage: capture-element <selector> <fichier.png>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        out = _safe_output_path(args[1])
        data = cdp.get_element_as_image(args[0])
        cdp.close()
        if data:
            with open(out, 'wb') as f:
                f.write(data)
            print(f"✓ Element {args[0]} → {out}")
        else:
            print(f"✗ Element non trouvé: {args[0]}", file=sys.stderr)
            sys.exit(1)

    elif cmd == "download-images":
        if not args:
            print("Usage: download-images <dossier>", file=sys.stderr)
            sys.exit(1)
        dossier = _safe_output_path(args[0])
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
                    if not _is_safe_url(src):
                        print(f"  ⚠ Skip (blocked URL): {src[:50]}...", file=sys.stderr)
                        continue
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
    # EVENT CAPTURE (additive — live-walk proof: console + network)
    # =====================================================================

    elif cmd == "console":
        seconds = float(args[0]) if args else 10
        cdp, _ = get_cdp()
        entries = cdp.capture_console(seconds)
        cdp.close()
        payload = "\n".join(json.dumps(e, ensure_ascii=False) for e in entries)
        if len(args) > 1:
            out = _safe_output_path(args[1])
            with open(out, 'w', encoding='utf-8') as f:
                f.write(payload + ("\n" if payload else ""))
            print(f"✓ {len(entries)} entrées console → {out}")
        else:
            print(payload if payload else "(aucune entrée console)")

    elif cmd == "network":
        seconds = float(args[0]) if args else 10
        cdp, _ = get_cdp()
        entries = cdp.capture_network(seconds)
        cdp.close()
        payload = "\n".join(json.dumps(e, ensure_ascii=False) for e in entries)
        if len(args) > 1:
            out = _safe_output_path(args[1])
            with open(out, 'w', encoding='utf-8') as f:
                f.write(payload + ("\n" if payload else ""))
            print(f"✓ {len(entries)} événements réseau → {out}")
        else:
            print(payload if payload else "(aucun événement réseau)")

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
        print("  screenshot, screenshot-full, pdf, read-images, capture-element, download-images,")
        print("  console, network")
        sys.exit(1)


if __name__ == "__main__":
    main()
