import React, { useState, useEffect } from 'react'
import { api } from '../basePath'

const VALID_PERIODS = [10, 30, 60, 120]

function CrontabPanel() {
  const [entries, setEntries] = useState([])
  const [error, setError] = useState(null)
  const [editing, setEditing] = useState(null) // { agent_id, period }
  const [editPrompt, setEditPrompt] = useState('')
  const [newEntry, setNewEntry] = useState({ agent_id: '', period: 10, prompt: '' })
  const [showNew, setShowNew] = useState(false)

  const fetchData = async () => {
    try {
      const res = await fetch(api('api/config/crontab'))
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setEntries(data.entries || [])
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }

  useEffect(() => { fetchData() }, [])

  const handleCreate = async () => {
    if (!newEntry.agent_id || !newEntry.prompt.trim()) return
    try {
      const res = await fetch(api('api/config/crontab'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newEntry),
      })
      if (!res.ok) {
        const d = await res.json()
        throw new Error(d.detail || `HTTP ${res.status}`)
      }
      setShowNew(false)
      setNewEntry({ agent_id: '', period: 10, prompt: '' })
      fetchData()
    } catch (e) {
      setError(e.message)
    }
  }

  const handleToggle = async (entry) => {
    try {
      const res = await fetch(api('api/config/crontab'), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agent_id: entry.agent_id,
          period: entry.period,
          action: entry.suspended ? 'resume' : 'suspend',
        }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      fetchData()
    } catch (e) {
      setError(e.message)
    }
  }

  const handleSaveEdit = async () => {
    if (!editing) return
    try {
      const res = await fetch(api('api/config/crontab'), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agent_id: editing.agent_id,
          period: editing.period,
          prompt: editPrompt,
        }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setEditing(null)
      fetchData()
    } catch (e) {
      setError(e.message)
    }
  }

  const handleDelete = async (entry) => {
    if (!confirm(`Delete crontab ${entry.agent_id} every ${entry.period}min?`)) return
    try {
      const res = await fetch(api('api/config/crontab'), {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: entry.agent_id, period: entry.period }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      fetchData()
    } catch (e) {
      setError(e.message)
    }
  }

  const startEdit = (entry) => {
    setEditing({ agent_id: entry.agent_id, period: entry.period })
    setEditPrompt(entry.prompt)
  }

  return (
    <div className="login-model-panel">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
        <span style={{ color: 'var(--text-secondary)', fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Crontab Scheduler
        </span>
        <button className="lm-restart-btn" onClick={() => setShowNew(!showNew)}
          style={{ fontSize: '0.7rem' }}>
          {showNew ? 'Cancel' : '+ New'}
        </button>
      </div>
      {error && <p style={{ color: 'var(--red)', fontSize: '0.75rem', marginBottom: '0.5rem' }}>{error}</p>}

      {showNew && (
        <div style={{ padding: '0.5rem', background: 'var(--bg-secondary)', borderRadius: '3px', marginBottom: '0.5rem', fontSize: '0.75rem' }}>
          <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.3rem' }}>
            <input
              placeholder="Agent ID (300)"
              value={newEntry.agent_id}
              onChange={e => setNewEntry({ ...newEntry, agent_id: e.target.value })}
              style={{ background: 'var(--bg-panel)', border: '1px solid var(--border-color)', color: 'var(--text-primary)', padding: '0.2rem 0.4rem', width: '8rem', fontFamily: 'inherit', fontSize: '0.75rem' }}
            />
            <select
              value={newEntry.period}
              onChange={e => setNewEntry({ ...newEntry, period: Number(e.target.value) })}
              className="lm-select"
            >
              {VALID_PERIODS.map(p => <option key={p} value={p}>{p}min</option>)}
            </select>
            <button className="lm-restart-btn" onClick={handleCreate} style={{ color: 'var(--green)', borderColor: 'var(--green)' }}>
              Create
            </button>
          </div>
          <textarea
            placeholder="Prompt content..."
            value={newEntry.prompt}
            onChange={e => setNewEntry({ ...newEntry, prompt: e.target.value })}
            rows={3}
            style={{ width: '100%', background: 'var(--bg-panel)', border: '1px solid var(--border-color)', color: 'var(--text-primary)', padding: '0.3rem', fontFamily: 'inherit', fontSize: '0.7rem', resize: 'vertical' }}
          />
        </div>
      )}

      <table className="lm-table">
        <thead>
          <tr>
            <th>Agent</th>
            <th>Period</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {entries.length === 0 && (
            <tr><td colSpan={4} style={{ color: 'var(--text-secondary)', textAlign: 'center' }}>No crontab entries</td></tr>
          )}
          {entries.map(e => {
            const isEditing = editing && editing.agent_id === e.agent_id && editing.period === e.period
            return (
              <tr key={`${e.agent_id}_${e.period}`}>
                <td style={{ fontWeight: 600 }}>{e.agent_id}</td>
                <td>{e.period}min</td>
                <td>
                  <span style={{ color: e.suspended ? 'var(--orange)' : 'var(--green)', fontSize: '0.7rem' }}>
                    {e.suspended ? 'suspended' : 'active'}
                  </span>
                </td>
                <td style={{ display: 'flex', gap: '0.3rem' }}>
                  <button className="lm-restart-btn" onClick={() => handleToggle(e)} title={e.suspended ? 'Resume' : 'Suspend'}>
                    {e.suspended ? 'Resume' : 'Pause'}
                  </button>
                  <button className="lm-restart-btn" onClick={() => startEdit(e)} title="Edit prompt">
                    Edit
                  </button>
                  <button className="lm-restart-btn" onClick={() => handleDelete(e)} title="Delete"
                    style={{ color: 'var(--red)', borderColor: 'var(--red)' }}>
                    Del
                  </button>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>

      {editing && (
        <div style={{ padding: '0.5rem', background: 'var(--bg-secondary)', borderRadius: '3px', marginTop: '0.5rem', fontSize: '0.75rem' }}>
          <div style={{ color: 'var(--text-secondary)', marginBottom: '0.3rem' }}>
            Editing {editing.agent_id} / {editing.period}min
          </div>
          <textarea
            value={editPrompt}
            onChange={e => setEditPrompt(e.target.value)}
            rows={4}
            style={{ width: '100%', background: 'var(--bg-panel)', border: '1px solid var(--border-color)', color: 'var(--text-primary)', padding: '0.3rem', fontFamily: 'inherit', fontSize: '0.7rem', resize: 'vertical' }}
          />
          <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.3rem' }}>
            <button className="lm-restart-btn" onClick={handleSaveEdit} style={{ color: 'var(--green)', borderColor: 'var(--green)' }}>Save</button>
            <button className="lm-restart-btn" onClick={() => setEditing(null)}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  )
}

export default CrontabPanel
