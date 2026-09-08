/**
 * Popup UI — for manual testing of CDP Bridge commands.
 * Sends messages to background.js via chrome.runtime.sendMessage.
 */

const logEl = document.getElementById("log");
const dot = document.getElementById("statusDot");

function log(msg, cls = "") {
  const line = document.createElement("div");
  line.className = cls;
  line.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
  logEl.appendChild(line);
  logEl.scrollTop = logEl.scrollHeight;
}

async function send(action, params = {}) {
  log(`→ ${action} ${JSON.stringify(params)}`, "info");
  try {
    const resp = await chrome.runtime.sendMessage({ action, params });
    if (resp.success) {
      // Truncate large data fields for display
      const display = { ...resp.result };
      if (display.data && display.data.length > 100) {
        display.data = display.data.substring(0, 100) + `... (${display.data.length} chars)`;
      }
      if (display.value && typeof display.value === "string" && display.value.length > 200) {
        display.value = display.value.substring(0, 200) + "...";
      }
      log(`✓ ${JSON.stringify(display, null, 2)}`, "ok");
    } else {
      log(`✗ ${resp.error}`, "err");
    }
    return resp;
  } catch (e) {
    log(`✗ ${e.message}`, "err");
    return { success: false, error: e.message };
  }
}

// --- Status check on popup open ---
(async () => {
  const resp = await send("ping");
  dot.classList.toggle("ok", resp.success);
})();

// --- Button handlers ---
document.getElementById("btnNavigate").addEventListener("click", () => {
  send("navigate", { url: document.getElementById("urlInput").value });
});

document.getElementById("btnNewTab").addEventListener("click", () => {
  send("new_tab", { url: document.getElementById("urlInput").value });
});

document.getElementById("btnScreenshot").addEventListener("click", async () => {
  const resp = await send("screenshot");
  if (resp.success && resp.result?.data) {
    // Open screenshot in new tab for preview
    const url = "data:image/png;base64," + resp.result.data;
    chrome.tabs.create({ url });
  }
});

document.getElementById("btnPdf").addEventListener("click", () => {
  send("pdf");
});

document.getElementById("btnHtml").addEventListener("click", () => {
  send("get_html");
});

document.getElementById("btnListTabs").addEventListener("click", async () => {
  const resp = await send("list_tabs");
  if (resp.success && Array.isArray(resp.result)) {
    resp.result.forEach(t => log(`  [${t.id}] ${t.title} — ${t.url}`, ""));
  }
});

document.getElementById("btnStatus").addEventListener("click", () => {
  send("status");
});

document.getElementById("btnPing").addEventListener("click", () => {
  send("ping");
});

document.getElementById("btnEval").addEventListener("click", () => {
  send("evaluate", { expression: document.getElementById("evalInput").value });
});

// Enter key in URL input → navigate
document.getElementById("urlInput").addEventListener("keypress", (e) => {
  if (e.key === "Enter") document.getElementById("btnNavigate").click();
});

// Enter key in eval input → run
document.getElementById("evalInput").addEventListener("keypress", (e) => {
  if (e.key === "Enter") document.getElementById("btnEval").click();
});
