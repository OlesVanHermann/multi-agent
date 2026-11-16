import { useState, useEffect, useRef, useCallback } from 'react'
import { api } from '../basePath'
import { createLogger } from '../lib/logger'

const log = createLogger('App')

// E2 : le WS status est la source temps réel ; le polling HTTP (agents +
// health) n'est actif qu'en fallback quand le WS n'est pas live, avec
// back-off exponentiel sur erreurs (plafond 60s). À chaque bascule de
// wsLive, un fetch unique de réconciliation récupère les champs complets
// (ctx, etc.) que le WS ne transporte pas.
export function useAgentsData(fetchSec, wsLive) {
  const [agents, setAgents] = useState([])
  const [mode, setMode] = useState('pipeline')
  const [triangles, setTriangles] = useState({})
  const [agentNames, setAgentNames] = useState({})
  const [lastUpdate, setLastUpdate] = useState(null)
  // redisStatus: 'unknown' | 'ok' | 'noauth' | 'jwt' | 'down'
  const [redisStatus, setRedisStatus] = useState('unknown')
  const [reconnecting, setReconnecting] = useState(false)
  const refetchAgentsRef = useRef(null)

  const applyUpdate = useCallback((data) => {
    // Only update if we got valid agent data
    if (data.agents && Array.isArray(data.agents) && data.agents.length > 0) {
      // Le WS n'envoie qu'une projection {id, status, last_seen} ; on fusionne
      // avec l'état connu pour préserver les champs complets (ctx…). Le 000
      // reste visible comme dans /api/agents, mais ses contrôles restent
      // interdits par les routes backend et le WebSocket terminal.
      const incoming = data.agents
      setAgents(prev => {
        const prevById = {}
        for (const a of prev) prevById[a.id] = a
        return incoming.map(a => ({ ...prevById[a.id], ...a }))
      })
      setLastUpdate(new Date())
      if (data.mode) setMode(data.mode)
      if (data.triangles) setTriangles(data.triangles)
      if (data.agent_names) setAgentNames(data.agent_names)
      setReconnecting(false)
    }
  }, [])

  // Fetch de réconciliation à chaque (re)montage / bascule wsLive,
  // puis polling de fallback uniquement quand le WS n'est pas live.
  useEffect(() => {
    let cancelled = false
    let timer = null
    let failures = 0

    const fetchAgents = async () => {
      try {
        const res = await fetch(api('api/agents'))
        const data = await res.json()
        applyUpdate(data)
        return true
      } catch (err) {
        log.error('fetchAgents failed', { error: err.message })
        // Don't clear agents on error - keep showing last known state
        return false
      }
    }

    const checkHealth = async () => {
      try {
        const res = await fetch(api('api/health'))
        if (res.status === 401 || res.status === 403) { setRedisStatus('jwt'); return }
        if (!res.ok)                                  { setRedisStatus('down'); return }
        const data = await res.json()
        if (typeof data.redis === 'string') {
          setRedisStatus(data.redis)                  // "ok" | "noauth" | "down"
        } else if (typeof data.redis === 'boolean') {
          setRedisStatus(data.redis ? 'ok' : 'down')  // backward-compat
        }
      } catch (err) {
        setRedisStatus('down')                        // network / backend unreachable
      }
    }

    refetchAgentsRef.current = () => { fetchAgents(); checkHealth() }

    const tick = async () => {
      const ok = await fetchAgents()
      await checkHealth()
      if (cancelled) return
      failures = ok ? 0 : failures + 1
      const delaySec = Math.min(fetchSec * 2 ** Math.min(failures, 5), 60)
      timer = setTimeout(tick, delaySec * 1000)
    }

    if (wsLive) {
      // WS source unique : un seul fetch de réconciliation, pas de polling
      fetchAgents()
      checkHealth()
    } else {
      tick()
    }

    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
      refetchAgentsRef.current = null
    }
  }, [fetchSec, applyUpdate, wsLive])

  return {
    agents, mode, triangles, agentNames, lastUpdate, redisStatus,
    reconnecting, setReconnecting, applyUpdate, refetchAgentsRef,
  }
}
