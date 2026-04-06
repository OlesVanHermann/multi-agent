import React, { useState } from 'react'

// Agent names come from the backend (extracted from prompt directory names)

function AgentGrid({ agents, selectedAgent, controlAgent, onAgentClick, agentNames = {} }) {
  const [hoveredAgent, setHoveredAgent] = useState(null)

  // Get status color based on server-reported status
  const getStatusColor = (status) => {
    switch (status) {
      case 'has_bashes': return 'green'
      case 'busy': return 'lightgreen'
      case 'active': return 'gray'
      case 'idle': case 'stale': return 'gray'
      case 'starting': return 'white'
      case 'waiting_approval': return 'blue'
      case 'plan_mode': return 'darkblue'
      case 'context_warning': return 'gray'
      case 'context_compacted': return 'red'
      case 'error': case 'blocked': return 'darkred'
      case 'stopped': return 'darkgray'
      default: return 'gray'
    }
  }

  // Label to display at top
  const displayId = hoveredAgent || selectedAgent || controlAgent
  const baseId = displayId?.split('-')[0]
  const name = agentNames[baseId] || ''
  const displayLabel = displayId
    ? name ? `${displayId} — ${name}` : displayId
    : null

  // Group agents into rows: [000,100] [200] [3xx] [400,500,600,700,800] [900+]
  const getRow = (id) => {
    const n = parseInt(id)
    if (n < 200) return 0       // 000, 100
    if (n < 300) return 1       // 200
    if (n < 400) return 2       // 3xx
    if (n < 900) return 3       // 400-800
    return 4                    // 900+
  }
  const groups = [[], [], [], [], []]
  agents.forEach(agent => {
    groups[getRow(agent.id)].push(agent)
  })

  return (
    <div className="agent-grid-container">
      {/* Hover/selected label */}
      <div className="agent-hover-label">
        {displayLabel || '\u00A0'}
      </div>

      {/* Visual grid grouped by range */}
      {groups.filter(g => g.length > 0).map((group, gi) => (
        <div key={gi} className="agent-grid-group">
          {group.map(agent => {
            const color = getStatusColor(agent.status)
            const isSelected = agent.id === selectedAgent || agent.id === controlAgent
            const isPulsing = agent.status === 'context_compacted'
            const ctx = agent.ctx ?? -1
            const borderClass = ctx === 0 || agent.status === 'context_compacted' || agent.status === 'error' || agent.status === 'blocked'
              ? 'border-red'
              : (ctx >= 1 && ctx <= 10) || agent.status === 'context_warning'
              ? 'border-orange'
              : ''

            return (
              <div
                key={agent.id}
                className={`agent-cell ${color} ${isSelected ? 'selected' : ''} ${isPulsing ? 'pulsing' : ''} ${borderClass}`}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => onAgentClick(agent.id)}
                onMouseEnter={() => setHoveredAgent(agent.id)}
                onMouseLeave={() => setHoveredAgent(null)}
              >
                {agent.id}
              </div>
            )
          })}
        </div>
      ))}
    </div>
  )
}

export default AgentGrid
