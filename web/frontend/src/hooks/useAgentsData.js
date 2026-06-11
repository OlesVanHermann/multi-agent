import { useState, useEffect, useRef, useCallback } from 'react'
import { api } from '../basePath'
import { createLogger } from '../lib/logger'

const log = createLogger('App')

// Source unique des données agents : fetch HTTP périodique + health check.
// applyUpdate est partagé avec le WS status (useStatusWebSocket) pour que
// les deux canaux alimentent le même état.
export function useAgentsData(fetchSec) {
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
      setAgents(data.agents)
      setLastUpdate(new Date())
      if (data.mode) setMode(data.mode)
      if (data.triangles) setTriangles(data.triangles)
      if (data.agent_names) setAgentNames(data.agent_names)
      setReconnecting(false)
    }
  }, [])

  // Fetch agents on mount and periodically
  useEffect(() => {
    const fetchAgents = async () => {
      try {
        const res = await fetch(api('api/agents'))
        const data = await res.json()
        applyUpdate(data)
      } catch (err) {
        log.error('fetchAgents failed', { error: err.message })
        // Don't clear agents on error - keep showing last known state
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
    fetchAgents()
    checkHealth()

    const interval = setInterval(() => {
      fetchAgents()
      checkHealth()
    }, fetchSec * 1000)

    return () => {
      clearInterval(interval)
      refetchAgentsRef.current = null
    }
  }, [fetchSec, applyUpdate])

  return {
    agents, mode, triangles, agentNames, lastUpdate, redisStatus,
    reconnecting, setReconnecting, applyUpdate, refetchAgentsRef,
  }
}
