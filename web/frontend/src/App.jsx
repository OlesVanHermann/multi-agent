import React, { useState, useEffect, useRef } from 'react'
import AgentGrid, { AGENT_LABELS } from './components/AgentGrid'
import Terminal from './components/Terminal'
import StatusBar from './components/StatusBar'
import { useAuth } from './AuthProvider'

function App() {
  const { user, logout, isOperator } = useAuth()
  const [agents, setAgents] = useState([])
  const [selectedAgent, setSelectedAgent] = useState(null)
  const [controlPlane, setControlPlane] = useState('100') // Master by default
  const [activePanel, setActivePanel] = useState('control') // 'control' or 'agent'
  const [lastUpdate, setLastUpdate] = useState(null)
  const [redisOk, setRedisOk] = useState(false)
  const wsRef = useRef(null)

  // Fetch agents on mount and periodically
  useEffect(() => {
    const fetchAgents = async () => {
      try {
        const res = await fetch('/api/agents')
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
        const res = await fetch('/api/health')
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
    }, 15000)  // Refresh every 15 seconds for stability

    return () => clearInterval(interval)
  }, [])

  // WebSocket for real-time status
  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/ws/status`

    const connect = () => {
      wsRef.current = new WebSocket(wsUrl)

      wsRef.current.onmessage = (event) => {
        const data = JSON.parse(event.data)
        if (data.type === 'status_update') {
          // Only update if we got valid agent data
          if (data.agents && Array.isArray(data.agents) && data.agents.length > 0) {
            setAgents(data.agents)
            setLastUpdate(new Date())
          }
        }
      }

      wsRef.current.onclose = () => {
        setTimeout(connect, 5000)  // Reconnect after 5 seconds
      }

      wsRef.current.onerror = (err) => {
        console.error('WebSocket error:', err)
      }
    }

    connect()

    return () => {
      if (wsRef.current) {
        wsRef.current.close()
      }
    }
  }, [])

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

  return (
    <div className="app">
      <header className="header">
        <h1>MULTI-AGENT DASHBOARD</h1>
        <div className="header-right">
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
          <Terminal agentId={controlPlane} focused={activePanel === 'control'} />
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
            <Terminal agentId={selectedAgent} focused={activePanel === 'agent'} />
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
