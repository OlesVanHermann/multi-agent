import React, { useState, useEffect, useRef } from 'react'
import AgentGrid from './components/AgentGrid'
import AgentSidebarX45 from './components/AgentSidebarX45'
import Terminal from './components/Terminal'
import FileViewer from './components/FileViewer'
import LoginModelPanel from './components/LoginModelPanel'
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
  const [mode, setMode] = useState('pipeline')
  const [triangles, setTriangles] = useState({})
  const [agentNames, setAgentNames] = useState({})
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
          if (data.mode) setMode(data.mode)
          if (data.triangles) setTriangles(data.triangles)
          if (data.agent_names) setAgentNames(data.agent_names)
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
            if (data.mode) setMode(data.mode)
            if (data.triangles) setTriangles(data.triangles)
            if (data.agent_names) setAgentNames(data.agent_names)
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

  const [selectedFile, setSelectedFile] = useState(null)
  const [showLoginModel, setShowLoginModel] = useState(false)
  const [showColors, setShowColors] = useState(false)
  const [panelConfig, setPanelConfig] = useState({})

  useEffect(() => {
    fetch(api('api/config/panel'))
      .then(r => r.json())
      .then(d => setPanelConfig(d.overrides || {}))
      .catch(() => {})
  }, [])

  const handlePanelChange = (agentId, panel) => {
    setPanelConfig(prev => {
      const next = { ...prev }
      if (panel === '') {
        delete next[agentId]
      } else {
        next[agentId] = panel
      }
      return next
    })
  }

  const handleAgentClick = (agentId) => {
    setSelectedFile(null) // clear file view when selecting an agent
    const override = panelConfig[agentId]
    if (override) {
      if (override === 'control') {
        setControlPlane(agentId)
        setActivePanel('control')
      } else {
        setSelectedAgent(agentId)
        setActivePanel('agent')
      }
      return
    }
    const num = parseInt(agentId)
    // For compound IDs (341-141), use suffix to determine role
    const suffixNum = agentId.includes('-') ? parseInt(agentId.split('-')[1]) : num
    // x45: 0xx/1xx go to control (incl. master satellites); pipeline: 0xx/1xx + 900+
    const isControl = mode === 'x45' ? (suffixNum < 200) : (num < 200 || num >= 900)
    if (isControl) {
      setControlPlane(agentId)
      setActivePanel('control')
    } else {
      setSelectedAgent(agentId)
      setActivePanel('agent')
    }
  }

  const handleFileClick = (filePath) => {
    setSelectedFile(filePath)
    setActivePanel('agent')
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
        <button
          className={`config-btn ${showLoginModel ? 'config-btn-active' : ''}`}
          onClick={() => { setShowLoginModel(!showLoginModel); setShowColors(false) }}
        >
          Login &amp; Model
        </button>
        <button
          className={`config-btn ${showColors ? 'config-btn-active' : ''}`}
          onClick={() => { setShowColors(!showColors); setShowLoginModel(false) }}
        >
          Couleurs
        </button>
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
        {/* Left column: Agent Grid or x45 Sidebar */}
        <section className="panel agents-panel">
          <h2>AGENTS ({agents.length}){mode === 'x45' ? ' — x45' : ''}</h2>
          {mode === 'x45' ? (
            <AgentSidebarX45
              agents={agents}
              triangles={triangles}
              selectedAgent={selectedAgent}
              controlAgent={controlPlane}
              onAgentClick={handleAgentClick}
              onFileClick={handleFileClick}
              agentNames={agentNames}
            />
          ) : (
            <AgentGrid
              agents={agents}
              selectedAgent={selectedAgent}
              controlAgent={controlPlane}
              onAgentClick={handleAgentClick}
              agentNames={agentNames}
            />
          )}
        </section>

        {/* Center column: Control Plane Terminal */}
        <section
          className={`panel control-panel ${activePanel === 'control' ? 'panel-active' : ''}`}
          onMouseEnter={() => setActivePanel('control')}
        >
          <div className="panel-header">
            <h2>CONTROL ({controlPlane}) — {agentNames[controlPlane.split('-')[0]] || getAgentType(controlPlane)}</h2>
          </div>
          <Terminal agentId={controlPlane} focused={activePanel === 'control'} pollInterval={agentPoll} />
        </section>

        {/* Right column: Selected Agent Terminal */}
        <section
          className={`panel agent-panel ${activePanel === 'agent' ? 'panel-active' : ''}`}
          onMouseEnter={() => setActivePanel('agent')}
        >
          <div className="panel-header">
            <h2>AGENT {selectedAgent ? `(${selectedAgent}) — ${agentNames[selectedAgent.split('-')[0]] || getAgentType(selectedAgent)}` : '---'}</h2>
          </div>
          <LoginModelPanel hidden={!showLoginModel} mode={mode} panelConfig={panelConfig} onPanelChange={handlePanelChange} />
          {showColors && (
            <div className="color-legend">
              <h3>Couleurs des agents</h3>
              <table>
                <thead>
                  <tr><th>Couleur</th><th>Statut</th></tr>
                </thead>
                <tbody>
                  <tr><td><span className="agent-cell lightgreen" style={{width:28,height:16,display:'inline-flex',fontSize:'0.5rem'}}>345</span></td><td>busy - travaille activement</td></tr>
                  <tr><td><span className="agent-cell gray" style={{width:28,height:16,display:'inline-flex',fontSize:'0.5rem'}}>200</span></td><td>active / idle / stale</td></tr>
                  <tr><td><span className="agent-cell blue" style={{width:28,height:16,display:'inline-flex',fontSize:'0.5rem'}}>000</span></td><td>starting / waiting_approval</td></tr>
                  <tr><td><span className="agent-cell orange" style={{width:28,height:16,display:'inline-flex',fontSize:'0.5rem'}}>500</span></td><td>context_warning / error / blocked</td></tr>
                  <tr><td><span className="agent-cell red" style={{width:28,height:16,display:'inline-flex',fontSize:'0.5rem'}}>100</span></td><td>context_compacted (pulsing)</td></tr>
                  <tr><td><span className="agent-cell darkgray" style={{width:28,height:16,display:'inline-flex',fontSize:'0.5rem'}}>600</span></td><td>stopped</td></tr>
                </tbody>
              </table>
              <h3 style={{marginTop:'1rem'}}>Priorite visuelle</h3>
              <ol style={{fontSize:'0.75rem',color:'#ccc',paddingLeft:'1.2rem',lineHeight:'1.8'}}>
                <li><strong style={{color:'var(--red)'}}>Rouge pulsant</strong> - context compacted, action urgente</li>
                <li><strong style={{color:'var(--orange)'}}>Orange</strong> - warning / erreur / bloque</li>
                <li><strong style={{color:'var(--lightgreen)'}}>Vert clair</strong> - busy, agent actif</li>
                <li><strong style={{color:'var(--blue)'}}>Bleu</strong> - demarrage / attente approbation</li>
                <li><strong style={{color:'var(--gray)'}}>Gris</strong> - actif mais idle</li>
                <li><strong style={{color:'#666'}}>Gris fonce</strong> - arrete</li>
              </ol>
            </div>
          )}
          {!showLoginModel && !showColors && (selectedFile ? (
            <FileViewer filePath={selectedFile} />
          ) : selectedAgent ? (
            <Terminal agentId={selectedAgent} focused={activePanel === 'agent'} pollInterval={agentPoll} />
          ) : (
            <div className="no-selection">
              Select an agent from the grid
            </div>
          ))}
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
