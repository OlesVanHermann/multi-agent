import React, { useState } from 'react'
import { api } from '../basePath'
import {
  getShortLabel, getAgentColors, getTriangleColors,
} from './sidebar/cells'
import { useFavoris } from './sidebar/useFavoris'
import TriangleDiagram from './sidebar/TriangleDiagram'
import SatelliteDiagram from './sidebar/SatelliteDiagram'
import FavorisConfig from './sidebar/FavorisConfig'
import PromptHistory from './sidebar/PromptHistory'

const HIDDEN_IDS = new Set(['001', '002'])

function AgentSidebarX45({ agents, triangles, selectedAgent, controlAgent, onAgentClick, onFileClick, agentNames = {}, chatElement, username = 'default' }) {
  const [selectedTriangle, setSelectedTriangle] = useState(null)
  const [selectedSatellite, setSelectedSatellite] = useState(null)
  const [hoveredTop, setHoveredTop] = useState(null)
  const [showContexts, setShowContexts] = useState(false)
  const [contexts, setContexts] = useState([])

  const {
    favoris, favorisMode, project, projectInput, setProjectInput, projects, projectRef,
    refreshProjects, enterFavorisMode, selectProject, deleteProject, handleFavChange,
  } = useFavoris(username)

  const agentMap = {}
  agents.forEach(a => { agentMap[a.id] = a })

  const triangleWorkerIds = new Set(Object.keys(triangles || {}))

  // Build root agents: non-compound agents + virtual entries for x45 groups with running agents
  const nonCompound = agents.filter(a => !a.id.includes('-') && !HIDDEN_IDS.has(a.id))
  const seenBareIds = new Set(nonCompound.map(a => a.id))
  // Add virtual root for x45 groups that have at least one running agent
  const virtualRoots = []
  triangleWorkerIds.forEach(gid => {
    if (seenBareIds.has(gid)) return
    const hasRunning = agents.some(a => a.id.startsWith(gid + '-'))
    if (hasRunning) virtualRoots.push({ id: gid, status: 'stopped' })
  })
  const rootAgents = [...nonCompound, ...virtualRoots]
    .sort((a, b) => parseInt(a.id) - parseInt(b.id))

  const handleTopClick = (agentId) => {
    if (triangleWorkerIds.has(agentId)) {
      const newTri = selectedTriangle === agentId ? null : agentId
      setSelectedTriangle(newTri)
      setSelectedSatellite(null)
      setShowContexts(false)
      // Use compound worker ID for terminal
      const tri = triangles[agentId]
      onAgentClick(tri?.worker || agentId)
      // Fetch z21 contexts if needed
      if (newTri && tri?.type === 'z21') {
        fetch(api(`api/agent/${agentId}/contexts`))
          .then(r => r.ok ? r.json() : { contexts: [] })
          .then(d => setContexts(d.contexts || []))
          .catch(() => setContexts([]))
      }
    } else {
      // Mono agent: clear triangle selection
      setSelectedTriangle(null)
      setSelectedSatellite(null)
      setShowContexts(false)
      onAgentClick(agentId)
    }
  }

  const handleSatelliteClick = (satId) => {
    setSelectedSatellite(selectedSatellite === satId ? null : satId)
    onAgentClick(satId)
  }

  const selectedTri = selectedTriangle ? triangles[selectedTriangle] : null

  const handleLogsClick = (agentId) => {
    const id = agentId || (selectedTri?.worker) || selectedTriangle
    if (!id) return
    onFileClick(`logs/${id}/bridge.log`)
  }

  const topLabel = hoveredTop ? getShortLabel(hoveredTop, agentNames) : null

  // Sorted favoris entries for the favoris bar
  const favEntries = Object.entries(favoris)
    .sort((a, b) => a[1] - b[1])
    .slice(0, 6)

  // Composite cell renderer for fav bar + root grid (triangle-aware colors)
  const renderTopCell = (aid, agent, withTitle) => {
    const { fillColor, borderColor, isPulsing } = triangleWorkerIds.has(aid)
      ? getTriangleColors(triangles, agentMap, aid)
      : getAgentColors(agent)
    const isSelected = aid === selectedTriangle || aid === selectedAgent || aid === controlAgent
    return (
      <div key={aid}
        className={`agent-cell ${fillColor} ${borderColor} ${isSelected ? 'selected' : ''} ${isPulsing ? 'pulsing' : ''}`}
        onMouseDown={e => e.preventDefault()}
        onClick={() => handleTopClick(aid)}
        onMouseEnter={() => setHoveredTop(aid)}
        onMouseLeave={() => setHoveredTop(null)}
        {...(withTitle ? { title: getShortLabel(aid, agentNames) } : {})}
      >{aid}</div>
    )
  }

  return (
    <div className="x45-sidebar">
      {/* Header: normal = (dropdown) [favoris] | config = [input] [x] [favoris] */}
      <div className="fav-header">
        {favorisMode ? (
          <>
            <input
              className="fav-project-input"
              value={projectInput}
              onChange={e => setProjectInput(e.target.value)}
              onBlur={() => {
                if (!projectInput.trim()) {
                  setProjectInput(projectRef.current || 'new')
                }
              }}
              spellCheck={false}
              autoFocus
            />
            <button className="fav-delete-btn" onClick={deleteProject} title="Delete project">x</button>
          </>
        ) : (
          <select
            className="fav-project-select"
            value={project || '__new__'}
            onFocus={() => refreshProjects()}
            onChange={e => selectProject(e.target.value)}
          >
            <option value="__new__">NEW</option>
            {projects.map(p => <option key={p} value={p}>{p}</option>)}
          </select>
        )}
        <button
          className={`fav-toggle ${favorisMode ? 'fav-toggle-active' : ''}`}
          onClick={enterFavorisMode}
        >favoris</button>
      </div>

      {favorisMode ? (
        /* Favoris config: replaces entire sidebar */
        <FavorisConfig
          agents={agents}
          hiddenIds={HIDDEN_IDS}
          agentNames={agentNames}
          favoris={favoris}
          onFavChange={handleFavChange}
          onAgentOpen={handleTopClick}
        />
      ) : (
        <>
          {/* TOP */}
          <div className="x45-third">
            {/* Favoris bar */}
            {favEntries.length > 0 && (
              <>
                <div className="fav-bar">
                  {favEntries.map(([aid]) => renderTopCell(aid, agentMap[aid], true))}
                </div>
                <div className="fav-separator" />
              </>
            )}

            <div className="agent-hover-label">{topLabel || '\u00A0'}</div>
            {(() => {
              const getRow = (id) => {
                const n = parseInt(id)
                if (n < 200) return 0
                if (n < 300) return 1
                if (n < 400) return 2
                if (n < 900) return 3
                return 4
              }
              const rows = [[], [], [], [], []]
              rootAgents.forEach(a => rows[getRow(a.id)].push(a))
              return rows.filter(r => r.length > 0)
            })().map((row, ri) => (
              <div key={ri} className="x45-grid">
                {row.map(a => renderTopCell(a.id, a, false))}
              </div>
            ))}
          </div>

          {/* MIDDLE */}
          <div className="x45-third x45-border-top">
            {selectedTri ? (
              <TriangleDiagram
                wid={selectedTriangle}
                tri={selectedTri}
                agentMap={agentMap}
                agentNames={agentNames}
                selectedAgent={selectedAgent}
                controlAgent={controlAgent}
                selectedSatellite={selectedSatellite}
                showContexts={showContexts}
                onAgentClick={onAgentClick}
                onSatelliteClick={handleSatelliteClick}
                onFileClick={onFileClick}
                onLogsClick={handleLogsClick}
                onToggleContexts={() => { setShowContexts(!showContexts); setSelectedSatellite(null) }}
              />
            ) : (
              <PromptHistory />
            )}
          </div>

          {/* BOTTOM: contexts list, satellite detail, or chat */}
          <div className="x45-third x45-border-top">
            {showContexts && selectedTri?.type === 'z21' ? (
              <div className="z21-contexts">
                <div className="agent-hover-label">Contextes {selectedTriangle}-*</div>
                <div className="z21-ctx-list">
                  {contexts.map(ctx => (
                    <div key={ctx.name} className="z21-ctx-item">
                      <div className="z21-ctx-name">{ctx.name}</div>
                      <div className="z21-ctx-desc">{ctx.description}</div>
                      <div className="z21-ctx-btns">
                        <button className="z21-ctx-btn" onClick={() => onFileClick(ctx.files.archi)}>archi</button>
                        <button className="z21-ctx-btn" onClick={() => onFileClick(ctx.files.methodology)}>method</button>
                        <button className="z21-ctx-btn" onClick={() => onFileClick(ctx.files.memory)}>memory</button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : selectedSatellite && selectedTri ? (
              <SatelliteDiagram
                sid={selectedSatellite}
                wid={selectedTriangle}
                tri={selectedTri}
                agentMap={agentMap}
                agentNames={agentNames}
                selectedAgent={selectedAgent}
                controlAgent={controlAgent}
                onAgentClick={onAgentClick}
                onSatelliteClick={handleSatelliteClick}
                onFileClick={onFileClick}
              />
            ) : chatElement}
          </div>
        </>
      )}
    </div>
  )
}

export default AgentSidebarX45
