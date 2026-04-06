/**
 * Frontend logger for multi-agent dashboard.
 *
 * Usage:
 *   import { createLogger } from '../lib/logger'
 *   const log = createLogger('Terminal')
 *   log.ws('open', { agentId: '300' })
 *   log.action('submit', { agentId: '300', len: 42 })
 *
 * All events are buffered and flushed every 5 s via POST /api/logs/frontend.
 * Memory snapshots (performance.memory) are captured every 5 minutes.
 * Each browser tab gets a unique session ID stored in sessionStorage.
 */

// ── Session ID ──────────────────────────────────────────────────────────────
// sessionStorage is per-tab: two open windows on the same server get distinct IDs.
function getSessionId() {
  let id = sessionStorage.getItem('ma_sess')
  if (!id) {
    id = `s${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`
    sessionStorage.setItem('ma_sess', id)
  }
  return id
}

const SESSION_ID = getSessionId()
const FLUSH_INTERVAL_MS  = 5_000      // flush buffer every 5 s
const MEMORY_INTERVAL_MS = 300_000    // memory snapshot every 5 min
const ENDPOINT = '/api/logs/frontend'
const WS_THROTTLE_MS = 10_000         // same ws event+endpoint logged at most once per 10 s

// ── Internal state ───────────────────────────────────────────────────────────
let buffer = []
let lastMemoryUsed = null   // for deltaMB
let startTime = Date.now()  // for uptimeMin
const wsLastSeen = {}       // key → timestamp, for throttling

function push(entry) {
  buffer.push({ ts: Date.now(), sess: SESSION_ID, ...entry })
}

// ── Flush ────────────────────────────────────────────────────────────────────
async function flush() {
  if (buffer.length === 0) return
  const batch = buffer.splice(0, buffer.length)

  // Use __maRawFetch (saved before the JWT interceptor in App.jsx) so the
  // logger's own POST doesn't get intercepted → no infinite loop.
  const fetchFn = window.__maRawFetch || window.fetch
  try {
    const token = localStorage.getItem('access_token')
    const headers = { 'Content-Type': 'application/json' }
    if (token) headers['Authorization'] = `Bearer ${token}`
    await fetchFn(ENDPOINT, {
      method: 'POST',
      headers,
      body: JSON.stringify({ events: batch }),
    })
  } catch {
    // On failure, put events back at the front so they aren't lost.
    buffer.unshift(...batch)
  }
}

// ── Memory snapshot ──────────────────────────────────────────────────────────
function captureMemory() {
  const mem = performance?.memory
  if (!mem) return
  const usedMB  = Math.round(mem.usedJSHeapSize  / 1048576)
  const totalMB = Math.round(mem.totalJSHeapSize / 1048576)
  const limitMB = Math.round(mem.jsHeapSizeLimit / 1048576)
  const deltaMB = lastMemoryUsed !== null ? usedMB - lastMemoryUsed : 0
  lastMemoryUsed = usedMB
  const uptimeMin = Math.round((Date.now() - startTime) / 60000)
  push({ type: 'memory', src: 'logger', usedMB, totalMB, limitMB, deltaMB, uptimeMin })
}

// ── Global error capture ─────────────────────────────────────────────────────
const _origConsoleError = console.error.bind(console)
const _origConsoleWarn  = console.warn.bind(console)

console.error = (...args) => {
  push({ type: 'error', src: 'console', msg: args.map(String).join(' ') })
  _origConsoleError(...args)
}
console.warn = (...args) => {
  push({ type: 'warn', src: 'console', msg: args.map(String).join(' ') })
  _origConsoleWarn(...args)
}

window.addEventListener('error', (e) => {
  push({ type: 'error', src: 'window', msg: e.message, file: e.filename, line: e.lineno })
})
window.addEventListener('unhandledrejection', (e) => {
  push({ type: 'error', src: 'promise', msg: String(e.reason) })
})

// ── Timers ───────────────────────────────────────────────────────────────────
setInterval(flush, FLUSH_INTERVAL_MS)
setInterval(captureMemory, MEMORY_INTERVAL_MS)
captureMemory()   // capture once at startup

// ── Public API ───────────────────────────────────────────────────────────────
/**
 * createLogger(src) → logger bound to that source module.
 * All methods accept an optional `extra` object for additional fields.
 */
export function createLogger(src) {
  return {
    info:   (msg, extra)        => push({ type: 'info',   src, msg, ...extra }),
    warn:   (msg, extra)        => push({ type: 'warn',   src, msg, ...extra }),
    error:  (msg, extra)        => push({ type: 'error',  src, msg, ...extra }),
    action: (action, extra)     => push({ type: 'action', src, action, ...extra }),
    api:    (method, url, extra)=> push({ type: 'api',    src, method, url, ...extra }),
    ws:     (event, extra)      => {
      const key = `${src}|${event}|${extra?.endpoint ?? extra?.agentId ?? ''}`
      const now = Date.now()
      if (wsLastSeen[key] && now - wsLastSeen[key] < WS_THROTTLE_MS) return
      wsLastSeen[key] = now
      push({ type: 'ws', src, event, ...extra })
    },
    nav:    (to, extra)         => push({ type: 'nav',    src, to, ...extra }),
  }
}
