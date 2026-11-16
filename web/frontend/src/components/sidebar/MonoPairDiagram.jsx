import React, { useState } from 'react'
import { AgentCell, LabeledCell, FileBox, fp, sfx, hoverLabel } from './cells'

// Pipeline compact au schéma x45 : principal 1XX + Contradictor 2XX.
// Aucun emplacement fantôme pour Architect/Curator/Coach/Observer 5XX.
export default function MonoPairDiagram({
  wid, tri, agentMap, agentNames, selectedAgent, controlAgent,
  selectedSatellite, onAgentClick, onSatelliteClick, onFileClick, onLogsClick,
}) {
  const [hovered, setHovered] = useState(null)
  const mainId = tri.worker
  const contradictorId = tri.echo

  const file = (type, label) => ({
    label,
    onClick: () => onFileClick(fp(mainId, type)),
    onHover: () => setHovered(fp(mainId, type)),
    onLeave: () => setHovered(null),
  })

  return <>
    <div className="agent-hover-label">
      {hoverLabel(hovered, agentNames) || `Mono ${wid}`}
    </div>
    <div className="tri-grid mono-pair-grid">
      {/* R1 : SYSTEM + logs, sans agents inexistants. */}
      <div /><div />
      <div className="tri-box-t" onClick={() => onFileClick(fp(mainId, 'system'))}>SYSTEM</div>
      <div />
      <div className="tri-logs-btn" onClick={() => onLogsClick(mainId)}>LOGS</div>

      {/* R2-R3 : mémoire → principal 1XX → sortie. */}
      <FileBox {...file('memory', 'MEMORY')} />
      <div className="tri-garrow" />
      <div className="tri-box-m" style={{ gridRow: 'span 2' }}>
        <AgentCell id={mainId} label={sfx(mainId)} agent={agentMap[mainId]}
          isSelected={mainId === selectedAgent || mainId === controlAgent}
          onClick={onAgentClick} onHover={setHovered} onLeave={() => setHovered(null)} big />
      </div>
      <div className="tri-garrow" style={{ gridRow: 'span 2' }} />
      <div className="tri-dir" style={{ gridRow: 'span 2' }}>OUTPUT</div>

      <div /><div />

      {/* R4 : méthodologie du principal. */}
      <div /><div />
      <div className="tri-box-b" onClick={() => onFileClick(fp(mainId, 'methodology'))}>METHODOLOGY</div>
      <div /><div />

      {/* R5-R6 : Contradictor 2XX directement sous le principal. */}
      <div /><div /><div className="tri-vline" /><div /><div />
      <div /><div />
      {contradictorId
        ? <LabeledCell id={contradictorId} label={sfx(contradictorId)} role="Contradictor"
            agent={agentMap[contradictorId]} isSelected={contradictorId === selectedSatellite}
            onClick={onSatelliteClick} onHover={setHovered} onLeave={() => setHovered(null)} />
        : <div />}
      <div /><div />
    </div>
  </>
}
