import React, { useState, useEffect, useRef } from 'react'
import { api } from '../basePath'

const RESTART_COOLDOWN = 60 // seconds
const TMUX_WIDTH_OPTIONS = [80, 90, 100, 110, 120, 132, 180, 220, 280]

function getDefaultPanel(agentId, mode) {
  const num = parseInt(agentId)
  const suffixNum = agentId.includes('-') ? parseInt(agentId.split('-')[1]) : num
  const isControl = mode === 'x45' ? (suffixNum < 200) : (num < 200 || num >= 900)
  return isControl ? 'control' : 'agent'
}

function LoginModelPanel({ hidden, mode, panelConfig, onPanelChange, runningAgents }) {
  const runningIds = new Set((runningAgents || []).map(a => a.id))
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [restartUntil, setRestartUntil] = useState({}) // { agentId: epoch_ms }
  const [activeRestart, setActiveRestart] = useState(null) // agentId currently restarting (API call in flight)
  const [now, setNow] = useState(Date.now())
  const [tmuxWidth, setTmuxWidth] = useState(null)
  const timerRef = useRef(null)

  // Tick every second while any agent is in cooldown
  useEffect(() => {
    const hasActive = Object.values(restartUntil).some(until => until > Date.now())
    if (hasActive && !timerRef.current) {
      timerRef.current = setInterval(() => setNow(Date.now()), 1000)
    } else if (!hasActive && timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [restartUntil, now])

  const fetchData = async () => {
    try {
      const res = await fetch(api('api/config/logins-models'))
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setData(await res.json())
      setError(null)
    } catch (err) {
      setError(err.message)
    }
  }

  // Fetch all config every time panel is opened
  useEffect(() => {
    if (!hidden) {
      fetchData()
      fetch(api('api/config/tmux-width'))
        .then(r => r.json())
        .then(d => setTmuxWidth(d.width))
        .catch(() => {})
      fetch(api('api/config/panel'))
        .then(r => r.json())
        .then(d => { if (onPanelChange && d.overrides) Object.entries(d.overrides).forEach(([id, p]) => onPanelChange(id, p)) })
        .catch(() => {})
    }
  }, [hidden])

  const handleTmuxWidth = async (newWidth) => {
    try {
      const res = await fetch(api('api/config/tmux-width'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ width: newWidth }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setTmuxWidth(newWidth)
    } catch (err) {
      setError(err.message)
    }
  }

  const handleChange = async (agentId, type, value) => {
    try {
      const res = await fetch(api('api/config/logins-models'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: agentId, type, value }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      await fetchData()
    } catch (err) {
      setError(err.message)
    }
  }

  const handleAction = async (agentId, action) => {
    if (activeRestart) return // already one in flight
    const until = Date.now() + RESTART_COOLDOWN * 1000
    setRestartUntil(prev => ({ ...prev, [agentId]: until }))
    setActiveRestart(agentId)
    setError(null)
    try {
      const res = await fetch(api(`api/agent/${agentId}/${action}`), { method: 'POST' })
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}))
        throw new Error(detail.detail || `HTTP ${res.status}`)
      }
    } catch (err) {
      setError(`${action} ${agentId}: ${err.message}`)
    } finally {
      setActiveRestart(null)
    }
  }

  const handleEffort = async (agentId, level) => {
    try {
      const res = await fetch(api('api/config/effort'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: agentId, level }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      await fetchData()
    } catch (err) {
      setError(err.message)
    }
  }

  const handlePanelToggle = async (agentId, panel) => {
    const def = getDefaultPanel(agentId, mode)
    const sendPanel = panel === def ? '' : panel // send "" to remove override if matches default
    try {
      const res = await fetch(api('api/config/panel'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: agentId, panel: sendPanel }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      if (onPanelChange) onPanelChange(agentId, sendPanel)
    } catch (err) {
      setError(err.message)
    }
  }

  const getRemaining = (agentId) => {
    const until = restartUntil[agentId]
    if (!until) return 0
    return Math.max(0, Math.ceil((until - now) / 1000))
  }

  if (error && !data) return <div className="login-model-panel" style={{ display: hidden ? 'none' : undefined }}><p style={{ color: 'var(--red)' }}>Error: {error}</p></div>
  if (!data) return <div className="login-model-panel" style={{ display: hidden ? 'none' : undefined }}><p style={{ color: 'var(--text-secondary)' }}>Loading...</p></div>

  const { logins, models, default_login, default_model, default_effort, agents, groups } = data
  const groupMap = {}
  ;(groups || []).forEach(g => { groupMap[g.id] = g })

  return (
    <div className="login-model-panel" style={{ display: hidden ? 'none' : undefined }}>
      {error && <p style={{ color: 'var(--red)', fontSize: '0.7rem', margin: '0 0 0.5rem' }}>Error: {error}</p>}
      <table className="lm-table">
        <thead>
          <tr>
            <th>Agent</th>
            <th>Login</th>
            <th>Model</th>
            <th>Effort</th>
            <th>Panel</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {/* Tmux width row */}
          <tr className="lm-default-row">
            <td><strong>tmux</strong></td>
            <td colSpan="5">
              <span className="lm-width-group">
                {TMUX_WIDTH_OPTIONS.map(w => (
                  <button
                    key={w}
                    className={`lm-width-btn ${tmuxWidth === w ? 'lm-width-active' : ''}`}
                    onClick={() => handleTmuxWidth(w)}
                  >
                    {w}
                  </button>
                ))}
                <span className="lm-width-label">cols</span>
              </span>
            </td>
          </tr>
          {/* Default row */}
          <tr className="lm-default-row">
            <td><strong>default</strong></td>
            <td>
              <select
                className="lm-select"
                value={default_login}
                onChange={(e) => handleChange('default', 'login', e.target.value)}
              >
                {logins.map(l => <option key={l} value={l}>{l}</option>)}
              </select>
            </td>
            <td>
              <select
                className="lm-select"
                value={default_model}
                onChange={(e) => handleChange('default', 'model', e.target.value)}
              >
                {models.map(m => <option key={m} value={m}>{m}</option>)}
              </select>
            </td>
            <td>
              <span className="lm-effort-toggle">
                {['L', 'M', 'H'].map(lvl => (
                  <button
                    key={lvl}
                    className={`lm-effort-btn ${(default_effort || 'H') === lvl ? 'lm-effort-active' : ''}`}
                    onClick={() => handleEffort('default', lvl)}
                  >{lvl}</button>
                ))}
              </span>
            </td>
            <td></td>
            <td></td>
          </tr>
          {/* Agent rows */}
          {agents.map((agent, idx) => {
            const remaining = getRemaining(agent.id)
            const isCooling = remaining > 0
            const isThis = activeRestart === agent.id
            const blocked = !!activeRestart && !isThis
            const group = agent.id.split('-')[0]
            const isCompound = agent.id.includes('-')
            const prevGroup = idx > 0 ? agents[idx - 1].id.split('-')[0] : group
            const prevCompound = idx > 0 ? agents[idx - 1].id.includes('-') : isCompound
            // Group header row for first agent of an x45/z21 group
            const groupInfo = isCompound ? groupMap[group] : null
            const isFirstInGroup = groupInfo && (idx === 0 || agents[idx - 1].id.split('-')[0] !== group)

            // No border on agent row if header row already provides the separation
            const modeBreak = idx > 0 && isCompound !== prevCompound && !isFirstInGroup
            const groupBreak = idx > 0 && !modeBreak && group !== prevGroup && !isFirstInGroup
            const breakClass = modeBreak ? 'lm-mode-break' : groupBreak ? (isCompound ? 'lm-mode-break' : 'lm-group-break') : ''
            const groupHeader = isFirstInGroup ? (
              <tr key={`group-${group}`} className="lm-mode-break lm-group-header">
                <td><strong>{group}-*</strong></td>
                <td><span className="lm-group-type">{groupInfo.type}</span></td>
                <td colSpan="3"></td>
                <td>
                  <span className="lm-actions-group">
                    {['start', 'stop', 'restart'].map(act => {
                      const gRemaining = getRemaining(`group-${group}`)
                      const gCooling = gRemaining > 0
                      const gThis = activeRestart === `group-${group}`
                      const gBlocked = !!activeRestart && !gThis
                      return (
                        <button key={act}
                          className={`lm-restart-btn ${gThis ? 'lm-restarting' : ''}`}
                          onClick={() => handleAction(group, act)}
                          disabled={gCooling || gBlocked || gThis}
                          title={`./scripts/agent.sh ${act} ${group}`}
                        >
                          {gThis ? '...' : gCooling ? `${gRemaining}s` : act}
                        </button>
                      )
                    })}
                  </span>
                </td>
              </tr>
            ) : null

            return (
              <React.Fragment key={agent.id}>
              {groupHeader}
              <tr className={breakClass}>
                <td style={{ color: runningIds.has(agent.id) ? 'var(--lightgreen)' : 'var(--text-secondary)' }}>
                  {runningIds.has(agent.id) ? `(${agent.id})` : agent.id}
                </td>
                <td>
                  <select
                    className={`lm-select ${agent.login_source === 'override' ? 'lm-override' : ''}`}
                    value={agent.login_source === 'override' ? agent.login : ''}
                    onChange={(e) => handleChange(agent.id, 'login', e.target.value)}
                  >
                    <option value="">({default_login})</option>
                    {logins.map(l => <option key={l} value={l}>{l}</option>)}
                  </select>
                </td>
                <td>
                  <select
                    className={`lm-select ${agent.model_source === 'override' ? 'lm-override' : ''}`}
                    value={agent.model_source === 'override' ? agent.model : ''}
                    onChange={(e) => handleChange(agent.id, 'model', e.target.value)}
                  >
                    <option value="">({default_model})</option>
                    {models.map(m => <option key={m} value={m}>{m}</option>)}
                  </select>
                </td>
                <td>
                  <span className="lm-effort-toggle">
                    {['L', 'M', 'H'].map(lvl => {
                      const isActive = agent.effort === lvl
                      const isOverride = agent.effort_source === 'override'
                      return (
                        <button
                          key={lvl}
                          className={`lm-effort-btn ${isActive ? (isOverride ? 'lm-effort-override' : 'lm-effort-active') : ''}`}
                          onClick={() => handleEffort(agent.id, isActive && isOverride ? '' : lvl)}
                        >{lvl}</button>
                      )
                    })}
                  </span>
                </td>
                <td>
                  {(() => {
                    const def = getDefaultPanel(agent.id, mode)
                    const current = (panelConfig && panelConfig[agent.id]) || def
                    return (
                      <span className="lm-panel-toggle">
                        <button
                          className={`lm-panel-btn ${current === 'control' ? 'lm-panel-active' : ''}`}
                          onClick={() => handlePanelToggle(agent.id, 'control')}
                        >M</button>
                        <button
                          className={`lm-panel-btn ${current === 'agent' ? 'lm-panel-active' : ''}`}
                          onClick={() => handlePanelToggle(agent.id, 'agent')}
                        >D</button>
                      </span>
                    )
                  })()}
                </td>
                <td>
                  <span className="lm-actions-group">
                    {['start', 'stop', 'restart'].map(act => (
                      <button key={act}
                        className={`lm-restart-btn ${isThis ? 'lm-restarting' : ''}`}
                        onClick={() => handleAction(agent.id, act)}
                        disabled={isCooling || blocked || isThis}
                        title={`./scripts/agent.sh ${act} ${agent.id}`}
                      >
                        {isThis ? '...' : isCooling ? `${remaining}s` : act}
                      </button>
                    ))}
                  </span>
                </td>
              </tr>
              </React.Fragment>
            )
          })}
        </tbody>
      </table>

    </div>
  )
}

export default LoginModelPanel
