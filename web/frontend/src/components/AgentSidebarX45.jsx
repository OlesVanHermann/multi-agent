import React, { useState } from 'react'
import { AGENT_LABELS } from './AgentGrid'

function getStatusColor(status) {
  switch (status) {
    case 'busy': return 'green'
    case 'active': case 'idle': case 'stale': return 'gray'
    case 'starting': case 'waiting_approval': return 'blue'
    case 'context_warning': return 'orange'
    case 'context_compacted': return 'red'
    case 'error': case 'blocked': return 'orange'
    case 'stopped': return 'darkgray'
    default: return 'gray'
  }
}

function getShortLabel(id) {
  if (AGENT_LABELS[id]) return AGENT_LABELS[id]
  return 'Agent ' + id
}

function AgentCell({ id, label, agent, isSelected, onClick, onHover, onLeave, big }) {
  const color = agent ? getStatusColor(agent.status) : 'darkgray'
  const isPulsing = agent && agent.status === 'context_compacted'
  return (
    <div
      className={`agent-cell ${color} ${isSelected ? 'selected' : ''} ${isPulsing ? 'pulsing' : ''} ${big ? 'tri-big' : 'tri-small'}`}
      onMouseDown={e => e.preventDefault()}
      onClick={() => onClick(id)}
      onMouseEnter={() => onHover(id)}
      onMouseLeave={onLeave}
    >{label}</div>
  )
}

function LabeledCell({ id, label, role, agent, isSelected, onClick, onHover, onLeave, big }) {
  return (
    <div className="tri-labeled-cell">
      <AgentCell id={id} label={label} agent={agent} isSelected={isSelected}
        onClick={onClick} onHover={onHover} onLeave={onLeave} big={big} />
      <span className="tri-role-tag">{role}</span>
    </div>
  )
}

function FileBox({ label, onClick, onHover, onLeave }) {
  return (
    <div className="tri-file" onClick={onClick}
      onMouseEnter={onHover} onMouseLeave={onLeave}
    >{label}</div>
  )
}

function InfoBox({ lines }) {
  return <div className="tri-info">{lines.map((l, i) => <div key={i}>{l}</div>)}</div>
}

function fp(agentId, type) {
  const parent = agentId.includes('-') ? agentId.split('-')[0] : agentId
  return `prompts/${parent}/${agentId}-${type}.md`
}

function AgentSidebarX45({ agents, triangles, selectedAgent, controlAgent, onAgentClick, onFileClick }) {
  const [selectedTriangle, setSelectedTriangle] = useState(null)
  const [selectedSatellite, setSelectedSatellite] = useState(null)
  const [hoveredTop, setHoveredTop] = useState(null)
  const [hoveredMid, setHoveredMid] = useState(null)
  const [hoveredBot, setHoveredBot] = useState(null)

  const agentMap = {}
  agents.forEach(a => { agentMap[a.id] = a })

  const triangleWorkerIds = new Set(
    Object.entries(triangles || {})
      .filter(([, tri]) => {
        const sats = ['master', 'observer', 'indexer', 'curator', 'coach', 'tri_architect']
        return sats.some(role => tri[role] && agentMap[tri[role]])
      })
      .map(([id]) => id)
  )

  const rootAgents = agents
    .filter(a => !a.id.includes('-'))
    .sort((a, b) => parseInt(a.id) - parseInt(b.id))

  const handleTopClick = (agentId) => {
    if (triangleWorkerIds.has(agentId)) {
      const newTri = selectedTriangle === agentId ? null : agentId
      setSelectedTriangle(newTri)
      setSelectedSatellite(null)
    }
    onAgentClick(agentId)
  }

  const handleSatelliteClick = (satId) => {
    setSelectedSatellite(selectedSatellite === satId ? null : satId)
    onAgentClick(satId)
  }

  const handleLogsClick = () => {
    if (!selectedTriangle) return
    onFileClick(`prompts/${selectedTriangle}/LOGS.md`)
  }

  const selectedTri = selectedTriangle ? triangles[selectedTriangle] : null
  const sfx = (id) => id && id.includes('-') ? id.split('-')[1] : id

  const satRole = (satId) => {
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

  const topLabel = hoveredTop ? getShortLabel(hoveredTop) : null

  const hoverLabel = (h) => {
    if (!h) return null
    if (typeof h === 'string' && h.includes('/')) return h
    return getShortLabel(h)
  }

  const mkCell = (id, big, hoverSet) => ({
    id, label: sfx(id), agent: agentMap[id],
    isSelected: id === selectedAgent || id === controlAgent,
    onClick: onAgentClick, onHover: hoverSet, onLeave: () => hoverSet(null), big,
  })

  const mkSatCell = (id, role, hoverSet) => ({
    id, label: sfx(id), role, agent: agentMap[id],
    isSelected: id === selectedSatellite,
    onClick: handleSatelliteClick, onHover: hoverSet, onLeave: () => hoverSet(null),
  })

  const mkFile = (path, label, hoverSet) => ({
    label,
    onClick: () => onFileClick(path),
    onHover: () => hoverSet(path),
    onLeave: () => hoverSet(null),
  })

  // --- MIDDLE: worker triangle diagram (CSS Grid 5 columns) ---
  //
  //  Col:   LEFT      arrow    CENTER    arrow    RIGHT
  //  R1:                       [945]
  //                           Architect
  //  R2:                         │
  //  R3:                     ┌─SYSTEM─┐
  //  R4:  [OUTPUT]     →     │  [345] │    →    [OUTPUT]
  //  R5:  [MEMORY]     →     │        │           │
  //  R6:                     └─METHOD─┘           │
  //  R7:     ↑                  ↑                 ↓
  //  R8:   [745]              [845]    ←        [545]
  //        Curator            Coach             Observer
  //
  const renderMiddle = () => {
    if (!selectedTri) return <div className="x45-empty">{'\u00A0'}</div>
    const wid = selectedTriangle

    const boxClick = (path) => ({
      onClick: () => onFileClick(path),
      onMouseEnter: () => setHoveredMid(path),
      onMouseLeave: () => setHoveredMid(null),
    })

    return (
      <>
        <div className="agent-hover-label">{hoverLabel(hoveredMid) || `Triangle ${wid}`}</div>
        <div className="tri-grid">
          {/* R1: [341-141] Master (left) + [945] Architect (center) */}
          {(() => {
            const mid = selectedTri.master || `${wid}-1${wid.slice(1)}`
            return <LabeledCell id={mid} label={sfx(mid)} role="Master" agent={agentMap[mid]}
              isSelected={mid === selectedAgent || mid === controlAgent}
              onClick={(id) => { setSelectedSatellite(id); onAgentClick(id) }}
              onHover={setHoveredMid} onLeave={() => setHoveredMid(null)} />
          })()}
          <div />
          {selectedTri.tri_architect
            ? <LabeledCell {...mkSatCell(selectedTri.tri_architect, 'Architect', setHoveredMid)} />
            : <div />}
          <div />
          <div className="tri-logs-btn"
            onClick={handleLogsClick}
            onMouseEnter={() => setHoveredMid('LOGS')}
            onMouseLeave={() => setHoveredMid(null)}
          >LOGS</div>

          {/* R2: vline center */}
          <div /><div /><div className="tri-vline" /><div /><div />

          {/* R3: SYSTEM (box top, center) */}
          <div /><div />
          <div className="tri-box-t" {...boxClick(fp(wid, 'system'))}>SYSTEM</div>
          <div /><div />

          {/* R4-R5: OUTPUT → [345 span2] → [OUTPUT span2] */}
          <div className="tri-dir">OUTPUT</div>
          <div className="tri-garrow" />
          <div className="tri-box-m" style={{ gridRow: 'span 2' }}>
            <AgentCell {...mkCell(wid, true, setHoveredMid)} />
          </div>
          <div className="tri-garrow" style={{ gridRow: 'span 2' }} />
          <div className="tri-dir" style={{ gridRow: 'span 2' }}>OUTPUT</div>

          {/* R5: MEMORY → [345 cont.] */}
          <FileBox {...mkFile(fp(wid, 'memory'), 'MEMORY', setHoveredMid)} />
          <div className="tri-garrow" />

          {/* R6: ↑ _ METHODOLOGY (box bottom) */}
          <div className="tri-garrow-up" /><div />
          <div className="tri-box-b" {...boxClick(fp(wid, 'methodology'))}>METHODOLOGY</div>
          <div /><div />

          {/* R7: │ _ ↑ _ ↓ */}
          <div className="tri-vline" /><div />
          <div className="tri-garrow-up" />
          <div />
          <div className="tri-garrow-down" />

          {/* R8: │ _ [845] ← [545 span2] */}
          <div className="tri-vline" /><div />
          {selectedTri.coach
            ? <LabeledCell {...mkSatCell(selectedTri.coach, 'Coach', setHoveredMid)} />
            : <div />}
          <div className="tri-garrow-left" />
          <div className="tri-cell-tall">
            {selectedTri.observer
              ? <LabeledCell {...mkSatCell(selectedTri.observer, 'Observer', setHoveredMid)} />
              : <div />}
          </div>

          {/* R9: [745] ← ── ── [545 cont] */}
          {selectedTri.curator
            ? <LabeledCell {...mkSatCell(selectedTri.curator, 'Curator', setHoveredMid)} />
            : <div />}
          <div className="tri-garrow-left" />
          <div className="tri-hline" />
          <div className="tri-hline" />
        </div>

        {/* Indexer (optional, below grid) */}
        {selectedTri.indexer && (
          <div className="tri-indexer-ext">
            <div className="tri-vline" />
            <span className="tri-flow-label">INDEX</span>
            <div className="tri-vline" />
            <LabeledCell {...mkSatCell(selectedTri.indexer, 'Indexer', setHoveredMid)} />
          </div>
        )}
      </>
    )
  }

  // --- BOTTOM: satellite diagram (same layout as middle) ---
  //
  //  R1:                 [supervisor]
  //  R2:                      │
  //  R3:                  ┌─SYSTEM─┐
  //  R4:  [INPUT1]    →   │ [AGENT]│   →  [OUTPUT]
  //  R5:  [MEMORY]    →   │        │
  //  R6:     ↑            └─METHOD─┘
  //  R7:     │                ↑
  //  R8:   [700]            [800]
  //
  const renderBottom = () => {
    if (!selectedSatellite || !selectedTri) return <div className="x45-empty">{'\u00A0'}</div>

    const role = satRole(selectedSatellite)
    const wid = selectedTriangle
    const sid = selectedSatellite
    const roleNames = { master: 'Master', observer: 'Observer', indexer: 'Indexer', curator: 'Curator', coach: 'Coach', tri_architect: 'Architect' }

    const boxClick = (path) => ({
      onClick: () => onFileClick(path),
      onMouseEnter: () => setHoveredBot(path),
      onMouseLeave: () => setHoveredBot(null),
    })

    // Supervisor at top: 900 for tri_architect, 945 for others
    // 900 = global agent → open right panel only; 945 = triangle satellite → navigate bottom
    const supId = (role === 'tri_architect') ? '900' : (selectedTri.tri_architect || '945')
    const supIsSatellite = supId !== '900' && satRole(supId) !== null
    const supervisorEl = <AgentCell
      id={supId} label={sfx(supId)} agent={agentMap[supId]}
      isSelected={supIsSatellite ? supId === selectedSatellite : supId === selectedAgent || supId === controlAgent}
      onClick={supIsSatellite ? handleSatelliteClick : onAgentClick}
      onHover={setHoveredBot} onLeave={() => setHoveredBot(null)}
    />

    // Per-role: input1 (top-left), output (right)
    let input1El, outputEl

    if (role === 'observer') {
      input1El = <InfoBox lines={[`${wid}`, 'OUTPUT']} />
      outputEl = (
        <div className="tri-grid-outputs">
          <div className="tri-output-col">
            <div className="tri-info-sm">bilans</div>
            <div className="tri-info-sm">métriques</div>
          </div>
          <div className="tri-target-col">
            <span className="tri-target-arrow">{sfx(selectedTri.coach) || '845'}</span>
            <span className="tri-target-arrow">{sfx(selectedTri.tri_architect) || '945'}</span>
          </div>
        </div>
      )
    } else if (role === 'indexer') {
      input1El = <InfoBox lines={['raw data', 'web pages', 'PDF, docs']} />
      outputEl = (
        <div className="tri-grid-outputs">
          <div className="tri-output-col">
            <div className="tri-info-sm">INDEX</div>
          </div>
          <div className="tri-target-col">
            <span className="tri-target-arrow">{sfx(selectedTri.curator) || '745'}</span>
            <span className="tri-target-arrow">{sfx(selectedTri.tri_architect) || '945'}</span>
          </div>
        </div>
      )
    } else if (role === 'curator') {
      input1El = <InfoBox lines={[`${sfx(selectedTri.observer) || '545'}`, 'output']} />
      outputEl = <FileBox {...mkFile(fp(wid, 'memory'), `${wid}-memory`, setHoveredBot)} />
    } else if (role === 'coach') {
      input1El = <InfoBox lines={[`${sfx(selectedTri.observer) || '545'}`, 'bilans']} />
      outputEl = <FileBox {...mkFile(fp(wid, 'methodology'), `${wid}-method.`, setHoveredBot)} />
    } else if (role === 'master') {
      input1El = <InfoBox lines={['project', 'config']} />
      outputEl = <InfoBox lines={['dispatch', 'pipeline']} />
    } else if (role === 'tri_architect') {
      const outputFiles = []
      if (selectedTri.indexer) outputFiles.push({ path: fp(selectedTri.indexer, 'system'), label: `${sfx(selectedTri.indexer)}-sys` })
      if (selectedTri.curator) outputFiles.push({ path: fp(selectedTri.curator, 'system'), label: `${sfx(selectedTri.curator)}-sys` })
      outputFiles.push({ path: fp(wid, 'system'), label: `${wid}-sys` })
      if (selectedTri.observer) outputFiles.push({ path: fp(selectedTri.observer, 'system'), label: `${sfx(selectedTri.observer)}-sys` })
      if (selectedTri.coach) outputFiles.push({ path: fp(selectedTri.coach, 'system'), label: `${sfx(selectedTri.coach)}-sys` })

      input1El = <InfoBox lines={['project', 'INDEX', `${sfx(selectedTri.observer) || '545'} bilans`]} />
      outputEl = (
        <div className="tri-output-col">
          {outputFiles.map(f => (
            <FileBox key={f.path} {...mkFile(f.path, f.label, setHoveredBot)} />
          ))}
        </div>
      )
    } else {
      input1El = <InfoBox lines={['input']} />
      outputEl = <div className="tri-dir">output/</div>
    }

    return (
      <>
        <div className="agent-hover-label">{hoverLabel(hoveredBot) || `${roleNames[role] || 'Agent'} ${sfx(sid)}`}</div>
        <div className="tri-grid">
          {/* R1: supervisor (center) */}
          <div /><div />{supervisorEl}<div /><div />

          {/* R2: vline */}
          <div /><div /><div className="tri-vline" /><div /><div />

          {/* R3: SYSTEM (box top) */}
          <div /><div />
          <div className="tri-box-t" {...boxClick(fp(sid, 'system'))}>SYSTEM</div>
          <div /><div />

          {/* R4-R5: INPUT1 → [AGENT span2] → [OUTPUT span2] */}
          {input1El}
          <div className="tri-garrow" />
          <div className="tri-box-m" style={{ gridRow: 'span 2' }}>
            <AgentCell {...mkCell(sid, true, setHoveredBot)} />
          </div>
          <div className="tri-garrow" style={{ gridRow: 'span 2' }} />
          <div style={{ gridRow: 'span 2' }}>{outputEl}</div>

          {/* R5: MEMORY → [AGENT cont.] */}
          <FileBox {...mkFile(fp(sid, 'memory'), 'MEMORY', setHoveredBot)} />
          <div className="tri-garrow" />

          {/* R6: ↑ _ METHODOLOGY (box bottom) */}
          <div className="tri-garrow-up" /><div />
          <div className="tri-box-b" {...boxClick(fp(sid, 'methodology'))}>METHODOLOGY</div>
          <div /><div />

          {/* R7: │ _ ↑ */}
          <div className="tri-vline" /><div />
          <div className="tri-garrow-up" />
          <div /><div />

          {/* R8: [700] _ [800] — global agents, dynamic color */}
          <div className="tri-labeled-cell">
            <AgentCell {...mkCell('700', false, setHoveredBot)} />
            <span className="tri-role-tag">Curator</span>
          </div>
          <div />
          <div className="tri-labeled-cell">
            <AgentCell {...mkCell('800', false, setHoveredBot)} />
            <span className="tri-role-tag">Coach</span>
          </div>
          <div /><div />
        </div>
      </>
    )
  }

  return (
    <div className="x45-sidebar">
      {/* TOP */}
      <div className="x45-third">
        <div className="agent-hover-label">{topLabel || '\u00A0'}</div>
        {Object.entries(
          rootAgents.reduce((groups, a) => {
            const g = a.id[0]
            ;(groups[g] = groups[g] || []).push(a)
            return groups
          }, {})
        ).map(([g, agents]) => (
          <div key={g} className="x45-grid">
            {agents.map(a => {
              const color = getStatusColor(a.status)
              const isSelected = a.id === selectedTriangle || a.id === selectedAgent || a.id === controlAgent
              const isPulsing = a.status === 'context_compacted'
              return (
                <div key={a.id}
                  className={`agent-cell ${color} ${isSelected ? 'selected' : ''} ${isPulsing ? 'pulsing' : ''}`}
                  onMouseDown={e => e.preventDefault()}
                  onClick={() => handleTopClick(a.id)}
                  onMouseEnter={() => setHoveredTop(a.id)}
                  onMouseLeave={() => setHoveredTop(null)}
                >{a.id}</div>
              )
            })}
          </div>
        ))}
      </div>

      {/* MIDDLE */}
      <div className="x45-third x45-border-top">{renderMiddle()}</div>

      {/* BOTTOM */}
      <div className="x45-third x45-border-top">{renderBottom()}</div>
    </div>
  )
}

export default AgentSidebarX45
