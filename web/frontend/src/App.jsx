import React, { useState, useEffect, useRef } from 'react'
import AgentGrid, { AGENT_LABELS } from './components/AgentGrid'
import Terminal from './components/Terminal'
import StatusBar from './components/StatusBar'
import { useAuth } from './AuthProvider'
import { api, wsUrl } from './basePath'

// Polling timing options
const AGENT_POLL_OPTIONS  = [0.3, 0.5, 1, 2, 3]      // ws/agent refresh (seconds)
const STATUS_POLL_OPTIONS = [2, 5, 10, 15, 30]        // ws/status refresh (seconds)
const FETCH_OPTIONS       = [5, 10, 15, 30, 60]       // api fetch interval (seconds)

function usePollSetting(key, defaultVal) {
  const [val, setVal] = useState(() => {
    const saved = localStorage.getItem(`poll_${key}`)
    return saved ? Number(saved) : defaultVal
  })
  const update = (e) => {
    const v = Number(e.target.value)
    setVal(v)
    localStorage.setItem(`poll_${key}`, v)
  }
  return [val, update]
}

function App() {
  const { user, logout, isOperator } = useAuth()
  const [agents, setAgents] = useState([])
  const [selectedAgent, setSelectedAgent] = useState(null)
  const [controlPlane, setControlPlane] = useState('000') // Super-Master by default
  const [activePanel, setActivePanel] = useState('control') // 'control' or 'agent'
  const [lastUpdate, setLastUpdate] = useState(null)
  const [redisOk, setRedisOk] = useState(false)
  const wsRef = useRef(null)

  const [agentPoll, setAgentPoll] = usePollSetting('agent', 1)
  const [statusPoll, setStatusPoll] = usePollSetting('status', 10)
  const [fetchSec, setFetchSec] = usePollSetting('fetch', 15)

  // Fetch agents on mount and periodically
  useEffect(() => {
    const fetchAgents = async () => {
      try {
        const res = await fetch(api('api/agents'))
        const data = await res.json()
        // Only update if we got valid agent data
        if (data.agents && Array.isArray(data.agents) && data.agents.length > 0) {
          setAgents(data.agents)
          setLastUpdate(new Date())
        }
      } catch (err) {
        console.error('Failed to fetch agents:', err)
        // Don't clear agents on error - keep showing last known state
      }
    }

    const checkHealth = async () => {
      try {
        const res = await fetch(api('api/health'))
        const data = await res.json()
        setRedisOk(data.redis)
      } catch (err) {
        setRedisOk(false)
      }
    }

    fetchAgents()
    checkHealth()

    const interval = setInterval(() => {
      fetchAgents()
      checkHealth()
    }, fetchSec * 1000)

    return () => clearInterval(interval)
  }, [fetchSec])

  // WebSocket for real-time status (pauses when tab is hidden)
  useEffect(() => {
    const statusWsUrl = wsUrl(`ws/status?poll=${statusPoll}`)
    let intentionalClose = false

    const connect = () => {
      if (document.hidden) return
      intentionalClose = false
      wsRef.current = new WebSocket(statusWsUrl)

      wsRef.current.onmessage = (event) => {
        const data = JSON.parse(event.data)
        if (data.type === 'status_update') {
          if (data.agents && Array.isArray(data.agents) && data.agents.length > 0) {
            setAgents(data.agents)
            setLastUpdate(new Date())
          }
        }
      }

      wsRef.current.onclose = () => {
        if (!intentionalClose) setTimeout(connect, 5000)
      }

      wsRef.current.onerror = (err) => {
        console.error('WebSocket error:', err)
      }
    }

    const handleVisibility = () => {
      if (document.hidden) {
        // Tab hidden: close WS to save CPU
        intentionalClose = true
        if (wsRef.current) { wsRef.current.close(); wsRef.current = null }
      } else {
        // Tab visible: reconnect
        if (!wsRef.current) connect()
      }
    }

    document.addEventListener('visibilitychange', handleVisibility)
    connect()

    return () => {
      document.removeEventListener('visibilitychange', handleVisibility)
      intentionalClose = true
      if (wsRef.current) wsRef.current.close()
    }
  }, [statusPoll])

  const handleAgentClick = (agentId) => {
    const num = parseInt(agentId)
    if (num < 200 || num >= 900) {
      setControlPlane(agentId)
      setActivePanel('control')
    } else {
      setSelectedAgent(agentId)
      setActivePanel('agent')
    }
  }

  const activeCount = agents.filter(a =>
    a.status === 'active' || a.status === 'busy' || a.status === 'idle'
  ).length
  const warningCount = agents.filter(a => a.status === 'context_warning').length
  const compactedCount = agents.filter(a => a.status === 'context_compacted').length

  return (
    <div className="app">
      <header className="header">
        <h1>MULTI-AGENT DASHBOARD</h1>
        <div className="header-right">
          <span className="poll-group">
            <label className="poll-label">Terminal</label>
            <select value={agentPoll} onChange={setAgentPoll} className="poll-select" title="Tmux terminal refresh rate">
              {AGENT_POLL_OPTIONS.map(v => <option key={v} value={v}>{v}s</option>)}
            </select>
          </span>
          <span className="poll-group">
            <label className="poll-label">Grille</label>
            <select value={statusPoll} onChange={setStatusPoll} className="poll-select" title="Agent grid status refresh">
              {STATUS_POLL_OPTIONS.map(v => <option key={v} value={v}>{v}s</option>)}
            </select>
          </span>
          <span className="poll-group">
            <label className="poll-label">Health</label>
            <select value={fetchSec} onChange={setFetchSec} className="poll-select" title="Health check + agent count refresh">
              {FETCH_OPTIONS.map(v => <option key={v} value={v}>{v}s</option>)}
            </select>
          </span>
          <span className="user">{user?.username || 'guest'}</span>
          <button onClick={logout} className="logout-btn">Logout</button>
        </div>
      </header>

      <main className="main">
        {/* Left column: Agent Grid */}
        <section className="panel agents-panel">
          <h2>AGENTS ({agents.length})</h2>
          <AgentGrid
            agents={agents}
            selectedAgent={selectedAgent}
            controlAgent={controlPlane}
            onAgentClick={handleAgentClick}
          />
        </section>

        {/* Center column: Control Plane Terminal */}
        <section
          className={`panel control-panel ${activePanel === 'control' ? 'panel-active' : ''}`}
          onMouseEnter={() => setActivePanel('control')}
        >
          <div className="panel-header">
            <h2>CONTROL ({controlPlane}) — {AGENT_LABELS[controlPlane] || getAgentType(controlPlane)}</h2>
          </div>
          <Terminal agentId={controlPlane} focused={activePanel === 'control'} pollInterval={agentPoll} />
        </section>

        {/* Right column: Selected Agent Terminal */}
        <section
          className={`panel agent-panel ${activePanel === 'agent' ? 'panel-active' : ''}`}
          onMouseEnter={() => setActivePanel('agent')}
        >
          <div className="panel-header">
            <h2>AGENT {selectedAgent ? `(${selectedAgent}) — ${AGENT_LABELS[selectedAgent] || getAgentType(selectedAgent)}` : '---'}</h2>
          </div>
          {selectedAgent ? (
            <Terminal agentId={selectedAgent} focused={activePanel === 'agent'} pollInterval={agentPoll} />
          ) : (
            <div className="no-selection">
              Select an agent from the grid
            </div>
          )}
        </section>
      </main>

      <StatusBar
        agentCount={agents.length}
        activeCount={activeCount}
        warningCount={warningCount}
        compactedCount={compactedCount}
        redisOk={redisOk}
        lastUpdate={lastUpdate}
      />
    </div>
  )
}

function getAgentType(id) {
  const num = parseInt(id)
  if (num < 100) return 'Super-Master'
  if (num < 200) return 'Master'
  if (num < 300) return 'Explorer'
  if (num < 400) return 'Developer'
  if (num < 500) return 'Integrator'
  if (num < 600) return 'Tester'
  if (num < 700) return 'Releaser'
  if (num < 800) return 'Documenter'
  if (num < 900) return 'Monitor'
  return 'Architect'
}

export default App
