#!/usr/bin/env python3
"""
Chrome Shared - UN SEUL Chrome pour tous les agents
CDP (Chrome DevTools Protocol) via WebSocket

Usage:
    python3 chrome-shared.py <commande> [args...]

Navigation:
    tab <url>                  Créer onglet + naviguer
    goto <url>                 Naviguer (onglet existant)
    reload                     Rafraîchir
    back                       Page précédente
    forward                    Page suivante
    url                        Afficher URL actuelle
    title                      Afficher titre

Lecture:
    read <fichier>             HTML complet → fichier
    read-text <fichier>        Texte seul → fichier
    read-element <sel> <fic>   HTML d'un élément → fichier
    read-attr <sel> <attr>     Valeur d'un attribut
    read-links                 Lister tous les liens
    eval <expression>          Exécuter JS, retourner résultat

Clics:
    click <selector>           Clic par sélecteur CSS
    click-text <texte>         Clic par texte visible
    dblclick <selector>        Double-clic
    hover <selector>           Survol (hover)

Saisie:
    type <selector> <texte>    Taper dans un champ
    clear <selector>           Vider un champ
    press <key>                Touche (enter, tab, escape, etc.)

Formulaires:
    fill <selector> <valeur>   Alias de type
    select <selector> <val>    Sélectionner dans dropdown
    check <selector>           Cocher checkbox
    uncheck <selector>         Décocher
    submit                     Soumettre formulaire actif

Scroll:
    scroll <direction>         down, up, bottom, top
    scroll-to <selector>       Scroll vers élément

Attente:
    wait <secondes>            Attendre N secondes
    wait-element <selector>    Attendre élément visible
    wait-hidden <selector>     Attendre élément disparu
    wait-text <texte>          Attendre texte présent

Captures:
    screenshot <fichier>       Screenshot viewport
    screenshot-full <fichier>  Screenshot page entière
    pdf <fichier>              Export PDF

Images:
    read-images                Liste toutes les images (JSON stdout)
    read-images <fichier>      Sauvegarde liste images en JSON
    capture-element <sel> <f>  Capture un élément en PNG
    download-images <dossier>  Télécharge toutes les images

Gestion onglets:
    get                        Récupérer mon tabId
    close                      Fermer mon onglet
    list                       Lister tous les mappings
    status                     Statut Chrome

Sécurité:
- JAMAIS fermer le dernier tab
- JAMAIS arrêter Chrome
- JAMAIS relancer Chrome automatiquement
- JAMAIS utiliser Playwright ou MCP

Codes de sortie:
    0   = Succès
    1   = Erreur générique
    100 = CRITIQUE: Chrome pas lancé (NE PAS relancer auto!)
    101 = Target obsolète (auto-cleanup effectué)
    102 = WebSocket timeout (retry possible)
"""

import subprocess
import sys
import time
import json
import urllib.request
import urllib.parse
import os
import base64

try:
    import redis
except ImportError:
    redis = None

try:
    import websocket
except ImportError:
    websocket = None
    print("⚠️  pip install websocket-client", file=sys.stderr)

try:
    from PIL import Image
    import io
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# Max image dimension for Claude API multi-image requests
MAX_IMAGE_DIM = 1800

CHROME_PORT = 9222
CHROME_USER_DATA = os.path.expanduser("~/.chrome-multi-agent")
REDIS_PREFIX = "ma:chrome:tab:"
BASE = "/Users/claude/multi-agent"

# Connexion Redis
r = None
if redis:
    try:
        r = redis.Redis(host='localhost', port=6379, decode_responses=True)
        r.ping()
    except:
        r = None


def get_my_agent_id():
    """Détecte agent_id depuis tmux ou env."""
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


def get_agent_tab(agent_id):
    """Récupère tab_id depuis Redis."""
    if r:
        return r.get(f"{REDIS_PREFIX}{agent_id}")
    return None


def set_agent_tab(agent_id, tab_id):
    """Stocke tab_id dans Redis."""
    if r:
        r.set(f"{REDIS_PREFIX}{agent_id}", tab_id)
        return True
    return False


def del_agent_tab(agent_id):
    """Supprime mapping Redis."""
    if r:
        r.delete(f"{REDIS_PREFIX}{agent_id}")


def get_tabs():
    """Liste tous les onglets."""
    try:
        url = f"http://127.0.0.1:{CHROME_PORT}/json"
        with urllib.request.urlopen(url, timeout=2) as response:
            return json.loads(response.read().decode())
    except:
        return []


def count_page_tabs():
    """Compte les tabs de type 'page'."""
    return len([t for t in get_tabs() if t.get("type") == "page"])


# ========== Sécurité Chrome ==========

# Codes de sortie
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CHROME_NOT_RUNNING = 100  # CRITIQUE: Chrome absent
EXIT_TARGET_STALE = 101        # Récupérable: target obsolète
EXIT_WEBSOCKET_FAILED = 102    # Récupérable: WebSocket timeout


def check_chrome_running(port=CHROME_PORT):
    """
    Vérifie si Chrome écoute sur le port CDP.
    Retourne True si Chrome est actif, False sinon.
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
    Vérifie si un target_id existe encore dans Chrome.
    Retourne True si le target existe, False sinon.
    """
    try:
        tabs = get_tabs()
        return any(t.get('id') == target_id for t in tabs)
    except:
        return False


def cleanup_stale_target(agent_id):
    """
    Supprime un mapping Redis obsolète.
    """
    if r:
        old_target = r.get(f"{REDIS_PREFIX}{agent_id}")
        if old_target:
            r.delete(f"{REDIS_PREFIX}{agent_id}")
            print(f"⚠ Target {old_target[:8]}... obsolète, mapping supprimé", file=sys.stderr)


def require_chrome_running():
    """
    Vérifie que Chrome tourne. Si non, affiche erreur et exit(100).
    JAMAIS relancer Chrome automatiquement.
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


def create_tab(target_url="about:blank"):
    """Crée un nouvel onglet."""
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
    """Ferme un onglet."""
    try:
        url = f"http://127.0.0.1:{CHROME_PORT}/json/close/{tab_id}"
        urllib.request.urlopen(url, timeout=5)
        return True
    except:
        return False


# ========== CDP WebSocket ==========

class CDP:
    """Client CDP synchrone."""

    def __init__(self, tab_id):
        self.tab_id = tab_id
        self.ws = None
        self.msg_id = 0

    def connect(self):
        """Connexion WebSocket."""
        if not websocket:
            raise Exception("pip install websocket-client")
        ws_url = f"ws://127.0.0.1:{CHROME_PORT}/devtools/page/{self.tab_id}"
        self.ws = websocket.create_connection(ws_url, timeout=30)
        return self

    def close(self):
        """Ferme la connexion."""
        if self.ws:
            self.ws.close()

    def send(self, method, params=None, timeout=30):
        """Envoie commande CDP et attend réponse."""
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
        """Exécute JS et retourne le résultat."""
        result = self.send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True
        })
        return result.get("result", {}).get("value")

    # === Navigation ===

    def navigate(self, url):
        """Navigue vers URL."""
        self.send("Page.enable")
        self.send("Page.navigate", {"url": url})
        time.sleep(2)  # Attendre chargement basique

    def reload(self):
        """Rafraîchit la page."""
        self.send("Page.reload")
        time.sleep(2)

    def go_back(self):
        """Page précédente."""
        self.evaluate("history.back()")
        time.sleep(1)

    def go_forward(self):
        """Page suivante."""
        self.evaluate("history.forward()")
        time.sleep(1)

    def get_url(self):
        """Retourne l'URL actuelle."""
        return self.evaluate("window.location.href")

    def get_title(self):
        """Retourne le titre."""
        return self.evaluate("document.title")

    # === Lecture ===

    def get_html(self):
        """Retourne le HTML complet."""
        return self.evaluate("document.documentElement.outerHTML")

    def get_text(self):
        """Retourne le texte."""
        return self.evaluate("document.body.innerText")

    def get_element_html(self, selector):
        """Retourne le HTML d'un élément."""
        return self.evaluate(f"document.querySelector('{selector}')?.outerHTML || ''")

    def get_attribute(self, selector, attr):
        """Retourne la valeur d'un attribut."""
        return self.evaluate(f"document.querySelector('{selector}')?.getAttribute('{attr}')")

    def get_links(self):
        """Retourne tous les liens."""
        return self.evaluate("[...document.querySelectorAll('a[href]')].map(a => a.href)")

    # === Clics ===

    def click(self, selector):
        """Clic sur élément par CSS selector."""
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

        self._mouse_click(coords["x"], coords["y"])

    def click_text(self, text, tag="*"):
        """Clic sur élément par texte."""
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
        """Double-clic."""
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

        self._mouse_click(coords["x"], coords["y"], click_count=2)

    def hover(self, selector):
        """Survol d'un élément."""
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

        self.send("Input.dispatchMouseEvent", {
            "type": "mouseMoved", "x": coords["x"], "y": coords["y"]
        })

    def _mouse_click(self, x, y, click_count=1):
        """Effectue un clic souris."""
        self.send("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": x, "y": y,
            "button": "left", "clickCount": click_count
        })
        self.send("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": x, "y": y,
            "button": "left", "clickCount": click_count
        })
        time.sleep(0.5)

    # === Saisie ===

    def type_text(self, selector, text, clear=True):
        """Tape du texte dans un champ."""
        self.evaluate(f"document.querySelector('{selector}')?.focus()")
        time.sleep(0.1)

        if clear:
            self.evaluate(f"document.querySelector('{selector}').value = ''")

        self.send("Input.insertText", {"text": text})
        time.sleep(0.1)

    def clear_field(self, selector):
        """Vide un champ."""
        self.evaluate(f"document.querySelector('{selector}').value = ''")

    def press_key(self, key):
        """Appuie sur une touche."""
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
            key_name = key
            code = key
            keycode = ord(key[0].upper()) if len(key) == 1 else 0

        self.send("Input.dispatchKeyEvent", {
            "type": "keyDown", "key": key_name, "code": code,
            "windowsVirtualKeyCode": keycode, "nativeVirtualKeyCode": keycode
        })
        self.send("Input.dispatchKeyEvent", {
            "type": "keyUp", "key": key_name, "code": code,
            "windowsVirtualKeyCode": keycode, "nativeVirtualKeyCode": keycode
        })
        time.sleep(0.2)

    # === Formulaires ===

    def select_option(self, selector, value):
        """Sélectionne une option dans un dropdown."""
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
        """Coche une checkbox."""
        self.evaluate(f"""
            const el = document.querySelector('{selector}');
            if (el && !el.checked) el.click();
        """)

    def uncheck(self, selector):
        """Décoche une checkbox."""
        self.evaluate(f"""
            const el = document.querySelector('{selector}');
            if (el && el.checked) el.click();
        """)

    def submit_form(self):
        """Soumet le formulaire actif."""
        self.evaluate("document.activeElement?.form?.submit()")
        time.sleep(1)

    # === Scroll ===

    def scroll(self, direction):
        """Scroll dans une direction."""
        if direction == "down":
            self.evaluate("window.scrollBy(0, 500)")
        elif direction == "up":
            self.evaluate("window.scrollBy(0, -500)")
        elif direction == "bottom":
            self.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        elif direction == "top":
            self.evaluate("window.scrollTo(0, 0)")
        time.sleep(0.3)

    def scroll_to(self, selector):
        """Scroll vers un élément."""
        self.evaluate(f"document.querySelector('{selector}')?.scrollIntoView({{block: 'center'}})")
        time.sleep(0.3)

    # === Attente ===

    def wait(self, seconds):
        """Attend N secondes."""
        time.sleep(float(seconds))

    def wait_element(self, selector, timeout=30):
        """Attend qu'un élément soit visible."""
        start = time.time()
        while time.time() - start < timeout:
            if self.evaluate(f"!!document.querySelector('{selector}')"):
                return True
            time.sleep(0.5)
        raise Exception(f"Timeout waiting for: {selector}")

    def wait_hidden(self, selector, timeout=30):
        """Attend qu'un élément disparaisse."""
        start = time.time()
        while time.time() - start < timeout:
            if not self.evaluate(f"!!document.querySelector('{selector}')"):
                return True
            time.sleep(0.5)
        raise Exception(f"Timeout waiting for hidden: {selector}")

    def wait_text(self, text, timeout=30):
        """Attend qu'un texte soit présent."""
        text_escaped = text.replace("'", "\\'")
        start = time.time()
        while time.time() - start < timeout:
            if self.evaluate(f"document.body.innerText.includes('{text_escaped}')"):
                return True
            time.sleep(0.5)
        raise Exception(f"Timeout waiting for text: {text}")

    # === Captures ===

    def screenshot(self, full_page=False, max_dim=None):
        """Capture d'écran, retourne bytes PNG. Redimensionne si > max_dim."""
        if max_dim is None:
            max_dim = MAX_IMAGE_DIM

        params = {"format": "png"}
        if full_page:
            params["captureBeyondViewport"] = True
            # Get full page dimensions
            metrics = self.evaluate("""
                ({
                    width: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
                    height: Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)
                })
            """)
            if metrics:
                self.send("Emulation.setDeviceMetricsOverride", {
                    "width": metrics["width"],
                    "height": metrics["height"],
                    "deviceScaleFactor": 1,
                    "mobile": False
                })

        result = self.send("Page.captureScreenshot", params)

        if full_page:
            self.send("Emulation.clearDeviceMetricsOverride")

        png_data = base64.b64decode(result.get("data", ""))

        # Resize if needed and PIL available
        if PIL_AVAILABLE and max_dim:
            try:
                img = Image.open(io.BytesIO(png_data))
                w, h = img.size
                if w > max_dim or h > max_dim:
                    # Calculate new size maintaining aspect ratio
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
        """Export PDF, retourne bytes."""
        result = self.send("Page.printToPDF", {
            "printBackground": True,
            "preferCSSPageSize": True
        })
        return base64.b64decode(result.get("data", ""))

    # === Images ===

    def get_images(self):
        """Extrait toutes les images de la page (statiques et dynamiques)."""
        return self.evaluate("""
            (() => {
                const images = [];

                // 1. Images <img>
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

                // 2. SVG inline
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

                // 3. Canvas
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
                        // Cross-origin canvas, skip
                    }
                });

                // 4. Background images CSS
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

                // 5. Picture/source (responsive)
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

                // Deduplicate by src
                const seen = new Set();
                return images.filter(img => {
                    if (seen.has(img.src)) return false;
                    seen.add(img.src);
                    return true;
                });
            })()
        """) or []

    def get_canvas_as_image(self, selector):
        """Convertit un canvas en data URI PNG."""
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
        """Convertit un SVG en data URI."""
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
        """Capture un élément spécifique en screenshot."""
        if max_dim is None:
            max_dim = MAX_IMAGE_DIM

        # Get element bounds
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

        result = self.send("Page.captureScreenshot", {
            "format": "png",
            "clip": {
                "x": bounds["x"],
                "y": bounds["y"],
                "width": bounds["width"],
                "height": bounds["height"],
                "scale": 1
            }
        })
        png_data = base64.b64decode(result.get("data", ""))

        # Resize if needed and PIL available
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


# ========== Commandes principales ==========

def get_cdp(agent_id=None):
    """
    Crée une connexion CDP pour l'agent.
    Avec vérification de sécurité: Chrome actif + target valide.
    """
    # ÉTAPE 1: Chrome tourne ?
    require_chrome_running()

    if not agent_id:
        agent_id = get_my_agent_id()
    if not agent_id:
        print("Erreur: agent_id non détectable", file=sys.stderr)
        sys.exit(EXIT_ERROR)

    tab_id = get_agent_tab(agent_id)

    # ÉTAPE 2: Target valide ?
    if tab_id and not validate_target(tab_id):
        cleanup_stale_target(agent_id)
        tab_id = None

    if not tab_id:
        print(f"Erreur: pas d'onglet pour agent {agent_id}", file=sys.stderr)
        print(f"  → Utiliser: chrome-shared.py tab <url>", file=sys.stderr)
        sys.exit(EXIT_ERROR)

    # ÉTAPE 3: Connexion WebSocket
    try:
        return CDP(tab_id).connect(), agent_id
    except Exception as e:
        # WebSocket failed - target peut être zombie
        print(f"⚠ WebSocket failed: {e}", file=sys.stderr)
        cleanup_stale_target(agent_id)
        print(f"  → Réessayer: chrome-shared.py tab <url>", file=sys.stderr)
        sys.exit(EXIT_WEBSOCKET_FAILED)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1].lower()
    args = sys.argv[2:]

    # === Gestion onglets (pas besoin de CDP) ===

    if cmd == "status":
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
            print("Redis non disponible")

    elif cmd == "tab":
        # SÉCURITÉ: Vérifier Chrome AVANT toute action
        require_chrome_running()

        # Créer onglet: tab [agent_id] <url>
        if len(args) >= 2 and not args[0].startswith("http"):
            agent_id, url = args[0], args[1]
        elif len(args) >= 1:
            agent_id, url = get_my_agent_id(), args[0]
        else:
            agent_id, url = get_my_agent_id(), "about:blank"

        if not agent_id:
            print("Erreur: agent_id non détectable", file=sys.stderr)
            sys.exit(EXIT_ERROR)

        # Vérifie si onglet existe déjà ET est valide
        existing = get_agent_tab(agent_id)
        if existing:
            if validate_target(existing):
                # Onglet existe et valide, naviguer
                try:
                    cdp = CDP(existing).connect()
                    cdp.navigate(url)
                    cdp.close()
                    print(existing)
                except Exception as e:
                    # WebSocket failed, cleanup et créer nouveau
                    print(f"⚠ Target zombie, création nouveau tab...", file=sys.stderr)
                    cleanup_stale_target(agent_id)
                    existing = None
            else:
                # Target obsolète, cleanup
                cleanup_stale_target(agent_id)
                existing = None

        if not existing:
            # Créer nouvel onglet
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

        # Vérifier si target valide avant de fermer
        if not validate_target(tab_id):
            cleanup_stale_target(agent_id)
            print(f"⚠ Target déjà fermé, mapping nettoyé")
            sys.exit(EXIT_OK)

        if count_page_tabs() <= 1:
            print("⚠️  REFUSÉ: Impossible de fermer le dernier tab", file=sys.stderr)
            sys.exit(EXIT_ERROR)

        if close_tab_by_id(tab_id):
            del_agent_tab(agent_id)
            print(f"✓ Onglet fermé")
        else:
            sys.exit(EXIT_ERROR)

    # === Navigation ===

    elif cmd == "goto":
        if not args:
            print("Usage: goto <url>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.navigate(args[0])
        cdp.close()
        print(f"✓ Navigué vers {args[0]}")

    elif cmd == "reload":
        cdp, _ = get_cdp()
        cdp.reload()
        cdp.close()
        print("✓ Page rafraîchie")

    elif cmd == "back":
        cdp, _ = get_cdp()
        cdp.go_back()
        cdp.close()
        print("✓ Page précédente")

    elif cmd == "forward":
        cdp, _ = get_cdp()
        cdp.go_forward()
        cdp.close()
        print("✓ Page suivante")

    elif cmd == "url":
        cdp, _ = get_cdp()
        print(cdp.get_url())
        cdp.close()

    elif cmd == "title":
        cdp, _ = get_cdp()
        print(cdp.get_title())
        cdp.close()

    # === Lecture ===

    elif cmd == "read":
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
        if len(args) < 2:
            print("Usage: read-attr <selector> <attribut>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        val = cdp.get_attribute(args[0], args[1])
        cdp.close()
        print(val or "")

    elif cmd == "read-links":
        cdp, _ = get_cdp()
        links = cdp.get_links()
        cdp.close()
        for link in (links or []):
            print(link)

    elif cmd == "eval":
        if not args:
            print("Usage: eval <expression>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        result = cdp.evaluate(" ".join(args))
        cdp.close()
        print(json.dumps(result) if isinstance(result, (dict, list)) else result)

    # === Clics ===

    elif cmd == "click":
        if not args:
            print("Usage: click <selector>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.click(args[0])
        cdp.close()
        print(f"✓ Cliqué sur {args[0]}")

    elif cmd == "click-text":
        if not args:
            print("Usage: click-text <texte>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.click_text(" ".join(args))
        cdp.close()
        print(f"✓ Cliqué sur texte '{' '.join(args)}'")

    elif cmd == "dblclick":
        if not args:
            print("Usage: dblclick <selector>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.dblclick(args[0])
        cdp.close()
        print(f"✓ Double-cliqué sur {args[0]}")

    elif cmd == "hover":
        if not args:
            print("Usage: hover <selector>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.hover(args[0])
        cdp.close()
        print(f"✓ Hover sur {args[0]}")

    # === Saisie ===

    elif cmd in ("type", "fill"):
        if len(args) < 2:
            print(f"Usage: {cmd} <selector> <texte>", file=sys.stderr)
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
        print(f"✓ Champ vidé")

    elif cmd == "press":
        if not args:
            print("Usage: press <key>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.press_key(args[0])
        cdp.close()
        print(f"✓ Touche {args[0]}")

    # === Formulaires ===

    elif cmd == "select":
        if len(args) < 2:
            print("Usage: select <selector> <valeur>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.select_option(args[0], args[1])
        cdp.close()
        print(f"✓ Sélectionné {args[1]}")

    elif cmd == "check":
        if not args:
            print("Usage: check <selector>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.check(args[0])
        cdp.close()
        print("✓ Coché")

    elif cmd == "uncheck":
        if not args:
            print("Usage: uncheck <selector>", file=sys.stderr)
            sys.exit(1)
        cdp, _ = get_cdp()
        cdp.uncheck(args[0])
        cdp.close()
        print("✓ Décoché")

    elif cmd == "submit":
        cdp, _ = get_cdp()
        cdp.submit_form()
        cdp.close()
        print("✓ Formulaire soumis")

    # === Scroll ===

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

    # === Attente ===

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

    # === Captures ===

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

    # === Images ===

    elif cmd == "read-images":
        cdp, _ = get_cdp()
        images = cdp.get_images()
        cdp.close()
        if args:
            # Sauvegarder en fichier
            with open(args[0], 'w') as f:
                json.dump(images, f, indent=2, ensure_ascii=False)
            print(f"✓ {len(images)} images → {args[0]}")
        else:
            # Afficher en JSON
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
        # urllib.request déjà importé en haut du fichier

        dossier = args[0]
        os.makedirs(dossier, exist_ok=True)

        cdp, _ = get_cdp()
        images = cdp.get_images()
        cdp.close()

        downloaded = 0
        for i, img in enumerate(images):
            src = img.get('src', '')
            img_type = img.get('type', 'img')

            try:
                if src.startswith('data:'):
                    # Data URI - decode base64
                    header, b64data = src.split(',', 1)
                    ext = 'png' if 'png' in header else 'svg' if 'svg' in header else 'jpg'
                    data = base64.b64decode(b64data)
                    filename = f"{img_type}_{i:03d}.{ext}"
                    with open(os.path.join(dossier, filename), 'wb') as f:
                        f.write(data)
                    downloaded += 1
                elif src.startswith('http'):
                    # URL - download
                    ext = src.split('.')[-1].split('?')[0][:4]
                    if ext not in ['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp']:
                        ext = 'png'
                    filename = f"{img_type}_{i:03d}.{ext}"
                    urllib.request.urlretrieve(src, os.path.join(dossier, filename))
                    downloaded += 1
            except Exception as e:
                print(f"  ⚠ Skip: {src[:50]}... ({e})", file=sys.stderr)

        print(f"✓ {downloaded}/{len(images)} images → {dossier}/")

    # === Interdit ===

    elif cmd == "stop":
        print("⛔ INTERDIT: Chrome ne doit JAMAIS être arrêté", file=sys.stderr)
        sys.exit(1)

    else:
        print(f"Commande inconnue: {cmd}", file=sys.stderr)
        print("Voir --help pour la liste des commandes")
        sys.exit(1)


if __name__ == "__main__":
    main()
