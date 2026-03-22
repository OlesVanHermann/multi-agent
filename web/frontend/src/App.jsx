import React, { useState, useEffect, useRef } from 'react'
import AgentGrid from './components/AgentGrid'
import AgentSidebarX45 from './components/AgentSidebarX45'
import Terminal from './components/Terminal'
import FileViewer from './components/FileViewer'
import LoginModelPanel from './components/LoginModelPanel'
import StatusBar from './components/StatusBar'
import DevChat from './components/DevChat'

import { useAuth, LoginForm } from './AuthProvider'
import { api, wsUrl } from './basePath'

// Intercept all fetch() calls to inject JWT Bearer token automatically.
// This secures every API call without modifying individual components.
const _originalFetch = window.fetch
window.fetch = function(url, options = {}) {
  const token = localStorage.getItem('access_token')
  if (token && typeof url === 'string' && (url.startsWith('/api/') || url.includes('/api/'))) {
    const headers = new Headers(options.headers || {})
    if (!headers.has('Authorization')) {
      headers.set('Authorization', `Bearer ${token}`)
    }
    options = { ...options, headers }
  }
  return _originalFetch.call(this, url, options)
}

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
  const { user, logout, isOperator, isAuthenticated } = useAuth()

  if (!isAuthenticated) return <LoginForm />
  const [agents, setAgents] = useState([])
  const [mode, setMode] = useState('pipeline')
  const [triangles, setTriangles] = useState({})
  const [agentNames, setAgentNames] = useState({})
  const [selectedAgent, setSelectedAgent] = useState(null)
  const [controlPlane, setControlPlane] = useState('000') // Super-Master by default
  const [activePanel, setActivePanel] = useState('control') // 'control' or 'agent'
  const [panelConfig, setPanelConfig] = useState({})
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
    let intentionalClose = false

    const connect = () => {
      if (document.hidden) return
      intentionalClose = false
      // Re-read token on every reconnect (token may have been refreshed after network loss)
      const freshStatusUrl = wsUrl(`ws/status?poll=${statusPoll}`)
      wsRef.current = new WebSocket(freshStatusUrl)

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
        if (!intentionalClose) setTimeout(connect, 3000)
      }

      wsRef.current.onerror = (err) => {
        console.error('WebSocket error:', err)
      }
    }

    const handleVisibility = () => {
      if (document.hidden) {
        intentionalClose = true
        if (wsRef.current) { wsRef.current.close(); wsRef.current = null }
      } else {
        if (!wsRef.current) connect()
      }
    }

    // Reconnect immediately when network comes back
    const handleOnline = () => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
        connect()
      }
    }

    document.addEventListener('visibilitychange', handleVisibility)
    window.addEventListener('online', handleOnline)
    connect()

    return () => {
      document.removeEventListener('visibilitychange', handleVisibility)
      window.removeEventListener('online', handleOnline)
      intentionalClose = true
      if (wsRef.current) wsRef.current.close()
    }
  }, [statusPoll])

  // Fetch panel config on mount
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

  const [selectedFile, setSelectedFile] = useState(null)
  const [showLoginModel, setShowLoginModel] = useState(false)
  const [showColors, setShowColors] = useState(false)
  const [showCrontab, setShowCrontab] = useState(false)
  const [showKeepAlive, setShowKeepAlive] = useState(false)
  const [keepAliveEntries, setKeepAliveEntries] = useState([])
  const [keepAliveInfo, setKeepAliveInfo] = useState({})
  const [keepAliveUsage, setKeepAliveUsage] = useState({})
  const [selectedKeepAlive, setSelectedKeepAlive] = useState(null)
  const [crontabEntries, setCrontabEntries] = useState([])
  const [crontabForm, setCrontabForm] = useState(false)
  const [crontabEdit, setCrontabEdit] = useState(null) // {agent_id, period, prompt} or null
  const [cronAgent, setCronAgent] = useState('')
  const [cronPeriod, setCronPeriod] = useState(10)
  const [cronPrompt, setCronPrompt] = useState('')

  const handleAgentClick = (agentId) => {
    setSelectedFile(null) // clear file view when selecting an agent
    // Check panel override first
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
    // Default logic
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

  // Crontab helpers
  const fetchCrontab = async () => {
    try {
      const res = await fetch(api('api/config/crontab'))
      const data = await res.json()
      setCrontabEntries(data.entries || [])
    } catch (err) { console.error('crontab fetch:', err) }
  }

  useEffect(() => { if (showCrontab) fetchCrontab() }, [showCrontab])

  const cronCreate = async () => {
    if (!cronAgent) return alert('Selectionnez un agent')
    if (!cronPrompt.trim()) return alert('Le prompt ne peut pas etre vide')
    const res = await fetch(api('api/config/crontab'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent_id: cronAgent, period: cronPeriod, prompt: cronPrompt })
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      return alert(err.detail || 'Erreur creation')
    }
    setCrontabForm(false); setCronAgent(''); setCronPeriod(10); setCronPrompt('')
    fetchCrontab()
  }

  const cronUpdate = async () => {
    if (!crontabEdit) return
    if (!cronAgent) return alert('Selectionnez un agent')
    if (!cronPrompt.trim()) return alert('Le prompt ne peut pas etre vide')
    const agentChanged = cronAgent !== crontabEdit.agent_id
    const periodChanged = cronPeriod !== crontabEdit.period
    if (agentChanged || periodChanged) {
      // Agent or period changed: delete old + create new
      await fetch(api('api/config/crontab'), {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: crontabEdit.agent_id, period: crontabEdit.period })
      })
      const res = await fetch(api('api/config/crontab'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: cronAgent, period: cronPeriod, prompt: cronPrompt })
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        return alert(err.detail || 'Erreur modification')
      }
    } else {
      await fetch(api('api/config/crontab'), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: crontabEdit.agent_id, period: crontabEdit.period, prompt: cronPrompt })
      })
    }
    setCrontabEdit(null); setCrontabForm(false); setCronPrompt('')
    fetchCrontab()
  }

  const cronSuspendResume = async (entry) => {
    await fetch(api('api/config/crontab'), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent_id: entry.agent_id, period: entry.period, action: entry.suspended ? 'resume' : 'suspend' })
    })
    fetchCrontab()
  }

  const cronDelete = async (entry) => {
    await fetch(api('api/config/crontab'), {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent_id: entry.agent_id, period: entry.period })
    })
    fetchCrontab()
  }

  const cronStartEdit = (entry) => {
    setCrontabEdit(entry)
    setCronAgent(entry.agent_id)
    setCronPeriod(entry.period)
    setCronPrompt(entry.prompt)
    setCrontabForm(true)
  }

  const cronStartCopy = (entry) => {
    setCrontabEdit(null)
    setCronAgent(entry.agent_id)
    setCronPeriod(entry.period)
    setCronPrompt(entry.prompt)
    setCrontabForm(true)
  }

  const cronStartNew = () => {
    setCrontabEdit(null)
    setCronAgent(agents.length > 0 ? agents[0].id : '')
    setCronPeriod(10)
    setCronPrompt('')
    setCrontabForm(true)
  }

  // Keep Alive helpers
  const kaProbe = async (profile) => {
    try {
      const res = await fetch(api('api/config/keepalive/probe'), {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ profile })
      })
      if (res.ok) {
        const data = await res.json()
        setKeepAliveInfo(prev => ({ ...prev, [profile]: data.info }))
      }
    } catch (err) { console.error('probe:', err) }
  }

  const fetchKeepAlive = async () => {
    try {
      const res = await fetch(api('api/config/keepalive'))
      const data = await res.json()
      const entries = data.entries || []
      setKeepAliveEntries(entries)
      for (const e of entries) {
        if (e.running) kaProbe(e.profile)
      }
    } catch (err) { console.error('keepalive fetch:', err) }
    // Also fetch usage bars
    try {
      const res = await fetch(api('api/usage'))
      const data = await res.json()
      const profiles = data.plan?.profiles || {}
      setKeepAliveUsage(profiles)
      // Also fill info from static files if not already probed
      for (const [pname, pdata] of Object.entries(profiles)) {
        if (pdata.info && !keepAliveInfo[pname]) {
          setKeepAliveInfo(prev => ({ ...prev, [pname]: pdata.info }))
        }
      }
    } catch (err) { console.error('usage fetch:', err) }
  }

  useEffect(() => { if (showKeepAlive) fetchKeepAlive() }, [showKeepAlive])

  const kaStart = async (profile) => {
    await fetch(api('api/config/keepalive/start'), {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ profile })
    })
    fetchKeepAlive()
  }

  const kaStop = async (profile) => {
    await fetch(api('api/config/keepalive/stop'), {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ profile })
    })
    fetchKeepAlive()
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
          onClick={() => { setShowLoginModel(!showLoginModel); setShowColors(false); setShowCrontab(false); setShowKeepAlive(false) }}
        >
          Login &amp; Model
        </button>
        <button
          className={`config-btn ${showColors ? 'config-btn-active' : ''}`}
          onClick={() => { setShowColors(!showColors); setShowLoginModel(false); setShowCrontab(false); setShowKeepAlive(false) }}
        >
          Couleurs
        </button>
        <button
          className={`config-btn ${showCrontab ? 'config-btn-active' : ''}`}
          onClick={() => { setShowCrontab(!showCrontab); setShowLoginModel(false); setShowColors(false); setShowKeepAlive(false) }}
        >
          Crontab
        </button>
        <button
          className={`config-btn ${showKeepAlive ? 'config-btn-active' : ''}`}
          onClick={() => { setShowKeepAlive(!showKeepAlive); setShowLoginModel(false); setShowColors(false); setShowCrontab(false) }}
        >
          Keep Alive
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
          <span className="poll-label">{user?.username}</span>
          <button onClick={logout} className="logout-btn">Logout</button>
        </div>
      </header>

      <main className="main">
        {/* Left column: Agent Grid or x45 Sidebar */}
        <section className="panel agents-panel">
          <h2>AGENTS ({agents.length})</h2>
          {mode === 'x45' ? (
            <AgentSidebarX45
              agents={agents}
              triangles={triangles}
              selectedAgent={selectedAgent}
              controlAgent={controlPlane}
              onAgentClick={handleAgentClick}
              onFileClick={handleFileClick}
              agentNames={agentNames}
              chatElement={<DevChat />}
              username={user?.username || 'default'}
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
          {mode !== 'x45' && <div style={{height:'180px',flexShrink:0,borderTop:'1px solid var(--border-color)'}}><DevChat /></div>}
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
          <LoginModelPanel hidden={!showLoginModel} mode={mode} panelConfig={panelConfig} onPanelChange={handlePanelChange} runningAgents={agents} />
          {showColors && (
            <div className="color-legend">
              <h3>Status — Couleurs</h3>
              <table>
                <thead><tr><th>Status</th><th>Couleur</th><th>Description</th></tr></thead>
                <tbody>
                  <tr><td><span className="agent-cell blue" style={{display:'inline-block',width:40,textAlign:'center'}}>●</span></td><td>Bleu</td><td>waiting_approval — En attente de confirmation</td></tr>
                  <tr><td><span className="agent-cell darkblue" style={{display:'inline-block',width:40,textAlign:'center'}}>●</span></td><td>Bleu foncé</td><td>plan_mode — Mode plan activé</td></tr>
                  <tr><td><span className="agent-cell white" style={{display:'inline-block',width:40,textAlign:'center'}}>●</span></td><td>Blanc</td><td>starting — Démarrage en cours</td></tr>
                  <tr><td><span className="agent-cell green" style={{display:'inline-block',width:40,textAlign:'center'}}>●</span></td><td>Vert foncé</td><td>has_bashes — Bashes en cours d'exécution</td></tr>
                  <tr><td><span className="agent-cell lightgreen" style={{display:'inline-block',width:40,textAlign:'center'}}>●</span></td><td>Vert clair</td><td>busy — Claude en cours (esc to interrupt)</td></tr>
                  <tr><td><span className="agent-cell orange" style={{display:'inline-block',width:40,textAlign:'center'}}>●</span></td><td>Orange</td><td>context_warning — Contexte restant 1-10%</td></tr>
                  <tr><td><span className="agent-cell red" style={{display:'inline-block',width:40,textAlign:'center'}}>●</span></td><td>Rouge</td><td>context_compacted — Contexte compacté</td></tr>
                  <tr><td><span className="agent-cell darkred" style={{display:'inline-block',width:40,textAlign:'center'}}>●</span></td><td>Rouge foncé</td><td>error / blocked — Erreur ou bloqué</td></tr>
                  <tr><td><span className="agent-cell gray" style={{display:'inline-block',width:40,textAlign:'center'}}>●</span></td><td>Gris</td><td>idle / stale — Inactif</td></tr>
                  <tr><td><span className="agent-cell darkgray" style={{display:'inline-block',width:40,textAlign:'center'}}>●</span></td><td>Gris foncé</td><td>stopped — Arrêté</td></tr>
                </tbody>
              </table>
              <h3 style={{marginTop:'1rem'}}>Priorité (haute → basse)</h3>
              <ol style={{margin:'0.5rem 0',paddingLeft:'1.5rem',color:'#ccc',fontSize:'0.85rem'}}>
                <li>context_limit / api_error</li>
                <li>context_compacted (compacting)</li>
                <li>plan_mode</li>
                <li>has_bashes</li>
                <li>busy</li>
                <li>context_warning (1-10%)</li>
                <li>active / idle</li>
              </ol>
            </div>
          )}
          {showCrontab && (
            <div className="crontab-3split">
              <div className="crontab-list">
                <div className="crontab-header">
                  <h3>TACHES PLANIFIEES</h3>
                  <button className="crontab-add-btn" onClick={cronStartNew}>+ Nouveau</button>
                </div>
                <table className="crontab-table">
                  <thead>
                    <tr><th>Agent</th><th>Periode</th><th>Prompt</th><th>Status</th><th>Actions</th></tr>
                  </thead>
                  <tbody>
                    {crontabEntries.map((e, i) => (
                      <tr key={i} className={e.suspended ? 'crontab-suspended' : ''}>
                        <td>{e.agent_id}</td>
                        <td>{e.period} min</td>
                        <td className="crontab-prompt-cell">{e.prompt.length > 60 ? e.prompt.slice(0, 60) + '...' : e.prompt}</td>
                        <td><span className={`crontab-status ${e.suspended ? 'crontab-status-off' : 'crontab-status-on'}`}>{e.suspended ? 'Suspendu' : 'Actif'}</span></td>
                        <td className="crontab-actions">
                          <button title="Modifier" onClick={() => cronStartEdit(e)}>Modifier</button>
                          <button title="Copier vers un autre agent/periode" onClick={() => cronStartCopy(e)}>Copier</button>
                          <button title={e.suspended ? 'Reactiver la tache' : 'Suspendre la tache'} className={e.suspended ? 'crontab-resume' : 'crontab-suspend'} onClick={() => cronSuspendResume(e)}>
                            {e.suspended ? 'Activer' : 'Suspendre'}
                          </button>
                          <button title="Supprimer la tache" className="crontab-del" onClick={() => cronDelete(e)}>Supprimer</button>
                        </td>
                      </tr>
                    ))}
                    {crontabEntries.length === 0 && (
                      <tr><td colSpan={5} style={{textAlign:'center',color:'var(--text-secondary)',fontStyle:'italic'}}>Aucune tache planifiee</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
              <div className="crontab-editor">
                {crontabForm ? (
                  <div className="crontab-form">
                    <div className="crontab-form-inline">
                      <span className="crontab-form-label">{crontabEdit ? 'Modifier' : 'Nouveau'}</span>
                      <select value={cronAgent} onChange={e => setCronAgent(e.target.value)}>
                        <option value="">Agent</option>
                        {agents.map(a => <option key={a.id} value={a.id}>{a.id}</option>)}
                      </select>
                      <select value={cronPeriod} onChange={e => setCronPeriod(Number(e.target.value))}>
                        {[10, 30, 60, 120].map(v => <option key={v} value={v}>{v}min</option>)}
                      </select>
                    </div>
                    <div className="crontab-form-row">
                      <label>Prompt</label>
                      <textarea rows={4} value={cronPrompt} onChange={e => setCronPrompt(e.target.value)} placeholder="Contenu du prompt..." />
                    </div>
                    <div className="crontab-form-actions">
                      <button onClick={crontabEdit ? cronUpdate : cronCreate}>
                        {crontabEdit ? 'Modifier' : 'Ajouter'}
                      </button>
                      <button onClick={() => { setCrontabForm(false); setCrontabEdit(null) }}>Annuler</button>
                    </div>
                  </div>
                ) : (
                  <div className="crontab-editor-empty">Cliquer sur Modifier ou + Nouveau</div>
                )}
              </div>
              <div className="crontab-bottom">
                <div className="crontab-terminal-header">SCHEDULER — 001</div>
                <Terminal agentId="001" focused={activePanel === 'agent'} pollInterval={agentPoll} />
              </div>
            </div>
          )}
          {showKeepAlive && (
            <div className="crontab-split">
              <div className="crontab-top">
                <div className="crontab-header">
                  <h3>LOGIN KEEP ALIVE</h3>
                </div>
                <table className="crontab-table keepalive-table">
                  <thead>
                    <tr><th>Profil</th><th>Login</th><th>Org</th><th>Email</th><th>CWD</th><th>Actions</th></tr>
                  </thead>
                  <tbody>
                    {keepAliveEntries.map((e) => {
                      const ki = keepAliveInfo[e.profile]
                      const usage = keepAliveUsage[e.profile]
                      const bars = usage?.bars || []
                      return (
                      <React.Fragment key={e.profile}>
                      <tr>
                        <td>
                          <button
                            className={`crontab-status ${e.running ? 'crontab-status-on' : 'crontab-status-off'} ka-profile-btn`}
                            onClick={() => setSelectedKeepAlive(e.session)}
                          >{e.profile}</button>
                        </td>
                        <td className="keepalive-info">{ki ? (ki.login_method || '?').slice(0, 20) : (e.running ? '...' : '—')}</td>
                        <td className="keepalive-info">{ki ? (ki.organization || '?').slice(0, 20) : ''}</td>
                        <td className="keepalive-info">{ki ? (ki.email || '?').slice(0, 20) : ''}</td>
                        <td className="keepalive-info">{ki ? './' + (ki.cwd || '').split('/').filter(Boolean).pop() + '/' : ''}</td>
                        <td className="crontab-actions">
                          {e.running
                            ? <button className="crontab-suspend" onClick={() => kaStop(e.profile)}>Stop</button>
                            : <button className="crontab-resume" onClick={() => kaStart(e.profile)}>Start</button>
                          }
                        </td>
                      </tr>
                      <tr className="ka-usage-row">
                        <td></td>
                        <td colSpan="5">
                          {bars.length > 0 ? (
                            <span className="lm-usage-bars">
                              {bars.map((b, i) => (
                                <span key={i} className="lm-usage-bar" title={`${b.label}: ${b.percent}% — resets ${b.resets || ''}`}>
                                  <span className="lm-usage-bar-fill" style={{
                                    width: `${b.percent}%`,
                                    background: b.percent > 80 ? 'var(--red)' : b.percent > 50 ? 'var(--orange)' : 'var(--green)'
                                  }} />
                                  <span className="lm-usage-bar-text">{b.percent}%</span>
                                </span>
                              ))}
                            </span>
                          ) : (
                            <span style={{ color: 'var(--text-secondary)', fontSize: '0.6rem', fontStyle: 'italic' }}>pas de données usage</span>
                          )}
                        </td>
                      </tr>
                      </React.Fragment>
                      )
                    })}
                    {keepAliveEntries.length === 0 && (
                      <tr><td colSpan={6} style={{textAlign:'center',color:'var(--text-secondary)',fontStyle:'italic'}}>Aucun profil de login</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
              <div className="crontab-bottom">
                <div className="crontab-terminal-header">
                  KEEPALIVE — {selectedKeepAlive || '(cliquez Voir)'}
                </div>
                {selectedKeepAlive
                  ? <Terminal agentId={selectedKeepAlive} focused={activePanel === 'agent'} pollInterval={agentPoll} />
                  : <div className="no-selection">Selectionnez un login pour voir son terminal</div>
                }
              </div>
            </div>
          )}
          {!showLoginModel && !showColors && !showCrontab && !showKeepAlive && (selectedFile ? (
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
