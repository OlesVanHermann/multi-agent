import React, { useState, useEffect } from 'react'
import { api } from '../basePath'

function KeepAlivePanel() {
  const [entries, setEntries] = useState([])
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState({}) // { profile: true }

  const fetchData = async () => {
    try {
      const res = await fetch(api('api/config/keepalive'))
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setEntries(data.entries || [])
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }

  useEffect(() => { fetchData() }, [])

  const handleStart = async (profile) => {
    setLoading(l => ({ ...l, [profile]: true }))
    try {
      const res = await fetch(api('api/config/keepalive/start'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profile }),
      })
      if (!res.ok) {
        const d = await res.json()
        throw new Error(d.detail || `HTTP ${res.status}`)
      }
      setTimeout(fetchData, 2000)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(l => ({ ...l, [profile]: false }))
    }
  }

  const handleStop = async (profile) => {
    setLoading(l => ({ ...l, [profile]: true }))
    try {
      const res = await fetch(api('api/config/keepalive/stop'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profile }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setTimeout(fetchData, 1000)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(l => ({ ...l, [profile]: false }))
    }
  }

  return (
    <div className="login-model-panel">
      <div style={{ marginBottom: '0.5rem' }}>
        <span style={{ color: 'var(--text-secondary)', fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Keep Alive Sessions
        </span>
      </div>
      {error && <p style={{ color: 'var(--red)', fontSize: '0.75rem', marginBottom: '0.5rem' }}>{error}</p>}

      <table className="lm-table">
        <thead>
          <tr>
            <th>Profile</th>
            <th>Tmux</th>
            <th>Keepalive</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          {entries.length === 0 && (
            <tr><td colSpan={4} style={{ color: 'var(--text-secondary)', textAlign: 'center' }}>No profiles found</td></tr>
          )}
          {entries.map(e => {
            const isLoading = loading[e.profile]
            return (
              <tr key={e.profile}>
                <td style={{ fontWeight: 600 }}>{e.profile}</td>
                <td>
                  <span style={{ color: e.running ? 'var(--green)' : 'var(--gray)', fontSize: '0.75rem' }}>
                    {e.running ? 'running' : 'stopped'}
                  </span>
                </td>
                <td>
                  <span style={{
                    color: e.keepalive ? 'var(--green)' : e.suspended ? 'var(--orange)' : 'var(--gray)',
                    fontSize: '0.75rem'
                  }}>
                    {e.keepalive ? 'active' : e.suspended ? 'suspended' : 'off'}
                  </span>
                </td>
                <td>
                  {e.running ? (
                    <button
                      className="lm-restart-btn"
                      onClick={() => handleStop(e.profile)}
                      disabled={isLoading}
                      style={{ color: 'var(--red)', borderColor: 'var(--red)' }}
                    >
                      {isLoading ? '...' : 'Stop'}
                    </button>
                  ) : (
                    <button
                      className="lm-restart-btn"
                      onClick={() => handleStart(e.profile)}
                      disabled={isLoading}
                      style={{ color: 'var(--green)', borderColor: 'var(--green)' }}
                    >
                      {isLoading ? '...' : 'Start'}
                    </button>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export default KeepAlivePanel
