#!/usr/bin/env node
/**
 * CDP Bridge — Native Messaging Host
 * ====================================
 * 
 * This Node.js script serves TWO roles simultaneously:
 * 
 *   1. NATIVE MESSAGING HOST (stdin/stdout)
 *      Chrome spawns this process and connects its stdin/stdout pipes.
 *      The extension sends commands and receives responses through these pipes.
 *      Protocol: 4-byte little-endian length prefix + UTF-8 JSON payload.
 * 
 *   2. HTTP SERVER (port 9222)
 *      Python scripts (chrome-shared.py) send commands via HTTP.
 *      This server translates HTTP requests into native messages,
 *      waits for the extension's response, and returns it to Python.
 * 
 * FLOW:
 *   Python → HTTP POST :9222/command → Node.js → stdout → Chrome → Extension
 *   Extension → stdin → Node.js → HTTP response → Python
 * 
 * ENDPOINTS:
 *   GET  /json          → List all tabs (compatible with CDP /json)
 *   GET  /json/version  → Version info (compatible with CDP /json/version)
 *   POST /command       → Execute any command: { action, params }
 *   GET  /health        → Health check
 * 
 * NATIVE MESSAGING PROTOCOL:
 *   Each message is: [4 bytes: uint32 LE length] [N bytes: UTF-8 JSON]
 *   Messages from Chrome (stdin):  responses from the extension
 *   Messages to Chrome (stdout):   commands for the extension
 * 
 * MESSAGE SIZE LIMIT:
 *   Native messaging has a 1MB limit per message. For large payloads
 *   (screenshots, full-page HTML), the base64 data is chunked if needed.
 *   In practice, most viewport screenshots are under 500KB base64.
 */

const http = require("http");
const { URL } = require("url");

// =============================================================================
// CONFIGURATION
// =============================================================================

const PORT = parseInt(process.env.CDP_BRIDGE_PORT || "9222", 10);
const COMMAND_TIMEOUT_MS = 60000; // 60s timeout per command
const MAX_NATIVE_MSG_SIZE = 1024 * 1024; // 1MB native messaging limit

// =============================================================================
// STATE
// =============================================================================

let nextId = 1;

/** @type {Map<number, {resolve: Function, reject: Function, timer: NodeJS.Timeout}>} */
const pendingRequests = new Map();

/** @type {boolean} Whether stdin is connected (extension is alive) */
let extensionConnected = false;

/** @type {Buffer} Accumulator for partial stdin reads */
let stdinBuffer = Buffer.alloc(0);

// =============================================================================
// NATIVE MESSAGING — STDIN (receive from extension)
// =============================================================================

/**
 * Read native messages from stdin.
 * 
 * Protocol: [4 bytes uint32 LE = length][length bytes = JSON payload]
 * 
 * We accumulate data in stdinBuffer because Node's stdin may deliver
 * partial reads. We parse complete messages as they become available.
 */
process.stdin.on("data", (chunk) => {
  extensionConnected = true;
  stdinBuffer = Buffer.concat([stdinBuffer, chunk]);

  // Process all complete messages in the buffer
  while (stdinBuffer.length >= 4) {
    const msgLen = stdinBuffer.readUInt32LE(0);

    // Safety check: reject absurdly large messages
    if (msgLen > MAX_NATIVE_MSG_SIZE * 2) {
      log("ERROR", `Message too large: ${msgLen} bytes, resetting buffer`);
      stdinBuffer = Buffer.alloc(0);
      break;
    }

    // Wait for the complete message body
    if (stdinBuffer.length < 4 + msgLen) break;

    // Extract and parse the message
    const msgData = stdinBuffer.slice(4, 4 + msgLen);
    stdinBuffer = stdinBuffer.slice(4 + msgLen);

    try {
      const msg = JSON.parse(msgData.toString("utf8"));
      handleExtensionResponse(msg);
    } catch (e) {
      log("ERROR", `Failed to parse native message: ${e.message}`);
    }
  }
});

process.stdin.on("end", () => {
  log("INFO", "stdin closed — extension disconnected");
  extensionConnected = false;
  // Reject all pending requests
  for (const [id, req] of pendingRequests) {
    clearTimeout(req.timer);
    req.reject(new Error("Extension disconnected"));
  }
  pendingRequests.clear();
  // Keep HTTP server alive — extension can reconnect later
  log("INFO", "HTTP server stays alive, waiting for extension reconnection...");
});

process.stdin.on("error", (err) => {
  log("ERROR", `stdin error: ${err.message}`);
});

// =============================================================================
// NATIVE MESSAGING — STDOUT (send to extension)
// =============================================================================

/**
 * Send a native message to the Chrome extension via stdout.
 * Format: [4 bytes uint32 LE length][JSON payload]
 */
function sendToExtension(msg) {
  const json = JSON.stringify(msg);
  const body = Buffer.from(json, "utf8");
  const header = Buffer.alloc(4);
  header.writeUInt32LE(body.length, 0);
  process.stdout.write(header);
  process.stdout.write(body);
}

// =============================================================================
// REQUEST-RESPONSE CORRELATION
// =============================================================================

/**
 * Send a command to the extension and return a Promise for the response.
 * Uses auto-incrementing IDs for request-response correlation.
 */
function sendCommand(action, params = {}) {
  return new Promise((resolve, reject) => {
    if (!extensionConnected) {
      return reject(new Error("Extension not connected"));
    }

    const id = nextId++;
    const timer = setTimeout(() => {
      pendingRequests.delete(id);
      reject(new Error(`Command timeout (${COMMAND_TIMEOUT_MS}ms): ${action}`));
    }, COMMAND_TIMEOUT_MS);

    pendingRequests.set(id, { resolve, reject, timer });
    sendToExtension({ id, action, params });
  });
}

/**
 * Handle a response from the extension (received via stdin).
 * Match it to a pending request by ID.
 */
function handleExtensionResponse(msg) {
  const { id, success, result, error } = msg;
  const pending = pendingRequests.get(id);
  if (!pending) {
    log("WARN", `No pending request for id=${id}`);
    return;
  }

  clearTimeout(pending.timer);
  pendingRequests.delete(id);

  if (success) {
    pending.resolve(result);
  } else {
    pending.reject(new Error(error || "Unknown extension error"));
  }
}

// =============================================================================
// HTTP SERVER
// =============================================================================

const server = http.createServer(async (req, res) => {
  // CORS headers for potential browser-based clients
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");

  if (req.method === "OPTIONS") {
    res.writeHead(204);
    return res.end();
  }

  const url = new URL(req.url, `http://localhost:${PORT}`);
  const path = url.pathname;

  try {
    // ─── CDP-compatible endpoints ────────────────────────────────────
    
    if (path === "/json" || path === "/json/list") {
      // GET /json — list all tabs (compatible with Chrome's CDP endpoint)
      const tabs = await sendCommand("list_tabs");
      // Transform to CDP-compatible format
      const cdpTabs = tabs.map(t => ({
        id: String(t.id),
        type: "page",
        title: t.title || "",
        url: t.url || "",
        webSocketDebuggerUrl: `ws://127.0.0.1:${PORT}/devtools/page/${t.id}`,
        devtoolsFrontendUrl: ""
      }));
      return jsonResponse(res, 200, cdpTabs);
    }

    if (path === "/json/version") {
      // GET /json/version — version info
      return jsonResponse(res, 200, {
        Browser: "CDP Bridge/1.0.0 (Chrome Extension)",
        "Protocol-Version": "1.3",
        "V8-Version": "N/A",
        "WebKit-Version": "N/A",
        webSocketDebuggerUrl: `ws://127.0.0.1:${PORT}/devtools/browser`
      });
    }

    if (path === "/health") {
      // GET /health — health check
      return jsonResponse(res, 200, {
        status: "ok",
        extensionConnected,
        pendingRequests: pendingRequests.size,
        uptime: process.uptime()
      });
    }

    // ─── Tab creation via HTTP (CDP-compatible) ──────────────────────

    if (path.startsWith("/json/new")) {
      // PUT /json/new?<url> — create new tab
      const targetUrl = url.search ? url.search.substring(1) : "about:blank";
      const decodedUrl = decodeURIComponent(targetUrl);
      const result = await sendCommand("new_tab", { url: decodedUrl });
      return jsonResponse(res, 200, {
        id: String(result.tabId),
        type: "page",
        title: result.title || "",
        url: result.url || decodedUrl,
        webSocketDebuggerUrl: `ws://127.0.0.1:${PORT}/devtools/page/${result.tabId}`
      });
    }

    if (path.startsWith("/json/close/")) {
      // GET /json/close/<tabId> — close tab
      const tabId = parseInt(path.split("/json/close/")[1], 10);
      await sendCommand("close_tab", { tabId });
      return textResponse(res, 200, "Target is closing");
    }

    // ─── Generic command endpoint ────────────────────────────────────

    if (path === "/command" && req.method === "POST") {
      // POST /command — execute any command
      const body = await readBody(req);
      const { action, params } = JSON.parse(body);
      if (!action) {
        return jsonResponse(res, 400, { error: "Missing 'action' field" });
      }
      const result = await sendCommand(action, params || {});
      return jsonResponse(res, 200, { success: true, result });
    }

    // ─── Shortcut endpoints (convenience) ────────────────────────────

    if (path === "/navigate" && req.method === "POST") {
      const body = await readBody(req);
      const { tabId, url: targetUrl } = JSON.parse(body);
      const result = await sendCommand("navigate", { tabId, url: targetUrl });
      return jsonResponse(res, 200, result);
    }

    if (path === "/screenshot" && (req.method === "GET" || req.method === "POST")) {
      let tabId = null;
      let fullPage = false;
      if (req.method === "POST") {
        const body = await readBody(req);
        const parsed = JSON.parse(body);
        tabId = parsed.tabId;
        fullPage = parsed.fullPage || false;
      } else {
        tabId = url.searchParams.get("tabId") ? parseInt(url.searchParams.get("tabId")) : null;
        fullPage = url.searchParams.get("fullPage") === "true";
      }
      const action = fullPage ? "screenshot_full" : "screenshot";
      const result = await sendCommand(action, { tabId });
      // Return raw PNG binary
      const png = Buffer.from(result.data, "base64");
      res.writeHead(200, { "Content-Type": "image/png", "Content-Length": png.length });
      return res.end(png);
    }

    if (path === "/pdf" && (req.method === "GET" || req.method === "POST")) {
      let tabId = null;
      if (req.method === "POST") {
        const body = await readBody(req);
        tabId = JSON.parse(body).tabId;
      } else {
        tabId = url.searchParams.get("tabId") ? parseInt(url.searchParams.get("tabId")) : null;
      }
      const result = await sendCommand("pdf", { tabId });
      const pdfBuf = Buffer.from(result.data, "base64");
      res.writeHead(200, { "Content-Type": "application/pdf", "Content-Length": pdfBuf.length });
      return res.end(pdfBuf);
    }

    if (path === "/eval" && req.method === "POST") {
      const body = await readBody(req);
      const { tabId, expression } = JSON.parse(body);
      const result = await sendCommand("evaluate", { tabId, expression });
      return jsonResponse(res, 200, result);
    }

    // ─── 404 ─────────────────────────────────────────────────────────

    return jsonResponse(res, 404, { error: `Unknown endpoint: ${path}` });

  } catch (err) {
    log("ERROR", `HTTP error: ${err.message}`);
    return jsonResponse(res, 500, { error: err.message });
  }
});

// =============================================================================
// HTTP HELPERS
// =============================================================================

function jsonResponse(res, status, data) {
  const body = JSON.stringify(data);
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(body);
}

function textResponse(res, status, text) {
  res.writeHead(status, { "Content-Type": "text/plain" });
  res.end(text);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

// =============================================================================
// LOGGING (to stderr so it doesn't corrupt the native messaging stdout)
// =============================================================================

function log(level, msg) {
  process.stderr.write(`[CDP Bridge Host] ${level}: ${msg}\n`);
}

// =============================================================================
// START
// =============================================================================

server.listen(PORT, "127.0.0.1", () => {
  log("INFO", `HTTP server listening on http://127.0.0.1:${PORT}`);
  log("INFO", "Waiting for extension connection via native messaging...");
  extensionConnected = true; // stdin is connected by Chrome at launch
});

server.on("error", (err) => {
  if (err.code === "EADDRINUSE") {
    log("ERROR", `Port ${PORT} already in use. Is another instance running?`);
    process.exit(1);
  }
  log("ERROR", `Server error: ${err.message}`);
});

// Handle graceful shutdown
process.on("SIGTERM", () => {
  log("INFO", "SIGTERM received, shutting down");
  server.close();
  process.exit(0);
});

process.on("SIGINT", () => {
  log("INFO", "SIGINT received, shutting down");
  server.close();
  process.exit(0);
});
