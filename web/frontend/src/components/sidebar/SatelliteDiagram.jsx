import React, { useState } from 'react'
import { AgentCell, FileBox, InfoBox, fp, sfx, hoverLabel, satRole } from './cells'

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
function SatelliteDiagram({
  sid, wid, tri, agentMap, agentNames,
  selectedAgent, controlAgent,
  onAgentClick, onSatelliteClick, onFileClick,
}) {
  const [hoveredBot, setHoveredBot] = useState(null)
  const role = satRole(sid)
  const mainId = tri.worker || wid
  const roleNames = { master: 'Master', observer: 'Observer', indexer: 'Indexer', curator: 'Curator', coach: 'Coach', tri_architect: 'Architect' }

  const boxClick = (path) => ({
    onClick: () => onFileClick(path),
    onMouseEnter: () => setHoveredBot(path),
    onMouseLeave: () => setHoveredBot(null),
  })

  const mkCell = (id, big) => ({
    id, label: sfx(id), agent: agentMap[id],
    isSelected: id === selectedAgent || id === controlAgent,
    onClick: onAgentClick, onHover: setHoveredBot, onLeave: () => setHoveredBot(null), big,
  })

  const mkFile = (path, label) => ({
    label,
    onClick: () => onFileClick(path),
    onHover: () => setHoveredBot(path),
    onLeave: () => setHoveredBot(null),
  })

  // Supervisor at top: 900 for tri_architect, 945 for others
  // 900 = global agent → open right panel only; 945 = triangle satellite → navigate bottom
  const supId = (role === 'tri_architect') ? '900' : (tri.tri_architect || '945')
  const supIsSatellite = supId !== '900' && satRole(supId) !== null
  const supervisorEl = <AgentCell
    id={supId} label={sfx(supId)} agent={agentMap[supId]}
    isSelected={supIsSatellite ? supId === sid : supId === selectedAgent || supId === controlAgent}
    onClick={supIsSatellite ? onSatelliteClick : onAgentClick}
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
          <span className="tri-target-arrow">{sfx(tri.coach) || '845'}</span>
          <span className="tri-target-arrow">{sfx(tri.tri_architect) || '945'}</span>
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
          <span className="tri-target-arrow">{sfx(tri.curator) || '745'}</span>
          <span className="tri-target-arrow">{sfx(tri.tri_architect) || '945'}</span>
        </div>
      </div>
    )
  } else if (role === 'curator') {
    input1El = <InfoBox lines={[`${sfx(tri.observer) || '545'}`, 'output']} />
    outputEl = <FileBox {...mkFile(fp(mainId, 'memory'), `${wid}-memory`)} />
  } else if (role === 'coach') {
    input1El = <InfoBox lines={[`${sfx(tri.observer) || '545'}`, 'bilans']} />
    outputEl = <FileBox {...mkFile(fp(mainId, 'methodology'), `${wid}-method.`)} />
  } else if (role === 'master') {
    input1El = <InfoBox lines={['project', 'config']} />
    outputEl = <InfoBox lines={['dispatch', 'pipeline']} />
  } else if (role === 'tri_architect') {
    const outputFiles = []
    if (tri.indexer) outputFiles.push({ path: fp(tri.indexer, 'system'), label: `${sfx(tri.indexer)}-sys` })
    if (tri.curator) outputFiles.push({ path: fp(tri.curator, 'system'), label: `${sfx(tri.curator)}-sys` })
    outputFiles.push({ path: fp(mainId, 'system'), label: `${wid}-sys` })
    if (tri.observer) outputFiles.push({ path: fp(tri.observer, 'system'), label: `${sfx(tri.observer)}-sys` })
    if (tri.coach) outputFiles.push({ path: fp(tri.coach, 'system'), label: `${sfx(tri.coach)}-sys` })

    input1El = <InfoBox lines={['project', 'INDEX', `${sfx(tri.observer) || '545'} bilans`]} />
    outputEl = (
      <div className="tri-output-col">
        {outputFiles.map(f => (
          <FileBox key={f.path} {...mkFile(f.path, f.label)} />
        ))}
      </div>
    )
  } else {
    input1El = <InfoBox lines={['input']} />
    outputEl = <div className="tri-dir">output/</div>
  }

  return (
    <>
      <div className="agent-hover-label">{hoverLabel(hoveredBot, agentNames) || `${roleNames[role] || 'Agent'} ${sfx(sid)}`}</div>
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
          <AgentCell {...mkCell(sid, true)} />
        </div>
        <div className="tri-garrow" style={{ gridRow: 'span 2' }} />
        <div style={{ gridRow: 'span 2' }}>{outputEl}</div>

        {/* R5: MEMORY → [AGENT cont.] */}
        <FileBox {...mkFile(fp(sid, 'memory'), 'MEMORY')} />
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
          <AgentCell {...mkCell('700', false)} />
          <span className="tri-role-tag">Curator</span>
        </div>
        <div />
        <div className="tri-labeled-cell">
          <AgentCell {...mkCell('800', false)} />
          <span className="tri-role-tag">Coach</span>
        </div>
        <div /><div />
      </div>
    </>
  )
}

export default SatelliteDiagram
