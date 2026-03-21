"""
cdp_commands.py — Commandes CDP de haut niveau (navigation, click, screenshot, etc.)
EF-005 — Module 3/4 : Toutes les méthodes d'interaction avec la page

Responsabilités :
  - Navigation : navigate, reload, back, forward, get_url, get_title
  - Lecture : get_html, get_text, get_element_html, get_attribute, get_links
  - Click : click, click_text, dblclick, hover
  - Saisie : type_text, clear_field, press_key
  - Formulaires : select_option, check, uncheck, submit_form
  - Scroll : scroll, scroll_to
  - Attente : wait, wait_element, wait_hidden, wait_text
  - Captures : screenshot, pdf, get_images, get_element_as_image

Réf spec 342 : CT-003 (port 9222 préservé), CT-004 (pas de nouvelle dépendance)
"""

import time
import base64
import sys

try:
    from .cdp_connection import CDP
except ImportError:
    from cdp_connection import CDP

# Optional PIL for screenshot resizing
try:
    from PIL import Image
    import io
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# Max image dimension for Claude API compatibility
MAX_IMAGE_DIM = 1800


class CDPCommands(CDP):
    """
    Extended CDP client with high-level browser interaction commands.

    Inherits connect/close/send/evaluate from CDP base class.
    Adds navigation, clicking, typing, screenshot, and other commands.

    Usage:
        cdp = CDPCommands(tab_id).connect()
        cdp.navigate("https://example.com")
        cdp.click("#button")
        data = cdp.screenshot()
        cdp.close()
    """

    # Timing constants (R-TIMING: configurable, no hardcoded sleep values)
    WAIT_NAVIGATION = 2
    WAIT_HISTORY = 1
    WAIT_SUBMIT = 1
    WAIT_CLICK = 0.5
    WAIT_SCROLL = 0.3
    WAIT_KEY = 0.2
    WAIT_SHORT = 0.1
    WAIT_POLL = 0.5

    @staticmethod
    def _safe_sel(selector):
        """Sanitise un sélecteur CSS pour injection dans JS evaluate() (R-SANIT, R-P1CLOSE)."""
        return selector.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "\\r")

    # =========================================================================
    # NAVIGATION
    # =========================================================================

    def navigate(self, url):
        """Navigate the tab to a new URL (EF-005: cdp_commands)."""
        self.send("Page.enable")
        self.send("Page.navigate", {"url": url})
        time.sleep(self.WAIT_NAVIGATION)

    def reload(self):
        """Reload the current page (EF-005: cdp_commands)."""
        self.send("Page.reload")
        time.sleep(self.WAIT_NAVIGATION)

    def go_back(self):
        """Navigate back in browser history (EF-005: cdp_commands)."""
        self.evaluate("history.back()")
        time.sleep(self.WAIT_HISTORY)

    def go_forward(self):
        """Navigate forward in browser history (EF-005: cdp_commands)."""
        self.evaluate("history.forward()")
        time.sleep(self.WAIT_HISTORY)

    def get_url(self):
        """Get the current page URL (EF-005: cdp_commands)."""
        return self.evaluate("window.location.href")

    def get_title(self):
        """Get the current page title (EF-005: cdp_commands)."""
        return self.evaluate("document.title")

    # =========================================================================
    # PAGE CONTENT READING
    # =========================================================================

    def get_html(self):
        """Get the full HTML source of the page (EF-005: cdp_commands)."""
        return self.evaluate("document.documentElement.outerHTML")

    def get_text(self):
        """Get the visible text content (no HTML tags) (EF-005: cdp_commands)."""
        return self.evaluate("document.body.innerText")

    def get_element_html(self, selector):
        """Get the HTML of a specific element by CSS selector (EF-005: cdp_commands)."""
        safe = self._safe_sel(selector)
        return self.evaluate(f"document.querySelector('{safe}')?.outerHTML || ''")

    def get_attribute(self, selector, attr):
        """Get the value of an attribute on an element (EF-005: cdp_commands)."""
        safe = self._safe_sel(selector)
        safe_attr = self._safe_sel(attr)
        return self.evaluate(
            f"document.querySelector('{safe}')?.getAttribute('{safe_attr}')"
        )

    def get_links(self):
        """Get all hyperlinks on the page (EF-005: cdp_commands)."""
        return self.evaluate(
            "[...document.querySelectorAll('a[href]')].map(a => a.href)"
        )

    # =========================================================================
    # CLICK
    # =========================================================================

    def click(self, selector):
        """Click on an element by CSS selector (EF-005: cdp_commands)."""
        safe = self._safe_sel(selector)
        coords = self.evaluate(f"""
            (() => {{
                const el = document.querySelector('{safe}');
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
        """Click on an element containing specified text (EF-005: cdp_commands)."""
        text_escaped = self._safe_sel(text)
        safe_tag = self._safe_sel(tag)
        coords = self.evaluate(f"""
            (() => {{
                const els = [...document.querySelectorAll('{safe_tag}')];
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
        """Double-click on an element by CSS selector (EF-005: cdp_commands)."""
        safe = self._safe_sel(selector)
        coords = self.evaluate(f"""
            (() => {{
                const el = document.querySelector('{safe}');
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
        """Hover over an element (mouseMoved event) (EF-005: cdp_commands)."""
        safe = self._safe_sel(selector)
        coords = self.evaluate(f"""
            (() => {{
                const el = document.querySelector('{safe}');
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
        """Low-level mouse click: mousePressed + mouseReleased (EF-005: cdp_commands)."""
        self.send("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": x, "y": y,
            "button": "left", "clickCount": click_count
        })
        self.send("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": x, "y": y,
            "button": "left", "clickCount": click_count
        })
        time.sleep(self.WAIT_CLICK)

    # =========================================================================
    # TEXT INPUT
    # =========================================================================

    def type_text(self, selector, text, clear=True):
        """Type text into an input field (EF-005: cdp_commands)."""
        safe = self._safe_sel(selector)
        self.evaluate(f"document.querySelector('{safe}')?.focus()")
        time.sleep(self.WAIT_SHORT)
        if clear:
            self.evaluate(f"document.querySelector('{safe}').value = ''")
        self.send("Input.insertText", {"text": text})
        time.sleep(self.WAIT_SHORT)

    def clear_field(self, selector):
        """Clear an input field (EF-005: cdp_commands)."""
        safe = self._safe_sel(selector)
        self.evaluate(f"document.querySelector('{safe}').value = ''")

    def press_key(self, key):
        """Press a keyboard key (EF-005: cdp_commands)."""
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
        time.sleep(self.WAIT_KEY)

    # =========================================================================
    # FORMS
    # =========================================================================

    def select_option(self, selector, value):
        """Select an option in a <select> dropdown (EF-005: cdp_commands)."""
        safe = self._safe_sel(selector)
        safe_value = self._safe_sel(value)
        self.evaluate(f"""
            (() => {{
                const sel = document.querySelector('{safe}');
                if (!sel) return;
                const opt = [...sel.options].find(
                    o => o.value === '{safe_value}' || o.text === '{safe_value}'
                );
                if (opt) sel.value = opt.value;
                sel.dispatchEvent(new Event('change', {{bubbles: true}}));
            }})()
        """)

    def check(self, selector):
        """Check a checkbox if unchecked (EF-005: cdp_commands)."""
        safe = self._safe_sel(selector)
        self.evaluate(f"""
            const el = document.querySelector('{safe}');
            if (el && !el.checked) el.click();
        """)

    def uncheck(self, selector):
        """Uncheck a checkbox if checked (EF-005: cdp_commands)."""
        safe = self._safe_sel(selector)
        self.evaluate(f"""
            const el = document.querySelector('{safe}');
            if (el && el.checked) el.click();
        """)

    def submit_form(self):
        """Submit the form containing the focused element (EF-005: cdp_commands)."""
        self.evaluate("document.activeElement?.form?.submit()")
        time.sleep(self.WAIT_SUBMIT)

    # =========================================================================
    # SCROLL
    # =========================================================================

    def scroll(self, direction):
        """Scroll page: down, up, bottom, top (EF-005: cdp_commands)."""
        if direction == "down":
            self.evaluate("window.scrollBy(0, 500)")
        elif direction == "up":
            self.evaluate("window.scrollBy(0, -500)")
        elif direction == "bottom":
            self.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        elif direction == "top":
            self.evaluate("window.scrollTo(0, 0)")
        time.sleep(self.WAIT_SCROLL)

    def scroll_to(self, selector):
        """Scroll element into center of viewport (EF-005: cdp_commands)."""
        safe = self._safe_sel(selector)
        self.evaluate(
            f"document.querySelector('{safe}')?.scrollIntoView({{block: 'center'}})"
        )
        time.sleep(self.WAIT_SCROLL)

    # =========================================================================
    # WAIT / POLLING
    # =========================================================================

    def wait(self, seconds):
        """Wait (sleep) for N seconds (EF-005: cdp_commands)."""
        time.sleep(float(seconds))

    def wait_element(self, selector, timeout=30):
        """Wait for element to appear in DOM (EF-005: cdp_commands)."""
        safe = self._safe_sel(selector)
        start = time.time()
        while time.time() - start < timeout:
            if self.evaluate(f"!!document.querySelector('{safe}')"):
                return True
            time.sleep(self.WAIT_POLL)
        raise Exception(f"Timeout waiting for: {selector}")

    def wait_hidden(self, selector, timeout=30):
        """Wait for element to disappear from DOM (EF-005: cdp_commands)."""
        safe = self._safe_sel(selector)
        start = time.time()
        while time.time() - start < timeout:
            if not self.evaluate(f"!!document.querySelector('{safe}')"):
                return True
            time.sleep(self.WAIT_POLL)
        raise Exception(f"Timeout waiting for hidden: {selector}")

    def wait_text(self, text, timeout=30):
        """Wait for text to appear on page (EF-005: cdp_commands)."""
        text_escaped = self._safe_sel(text)
        start = time.time()
        while time.time() - start < timeout:
            if self.evaluate(f"document.body.innerText.includes('{text_escaped}')"):
                return True
            time.sleep(self.WAIT_POLL)
        raise Exception(f"Timeout waiting for text: {text}")

    # =========================================================================
    # SCREENSHOT & PDF
    # =========================================================================

    def screenshot(self, full_page=False, max_dim=None):
        """
        Capture a screenshot. Optionally resized for Claude API compatibility.

        Args:
            full_page: If True, capture entire scrollable page.
            max_dim: Maximum dimension in pixels. None uses MAX_IMAGE_DIM.

        Returns:
            bytes: PNG image data (EF-005: cdp_commands).
        """
        if max_dim is None:
            max_dim = MAX_IMAGE_DIM

        params = {"format": "png"}
        if full_page:
            params["captureBeyondViewport"] = True
            metrics = self.evaluate("""
                ({
                    width: Math.max(
                        document.documentElement.scrollWidth,
                        document.body.scrollWidth
                    ),
                    height: Math.max(
                        document.documentElement.scrollHeight,
                        document.body.scrollHeight
                    )
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
        """Export the current page as PDF (EF-005: cdp_commands)."""
        result = self.send("Page.printToPDF", {
            "printBackground": True,
            "preferCSSPageSize": True
        })
        return base64.b64decode(result.get("data", ""))

    # =========================================================================
    # IMAGE EXTRACTION
    # =========================================================================

    def get_images(self):
        """
        Extract all images from 5 sources: img, svg, canvas, bg, picture.

        Returns:
            list[dict]: Array of image descriptors (EF-005: cdp_commands).
        """
        return self.evaluate("""
            (() => {
                const images = [];
                document.querySelectorAll('img').forEach((img, i) => {
                    if (img.src) {
                        images.push({
                            type: 'img', src: img.src, alt: img.alt || '',
                            width: img.naturalWidth || img.width,
                            height: img.naturalHeight || img.height,
                            selector: img.id ? '#' + img.id : `img:nth-of-type(${i+1})`
                        });
                    }
                });
                document.querySelectorAll('svg').forEach((svg, i) => {
                    const s = new XMLSerializer();
                    const str = s.serializeToString(svg);
                    const uri = 'data:image/svg+xml;base64,' +
                                btoa(unescape(encodeURIComponent(str)));
                    images.push({
                        type: 'svg', src: uri,
                        width: svg.width?.baseVal?.value || svg.viewBox?.baseVal?.width || 0,
                        height: svg.height?.baseVal?.value || svg.viewBox?.baseVal?.height || 0,
                        selector: svg.id ? '#' + svg.id : `svg:nth-of-type(${i+1})`
                    });
                });
                document.querySelectorAll('canvas').forEach((canvas, i) => {
                    try {
                        images.push({
                            type: 'canvas', src: canvas.toDataURL('image/png'),
                            width: canvas.width, height: canvas.height,
                            selector: canvas.id ? '#' + canvas.id : `canvas:nth-of-type(${i+1})`
                        });
                    } catch(e) {}
                });
                document.querySelectorAll('*').forEach((el) => {
                    const bg = getComputedStyle(el).backgroundImage;
                    if (bg && bg !== 'none' && bg.startsWith('url(')) {
                        const m = bg.match(/url\\(["']?(.+?)["']?\\)/);
                        if (m && m[1] && !m[1].startsWith('data:image/svg')) {
                            images.push({
                                type: 'background', src: m[1],
                                selector: el.id ? '#' + el.id :
                                    el.className ? '.' + el.className.split(' ')[0] :
                                    el.tagName.toLowerCase()
                            });
                        }
                    }
                });
                document.querySelectorAll('picture source').forEach((source, i) => {
                    if (source.srcset) {
                        source.srcset.split(',').map(s => s.trim().split(' ')[0])
                            .forEach(src => {
                                images.push({
                                    type: 'picture', src: src,
                                    media: source.media || '',
                                    selector: `picture:nth-of-type(${i+1}) source`
                                });
                            });
                    }
                });
                const seen = new Set();
                return images.filter(img => {
                    if (seen.has(img.src)) return false;
                    seen.add(img.src);
                    return true;
                });
            })()
        """) or []

    def get_element_as_image(self, selector, max_dim=None):
        """
        Capture a specific DOM element as PNG screenshot.

        Args:
            selector: CSS selector for the element.
            max_dim: Maximum dimension in pixels.

        Returns:
            bytes: PNG image data, or None if element not found (EF-005: cdp_commands).
        """
        if max_dim is None:
            max_dim = MAX_IMAGE_DIM

        safe = self._safe_sel(selector)
        bounds = self.evaluate(f"""
            (() => {{
                const el = document.querySelector('{safe}');
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
                "x": bounds["x"], "y": bounds["y"],
                "width": bounds["width"], "height": bounds["height"],
                "scale": 1
            }
        })
        png_data = base64.b64decode(result.get("data", ""))

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
