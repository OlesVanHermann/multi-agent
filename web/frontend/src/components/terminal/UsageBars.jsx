import React, { useState, useEffect } from 'react'
import { apiFetch } from '../../apiFetch'

// Barres d'usage du plan Claude pour le login de l'agent (api/usage/{id}).
function UsageBars({ agentId }) {
  const initialLogin = agentId?.startsWith('002-') ? agentId.slice(4) : ''
  const [usage, setUsage] = useState(
    initialLogin ? { login: initialLogin, bars: [], status: 'loading' } : null
  )

  useEffect(() => {
    if (!agentId) return
    let active = true
    const refresh = () => apiFetch(`api/usage/${agentId}`, { cache: 'no-store' })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (active && d?.login) setUsage(d) })
      .catch(() => {})
    refresh()
    const timer = window.setInterval(refresh, 15000)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [agentId])

  if (!usage) return null
  return (
    <span className="usage-bars">
      <span className="usage-bar-name">{usage.login}</span>
      {usage.bars?.length ? usage.bars.map((b, i) => (
        <span key={i} className="usage-bar-item" title={`${b.label}: ${b.percent}% used${b.resets ? ' — Resets ' + b.resets : ''}`}>
          <span className="usage-bar-track">
            <span className="usage-bar-fill" style={{width: `${Math.min(b.percent, 100)}%`}} />
          </span>
          <span className="usage-bar-pct">{b.percent}%</span>
        </span>
      )) : <span className="usage-bar-pct" title={usage.status || 'Usage indisponible'}>
        {usage.status === 'loading' ? '…' : usage.status === 'login_required' ? 'login requis' : 'N/A'}
      </span>}
    </span>
  )
}

export default UsageBars
