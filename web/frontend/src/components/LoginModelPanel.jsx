import React, { useState, useEffect } from 'react'
import { api } from '../basePath'
import { setAutoScroll } from '../lib/terminalPrefs'

const TMUX_WIDTH_OPTIONS = [80, 90, 100, 110, 120, 132, 180, 220, 280]
// Un seul réglage « lignes/scroll » : la valeur fixe la hauteur du pane ET
// l'history-limit (décision opérateur, 2026-10-08). Le TUI tourne en écran
// alterné : tmux ne garde aucun scrollback, la hauteur décide seule du
// transcript visible ; l'historique ne vaut qu'aux sessions créées ensuite.
// 10k = hauteur max de tmux. [Mesuré mx3, Claude Code 2.1.293, transcript de
// 6 000 lignes : frappe affichée en ~35 ms à 2k, ~22 s à 5k et 10k.]
const TMUX_LINES_OPTIONS = [2000, 5000, 10000]

// Effort : codes stockés L/M/H/X/MAX = low/medium/high/xhigh/max (décision
// opérateur, 2026-10-09). Max s'affiche « M » comme demandé ; le nom complet
// est dans la bulle d'aide pour lever l'ambiguïté avec medium.
const EFFORT_LABELS = { L: 'L', M: 'M', H: 'H', X: 'X', MAX: 'M' }
const EFFORT_NAMES = { L: 'low', M: 'medium', H: 'high', X: 'xhigh', MAX: 'max' }

// Ultracode : interrupteur séparé de l'effort (claude uniquement). Un seul
// bouton, même style que M/D : « U » en bleu = actif, « U » normal = éteint.
function UltracodeToggle({ on, onToggle }) {
  return (
    <span className="lm-panel-toggle lm-ultracode-toggle">
      <button
        className={`lm-panel-btn ${on ? 'lm-panel-active' : ''}`}
        title={on ? 'Ultracode actif — cliquer pour l’éteindre' : 'Ultracode éteint — cliquer pour l’activer'}
        onClick={onToggle}
      >U</button>
    </span>
  )
}

function getDefaultPanel(agentId, mode) {
  const num = parseInt(agentId)
  const suffixNum = agentId.includes('-') ? parseInt(agentId.split('-')[1]) : num
  // x45 : les 9XX (tri-architects) sont du plan de controle, comme les 1XX
  const isControl = mode === 'x45' ? (suffixNum < 200 || suffixNum >= 900) : (num < 200 || num >= 900)
  return isControl ? 'control' : 'agent'
}

// onNotice({kind, text} | null) : un message par réglage — OK (vert),
// « enregistré mais non appliqué » (jaune), KO (rouge) — dans l'en-tête de la
// sous-fenêtre AGENT (App.jsx, effacé après 10 s), jamais en bandeau
// au-dessus du tableau (décision opérateur, 2026-10-08).
function LoginModelPanel({ hidden, mode, panelConfig, onPanelChange, runningAgents, onNotice }) {
  const notify = (notice) => { if (onNotice) onNotice(notice) }
  const runningIds = new Set((runningAgents || []).map(a => a.id))
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
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
      setError(`Login & Model : chargement KO — ${err.message}`)
    }
  }

  // Fetch all config every time panel is opened
  useEffect(() => {
    if (!hidden) {
      notify(null)
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

  // Erreur → en-tête AGENT, texte déjà formé « <sujet> : <action> KO — <motif> ».
  // Chaque action commence par clearMessages() : une même erreur répétée
  // redevient un changement d'état et se réaffiche.
  useEffect(() => {
    if (error) notify({ kind: 'error', text: error })
  }, [error])

  const clearMessages = () => {
    setError(null)
    notify(null)
  }

  // La ligne « Défaut global » s'appelle `default` côté API.
  const who = (agentId) => (agentId === 'default' ? 'défaut global' : agentId)

  // Un message à CHAQUE réglage, format unique « <agent> : <message> »
  // (décision opérateur, 2026-10-08). OK et « non appliqué » à la couleur du
  // titre, KO en rouge (via setError).
  const fail = (subject, label, message) => setError(`${subject} : ${label} KO — ${message}`)
  const report = (detail, subject, okText, label) => {
    if (detail.applied === false) {
      notify({
        kind: 'warning',
        text: `${subject} : ${label} enregistré mais non appliqué — ${detail.reason || 'raison inconnue'}${detail.restart_required ? ', redémarrage requis' : ''}`,
      })
    } else {
      notify({ kind: 'ok', text: `${subject} : ${okText}` })
    }
  }

  // Advisor : endpoint dédié, sans préflight moteur ni redémarrage. Le backend
  // envoie `/advisor <alias|off>` au TUI vivant, comme /effort.
  const handleAdvisor = async (agentId, value) => {
    clearMessages()
    try {
      const res = await fetch(api('api/config/advisor'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: agentId, value, confirm_global: agentId === 'default' }),
      })
      const detail = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(detail.detail || `HTTP ${res.status}`)
      await fetchData()
      report(detail, who(agentId),
        `Advisor ${detail.advisor || value || 'aucun'} appliqué`,
        `Advisor ${value || 'aucun'}`)
    } catch (err) {
      fail(who(agentId), `Advisor ${value || 'aucun'}`, err.message)
    }
  }

  // patch ne porte qu'un réglage : le backend laisse les autres inchangés.
  const handleTmuxSize = async (patch) => {
    clearMessages()
    let label = 'réglage'
    if ('height' in patch) label = `lignes/scroll ${patch.height / 1000}k`
    else if ('width' in patch) label = `cols ${patch.width}`
    else if ('autoscroll' in patch) label = `scrollback ${patch.autoscroll ? 'oui' : 'non'}`
    try {
      const res = await fetch(api('api/config/tmux-size'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      })
      const detail = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(detail.detail || `HTTP ${res.status}`)
      applyTmuxConfig(detail)
      const sessions = `${detail.sessions ?? 0} session(s)`
      let text = `${label} appliqué`
      if ('height' in patch) {
        text = `${label} appliqué — hauteur sur ${sessions}, historique au prochain démarrage des sessions`
      } else if ('width' in patch) {
        text = `${label} appliqué sur ${sessions}`
      }
      notify({ kind: 'ok', text: `tmux : ${text}` })
    } catch (err) {
      fail('tmux', label, err.message)
    }
  }

  const handleChange = async (agentId, type, value) => {
    clearMessages()
    const what = type === 'model' ? 'Modèle' : 'Login'
    try {
      // Pas de popup pour la ligne explicitement nommée « Défaut global ».
      // confirm_global reste envoyé : le backend l'exige pour les autres clients.
      const confirmGlobal = agentId === 'default'
      const res = await fetch(api('api/config/logins-models'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: agentId, type, value, confirm_global: confirmGlobal }),
      })
      // E1 : le backend renvoie un detail explicite sur les incompatibilités
      // modèle ↔ moteur — l'afficher plutôt qu'un « HTTP 400 » opaque.
      const detail = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(detail.detail || `HTTP ${res.status}`)
      await fetchData()
      if (detail.status === 'removed') {
        notify({ kind: 'ok', text: `${who(agentId)} : ${what} override retiré, valeur héritée` })
      } else {
        report(detail, who(agentId), `${what} ${value} appliqué`, `${what} ${value}`)
      }
    } catch (err) {
      fail(who(agentId), `${what} ${value || '(hérité)'}`, err.message)
    }
  }

  const handleAction = async (agentId, action) => {
    if (activeRestart) return // already one in flight
    setActiveRestart({ id: agentId, action })
    clearMessages()
    try {
      const res = await fetch(api(`api/agent/${agentId}/${action}`), { method: 'POST' })
      const detail = await res.json().catch(() => ({}))
      if (!res.ok) {
        throw new Error(detail.detail || `HTTP ${res.status}`)
      }
      // Le backend a vérifié l'état réel (session tmux) avant de répondre.
      const members = Object.entries(detail.member_ok || {})
      if (members.length > 1) {
        // Groupe x45/z21 : un seul message, résumé membre par membre
        // (décision opérateur, 2026-10-08). Un KO → message rouge.
        const summary = members.map(([m, ok]) => `${m} ${ok ? 'OK' : 'KO'}`).join(' · ')
        notify({ kind: members.every(([, ok]) => ok) ? 'ok' : 'error', text: `${agentId} : ${action} — ${summary}` })
      } else if (detail.verified === false) {
        fail(agentId, action, 'état non confirmé, voir logs agent.sh')
      } else {
        notify({ kind: 'ok', text: `${agentId} : ${action} OK` })
      }
    } catch (err) {
      fail(agentId, action, err.message)
    } finally {
      setActiveRestart(null)
      fetchData()
    }
  }

  // Ultracode : interrupteur séparé de l'effort (décision opérateur, 2026-10-09).
  const handleUltracode = async (agentId, value) => {
    clearMessages()
    const label = `Ultracode ${value === 'on' ? 'ON' : 'OFF'}`
    try {
      const res = await fetch(api('api/config/ultracode'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: agentId, value, confirm_global: agentId === 'default' }),
      })
      const detail = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(detail.detail || `HTTP ${res.status}`)
      await fetchData()
      report(detail, who(agentId), `${label} appliqué`, label)
    } catch (err) {
      fail(who(agentId), label, err.message)
    }
  }

  const handleEffort = async (agentId, level) => {
    if (activeEffort) return
    setActiveEffort({ id: agentId, level })
    clearMessages()
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
      report(detail, who(agentId),
        detail.status === 'removed'
          ? `Effort override retiré, hérité ${EFFORT_NAMES[detail.level] || detail.level}`
          : `Effort ${EFFORT_NAMES[detail.level || level] || detail.level || level} appliqué`,
        `Effort ${EFFORT_NAMES[detail.level || level] || detail.level || level}`)
    } catch (err) {
      fail(who(agentId), `Effort ${EFFORT_NAMES[level] || level || '(hérité)'}`, err.message)
    } finally {
      setActiveEffort(null)
    }
  }

  const handlePanelToggle = async (agentId, panel) => {
    const def = getDefaultPanel(agentId, mode)
    const sendPanel = panel === def ? '' : panel // send "" to remove override if matches default
    clearMessages()
    try {
      const res = await fetch(api('api/config/panel'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: agentId, panel: sendPanel }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `HTTP ${res.status}`)
      }
      if (onPanelChange) onPanelChange(agentId, sendPanel)
      notify({ kind: 'ok', text: `${agentId} : Panneau ${panel}` })
    } catch (err) {
      fail(agentId, `Panneau ${panel}`, err.message)
    }
  }


  if (error && !data) return <div className="login-model-panel" style={{ display: hidden ? 'none' : undefined }}><p style={{ color: 'var(--red)' }}>{error}</p></div>
  if (!data) return <div className="login-model-panel" style={{ display: hidden ? 'none' : undefined }}><p style={{ color: 'var(--text-secondary)' }}>Loading...</p></div>

  const {
    logins, models, default_login, default_model, default_effort,
    default_effort_levels, agents, groups, default_ultracode, default_ultracode_supported,
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
              {/* Deux lignes : cols · lignes/scroll + scrollback
                  (décision opérateur, 2026-10-08). Libellé de tête à largeur
                  fixe pour l'alignement vertical, libellé inline ensuite. */}
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
                  <span className="lm-tmux-label">lignes/scroll :</span>
                  <span className="lm-width-group">
                    {TMUX_LINES_OPTIONS.map(n => (
                      <button
                        key={`l${n}`}
                        title={`Hauteur ${n} lignes (immédiat) et history-limit ${n} (prochain démarrage des sessions)`}
                        className={`lm-width-btn ${tmuxHeight === n && tmuxHistory === n ? 'lm-width-active' : ''}`}
                        onClick={() => handleTmuxSize({ height: n, history: n })}
                      >
                        {`${n / 1000}k`}
                      </button>
                    ))}
                  </span>
                  <span className="lm-tmux-label lm-tmux-label-inline">scrollback :</span>
                  {/* Un seul bouton qui bascule (décision opérateur,
                      2026-10-09) : « oui » en bleu = actif, « non » normal. */}
                  <span className="lm-panel-toggle">
                    <button
                      className={`lm-panel-btn ${tmuxAutoScroll ? 'lm-panel-active' : ''}`}
                      title={tmuxAutoScroll
                        ? 'Actif : on remonte dans la sortie puis ça redescend tout seul après 5 s — cliquer pour désactiver'
                        : 'Inactif : on reste où on a remonté — cliquer pour activer'}
                      onClick={() => handleTmuxSize({ autoscroll: !tmuxAutoScroll })}
                    >
                      {tmuxAutoScroll ? 'oui' : 'non'}
                    </button>
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
                    title={EFFORT_NAMES[lvl] || lvl}
                    className={`lm-effort-btn ${(default_effort || 'H') === lvl ? 'lm-effort-active' : ''} ${activeEffort?.id === 'default' && activeEffort?.level === lvl ? 'lm-effort-pending' : ''}`}
                    onClick={() => handleEffort('default', lvl)}
                    disabled={!!activeEffort}
                  >{EFFORT_LABELS[lvl] || lvl}</button>
                ))}
              </span>
              {default_ultracode_supported && (
                <UltracodeToggle on={default_ultracode === 'on'} onToggle={() => handleUltracode('default', default_ultracode === 'on' ? 'off' : 'on')} />
              )}
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
                          title={EFFORT_NAMES[lvl] || lvl}
                          className={`lm-effort-btn ${isActive ? (isOverride ? 'lm-effort-override' : 'lm-effort-active') : ''} ${activeEffort?.id === agent.id && activeEffort?.level === lvl ? 'lm-effort-pending' : ''}`}
                          onClick={() => handleEffort(agent.id, lvl)}
                          disabled={!!activeEffort || isActive}
                        >{EFFORT_LABELS[lvl] || lvl}</button>
                      )
                    })}
                    {/* Bouton de retrait de l’override (reset) supprimé — décision
                        opérateur, 2026-10-08. */}
                  </span>
                  {agent.ultracode_supported && (
                    <UltracodeToggle on={agent.ultracode === 'on'} onToggle={() => handleUltracode(agent.id, agent.ultracode === 'on' ? 'off' : 'on')} />
                  )}
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
