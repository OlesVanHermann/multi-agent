import React from 'react'

// Briques partagées des diagrammes x45 (sidebar) : cellules agent,
// boîtes fichier/info, et helpers de couleur/label.

export function getStatusColor(status) {
  switch (status) {
    case 'has_bashes': return 'green'
    case 'busy': return 'lightgreen'
    case 'model_mismatch': return 'yellow'
    case 'active': return 'gray'
    case 'idle': case 'stale': return 'gray'
    case 'starting': return 'white'
    case 'waiting_approval': return 'blue'
    case 'plan_mode': return 'darkblue'
    case 'context_warning': return 'gray'
    case 'context_compacted': return 'red'
    case 'needs_clear': case 'error': case 'blocked': return 'darkred'
    case 'stopped': return 'darkgray'
    default: return 'gray'
  }
}

export function getShortLabel(id, agentNames) {
  const baseId = id?.split('-')[0]
  if (agentNames[baseId]) return `${id} — ${agentNames[baseId]}`
  return id
}

// Fill + border + pulse pour un agent isolé (fav bar, grille racine).
export function getAgentColors(agent) {
  const ctx = agent?.ctx ?? -1
  return {
    fillColor: getStatusColor(agent?.status),
    borderColor: ctx === 0 || agent?.status === 'context_compacted' || agent?.status === 'error' || agent?.status === 'blocked'
      ? 'border-red'
      : (ctx >= 1 && ctx <= 10) || agent?.status === 'context_warning'
      ? 'border-orange'
      : '',
    isPulsing: agent?.status === 'context_compacted',
  }
}

// Compute composite colors for a triangle (all agents)
export function getTriangleColors(triangles, agentMap, workerId) {
  const tri = triangles[workerId]
  const mainId = tri?.worker || workerId
  const ids = [mainId]
  if (tri) {
    const roles = ['master', 'observer', 'indexer', 'curator', 'coach', 'tri_architect']
    roles.forEach(r => { if (tri[r]) ids.push(tri[r]) })
  }
  const statuses = ids.map(id => agentMap[id]?.status).filter(Boolean)

  // Fill: best activity — blue > green (bashes) > yellow (busy) > gray
  const fillPriority = { waiting_approval: 6, plan_mode: 5, starting: 4, has_bashes: 3, busy: 2, active: 1 }
  let bestFill = 0
  statuses.forEach(s => { if ((fillPriority[s] || 0) > bestFill) bestFill = fillPriority[s] })
  const fillColor = bestFill >= 6 ? 'blue' : bestFill >= 5 ? 'darkblue' : bestFill >= 4 ? 'white' : bestFill >= 3 ? 'green' : bestFill >= 2 ? 'lightgreen' : 'gray'

  // Border: worst problem — darkred > orange > none
  const hasRed = ids.some(id => { const _a = agentMap[id]; return (_a?.ctx ?? -1) === 0 || _a?.status === 'context_compacted' || _a?.status === 'error' || _a?.status === 'blocked' })
  const hasOrange = ids.some(id => { const _a = agentMap[id]; return ((_a?.ctx ?? -1) >= 1 && (_a?.ctx ?? -1) <= 10) || _a?.status === 'context_warning' })
  const borderColor = hasRed ? 'border-red' : hasOrange ? 'border-orange' : ''

  const isPulsing = statuses.some(s => s === 'context_compacted')
  return { fillColor, borderColor, isPulsing }
}

export function AgentCell({ id, label, agent, isSelected, onClick, onHover, onLeave, big }) {
  const color = agent ? getStatusColor(agent.status) : 'darkgray'
  const isPulsing = agent && agent.status === 'context_compacted'
  const ctx = agent?.ctx ?? -1
  const borderClass = ctx === 0 || agent?.status === 'context_compacted' || agent?.status === 'error' || agent?.status === 'blocked'
    ? 'border-red'
    : (ctx >= 1 && ctx <= 10) || agent?.status === 'context_warning'
    ? 'border-orange'
    : ''
  return (
    <div
      className={`agent-cell ${color} ${isSelected ? 'selected' : ''} ${isPulsing ? 'pulsing' : ''} ${borderClass} ${big ? 'tri-big' : 'tri-small'}`}
      onMouseDown={e => e.preventDefault()}
      onClick={() => onClick(id)}
      onMouseEnter={() => onHover(id)}
      onMouseLeave={onLeave}
    >{label}</div>
  )
}

export function LabeledCell({ id, label, role, agent, isSelected, onClick, onHover, onLeave, big }) {
  return (
    <div className="tri-labeled-cell">
      <AgentCell id={id} label={label} agent={agent} isSelected={isSelected}
        onClick={onClick} onHover={onHover} onLeave={onLeave} big={big} />
      <span className="tri-role-tag">{role}</span>
    </div>
  )
}

export function FileBox({ label, onClick, onHover, onLeave }) {
  return (
    <div className="tri-file" onClick={onClick}
      onMouseEnter={onHover} onMouseLeave={onLeave}
    >{label}</div>
  )
}

export function InfoBox({ lines }) {
  return <div className="tri-info">{lines.map((l, i) => <div key={i}>{l}</div>)}</div>
}

// Chemin d'un fichier prompt x45 : prompts/{parent}/{agentId}-{type}.md
export function fp(agentId, type) {
  const parent = agentId.includes('-') ? agentId.split('-')[0] : agentId
  return `prompts/${parent}/${agentId}-${type}.md`
}

// Suffixe d'un ID composé (341-141 → 141)
export const sfx = (id) => id && id.includes('-') ? id.split('-')[1] : id

export function hoverLabel(h, agentNames) {
  if (!h) return null
  if (typeof h === 'string' && h.includes('/')) return h
  return getShortLabel(h, agentNames)
}

// Rôle d'un satellite d'après le premier chiffre du suffixe
export function satRole(satId) {
  if (!satId || !satId.includes('-')) return null
  const s = satId.split('-')[1]
  if (s[0] === '1') return 'master'
  if (s[0] === '5') return 'observer'
  if (s[0] === '6') return 'indexer'
  if (s[0] === '7') return 'curator'
  if (s[0] === '8') return 'coach'
  if (s[0] === '9') return 'tri_architect'
  return null
}
