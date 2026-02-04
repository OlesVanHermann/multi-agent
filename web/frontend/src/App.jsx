import React, { useState, useEffect, useRef } from 'react'
import AgentGrid from './components/AgentGrid'
import Terminal from './components/Terminal'
import StatusBar from './components/StatusBar'

function App() {
  const [agents, setAgents] = useState([])
  const [selectedAgent, setSelectedAgent] = useState(null)
  const [controlPlane, setControlPlane] = useState('100') // Master by default
  const [lastUpdate, setLastUpdate] = useState(null)
  const [redisOk, setRedisOk] = useState(false)
  const wsRef = useRef(null)

  // Fetch agents on mount and periodically
  useEffect(() => {
    const fetchAgents = async () => {
      try {
        const res = await fetch('/api/agents')
        const data = await res.json()
        setAgents(data.agents)
        setLastUpdate(new Date())
      } catch (err) {
        console.error('Failed to fetch agents:', err)
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
    }, 5000)

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
          setAgents(data.agents)
          setLastUpdate(new Date())
        }
      }

      wsRef.current.onclose = () => {
        setTimeout(connect, 3000)
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
    setSelectedAgent(agentId)
  }

  const handleControlPlaneToggle = () => {
    setControlPlane(prev => prev === '100' ? '900' : '100')
  }

  const activeCount = agents.filter(a =>
    a.status === 'busy' || a.status === 'idle'
  ).length

  return (
    <div className="app">
      <header className="header">
        <h1>MULTI-AGENT DASHBOARD</h1>
        <div className="header-right">
          <span className="user">octave</span>
        </div>
      </header>

      <main className="main">
        {/* Left column: Agent Grid */}
        <section className="panel agents-panel">
          <h2>AGENTS ({agents.length})</h2>
          <AgentGrid
            agents={agents}
            selectedAgent={selectedAgent}
            onAgentClick={handleAgentClick}
          />
        </section>

        {/* Center column: Control Plane Terminal */}
        <section className="panel control-panel">
          <div className="panel-header">
            <h2>CONTROL PLANE ({controlPlane})</h2>
            <button onClick={handleControlPlaneToggle} className="toggle-btn">
              Switch to {controlPlane === '100' ? '900' : '100'}
            </button>
          </div>
          <Terminal agentId={controlPlane} />
        </section>

        {/* Right column: Selected Agent Terminal */}
        <section className="panel agent-panel">
          <div className="panel-header">
            <h2>AGENT {selectedAgent || '---'}</h2>
            {selectedAgent && (
              <span className="agent-type">
                {getAgentType(selectedAgent)}
              </span>
            )}
          </div>
          {selectedAgent ? (
            <Terminal agentId={selectedAgent} />
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
