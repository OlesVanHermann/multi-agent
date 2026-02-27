import React, { useState, useEffect, useRef } from 'react'
import { api } from '../basePath'

const RESTART_COOLDOWN = 60 // seconds

function LoginModelPanel() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [restartUntil, setRestartUntil] = useState({}) // { agentId: epoch_ms }
  const [now, setNow] = useState(Date.now())
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

  useEffect(() => { fetchData() }, [])

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

  const handleRestart = async (agentId) => {
    const until = Date.now() + RESTART_COOLDOWN * 1000
    setRestartUntil(prev => ({ ...prev, [agentId]: until }))
    setError(null)
    try {
      const res = await fetch(api(`api/agent/${agentId}/restart`), { method: 'POST' })
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}))
        throw new Error(detail.detail || `HTTP ${res.status}`)
      }
    } catch (err) {
      setError(`restart ${agentId}: ${err.message}`)
      // Don't clear cooldown on error — agent.sh may have partially executed
    }
  }

  const getRemaining = (agentId) => {
    const until = restartUntil[agentId]
    if (!until) return 0
    return Math.max(0, Math.ceil((until - now) / 1000))
  }

  if (error && !data) return <div className="login-model-panel"><p style={{ color: 'var(--red)' }}>Error: {error}</p></div>
  if (!data) return <div className="login-model-panel"><p style={{ color: 'var(--text-secondary)' }}>Loading...</p></div>

  const { logins, models, default_login, default_model, agents } = data

  return (
    <div className="login-model-panel">
      {error && <p style={{ color: 'var(--red)', fontSize: '0.7rem', margin: '0 0 0.5rem' }}>Error: {error}</p>}
      <table className="lm-table">
        <thead>
          <tr>
            <th>Agent</th>
            <th>Login</th>
            <th>Model</th>
            <th>Restart</th>
          </tr>
        </thead>
        <tbody>
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
            <td></td>
          </tr>
          {/* Agent rows */}
          {agents.map(agent => {
            const remaining = getRemaining(agent.id)
            const isCooling = remaining > 0
            return (
              <tr key={agent.id}>
                <td>{agent.id}</td>
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
                  <button
                    className={`lm-restart-btn ${isCooling ? 'lm-restarting' : ''}`}
                    onClick={() => handleRestart(agent.id)}
                    disabled={isCooling}
                    title={`./scripts/agent.sh restart ${agent.id}`}
                  >
                    {isCooling ? `${remaining}s` : 'restart'}
                  </button>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export default LoginModelPanel
