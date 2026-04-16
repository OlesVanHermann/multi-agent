import React, { useState, useEffect } from 'react'

const DEFAULT_COLORS = {
  idle: '#00ff88',
  active: '#00ff88',
  busy: '#ff9500',
  context_warning: '#ff9500',
  context_compacted: '#ff4444',
  blocked: '#ff4444',
  error: '#ff4444',
  stopped: '#555',
}

const COLOR_LABELS = {
  idle: 'Idle',
  active: 'Active',
  busy: 'Busy / Working',
  context_warning: 'Context Warning',
  context_compacted: 'Context Compacted',
  blocked: 'Blocked',
  error: 'Error',
  stopped: 'Stopped',
}

const STORAGE_KEY = 'agent_colors'

function loadColors() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    return saved ? { ...DEFAULT_COLORS, ...JSON.parse(saved) } : { ...DEFAULT_COLORS }
  } catch {
    return { ...DEFAULT_COLORS }
  }
}

function applyColors(colors) {
  const root = document.documentElement
  Object.entries(colors).forEach(([status, color]) => {
    root.style.setProperty(`--status-${status}`, color)
  })
}

function CouleursPanel() {
  const [colors, setColors] = useState(loadColors)

  useEffect(() => {
    applyColors(colors)
  }, [colors])

  const handleChange = (status, color) => {
    const updated = { ...colors, [status]: color }
    setColors(updated)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(updated))
  }

  const handleReset = () => {
    setColors({ ...DEFAULT_COLORS })
    localStorage.removeItem(STORAGE_KEY)
  }

  return (
    <div className="login-model-panel">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
        <span style={{ color: 'var(--text-secondary)', fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Agent Status Colors
        </span>
        <button className="lm-restart-btn" onClick={handleReset} style={{ fontSize: '0.7rem' }}>
          Reset
        </button>
      </div>

      <table className="lm-table">
        <thead>
          <tr>
            <th>Status</th>
            <th>Color</th>
            <th>Preview</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(COLOR_LABELS).map(([status, label]) => (
            <tr key={status}>
              <td>{label}</td>
              <td>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                  <input
                    type="color"
                    value={colors[status]}
                    onChange={e => handleChange(status, e.target.value)}
                    style={{ width: '1.5rem', height: '1.2rem', border: 'none', background: 'none', cursor: 'pointer', padding: 0 }}
                  />
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
                    {colors[status]}
                  </span>
                </div>
              </td>
              <td>
                <span style={{
                  display: 'inline-block',
                  width: '1.2rem',
                  height: '1.2rem',
                  borderRadius: '3px',
                  background: colors[status],
                  opacity: 0.9,
                }} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export { loadColors, applyColors }
export default CouleursPanel
