import React, { useState, useEffect } from 'react'
import { api } from '../basePath'
import { setAutoScroll } from '../lib/terminalPrefs'

const TMUX_WIDTH_OPTIONS = [80, 90, 100, 110, 120, 132, 180, 220, 280]
// Le TUI tourne en écran alterné : tmux ne garde aucun scrollback, donc la
// hauteur du pane décide seule du nombre de lignes de transcript visibles.
const TMUX_HEIGHT_OPTIONS = [24, 40, 50, 80, 100, 140, 200]
// history-limit tmux. tmux ne l'applique qu'aux panes créés ensuite : la
// nouvelle valeur ne vaut qu'au prochain démarrage des sessions.
const TMUX_HISTORY_OPTIONS = [2000, 5000, 10000, 25000, 50000, 100000]

function getDefaultPanel(agentId, mode) {
  const num = parseInt(agentId)
  const suffixNum = agentId.includes('-') ? parseInt(agentId.split('-')[1]) : num
  // x45 : les 9XX (tri-architects) sont du plan de controle, comme les 1XX
  const isControl = mode === 'x45' ? (suffixNum < 200 || suffixNum >= 900) : (num < 200 || num >= 900)
  return isControl ? 'control' : 'agent'
}

function LoginModelPanel({ hidden, mode, panelConfig, onPanelChange, runningAgents }) {
  const runningIds = new Set((runningAgents || []).map(a => a.id))
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [feedback, setFeedback] = useState(null)
  // Action en cours : {id, action}. Pas de compte à rebours — le backend
  // rend la main quand l'état réel est atteint (session tmux présente/absente),
  // les boutons se réactivent à la réponse.
  const [activeRestart, setActiveRestart] = useState(null)
  const [activeEffort, setActiveEffort] = useState(null)
  const [tmuxWidth, setTmuxWidth] = useState(null)
  const [tmuxHeight, setTmuxHeight] = useState(null)
  const [tmuxHistory, setTmuxHistory] = useState(null)
  const [tmuxAutoScroll, setTmuxAutoScroll] = useState(null)

  const fetchData = async () => {
    try {
      const res = await fetch(api('api/config/logins-models'))
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setData(await res.json())
      setError(null)
    } catch (err) {
      setError(err.message)
    }
  }

  // Fetch all config every time panel is opened
  useEffect(() => {
    if (!hidden) {
      setFeedback(null)
      fetchData()
      fetch(api('api/config/tmux-size'))
        .then(r => r.json())
        .then(d => applyTmuxConfig(d))
        .catch(() => {})
      fetch(api('api/config/panel'))
        .then(r => r.json())
        .then(d => { if (onPanelChange && d.overrides) Object.entries(d.overrides).forEach(([id, p]) => onPanelChange(id, p)) })
        .catch(() => {})
    }
  }, [hidden])

  // Reflète la réponse serveur, seule source de vérité des quatre réglages.
  const applyTmuxConfig = (d) => {
    if (!d) return
    setTmuxWidth(d.width)
    setTmuxHeight(d.height)
    setTmuxHistory(d.history)
    if (typeof d.autoscroll === 'boolean') {
      setTmuxAutoScroll(d.autoscroll)
      setAutoScroll(d.autoscroll)   // propage aux <Terminal> déjà montés
    }
  }

  // Advisor : endpoint dédié, sans préflight moteur ni redémarrage. Le backend
  // envoie `/advisor <alias|off>` au TUI vivant, comme /effort.
  const handleAdvisor = async (agentId, value) => {
    setError(null)
    setFeedback(null)
    try {
      const res = await fetch(api('api/config/advisor'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: agentId, value, confirm_global: agentId === 'default' }),
      })
      const detail = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(detail.detail || `HTTP ${res.status}`)
      await fetchData()
      // Succès silencieux : le select affiche déjà la valeur. Seul un échec
      // d'application mérite un message.
      if (detail.applied === false) {
        setFeedback({
          kind: 'warning',
          text: `Advisor ${agentId} enregistré mais non appliqué : ${detail.reason || 'raison inconnue'}`,
        })
      }
    } catch (err) {
      setError(err.message)
    }
  }

  // patch ne porte qu'un réglage : le backend laisse les autres inchangés.
  const handleTmuxSize = async (patch) => {
    try {
      const res = await fetch(api('api/config/tmux-size'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      applyTmuxConfig(await res.json())
    } catch (err) {
      setError(err.message)
    }
  }

  const handleChange = async (agentId, type, value) => {
    try {
      // Pas de popup pour la ligne explicitement nommée « Défaut global ».
      // confirm_global reste envoyé : le backend l'exige pour les autres clients.
      const confirmGlobal = agentId === 'default'
      const res = await fetch(api('api/config/logins-models'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: agentId, type, value, confirm_global: confirmGlobal }),
      })
      if (!res.ok) {
        // E1 : le backend renvoie un detail explicite sur les incompatibilités
        // modèle ↔ moteur — l'afficher plutôt qu'un « HTTP 400 » opaque.
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `HTTP ${res.status}`)
      }
      await fetchData()
    } catch (err) {
      setError(err.message)
    }
  }

  const handleAction = async (agentId, action) => {
    if (activeRestart) return // already one in flight
    setActiveRestart({ id: agentId, action })
    setError(null)
    try {
      const res = await fetch(api(`api/agent/${agentId}/${action}`), { method: 'POST' })
      const detail = await res.json().catch(() => ({}))
      if (!res.ok) {
        throw new Error(detail.detail || `HTTP ${res.status}`)
      }
      // Le backend a vérifié l'état réel (session tmux) avant de répondre.
      if (detail.verified === false) {
        setError(`${action} ${agentId}: état non confirmé — voir logs agent.sh`)
      }
    } catch (err) {
      setError(`${action} ${agentId}: ${err.message}`)
    } finally {
      setActiveRestart(null)
      fetchData()
    }
  }

  const handleEffort = async (agentId, level) => {
    if (activeEffort) return
    setActiveEffort({ id: agentId, level })
    setError(null)
    setFeedback(null)
    try {
      // Même politique explicite que handleChange pour « Défaut global ».
      const confirmGlobal = agentId === 'default'
      const res = await fetch(api('api/config/effort'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: agentId, level, confirm_global: confirmGlobal }),
      })
      const detail = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(detail.detail || `HTTP ${res.status}`)
      await fetchData()
      if (detail.applied === false) {
        setFeedback({
          kind: 'warning',
          text: `Effort ${agentId} enregistré mais non appliqué : ${detail.reason || 'raison inconnue'}`,
        })
      } else {
        const action = detail.status === 'removed'
          ? `Override retiré ; effort hérité ${detail.level}`
          : `Effort ${detail.level} appliqué`
        setFeedback({ kind: 'success', text: `${action} sur ${agentId}` })
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setActiveEffort(null)
    }
  }

  const handlePanelToggle = async (agentId, panel) => {
    const def = getDefaultPanel(agentId, mode)
    const sendPanel = panel === def ? '' : panel // send "" to remove override if matches default
    try {
      const res = await fetch(api('api/config/panel'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: agentId, panel: sendPanel }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      if (onPanelChange) onPanelChange(agentId, sendPanel)
    } catch (err) {
      setError(err.message)
    }
  }


  if (error && !data) return <div className="login-model-panel" style={{ display: hidden ? 'none' : undefined }}><p style={{ color: 'var(--red)' }}>Error: {error}</p></div>
  if (!data) return <div className="login-model-panel" style={{ display: hidden ? 'none' : undefined }}><p style={{ color: 'var(--text-secondary)' }}>Loading...</p></div>

  const {
    logins, models, default_login, default_model, default_effort,
    default_effort_levels, agents, groups,
    advisor_models, default_advisor, model_ids,
  } = data

  // E1 : n'exposer que les modèles compatibles avec le moteur de la ligne.
  // Sans ce filtre, l'UI laisse choisir gpt-5.6-sol sur un agent Claude Code :
  // la slash-command /model est alors ignorée par le TUI, sans erreur visible.
  const accountSlots = (logins || []).filter(l => l.startsWith('login'))
  const groupMap = {}
  ;(groups || []).forEach(g => { groupMap[g.id] = g })

  return (
    <div className="login-model-panel" style={{ display: hidden ? 'none' : undefined }}>
      {error && <p style={{ color: 'var(--red)', fontSize: '0.7rem', margin: '0 0 0.5rem' }}>Error: {error}</p>}
      {feedback && (
        <p style={{
          color: feedback.kind === 'warning' ? 'var(--yellow)' : 'var(--green)',
          fontSize: '0.7rem',
          margin: '0 0 0.5rem',
        }}>{feedback.text}</p>
      )}
      <table className="lm-table">
        <thead>
          <tr>
            <th>Agent</th>
            <th>Login</th>
            <th>Model</th>
            <th title="Claude: /effort · Codex: /reasoning">Effort / Reasoning</th>
            <th>Panel</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {/* Tmux geometry row : largeur et hauteur, deux paramètres distincts */}
          <tr className="lm-default-row">
            <td><strong>tmux</strong></td>
            <td colSpan="5">
              {/* Trois lignes : cols · lignes · scroll + scrollback.
                  Libellé devant chaque groupe, largeur fixe pour qu'ils
                  s'alignent verticalement. */}
              <div className="lm-tmux-grid">
                <div className="lm-tmux-row">
                  <span className="lm-tmux-label">cols :</span>
                  <span className="lm-width-group">
                    {TMUX_WIDTH_OPTIONS.map(w => (
                      <button
                        key={`w${w}`}
                        title={`Largeur ${w} colonnes`}
                        className={`lm-width-btn ${tmuxWidth === w ? 'lm-width-active' : ''}`}
                        onClick={() => handleTmuxSize({ width: w })}
                      >
                        {w}
                      </button>
                    ))}
                  </span>
                </div>
                <div className="lm-tmux-row">
                  <span className="lm-tmux-label">lignes :</span>
                  <span className="lm-width-group">
                    {TMUX_HEIGHT_OPTIONS.map(h => (
                      <button
                        key={`h${h}`}
                        title={`Hauteur ${h} lignes de transcript visibles`}
                        className={`lm-width-btn ${tmuxHeight === h ? 'lm-width-active' : ''}`}
                        onClick={() => handleTmuxSize({ height: h })}
                      >
                        {h}
                      </button>
                    ))}
                  </span>
                </div>
                <div className="lm-tmux-row">
                  <span className="lm-tmux-label">scroll :</span>
                  <span className="lm-width-group">
                    {TMUX_HISTORY_OPTIONS.map(n => (
                      <button
                        key={`n${n}`}
                        title={`history-limit ${n} — effectif au prochain démarrage des sessions`}
                        className={`lm-width-btn ${tmuxHistory === n ? 'lm-width-active' : ''}`}
                        onClick={() => handleTmuxSize({ history: n })}
                      >
                        {n >= 1000 ? `${n / 1000}k` : n}
                      </button>
                    ))}
                  </span>
                  <span className="lm-tmux-label lm-tmux-label-inline">scrollback :</span>
                  <span className="lm-width-group">
                    {[['oui', true], ['non', false]].map(([label, value]) => (
                      <button
                        key={`a${label}`}
                        title={value
                          ? 'Remonter dans la sortie puis redescendre tout seul après 5 s'
                          : 'Rester où on a remonté ; redescendre à la main pour reprendre'}
                        className={`lm-width-btn ${tmuxAutoScroll === value ? 'lm-width-active' : ''}`}
                        onClick={() => handleTmuxSize({ autoscroll: value })}
                      >
                        {label}
                      </button>
                    ))}
                  </span>
                </div>
              </div>
            </td>
          </tr>
          {/* Default row */}
          <tr className="lm-default-row">
            <td title="Affecte tous les agents sans override explicite"><strong>Défaut global</strong></td>
            <td>
              <select
                className="lm-select"
                value={default_login}
                onChange={(e) => handleChange('default', 'login', e.target.value)}
              >
                {accountSlots.map(l => <option key={l} value={l}>{l}</option>)}
              </select>
            </td>
            <td>
              <span className="lm-model-cell">
                <select
                  className="lm-select"
                  value={default_model}
                  onChange={(e) => handleChange('default', 'model', e.target.value)}
                >
                  {models.map(m => <option key={m} value={m}>{m}</option>)}
                </select>
                {/* Même règle que les lignes agent : l'advisor est propre au
                    moteur claude. Le défaut global suit son propre modèle. */}
                {!((model_ids || {})[default_model] || '').startsWith('gpt-') ? (
                  <select
                    className="lm-select lm-advisor"
                    title="Advisor — modèle de second avis"
                    value={default_advisor || ''}
                    onChange={(e) => handleAdvisor('default', e.target.value)}
                  >
                    <option value="">— aucun —</option>
                    {(advisor_models || []).map(m => <option key={m} value={m}>{m}</option>)}
                  </select>
                ) : (
                  <span className="lm-advisor lm-advisor-na" title="Advisor : moteur claude uniquement">—</span>
                )}
              </span>
            </td>
            <td>
              <span className="lm-effort-toggle">
                {(default_effort_levels || ['L', 'M', 'H']).map(lvl => (
                  <button
                    key={lvl}
                    className={`lm-effort-btn ${(default_effort || 'M') === lvl ? 'lm-effort-active' : ''} ${activeEffort?.id === 'default' && activeEffort?.level === lvl ? 'lm-effort-pending' : ''}`}
                    onClick={() => handleEffort('default', lvl)}
                    disabled={!!activeEffort}
                  >{lvl}</button>
                ))}
              </span>
            </td>
            <td></td>
            <td></td>
          </tr>
          {/* Agent rows */}
          {agents.map((agent, idx) => {
            const isThis = activeRestart && activeRestart.id === agent.id
            const blocked = !!activeRestart && !isThis
            const group = agent.id.split('-')[0]
            const isCompound = agent.id.includes('-')
            const prevGroup = idx > 0 ? agents[idx - 1].id.split('-')[0] : group
            const prevCompound = idx > 0 ? agents[idx - 1].id.includes('-') : isCompound
            // Group header row for first agent of an x45/z21 group
            const groupInfo = isCompound ? groupMap[group] : null
            const isFirstInGroup = groupInfo && (idx === 0 || agents[idx - 1].id.split('-')[0] !== group)

            // No border on agent row if header row already provides the separation
            const modeBreak = idx > 0 && isCompound !== prevCompound && !isFirstInGroup
            const groupBreak = idx > 0 && !modeBreak && group !== prevGroup && !isFirstInGroup
            const breakClass = modeBreak ? 'lm-mode-break' : groupBreak ? (isCompound ? 'lm-mode-break' : 'lm-group-break') : ''
            const groupHeader = isFirstInGroup ? (
              <tr key={`group-${group}`} className="lm-mode-break lm-group-header">
                <td><strong>{group}-*</strong></td>
                <td><span className="lm-group-type">{groupInfo.type}</span></td>
                <td colSpan="3"></td>
                <td>
                  <span className="lm-actions-group">
                    {['start', 'stop', 'restart'].map(act => {
                      const gThis = activeRestart && activeRestart.id === group
                      const gBlocked = !!activeRestart && !gThis
                      return (
                        <button key={act}
                          className={`lm-restart-btn ${gThis && activeRestart.action === act ? 'lm-restarting' : ''}`}
                          onClick={() => handleAction(group, act)}
                          disabled={gBlocked || gThis}
                          title={`./scripts/agent.sh ${act} ${group}`}
                        >
                          {gThis && activeRestart.action === act ? '…' : act}
                        </button>
                      )
                    })}
                  </span>
                </td>
              </tr>
            ) : null

            return (
              <React.Fragment key={agent.id}>
              {groupHeader}
              <tr className={breakClass}>
                <td style={{ color: runningIds.has(agent.id) ? 'var(--lightgreen)' : 'var(--text-secondary)' }}>
                  {runningIds.has(agent.id) ? `(${agent.id})` : agent.id}
                </td>
                <td>
                  <select
                    className={`lm-select ${agent.login_source === 'override' ? 'lm-override' : ''}`}
                    value={agent.login_source === 'override' ? agent.login : ''}
                    onChange={(e) => handleChange(agent.id, 'login', e.target.value)}
                  >
                    <option value="">({default_login})</option>
                    {accountSlots.map(l => <option key={l} value={l}>{l}</option>)}
                  </select>
                </td>
                <td>
                  <span className="lm-model-cell">
                    <select
                      className={`lm-select ${agent.model_source === 'override' ? 'lm-override' : ''}`}
                      value={agent.model_source === 'override' ? agent.model : ''}
                      onChange={(e) => handleChange(agent.id, 'model', e.target.value)}
                    >
                      <option value="">({default_model})</option>
                      {models.map(m => <option key={m} value={m}>{m}</option>)}
                    </select>
                    {agent.cli === 'claude' ? (
                      <select
                        className={`lm-select lm-advisor ${agent.advisor_source === 'override' ? 'lm-override' : ''}`}
                        title="Advisor — modèle de second avis"
                        value={agent.advisor_source === 'override' ? agent.advisor : ''}
                        onChange={(e) => handleAdvisor(agent.id, e.target.value)}
                      >
                        <option value="">({default_advisor || '— aucun —'})</option>
                        {(advisor_models || []).map(m => <option key={m} value={m}>{m}</option>)}
                      </select>
                    ) : (
                      <span className="lm-advisor lm-advisor-na" title="Advisor : moteur claude uniquement">—</span>
                    )}
                  </span>
                </td>
                <td>
                  <span className="lm-effort-toggle">
                    {(agent.effort_levels || ['L', 'M', 'H']).map(lvl => {
                      const isActive = agent.effort === lvl
                      const isOverride = agent.effort_source === 'override'
                      return (
                        <button
                          key={lvl}
                          className={`lm-effort-btn ${isActive ? (isOverride ? 'lm-effort-override' : 'lm-effort-active') : ''} ${activeEffort?.id === agent.id && activeEffort?.level === lvl ? 'lm-effort-pending' : ''}`}
                          onClick={() => handleEffort(agent.id, lvl)}
                          disabled={!!activeEffort || isActive}
                        >{lvl}</button>
                      )
                    })}
                    {agent.effort_source === 'override' && (
                      <button
                        className={`lm-effort-btn lm-effort-reset ${activeEffort?.id === agent.id && activeEffort?.level === '' ? 'lm-effort-pending' : ''}`}
                        onClick={() => handleEffort(agent.id, '')}
                        disabled={!!activeEffort}
                        title="Retirer l’override et réappliquer l’effort hérité"
                      >↺</button>
                    )}
                  </span>
                </td>
                <td>
                  {(() => {
                    const def = getDefaultPanel(agent.id, mode)
                    const current = (panelConfig && panelConfig[agent.id]) || def
                    return (
                      <span className="lm-panel-toggle">
                        <button
                          className={`lm-panel-btn ${current === 'control' ? 'lm-panel-active' : ''}`}
                          onClick={() => handlePanelToggle(agent.id, 'control')}
                        >M</button>
                        <button
                          className={`lm-panel-btn ${current === 'agent' ? 'lm-panel-active' : ''}`}
                          onClick={() => handlePanelToggle(agent.id, 'agent')}
                        >D</button>
                      </span>
                    )
                  })()}
                </td>
                <td>
                  <span className="lm-actions-group">
                    {['start', 'stop', 'restart'].map(act => (
                      <button key={act}
                        className={`lm-restart-btn ${isThis && activeRestart.action === act ? 'lm-restarting' : ''}`}
                        onClick={() => handleAction(agent.id, act)}
                        disabled={blocked || isThis}
                        title={`./scripts/agent.sh ${act} ${agent.id}`}
                      >
                        {isThis && activeRestart.action === act ? '…' : act}
                      </button>
                    ))}
                  </span>
                </td>
              </tr>
              </React.Fragment>
            )
          })}
        </tbody>
      </table>

    </div>
  )
}

export default LoginModelPanel
