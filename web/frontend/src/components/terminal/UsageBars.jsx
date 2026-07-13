import React, { useState, useEffect } from 'react'
import { api } from '../../basePath'

// Barres d'usage du plan Claude pour le login de l'agent (api/usage/{id}).
function UsageBars({ agentId }) {
  const [usage, setUsage] = useState(null)

  useEffect(() => {
    if (!agentId) return
    fetch(api(`api/usage/${agentId}`))
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d?.login) setUsage(d) })
      .catch(() => {})
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
      )) : <span className="usage-bar-pct" title="Usage data unavailable (personal account)">N/A</span>}
    </span>
  )
}

export default UsageBars
