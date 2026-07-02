import React, { useState } from 'react'
import { AgentCell, LabeledCell, FileBox, fp, sfx, hoverLabel } from './cells'

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
function TriangleDiagram({
  wid, tri, agentMap, agentNames,
  selectedAgent, controlAgent, selectedSatellite, showContexts,
  onAgentClick, onSatelliteClick, onFileClick, onLogsClick, onToggleContexts,
}) {
  const [hoveredMid, setHoveredMid] = useState(null)
  const mainId = tri.worker || wid

  const boxClick = (path) => ({
    onClick: () => onFileClick(path),
    onMouseEnter: () => setHoveredMid(path),
    onMouseLeave: () => setHoveredMid(null),
  })

  const mkCell = (id, big) => ({
    id, label: sfx(id), agent: agentMap[id],
    isSelected: id === selectedAgent || id === controlAgent,
    onClick: onAgentClick, onHover: setHoveredMid, onLeave: () => setHoveredMid(null), big,
  })

  const mkSatCell = (id, role) => ({
    id, label: sfx(id), role, agent: agentMap[id],
    isSelected: id === selectedSatellite,
    onClick: onSatelliteClick, onHover: setHoveredMid, onLeave: () => setHoveredMid(null),
  })

  const mkFile = (path, label) => ({
    label,
    onClick: () => onFileClick(path),
    onHover: () => setHoveredMid(path),
    onLeave: () => setHoveredMid(null),
  })

  return (
    <>
      <div className="agent-hover-label">{hoverLabel(hoveredMid, agentNames) || `Triangle ${wid}`}</div>
      <div className="tri-grid">
        {/* R1: [341-141] Master (left) + [945] Architect (center) */}
        {(() => {
          const mid = tri.master || `${wid}-1${wid.slice(1)}`
          return <LabeledCell id={mid} label={sfx(mid)} role="Master" agent={agentMap[mid]}
            isSelected={mid === selectedAgent || mid === controlAgent}
            onClick={onSatelliteClick}
            onHover={setHoveredMid} onLeave={() => setHoveredMid(null)} />
        })()}
        <div />
        {tri.tri_architect
          ? <LabeledCell {...mkSatCell(tri.tri_architect, 'Architect')} />
          : <div />}
        <div />
        <div className="tri-logs-btn"
          onClick={() => onLogsClick()}
          onMouseEnter={() => setHoveredMid('LOGS')}
          onMouseLeave={() => setHoveredMid(null)}
        >LOGS</div>

        {/* R2: vline center */}
        <div /><div /><div className="tri-vline" /><div /><div />

        {/* R3: SYSTEM (box top, center) */}
        <div /><div />
        <div className="tri-box-t" {...boxClick(fp(mainId, 'system'))}>SYSTEM</div>
        <div /><div />

        {/* R4-R5: OUTPUT → [345 span2] → [OUTPUT span2] */}
        <div className="tri-dir">OUTPUT</div>
        <div className="tri-garrow" />
        <div className="tri-box-m" style={{ gridRow: 'span 2' }}>
          <AgentCell {...mkCell(mainId, true)} />
        </div>
        <div className="tri-garrow" style={{ gridRow: 'span 2' }} />
        <div className="tri-dir" style={{ gridRow: 'span 2' }}>OUTPUT</div>

        {/* R5: MEMORY → [345 cont.] */}
        <FileBox {...mkFile(fp(mainId, 'memory'), 'MEMORY')} />
        <div className="tri-garrow" />

        {/* R6: ↑ _ METHODOLOGY (box bottom) */}
        <div className="tri-garrow-up" /><div />
        <div className="tri-box-b" {...boxClick(fp(mainId, 'methodology'))}>METHODOLOGY</div>
        <div /><div />

        {/* R7: │ _ ↑ _ ↓ */}
        <div className="tri-vline" /><div />
        <div className="tri-garrow-up" />
        <div />
        <div className="tri-garrow-down" />

        {/* R8: │ _ [845] ← [545 span2] */}
        <div className="tri-vline" /><div />
        {tri.coach
          ? <LabeledCell {...mkSatCell(tri.coach, 'Coach')} />
          : <div />}
        <div className="tri-garrow-left" />
        <div className="tri-cell-tall">
          {tri.observer
            ? <LabeledCell {...mkSatCell(tri.observer, 'Observer')} />
            : <div />}
        </div>

        {/* R9: [745] ← ── ── [545 cont] */}
        {tri.curator
          ? <LabeledCell {...mkSatCell(tri.curator, 'Curator')} />
          : <div />}
        <div className="tri-garrow-left" />
        <div className="tri-hline" />
        <div className="tri-hline" />
      </div>

      {/* Indexer (optional, below grid) */}
      {tri.indexer && (
        <div className="tri-indexer-ext">
          <div className="tri-vline" />
          <span className="tri-flow-label">INDEX</span>
          <div className="tri-vline" />
          <LabeledCell {...mkSatCell(tri.indexer, 'Indexer')} />
        </div>
      )}

      {/* z21: Contextes button — full width below triangle */}
      {tri?.type === 'z21' && (
        <div
          className={`z21-ctx-toggle ${showContexts ? 'tri-btn-active' : ''}`}
          onClick={onToggleContexts}
        >contextes</div>
      )}
    </>
  )
}

export default TriangleDiagram
