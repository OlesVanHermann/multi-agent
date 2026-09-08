import React from 'react'

const REDIS_LABELS = {
  ok:      { text: 'OK',      cls: 'ok',    title: 'Redis répond, auth OK' },
  noauth:  { text: 'NOAUTH',  cls: 'error', title: "Redis joignable mais mot de passe invalide (REDIS_PASSWORD côté backend)" },
  jwt:     { text: 'JWT',     cls: 'error', title: "Token Keycloak invalide ou expiré — re-login requis" },
  down:    { text: 'DOWN',    cls: 'error', title: "API /api/health inaccessible (backend down ou réseau)" },
  unknown: { text: '…',       cls: 'ok',    title: "État Redis pas encore vérifié" },
}

function StatusBar({ agentCount, activeCount, warningCount, compactedCount, redisStatus, lastUpdate, reconnecting }) {
  const timeSince = lastUpdate
    ? Math.floor((Date.now() - lastUpdate.getTime()) / 1000)
    : null
  const r = REDIS_LABELS[redisStatus] || REDIS_LABELS.unknown

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
        <span className={`indicator ${r.cls}`} title={r.title}>{r.text}</span>
      </div>
      <div className="status-item">
        <span className="label">Updated:</span>
        <span className="value">
          {timeSince !== null ? `${timeSince}s ago` : '---'}
        </span>
      </div>
      {reconnecting && (
        <div className="status-item">
          <span className="indicator reconnecting">Reconnexion…</span>
        </div>
      )}
    </footer>
  )
}

export default StatusBar
