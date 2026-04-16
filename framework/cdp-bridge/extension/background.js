/**
 * CDP Bridge — Background Service Worker
 * ========================================
 * 
 * This service worker is the core of the CDP Bridge extension.
 * It receives commands from the Native Messaging Host (which receives
 * them from Python scripts via HTTP on port 9222) and executes them
 * using Chrome's extension APIs:
 * 
 *   - chrome.debugger  → CDP commands (navigate, screenshot, click, type, etc.)
 *   - chrome.tabs      → tab management (create, close, list, query)
 *   - chrome.pageCapture → MHTML export
 * 
 * ARCHITECTURE:
 *   Python (HTTP) → Native Host (stdin/stdout) → This Service Worker → Chrome
 * 
 * The native messaging port keeps this service worker alive indefinitely.
 * If the port disconnects, we reconnect on the next alarm tick (every 25s).
 * 
 * DEBUGGER MANAGEMENT:
 *   chrome.debugger.attach() shows a yellow banner in Chrome but does NOT
 *   trigger Google's automation detection (unlike --remote-debugging-port).
 *   We keep the debugger attached per-tab to avoid attach/detach overhead.
 *   The banner reads: "CDP Bridge is debugging this browser" — harmless.
 */

// =============================================================================
// CONSTANTS
// =============================================================================

const NATIVE_HOST_NAME = "com.cdpbridge.host";
const CDP_VERSION = "1.3";
const KEEPALIVE_INTERVAL_MS = 25000; // 25 seconds — keep service worker alive

// =============================================================================
// STATE
// =============================================================================

/** @type {chrome.runtime.Port|null} Native messaging port to the Node.js host */
let nativePort = null;

/** @type {Set<number>} Set of tab IDs that have the debugger attached */
const attachedTabs = new Set();

/** @type {boolean} Whether we're currently trying to connect */
let connecting = false;

// =============================================================================
// NATIVE MESSAGING — CONNECTION LIFECYCLE
// =============================================================================

/**
 * Connect to the Native Messaging Host.
 * 
 * Chrome will spawn the Node.js process as a child, piping stdin/stdout.
 * The Node.js process also starts an HTTP server on port 9222.
 * 
 * As long as this port is open, the service worker stays alive.
 */
function connectNativeHost() {
  if (nativePort || connecting) return;
  connecting = true;

  try {
    nativePort = chrome.runtime.connectNative(NATIVE_HOST_NAME);
    connecting = false;
    console.log("[CDP Bridge] ✓ Connected to native host");

    // --- Handle incoming commands from native host ---
    nativePort.onMessage.addListener(async (msg) => {
      try {
        const result = await handleCommand(msg);
        nativePort.postMessage({ id: msg.id, success: true, result });
      } catch (err) {
        console.error("[CDP Bridge] Command error:", err);
        nativePort.postMessage({
          id: msg.id,
          success: false,
          error: err.message || String(err)
        });
      }
    });

    // --- Handle disconnection ---
    nativePort.onDisconnect.addListener(() => {
      const err = chrome.runtime.lastError?.message || "unknown";
      console.warn("[CDP Bridge] Native host disconnected:", err);
      nativePort = null;
      connecting = false;
      // Don't reconnect immediately — let the alarm handle it
    });

  } catch (e) {
    console.error("[CDP Bridge] Failed to connect:", e);
    nativePort = null;
    connecting = false;
  }
}

// =============================================================================
// SERVICE WORKER LIFECYCLE — KEEPALIVE
// =============================================================================

// On install: connect immediately + set up keepalive alarm
chrome.runtime.onInstalled.addListener(() => {
  console.log("[CDP Bridge] Extension installed");
  chrome.alarms.create("keepalive", { periodInMinutes: 0.4 }); // ~25 seconds
  connectNativeHost();
});

// On Chrome startup: reconnect
chrome.runtime.onStartup.addListener(() => {
  console.log("[CDP Bridge] Chrome started");
  chrome.alarms.create("keepalive", { periodInMinutes: 0.4 });
  connectNativeHost();
});

// Keepalive alarm — reconnect native host if disconnected
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "keepalive") {
    if (!nativePort) {
      connectNativeHost();
    }
  }
});

// Clean up debugger on tab close
chrome.tabs.onRemoved.addListener((tabId) => {
  attachedTabs.delete(tabId);
});

// =============================================================================
// MESSAGE HANDLER — from popup UI (for testing)
// =============================================================================

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  handleCommand(msg)
    .then((result) => sendResponse({ success: true, result }))
    .catch((err) => sendResponse({ success: false, error: err.message || String(err) }));
  return true; // keep channel open for async response
});

// =============================================================================
// DEBUGGER HELPERS
// =============================================================================

/**
 * Attach the Chrome debugger to a tab (if not already attached).
 * This shows a yellow banner but does NOT trigger Google automation detection.
 */
async function ensureAttached(tabId) {
  if (attachedTabs.has(tabId)) return;
  return new Promise((resolve, reject) => {
    chrome.debugger.attach({ tabId }, CDP_VERSION, () => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
      } else {
        attachedTabs.add(tabId);
        resolve();
      }
    });
  });
}

/**
 * Detach the Chrome debugger from a tab.
 */
async function detachDebugger(tabId) {
  if (!attachedTabs.has(tabId)) return;
  return new Promise((resolve) => {
    chrome.debugger.detach({ tabId }, () => {
      attachedTabs.delete(tabId);
      resolve();
    });
  });
}

/**
 * Send a raw CDP command to a tab via chrome.debugger.
 * Auto-attaches if needed.
 * 
 * This is the core function — it replaces the WebSocket CDP client.
 */
async function sendCDP(tabId, method, params = {}) {
  await ensureAttached(tabId);
  return new Promise((resolve, reject) => {
    chrome.debugger.sendCommand({ tabId }, method, params, (result) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
      } else {
        resolve(result || {});
      }
    });
  });
}

// =============================================================================
// TAB HELPERS
// =============================================================================

/**
 * Resolve a tab ID: if not provided, use the active tab.
 */
async function resolveTabId(tabId) {
  if (tabId) return tabId;
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) throw new Error("No active tab found");
  return tab.id;
}

/**
 * Wait for a tab to finish loading (status = "complete").
 */
function waitForTabLoad(tabId, timeout = 30000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      reject(new Error("Tab load timeout"));
    }, timeout);

    function listener(updatedTabId, changeInfo) {
      if (updatedTabId === tabId && changeInfo.status === "complete") {
        clearTimeout(timer);
        chrome.tabs.onUpdated.removeListener(listener);
        resolve();
      }
    }
    chrome.tabs.onUpdated.addListener(listener);

    // Check if already loaded
    chrome.tabs.get(tabId, (tab) => {
      if (tab && tab.status === "complete") {
        clearTimeout(timer);
        chrome.tabs.onUpdated.removeListener(listener);
        resolve();
      }
    });
  });
}

// =============================================================================
// COMMAND ROUTER
// =============================================================================
// Maps action names to handler functions.
// Action names match what the Native Host forwards from Python.
// =============================================================================

async function handleCommand(msg) {
  const { action, params = {} } = msg;

  switch (action) {

    // ─── Tab Management ───────────────────────────────────────────────
    // These use chrome.tabs API directly (no debugger needed)

    case "status":
      return await cmdStatus();

    case "list_tabs":
      return await cmdListTabs();

    case "new_tab":
      return await cmdNewTab(params.url || "about:blank");

    case "close_tab":
      return await cmdCloseTab(params.tabId);

    case "get_tab":
      return await cmdGetTab(params.tabId);

    // ─── Navigation ───────────────────────────────────────────────────

    case "navigate":
    case "goto":
      return await cmdNavigate(params.tabId, params.url);

    case "reload":
      return await cmdReload(params.tabId);

    case "back":
      return await cmdEval(params.tabId, "history.back()");

    case "forward":
      return await cmdEval(params.tabId, "history.forward()");

    case "get_url":
      return await cmdEval(params.tabId, "window.location.href");

    case "get_title":
      return await cmdEval(params.tabId, "document.title");

    // ─── Page Reading ─────────────────────────────────────────────────

    case "get_html":
      return await cmdEval(params.tabId, "document.documentElement.outerHTML");

    case "get_text":
      return await cmdEval(params.tabId, "document.body.innerText");

    case "get_element_html":
      return await cmdEval(params.tabId,
        `document.querySelector('${esc(params.selector)}')?.outerHTML || null`);

    case "get_attribute":
      return await cmdEval(params.tabId,
        `document.querySelector('${esc(params.selector)}')?.getAttribute('${esc(params.attribute)}') || null`);

    case "get_links":
      return await cmdEval(params.tabId, `
        [...document.querySelectorAll('a[href]')].map(a => ({
          href: a.href, text: a.textContent.trim().substring(0, 100)
        }))
      `);

    case "evaluate":
      return await cmdEval(params.tabId, params.expression);

    // ─── Click / Mouse ────────────────────────────────────────────────

    case "click":
      return await cmdClick(params.tabId, params.selector);

    case "click_text":
      return await cmdClickText(params.tabId, params.text, params.tag || "*");

    case "dblclick":
      return await cmdClick(params.tabId, params.selector, 2);

    case "hover":
      return await cmdHover(params.tabId, params.selector);

    // ─── Keyboard / Input ─────────────────────────────────────────────

    case "type":
    case "fill":
      return await cmdType(params.tabId, params.selector, params.text, params.clear !== false);

    case "clear":
      return await cmdEval(params.tabId,
        `document.querySelector('${esc(params.selector)}').value = ''`);

    case "press":
      return await cmdPressKey(params.tabId, params.key);

    // ─── Forms ────────────────────────────────────────────────────────

    case "select":
      return await cmdEval(params.tabId, `
        (() => {
          const sel = document.querySelector('${esc(params.selector)}');
          if (!sel) return null;
          const opt = [...sel.options].find(o => o.value === '${esc(params.value)}' || o.text === '${esc(params.value)}');
          if (opt) sel.value = opt.value;
          sel.dispatchEvent(new Event('change', {bubbles: true}));
          return true;
        })()
      `);

    case "check":
      return await cmdEval(params.tabId, `
        (() => { const el = document.querySelector('${esc(params.selector)}'); if (el && !el.checked) el.click(); return true; })()
      `);

    case "uncheck":
      return await cmdEval(params.tabId, `
        (() => { const el = document.querySelector('${esc(params.selector)}'); if (el && el.checked) el.click(); return true; })()
      `);

    case "submit":
      return await cmdEval(params.tabId,
        "document.activeElement?.form?.submit()");

    // ─── Scroll ───────────────────────────────────────────────────────

    case "scroll":
      return await cmdScroll(params.tabId, params.direction);

    case "scroll_to":
      return await cmdEval(params.tabId,
        `document.querySelector('${esc(params.selector)}')?.scrollIntoView({block:'center'})`);

    // ─── Wait / Poll ──────────────────────────────────────────────────

    case "wait_element":
      return await cmdWaitElement(params.tabId, params.selector, params.timeout || 30);

    case "wait_hidden":
      return await cmdWaitHidden(params.tabId, params.selector, params.timeout || 30);

    case "wait_text":
      return await cmdWaitText(params.tabId, params.text, params.timeout || 30);

    // ─── Screenshot / PDF ─────────────────────────────────────────────

    case "screenshot":
      return await cmdScreenshot(params.tabId, false);

    case "screenshot_full":
      return await cmdScreenshot(params.tabId, true);

    case "pdf":
      return await cmdPDF(params.tabId);

    case "capture_element":
      return await cmdCaptureElement(params.tabId, params.selector);

    // ─── Images ───────────────────────────────────────────────────────

    case "get_images":
      return await cmdGetImages(params.tabId);

    // ─── Debugger Control ─────────────────────────────────────────────

    case "attach":
      await ensureAttached(params.tabId);
      return { attached: true };

    case "detach":
      await detachDebugger(params.tabId);
      return { detached: true };

    // ─── Raw CDP Pass-through ─────────────────────────────────────────
    // Allows sending any CDP command directly: { action: "Page.enable", params: { tabId, cdpParams } }

    case "raw_cdp":
      return await sendCDP(params.tabId, params.method, params.cdpParams || {});

    // ─── Ping (health check) ──────────────────────────────────────────

    case "ping":
      return { pong: true, timestamp: Date.now(), version: "1.0.0" };

    default:
      // Try as raw CDP method name (e.g. "Page.navigate")
      if (action && action.includes(".")) {
        const tabId = await resolveTabId(params.tabId);
        const cdpParams = { ...params };
        delete cdpParams.tabId;
        return await sendCDP(tabId, action, cdpParams);
      }
      throw new Error(`Unknown action: ${action}`);
  }
}

// =============================================================================
// COMMAND IMPLEMENTATIONS
// =============================================================================

// ─── Tab Management ─────────────────────────────────────────────────────

async function cmdStatus() {
  const tabs = await chrome.tabs.query({});
  return {
    running: true,
    tabCount: tabs.length,
    attachedTabs: [...attachedTabs],
    nativeHostConnected: !!nativePort,
    version: "1.0.0"
  };
}

async function cmdListTabs() {
  const tabs = await chrome.tabs.query({});
  return tabs.map(t => ({
    id: t.id,
    url: t.url,
    title: t.title,
    active: t.active,
    windowId: t.windowId,
    status: t.status
  }));
}

async function cmdNewTab(url) {
  const tab = await chrome.tabs.create({ url, active: false });
  try {
    await waitForTabLoad(tab.id, 30000);
  } catch (e) {
    // Timeout is not fatal — tab might be slow but still usable
    console.warn("[CDP Bridge] Tab load timeout, continuing anyway");
  }
  const updated = await chrome.tabs.get(tab.id);
  return { tabId: updated.id, url: updated.url, title: updated.title };
}

async function cmdCloseTab(tabId) {
  tabId = await resolveTabId(tabId);
  // Safety: never close the last tab
  const allTabs = await chrome.tabs.query({});
  if (allTabs.length <= 1) {
    throw new Error("Cannot close the last tab — Chrome would exit");
  }
  await detachDebugger(tabId);
  await chrome.tabs.remove(tabId);
  return { closed: true, tabId };
}

async function cmdGetTab(tabId) {
  tabId = await resolveTabId(tabId);
  const tab = await chrome.tabs.get(tabId);
  return { id: tab.id, url: tab.url, title: tab.title, status: tab.status };
}

// ─── Navigation ─────────────────────────────────────────────────────────

async function cmdNavigate(tabId, url) {
  tabId = await resolveTabId(tabId);
  if (!url) throw new Error("URL is required");
  await chrome.tabs.update(tabId, { url });
  try {
    await waitForTabLoad(tabId, 30000);
  } catch (e) {
    console.warn("[CDP Bridge] Navigate load timeout, continuing");
  }
  const tab = await chrome.tabs.get(tabId);
  return { tabId: tab.id, url: tab.url, title: tab.title };
}

async function cmdReload(tabId) {
  tabId = await resolveTabId(tabId);
  await chrome.tabs.reload(tabId);
  try {
    await waitForTabLoad(tabId, 30000);
  } catch (e) {
    console.warn("[CDP Bridge] Reload timeout, continuing");
  }
  return { reloaded: true };
}

// ─── JavaScript Evaluation ──────────────────────────────────────────────

async function cmdEval(tabId, expression) {
  tabId = await resolveTabId(tabId);
  const result = await sendCDP(tabId, "Runtime.evaluate", {
    expression,
    returnByValue: true
  });
  const val = result?.result?.value;
  return { value: val };
}

// ─── Click ──────────────────────────────────────────────────────────────

async function cmdClick(tabId, selector, clickCount = 1) {
  tabId = await resolveTabId(tabId);
  // Get element center coordinates
  const { value: coords } = await cmdEval(tabId, `
    (() => {
      const el = document.querySelector('${esc(selector)}');
      if (!el) return null;
      el.scrollIntoView({block: 'center'});
      const rect = el.getBoundingClientRect();
      return {x: rect.x + rect.width/2, y: rect.y + rect.height/2};
    })()
  `);
  if (!coords) throw new Error(`Element not found: ${selector}`);
  await mouseClick(tabId, coords.x, coords.y, clickCount);
  return { clicked: true, selector };
}

async function cmdClickText(tabId, text, tag = "*") {
  tabId = await resolveTabId(tabId);
  const textEsc = text.replace(/'/g, "\\'").replace(/"/g, '\\"');
  const { value: coords } = await cmdEval(tabId, `
    (() => {
      const els = [...document.querySelectorAll('${tag}')];
      const el = els.find(e => e.textContent.includes('${textEsc}'));
      if (!el) return null;
      el.scrollIntoView({block: 'center'});
      const rect = el.getBoundingClientRect();
      return {x: rect.x + rect.width/2, y: rect.y + rect.height/2};
    })()
  `);
  if (!coords) throw new Error(`Element with text '${text}' not found`);
  await mouseClick(tabId, coords.x, coords.y, 1);
  return { clicked: true, text };
}

async function cmdHover(tabId, selector) {
  tabId = await resolveTabId(tabId);
  const { value: coords } = await cmdEval(tabId, `
    (() => {
      const el = document.querySelector('${esc(selector)}');
      if (!el) return null;
      el.scrollIntoView({block: 'center'});
      const rect = el.getBoundingClientRect();
      return {x: rect.x + rect.width/2, y: rect.y + rect.height/2};
    })()
  `);
  if (!coords) throw new Error(`Element not found: ${selector}`);
  await sendCDP(tabId, "Input.dispatchMouseEvent", {
    type: "mouseMoved", x: coords.x, y: coords.y
  });
  return { hovered: true, selector };
}

async function mouseClick(tabId, x, y, clickCount = 1) {
  await sendCDP(tabId, "Input.dispatchMouseEvent", {
    type: "mousePressed", x, y, button: "left", clickCount
  });
  await sendCDP(tabId, "Input.dispatchMouseEvent", {
    type: "mouseReleased", x, y, button: "left", clickCount
  });
}

// ─── Keyboard Input ─────────────────────────────────────────────────────

async function cmdType(tabId, selector, text, clear = true) {
  tabId = await resolveTabId(tabId);
  // Focus the element
  await cmdEval(tabId, `document.querySelector('${esc(selector)}')?.focus()`);
  if (clear) {
    await cmdEval(tabId, `document.querySelector('${esc(selector)}').value = ''`);
  }
  await sendCDP(tabId, "Input.insertText", { text });
  return { typed: true, selector };
}

async function cmdPressKey(tabId, key) {
  tabId = await resolveTabId(tabId);
  const keyMap = {
    enter:      { key: "Enter",      code: "Enter",      keyCode: 13 },
    tab:        { key: "Tab",        code: "Tab",        keyCode: 9 },
    escape:     { key: "Escape",     code: "Escape",     keyCode: 27 },
    backspace:  { key: "Backspace",  code: "Backspace",  keyCode: 8 },
    delete:     { key: "Delete",     code: "Delete",     keyCode: 46 },
    arrowup:    { key: "ArrowUp",    code: "ArrowUp",    keyCode: 38 },
    arrowdown:  { key: "ArrowDown",  code: "ArrowDown",  keyCode: 40 },
    arrowleft:  { key: "ArrowLeft",  code: "ArrowLeft",  keyCode: 37 },
    arrowright: { key: "ArrowRight", code: "ArrowRight", keyCode: 39 },
  };

  const mapped = keyMap[key.toLowerCase()] || {
    key, code: key, keyCode: key.length === 1 ? key.charCodeAt(0) : 0
  };

  await sendCDP(tabId, "Input.dispatchKeyEvent", {
    type: "keyDown", key: mapped.key, code: mapped.code,
    windowsVirtualKeyCode: mapped.keyCode, nativeVirtualKeyCode: mapped.keyCode
  });
  await sendCDP(tabId, "Input.dispatchKeyEvent", {
    type: "keyUp", key: mapped.key, code: mapped.code,
    windowsVirtualKeyCode: mapped.keyCode, nativeVirtualKeyCode: mapped.keyCode
  });
  return { pressed: true, key };
}

// ─── Scroll ─────────────────────────────────────────────────────────────

async function cmdScroll(tabId, direction) {
  tabId = await resolveTabId(tabId);
  const scripts = {
    down:   "window.scrollBy(0, 500)",
    up:     "window.scrollBy(0, -500)",
    bottom: "window.scrollTo(0, document.body.scrollHeight)",
    top:    "window.scrollTo(0, 0)",
  };
  const expr = scripts[direction];
  if (!expr) throw new Error(`Invalid scroll direction: ${direction}. Use: down, up, bottom, top`);
  await cmdEval(tabId, expr);
  return { scrolled: true, direction };
}

// ─── Wait / Poll ────────────────────────────────────────────────────────

async function cmdWaitElement(tabId, selector, timeout = 30) {
  tabId = await resolveTabId(tabId);
  const deadline = Date.now() + timeout * 1000;
  while (Date.now() < deadline) {
    const { value } = await cmdEval(tabId, `!!document.querySelector('${esc(selector)}')`);
    if (value) return { found: true, selector };
    await sleep(500);
  }
  throw new Error(`Timeout waiting for element: ${selector}`);
}

async function cmdWaitHidden(tabId, selector, timeout = 30) {
  tabId = await resolveTabId(tabId);
  const deadline = Date.now() + timeout * 1000;
  while (Date.now() < deadline) {
    const { value } = await cmdEval(tabId, `!document.querySelector('${esc(selector)}')`);
    if (value) return { hidden: true, selector };
    await sleep(500);
  }
  throw new Error(`Timeout waiting for element to disappear: ${selector}`);
}

async function cmdWaitText(tabId, text, timeout = 30) {
  tabId = await resolveTabId(tabId);
  const textEsc = text.replace(/'/g, "\\'");
  const deadline = Date.now() + timeout * 1000;
  while (Date.now() < deadline) {
    const { value } = await cmdEval(tabId, `document.body.innerText.includes('${textEsc}')`);
    if (value) return { found: true, text };
    await sleep(500);
  }
  throw new Error(`Timeout waiting for text: ${text}`);
}

// ─── Screenshot / PDF ───────────────────────────────────────────────────

async function cmdScreenshot(tabId, fullPage = false) {
  tabId = await resolveTabId(tabId);
  const cdpParams = { format: "png" };

  if (fullPage) {
    cdpParams.captureBeyondViewport = true;
    // Measure full document size
    const { value: metrics } = await cmdEval(tabId, `({
      width: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
      height: Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)
    })`);
    if (metrics) {
      await sendCDP(tabId, "Emulation.setDeviceMetricsOverride", {
        width: metrics.width, height: metrics.height,
        deviceScaleFactor: 1, mobile: false
      });
    }
  }

  const result = await sendCDP(tabId, "Page.captureScreenshot", cdpParams);

  if (fullPage) {
    await sendCDP(tabId, "Emulation.clearDeviceMetricsOverride");
  }

  // Return base64 data — Python will decode and save to file
  return { data: result.data, format: "png" };
}

async function cmdPDF(tabId) {
  tabId = await resolveTabId(tabId);
  const result = await sendCDP(tabId, "Page.printToPDF", {
    printBackground: true,
    preferCSSPageSize: true
  });
  return { data: result.data, format: "pdf" };
}

async function cmdCaptureElement(tabId, selector) {
  tabId = await resolveTabId(tabId);
  const { value: bounds } = await cmdEval(tabId, `
    (() => {
      const el = document.querySelector('${esc(selector)}');
      if (!el) return null;
      const rect = el.getBoundingClientRect();
      return {
        x: rect.x + window.scrollX,
        y: rect.y + window.scrollY,
        width: rect.width,
        height: rect.height
      };
    })()
  `);
  if (!bounds) throw new Error(`Element not found: ${selector}`);

  const result = await sendCDP(tabId, "Page.captureScreenshot", {
    format: "png",
    clip: { x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height, scale: 1 }
  });
  return { data: result.data, format: "png" };
}

// ─── Images ─────────────────────────────────────────────────────────────

async function cmdGetImages(tabId) {
  tabId = await resolveTabId(tabId);
  // This is the exact same JS from chrome-shared.py get_images()
  const { value } = await cmdEval(tabId, `
    (() => {
      const images = [];
      document.querySelectorAll('img').forEach((img, i) => {
        if (img.src) images.push({
          type: 'img', src: img.src, alt: img.alt || '',
          width: img.naturalWidth || img.width, height: img.naturalHeight || img.height,
          selector: img.id ? '#' + img.id : 'img:nth-of-type(' + (i+1) + ')'
        });
      });
      document.querySelectorAll('svg').forEach((svg, i) => {
        const s = new XMLSerializer();
        const str = s.serializeToString(svg);
        const uri = 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(str)));
        images.push({
          type: 'svg', src: uri,
          width: svg.width?.baseVal?.value || svg.viewBox?.baseVal?.width || 0,
          height: svg.height?.baseVal?.value || svg.viewBox?.baseVal?.height || 0,
          selector: svg.id ? '#' + svg.id : 'svg:nth-of-type(' + (i+1) + ')'
        });
      });
      document.querySelectorAll('canvas').forEach((c, i) => {
        try {
          images.push({
            type: 'canvas', src: c.toDataURL('image/png'),
            width: c.width, height: c.height,
            selector: c.id ? '#' + c.id : 'canvas:nth-of-type(' + (i+1) + ')'
          });
        } catch(e) {}
      });
      document.querySelectorAll('*').forEach((el) => {
        const bg = getComputedStyle(el).backgroundImage;
        if (bg && bg !== 'none' && bg.startsWith('url(')) {
          const m = bg.match(/url\\(["']?(.+?)["']?\\)/);
          if (m && m[1] && !m[1].startsWith('data:image/svg'))
            images.push({
              type: 'background', src: m[1],
              selector: el.id ? '#'+el.id : el.className ? '.'+el.className.split(' ')[0] : el.tagName.toLowerCase()
            });
        }
      });
      document.querySelectorAll('picture source').forEach((s, i) => {
        if (s.srcset) s.srcset.split(',').map(x => x.trim().split(' ')[0]).forEach(src => {
          images.push({ type: 'picture', src, media: s.media || '', selector: 'picture:nth-of-type('+(i+1)+') source' });
        });
      });
      const seen = new Set();
      return images.filter(img => { if (seen.has(img.src)) return false; seen.add(img.src); return true; });
    })()
  `);
  return value || [];
}

// =============================================================================
// UTILITIES
// =============================================================================

/** Escape single quotes for CSS selector injection in JS strings */
function esc(str) {
  if (!str) return "";
  return str.replace(/\\/g, "\\\\").replace(/'/g, "\\'");
}

/** Promise-based sleep */
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}
