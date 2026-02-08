import React from 'react'

function StatusBar({ agentCount, activeCount, warningCount, compactedCount, redisOk, lastUpdate }) {
  const timeSince = lastUpdate
    ? Math.floor((Date.now() - lastUpdate.getTime()) / 1000)
    : null

  return (
    <footer className="status-bar">
      <div className="status-item">
        <span className="label">Agents:</span>
        <span className="value">{agentCount}</span>
      </div>
      <div className="status-item">
        <span className="label">Active:</span>
        <span className="value">{activeCount}</span>
      </div>
      {warningCount > 0 && (
        <div className="status-item">
          <span className="label">Context warn:</span>
          <span className="value" style={{ color: 'var(--orange)' }}>{warningCount}</span>
        </div>
      )}
      {compactedCount > 0 && (
        <div className="status-item">
          <span className="label">Compacted:</span>
          <span className="value" style={{ color: 'var(--red)' }}>{compactedCount}</span>
        </div>
      )}
      <div className="status-item">
        <span className="label">Redis:</span>
        <span className={`indicator ${redisOk ? 'ok' : 'error'}`}>
          {redisOk ? 'OK' : 'ERROR'}
        </span>
      </div>
      <div className="status-item">
        <span className="label">Updated:</span>
        <span className="value">
          {timeSince !== null ? `${timeSince}s ago` : '---'}
        </span>
      </div>
    </footer>
  )
}

export default StatusBar
