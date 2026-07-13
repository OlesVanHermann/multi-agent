import React from 'react'
import { getShortLabel } from './cells'

// Favoris config mode: list of active agents with label + select (no/1-6)
function FavorisConfig({ agents, hiddenIds, agentNames, favoris, onFavChange, onAgentOpen }) {
  const activeIds = new Set()
  agents.forEach(a => {
    const base = a.id.split('-')[0]
    if (!hiddenIds.has(base)) activeIds.add(base)
  })
  const allAgents = [...activeIds].sort((a, b) => parseInt(a) - parseInt(b))

  return (
    <div className="fav-config">
      {allAgents.map(aid => {
        const label = getShortLabel(aid, agentNames)
        const truncated = label.length > 20 ? label.slice(0, 20) + '…' : label
        const curVal = favoris[aid] || 'no'
        return (
          <div key={aid} className="fav-config-row">
            <span className="fav-config-label" onClick={() => onAgentOpen(aid)}>{truncated}</span>
            <select value={curVal} onChange={e => onFavChange(aid, e.target.value)} className="fav-config-select">
              <option value="no">no</option>
              <option value="1">1</option>
              <option value="2">2</option>
              <option value="3">3</option>
              <option value="4">4</option>
              <option value="5">5</option>
              <option value="6">6</option>
            </select>
          </div>
        )
      })}
    </div>
  )
}

export default FavorisConfig
