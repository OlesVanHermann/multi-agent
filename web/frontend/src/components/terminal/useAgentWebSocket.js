import { useState, useEffect, useRef } from 'react'
import { wsUrl } from '../../basePath'
import { getWsTicket } from '../../apiFetch'
import { createLogger } from '../../lib/logger'
import { useWakeDetector } from '../../lib/useWakeDetector'

// Cycle de vie du WebSocket ws/agent/{id} : heartbeat 25s/5s, reconnexion 2s,
// pause quand l'onglet est caché, watchdog 30s, détection de réveil.
// Les effets applicatifs (output, input_sync, reset, cleanup) sont délégués
// au composant via handlersRef (ref mise à jour à chaque render → pas de
// closure périmée).
export function useAgentWebSocket({ agentId, pollInterval, ensureFreshToken, handlersRef }) {
  // wsState: 'live' | 'jwt' | 'rate' | 'forbidden' | 'overloaded' | 'disconnected'
  const [wsState, setWsState] = useState('disconnected')
  const wsRef = useRef(null)
  const reconnectTimeoutRef = useRef(null)
  const wakeReconnectRef = useRef(null)
  const disconnectTimerRef = useRef(null)

  // Load and connect
  useEffect(() => {
    if (!agentId) return
    const log = createLogger(`Terminal:${agentId}`)

    const clearDisconnectTimer = () => {
      if (disconnectTimerRef.current) { clearTimeout(disconnectTimerRef.current); disconnectTimerRef.current = null }
    }
    // Grace period before showing the red 'disconnected' badge. Fast reconnects
    // (wake detector, watchdog, hide/show — median gap ~0.5s) shouldn't flash red.
    // Mapped error states (jwt/rate/forbidden/overloaded) are shown immediately;
    // a real outage still turns red after 3s (reconnect attempts keep failing).
    const applyWsState = (s) => {
      if (s === 'disconnected') {
        if (disconnectTimerRef.current) return  // grace already pending — keep it
        disconnectTimerRef.current = setTimeout(() => {
          disconnectTimerRef.current = null
          setWsState('disconnected')
        }, 3000)
      } else {
        clearDisconnectTimer()
        setWsState(s)
      }
    }

    setWsState('disconnected')
    if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current)
    handlersRef.current.onReset()

    // Fetch initial output
    handlersRef.current.fetchInitial()

    // Connect WebSocket (pauses when tab is hidden)
    let intentionalClose = false
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
          log.ws('pong-miss', { agentId })
          try { ws.close() } catch {}
        }, 5000)
      }, 25000)
    }

    const connect = async () => {
      if (document.hidden) return  // Don't connect if tab is hidden
      const token = await ensureFreshToken()
      if (!token) {
        reconnectTimeoutRef.current = setTimeout(() => {
          reconnectTimeoutRef.current = null  // clear fired timer so scheduleReconnect/visibility/online aren't blocked
          connect()
        }, 1000)
        return
      }
      // B4 : ticket à usage unique demandé à chaque (re)connexion ;
      // en cas d'échec le cookie HttpOnly authentifie encore le handshake.
      const ticket = await getWsTicket()
      intentionalClose = false
      const freshWsUrl = wsUrl(`ws/agent/${agentId}?poll=${pollInterval}${ticket ? `&ticket=${ticket}` : ''}`)
      const ws = new WebSocket(freshWsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        if (wsRef.current !== ws) {
          // This WS is stale (component changed agentId or unmounted while connecting)
          ws.close()
          return
        }
        applyWsState('live')
        log.ws('open', { agentId })
        startHeartbeat(ws)
      }

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data)

        if (data.type === 'pong') {
          if (pongTimer) { clearTimeout(pongTimer); pongTimer = null }
          return
        }
        if (data.type === 'output') {
          handlersRef.current.onOutput(data.output || '')
        }
        else if (data.type === 'input_sync') {
          handlersRef.current.onInputSync(data.current_input || '')
        }
        else if (data.type === 'error') {
          handlersRef.current.onError(data.message)
        }
      }

      const scheduleReconnect = () => {
        clearHeartbeat()
        if (intentionalClose) return  // prevent zombie reconnects after cleanup
        if (reconnectTimeoutRef.current) return  // already scheduled, avoid double-fire
        reconnectTimeoutRef.current = setTimeout(() => {
          reconnectTimeoutRef.current = null
          connect()
        }, 2000)
      }

      ws.onclose = (event) => {
        // Map close codes set by backend (/ws/agent handler)
        const codeToState = {
          4001: 'jwt',        // JWT invalid/missing
          4002: 'rate',       // Rate limit exceeded
          4005: 'forbidden',  // Agent 000 forbidden
          1013: 'overloaded', // Server overloaded (max connections)
        }
        const newState = codeToState[event.code] || 'disconnected'
        applyWsState(newState)
        log.ws('close', { agentId, code: event.code, state: newState })
        if (wsRef.current === ws) wsRef.current = null  // clear stale ref so handleVisibility can reconnect
        if (newState !== 'forbidden') scheduleReconnect()  // 4005 (agent 000) is permanent — don't hammer every 2s
      }

      ws.onerror = () => {
        // Don't set 'disconnected' here — onclose fires next with the real code
        log.ws('error', { agentId })
      }
    }

    // Force-close current WS and reconnect (used by wake detector and watchdog).
    // intentionalClose=true *before* close() suppresses the stale onclose →
    // scheduleReconnect path that would race the fresh socket.
    const forceReconnect = async () => {
      log.ws('force-reconnect', { agentId })
      if (reconnectTimeoutRef.current) { clearTimeout(reconnectTimeoutRef.current); reconnectTimeoutRef.current = null }
      clearHeartbeat()
      const ws = wsRef.current
      wsRef.current = null
      applyWsState('disconnected')
      if (ws) {
        intentionalClose = true
        try { ws.close() } catch {}
      }
      await connect()             // connect() resets intentionalClose=false
    }
    wakeReconnectRef.current = forceReconnect

    // Live = present AND CONNECTING/OPEN. Do not gate on truthiness alone:
    // CLOSING/CLOSED refs without onclose firing would block reconnects.
    const isLive = (ws) => ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)

    const handleVisibility = () => {
      if (document.hidden) {
        intentionalClose = true
        clearHeartbeat()
        if (reconnectTimeoutRef.current) { clearTimeout(reconnectTimeoutRef.current); reconnectTimeoutRef.current = null }
        // Only close OPEN sockets immediately; CONNECTING ones are handled in onopen to avoid Chrome warning
        if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
          wsRef.current.close()
          wsRef.current = null
        }
        clearDisconnectTimer()
        setWsState('disconnected')  // tab hidden: invisible to user, mark immediately
      } else {
        intentionalClose = false
        if (!isLive(wsRef.current) && !reconnectTimeoutRef.current) forceReconnect()
      }
    }

    // Reconnect immediately when network comes back (only if no active/pending connection)
    const handleOnline = () => {
      if (!isLive(wsRef.current) && !reconnectTimeoutRef.current) forceReconnect()
    }

    document.addEventListener('visibilitychange', handleVisibility)
    window.addEventListener('online', handleOnline)
    connect()

    return () => {
      document.removeEventListener('visibilitychange', handleVisibility)
      window.removeEventListener('online', handleOnline)
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current)
      clearDisconnectTimer()
      intentionalClose = true
      clearHeartbeat()
      wakeReconnectRef.current = null
      if (wsRef.current) {
        // Only close OPEN sockets; CONNECTING ones will be closed in onopen via stale check
        if (wsRef.current.readyState === WebSocket.OPEN) {
          wsRef.current.close()
        }
        wsRef.current = null
      }
      handlersRef.current.onCleanup()
    }
  }, [agentId, pollInterval, ensureFreshToken])

  // Wake handler: trigger force-reconnect on wake event
  useWakeDetector(() => {
    if (wakeReconnectRef.current) wakeReconnectRef.current()
  })

  // WS health watchdog (per terminal). Recovers from broken reconnect chains
  // (suspended setTimeout, onclose never firing). 30s cadence.
  useEffect(() => {
    if (!agentId) return
    const log = createLogger(`Terminal:${agentId}`)
    const tick = () => {
      if (document.hidden) return
      const ws = wsRef.current
      const live = ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)
      if (live) return
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
        reconnectTimeoutRef.current = null
      }
      if (wakeReconnectRef.current) {
        log.info('watchdog: no live ws, forcing reconnect')
        wakeReconnectRef.current()
      }
    }
    const id = setInterval(tick, 30000)
    return () => clearInterval(id)
  }, [agentId])

  return wsState
}
