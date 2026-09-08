import React from 'react'
import { createLogger } from '../lib/logger'

const log = createLogger('App')

// Polling timing options
const AGENT_POLL_OPTIONS  = [0.3, 0.5, 1, 2, 3]      // ws/agent refresh (seconds)
const STATUS_POLL_OPTIONS = [2, 5, 10, 15, 30]        // ws/status refresh (seconds)
const FETCH_OPTIONS       = [5, 10, 15, 30, 60]       // api fetch interval (seconds)

const PANEL_BUTTONS = [
  { key: 'loginModel', label: <>Login &amp; Model</> },
  { key: 'couleurs',   label: 'Couleurs' },
  { key: 'crontab',    label: 'Crontab' },
  { key: 'keepAlive',  label: 'Keep Alive' },
]

function HeaderBar({
  activeConfigPanel, onTogglePanel,
  agentPoll, setAgentPoll, statusPoll, setStatusPoll, fetchSec, setFetchSec,
  username, onLogout,
}) {
  return (
    <header className="header">
      <h1>MULTI-AGENT DASHBOARD</h1>
      {PANEL_BUTTONS.map(({ key, label }) => (
        <button
          key={key}
          className={`config-btn ${activeConfigPanel === key ? 'config-btn-active' : ''}`}
          onClick={() => { log.nav('panel-toggle', { panel: key }); onTogglePanel(key) }}
        >
          {label}
        </button>
      ))}
      <div className="header-right">
        <span className="poll-group">
          <label className="poll-label">Terminal</label>
          <select value={agentPoll} onChange={setAgentPoll} className="poll-select" title="Tmux terminal refresh rate">
            {AGENT_POLL_OPTIONS.map(v => <option key={v} value={v}>{v}s</option>)}
          </select>
        </span>
        <span className="poll-group">
          <label className="poll-label">Grille</label>
          <select value={statusPoll} onChange={setStatusPoll} className="poll-select" title="Agent grid status refresh">
            {STATUS_POLL_OPTIONS.map(v => <option key={v} value={v}>{v}s</option>)}
          </select>
        </span>
        <span className="poll-group">
          <label className="poll-label">Health</label>
          <select value={fetchSec} onChange={setFetchSec} className="poll-select" title="Health check + agent count refresh">
            {FETCH_OPTIONS.map(v => <option key={v} value={v}>{v}s</option>)}
          </select>
        </span>
        <span className="poll-label">{username}</span>
        <button onClick={() => { log.action('logout'); onLogout() }} className="logout-btn">Logout</button>
      </div>
    </header>
  )
}

export default HeaderBar
