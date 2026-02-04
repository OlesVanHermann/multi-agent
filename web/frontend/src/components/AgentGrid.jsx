import React from 'react'

const AGENT_RANGES = [
  { start: 0, end: 99, label: '0XX Super-Masters' },
  { start: 100, end: 199, label: '1XX Masters' },
  { start: 200, end: 299, label: '2XX Explorers' },
  { start: 300, end: 399, label: '3XX Developers' },
  { start: 400, end: 499, label: '4XX Integrators' },
  { start: 500, end: 599, label: '5XX Testers' },
  { start: 600, end: 699, label: '6XX Releasers' },
  { start: 900, end: 999, label: '9XX Architects' },
]

function AgentGrid({ agents, selectedAgent, onAgentClick }) {
  // Create a map for quick lookup
  const agentMap = {}
  agents.forEach(a => {
    agentMap[a.id] = a
  })

  // Get status color
  const getStatusColor = (status) => {
    switch (status) {
      case 'idle': return 'green'
      case 'busy': return 'orange'
      case 'blocked':
      case 'error': return 'red'
      case 'stopped': return 'gray'
      default: return 'gray'
    }
  }

  // Check if agent is stale (not seen in 30s)
  const isStale = (lastSeen) => {
    if (!lastSeen) return true
    const now = Math.floor(Date.now() / 1000)
    return (now - lastSeen) > 30
  }

  // Get range status (worst status of any agent in range)
  const getRangeStatus = (start, end) => {
    let hasRunning = false
    let hasWorking = false
    let hasError = false

    for (let id = start; id <= end; id++) {
      const agent = agentMap[id.toString()]
      if (agent && !isStale(agent.last_seen)) {
        hasRunning = true
        if (agent.status === 'busy') hasWorking = true
        if (agent.status === 'blocked' || agent.status === 'error') hasError = true
      }
    }

    if (hasError) return 'red'
    if (hasWorking) return 'orange'
    if (hasRunning) return 'green'
    return 'gray'
  }

  return (
    <div className="agent-grid-container">
      {/* Visual grid */}
      <div className="agent-grid">
        {agents.map(agent => {
          const status = isStale(agent.last_seen) ? 'stopped' : agent.status
          const color = getStatusColor(status)
          const isSelected = agent.id === selectedAgent

          return (
            <div
              key={agent.id}
              className={`agent-cell ${color} ${isSelected ? 'selected' : ''}`}
              onClick={() => onAgentClick(agent.id)}
              title={`Agent ${agent.id} - ${status}`}
            >
              {agent.id}
            </div>
          )
        })}
      </div>

      {/* Range summary */}
      <div className="range-summary">
        {AGENT_RANGES.map(range => {
          const status = getRangeStatus(range.start, range.end)
          return (
            <div key={range.start} className={`range-item ${status}`}>
              <span className="range-indicator"></span>
              {range.label}
            </div>
          )
        })}
      </div>

      {/* Legend */}
      <div className="legend">
        <div className="legend-item">
          <span className="dot green"></span> IDLE
        </div>
        <div className="legend-item">
          <span className="dot orange"></span> WORKING
        </div>
        <div className="legend-item">
          <span className="dot red"></span> BLOCKED/ERROR
        </div>
        <div className="legend-item">
          <span className="dot gray"></span> STOPPED
        </div>
      </div>
    </div>
  )
}

export default AgentGrid
