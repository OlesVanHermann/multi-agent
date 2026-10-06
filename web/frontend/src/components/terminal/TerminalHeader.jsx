import React from 'react'
import UsageBars from './UsageBars'

const WS_LABELS = {
  live:         { text: 'live',         dot: 'green', title: 'WebSocket connecté, messages reçus' },
  jwt:          { text: 'JWT',          dot: 'red',   title: 'Token Keycloak invalide ou expiré — re-login requis' },
  rate:         { text: 'RATE',         dot: 'red',   title: 'Rate limit dépassé (300 req/min/IP) — attends 60s' },
  forbidden:    { text: 'FORBIDDEN',    dot: 'red',   title: 'Agent 000 (Architect) ne peut pas être contrôlé via le dashboard' },
  overloaded:   { text: 'OVERLOADED',   dot: 'red',   title: 'Backend a atteint le max de connexions WS' },
  disconnected: { text: 'disconnected', dot: 'red',   title: 'Connexion fermée (réseau, backend down, ou close normal)' },
}

function TerminalHeader({
  agentId, wsState, syncing, paused,
  showHistory, onToggleHistory, showNotes, onToggleNotes,
  fileRef, uploading, onUpload,
}) {
  const w = WS_LABELS[wsState] || WS_LABELS.disconnected
  return (
    <div className="terminal-header">
      <span className={`status-dot ${w.dot}`}></span>
      Agent {agentId} <span title={w.title}>({w.text})</span>
      {syncing && <span className="sync-indicator"> ⟳</span>}
      {paused && <span className="pause-indicator"> ⏸</span>}
      <UsageBars agentId={agentId} />
      <button onClick={onToggleHistory} className={`config-btn${showHistory ? ' config-btn-active' : ''}`}
        title="Voir historique des prompts">{showHistory ? 'terminal' : 'historique'}</button>
      <button onClick={onToggleNotes} className={`config-btn${showNotes ? ' config-btn-active' : ''}`}
        title="Notes de l'agent">notes</button>
      <input type="file" ref={fileRef} hidden multiple onChange={onUpload} />
      <button onClick={() => fileRef.current?.click()} className="config-btn" title="Upload file" disabled={uploading}>
        {uploading ? '...' : 'upload'}</button>
    </div>
  )
}

export default TerminalHeader
