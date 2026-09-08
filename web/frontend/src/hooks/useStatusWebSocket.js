import { useEffect, useRef } from 'react'
import { wsUrl } from '../basePath'
import { getWsTicket } from '../apiFetch'
import { createLogger } from '../lib/logger'
import { useWakeDetector } from '../lib/useWakeDetector'

const log = createLogger('App')

// WebSocket temps réel ws/status : heartbeat, reconnexion, watchdog 30s,
// détection de réveil machine. Alimente l'état agents via applyUpdate
// (partagé avec useAgentsData). setWsLive signale l'état OPEN du WS pour
// que useAgentsData désactive le polling HTTP tant que le WS est la
// source temps réel (E2).
export function useStatusWebSocket({ statusPoll, ensureFreshToken, applyUpdate, setReconnecting, setWsLive, refetchAgentsRef }) {
  const wsRef = useRef(null)
  const reconnectTimer = useRef(null)
  const wakeReconnectRef = useRef(null)

  // WebSocket for real-time status (pauses when tab is hidden)
  useEffect(() => {
    let intentionalClose = false
    // Backoff exponentiel : 3s, 6s, 12s… plafonné à 60s, remis à zéro à
    // l'ouverture — un retry fixe entretient la charge pendant un incident.
    let reconnectAttempts = 0
    let pingTimer = null
    let pongTimer = null

    const clearHeartbeat = () => {
      if (pingTimer) { clearInterval(pingTimer); pingTimer = null }
      if (pongTimer) { clearTimeout(pongTimer); pongTimer = null }
    }

    const startHeartbeat = (ws) => {
      clearHeartbeat()
      pingTimer = setInterval(() => {
        if (ws.readyState !== WebSocket.OPEN) return
        try { ws.send(JSON.stringify({ type: 'ping' })) } catch {}
        if (pongTimer) clearTimeout(pongTimer)
        pongTimer = setTimeout(() => {
          // Pong missed → consider WS dead
          log.ws('pong-miss', { endpoint: 'ws/status' })
          try { ws.close() } catch {}
        }, 5000)
      }, 25000)
    }

    const connect = async () => {
      if (document.hidden) return
      const token = await ensureFreshToken()
      if (!token) {
        // No valid token; retry shortly (e.g. just after login race or refresh failure)
        setTimeout(() => connect(), 1000)
        return
      }
      // B4 : ticket à usage unique ; en cas d'échec (ex. Redis indisponible)
      // le cookie HttpOnly authentifie encore le handshake.
      const ticket = await getWsTicket()
      intentionalClose = false
      const freshStatusUrl = wsUrl(`ws/status?poll=${statusPoll}${ticket ? `&ticket=${ticket}` : ''}`)
      const ws = new WebSocket(freshStatusUrl)
      wsRef.current = ws

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data)
        if (data.type === 'pong') {
          if (pongTimer) { clearTimeout(pongTimer); pongTimer = null }
          return
        }
        if (data.type === 'status_update') {
          applyUpdate(data)
        }
      }

      ws.onopen = () => {
        log.ws('open', { endpoint: 'ws/status' })
        setWsLive(true)
        reconnectAttempts = 0
        startHeartbeat(ws)
      }

      const scheduleReconnect = () => {
        clearHeartbeat()
        if (intentionalClose) return
        if (reconnectTimer.current) return  // already scheduled
        const delay = Math.min(3000 * 2 ** reconnectAttempts, 60000)
        reconnectAttempts += 1
        reconnectTimer.current = setTimeout(() => {
          reconnectTimer.current = null
          connect()
        }, delay)
      }

      ws.onclose = () => {
        log.ws('close', { endpoint: 'ws/status' })
        if (wsRef.current === ws) wsRef.current = null
        setWsLive(false)
        scheduleReconnect()
      }

      ws.onerror = () => {
        log.ws('error', { endpoint: 'ws/status' })
        // onclose always fires after onerror — reconnect handled there
      }
    }

    // Force a fresh connection: cancel pending reconnect, close current ws,
    // refresh token, reopen. Used by wake detector and watchdog.
    // Set intentionalClose=true *before* close() so the closing socket's
    // onclose does not arm a stale 3s reconnectTimer that would race the
    // fresh socket created here.
    const forceReconnect = async () => {
      log.ws('force-reconnect', { endpoint: 'ws/status' })
      setReconnecting(true)
      setWsLive(false)
      if (reconnectTimer.current) { clearTimeout(reconnectTimer.current); reconnectTimer.current = null }
      clearHeartbeat()
      const ws = wsRef.current
      wsRef.current = null
      if (ws) {
        intentionalClose = true   // suppress onclose → scheduleReconnect race
        try { ws.close() } catch {}
      }
      await connect()             // connect() resets intentionalClose=false
    }
    wakeReconnectRef.current = forceReconnect

    // A WS is "live" only when present AND readyState is CONNECTING (0) or OPEN (1).
    // CLOSING (2) and CLOSED (3) mean we should not assume an existing socket;
    // some browsers/states fail to fire onclose, so we must not gate on truthiness alone.
    const isLive = (ws) => ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)

    const handleVisibility = () => {
      if (document.hidden) {
        intentionalClose = true
        clearHeartbeat()
        if (wsRef.current) { try { wsRef.current.close() } catch {}; wsRef.current = null }
        setWsLive(false)
      } else {
        if (!isLive(wsRef.current)) forceReconnect()
      }
    }

    // Reconnect immediately when network comes back
    const handleOnline = () => {
      if (!isLive(wsRef.current)) forceReconnect()
    }

    document.addEventListener('visibilitychange', handleVisibility)
    window.addEventListener('online', handleOnline)
    connect()

    return () => {
      document.removeEventListener('visibilitychange', handleVisibility)
      window.removeEventListener('online', handleOnline)
      intentionalClose = true
      clearHeartbeat()
      if (reconnectTimer.current) { clearTimeout(reconnectTimer.current); reconnectTimer.current = null }
      if (wsRef.current) { try { wsRef.current.close() } catch {} ; wsRef.current = null }
      wakeReconnectRef.current = null
      setWsLive(false)
    }
  }, [statusPoll, ensureFreshToken, applyUpdate, setReconnecting, setWsLive])

  // Wake detection → force reconnect WS + immediate HTTP refetch
  useWakeDetector((info) => {
    log.info('wake detected', info)
    setReconnecting(true)
    if (refetchAgentsRef.current) refetchAgentsRef.current()
    if (wakeReconnectRef.current) wakeReconnectRef.current()
  })

  // WS health watchdog: independent timer that recovers from cases where the
  // normal reconnect chain is broken (browser-throttled setTimeout, onclose
  // that never fires, stale reconnectTimer.current ref). Runs every 30s.
  useEffect(() => {
    const tick = () => {
      if (document.hidden) return
      const ws = wsRef.current
      const live = ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)
      if (live) return
      // No live WS. If a reconnect timer is armed, give it 1 more cycle then
      // assume it has been suspended/lost and force a fresh attempt.
      if (reconnectTimer.current) {
        // Clear stale timer; force a clean reconnect via forceReconnect.
        clearTimeout(reconnectTimer.current)
        reconnectTimer.current = null
      }
      if (wakeReconnectRef.current) {
        log.info('watchdog: no live ws, forcing reconnect')
        wakeReconnectRef.current()
      }
    }
    const id = setInterval(tick, 30000)
    return () => clearInterval(id)
  }, [])
}
