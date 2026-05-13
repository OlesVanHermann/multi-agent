import React, { useState, useEffect, useCallback } from 'react'
import { api } from '../basePath'

function getStatusColor(status) {
  switch (status) {
    case 'has_bashes': return 'green'
    case 'busy': return 'lightgreen'
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

function getShortLabel(id, agentNames) {
  const baseId = id?.split('-')[0]
  if (agentNames[baseId]) return `${id} — ${agentNames[baseId]}`
  return id
}

function AgentCell({ id, label, agent, isSelected, onClick, onHover, onLeave, big }) {
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

function fmtTokens(n) {
  n = parseInt(n) || 0
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M'
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K'
  return String(n)
}

function AgentSidebarX45({ agents, triangles, selectedAgent, controlAgent, onAgentClick, onFileClick, agentNames = {}, chatElement, username = 'default' }) {
  const [selectedTriangle, setSelectedTriangle] = useState(null)
  const [selectedSatellite, setSelectedSatellite] = useState(null)
  const [hoveredTop, setHoveredTop] = useState(null)
  const [hoveredMid, setHoveredMid] = useState(null)
  const [hoveredBot, setHoveredBot] = useState(null)
  const [showContexts, setShowContexts] = useState(false)
  const [contexts, setContexts] = useState([])
  const [promptHistory, setPromptHistory] = useState([])
  const [usage, setUsage] = useState(null)
  const [favoris, setFavoris] = useState({})       // {agentId: position 1-6}
  const [favorisMode, setFavorisMode] = useState(false) // config view
  const [project, setProject] = useState(() =>
    localStorage.getItem(`fav_project_${username}`) || ''
  )
  const [projectInput, setProjectInput] = useState('')
  const [projects, setProjects] = useState([])
  const projectRef = React.useRef(project)

  // Refresh projects list from backend
  const refreshProjects = useCallback(() => {
    return fetch(api(`api/config/favoris/projects?user=${username}`))
      .then(r => r.ok ? r.json() : { projects: [] })
      .then(d => { setProjects(d.projects || []); return d.projects || [] })
      .catch(() => [])
  }, [username])

  // Load projects list + resolve initial project
  useEffect(() => {
    refreshProjects().then(list => {
      let p = localStorage.getItem(`fav_project_${username}`) || ''
      if ((!p || !list.includes(p)) && list.length > 0) p = list[0]
      if (p) {
        setProject(p)
        projectRef.current = p
        localStorage.setItem(`fav_project_${username}`, p)
      }
    })
  }, [username, refreshProjects])

  // Load favoris when project changes
  useEffect(() => {
    if (!project) return
    projectRef.current = project
    fetch(api(`api/config/favoris?user=${username}&project=${encodeURIComponent(project)}`))
      .then(r => r.ok ? r.json() : {})
      .then(d => setFavoris(d || {}))
      .catch(() => {})
  }, [username, project])

  // Debounced project rename (only active in favorisMode with existing project)
  useEffect(() => {
    if (!favorisMode || !projectInput || !projectRef.current || projectInput === projectRef.current) return
    const timer = setTimeout(() => {
      const oldP = projectRef.current
      const newP = projectInput
      if (!oldP || oldP === newP) return
      fetch(api('api/config/favoris/rename'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user: username, old_project: oldP, new_project: newP })
      })
        .then(r => r.ok ? r.json() : null)
        .then(d => {
          if (!d) return
          setProject(d.project)
          projectRef.current = d.project
          setFavoris(d.favoris || {})
          localStorage.setItem(`fav_project_${username}`, d.project)
          refreshProjects()
        })
        .catch(() => {})
    }, 500)
    return () => clearTimeout(timer)
  }, [projectInput, favorisMode, username, refreshProjects])

  // Enter favoris mode: if no project yet (NEW), create one
  const enterFavorisMode = useCallback(() => {
    if (favorisMode) {
      // Exit config mode
      setFavorisMode(false)
      return
    }
    if (!project) {
      // NEW — create project with name "new", enter config
      const newName = 'new'
      fetch(api('api/config/favoris'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user: username, project: newName, favoris: {} })
      })
        .then(r => r.ok ? r.json() : null)
        .then(d => {
          if (!d) return
          setProject(d.project)
          projectRef.current = d.project
          setProjectInput(d.project)
          setFavoris({})
          localStorage.setItem(`fav_project_${username}`, d.project)
          refreshProjects()
          setFavorisMode(true)
        })
        .catch(() => {})
    } else {
      // Existing project — enter config, populate input
      setProjectInput(project)
      setFavorisMode(true)
    }
  }, [favorisMode, project, username, refreshProjects])

  // Delete current project
  const deleteProject = useCallback(() => {
    if (!project) return
    fetch(api('api/config/favoris/delete'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user: username, project })
    })
      .then(r => r.ok ? r.json() : null)
      .then(() => {
        setFavorisMode(false)
        setFavoris({})
        setProject('')
        projectRef.current = ''
        setProjectInput('')
        localStorage.removeItem(`fav_project_${username}`)
        refreshProjects().then(list => {
          if (list.length > 0) {
            setProject(list[0])
            projectRef.current = list[0]
            localStorage.setItem(`fav_project_${username}`, list[0])
          }
        })
      })
      .catch(() => {})
  }, [project, username, refreshProjects])

  const saveFavoris = useCallback((newFav) => {
    setFavoris(newFav)
    if (!project) return
    fetch(api('api/config/favoris'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user: username, project, favoris: newFav })
    }).catch(() => {})
  }, [username, project])

  const handleFavChange = (agentId, val) => {
    const newFav = { ...favoris }
    if (val === 'no') {
      delete newFav[agentId]
    } else {
      // Remove any other agent with same position
      const pos = parseInt(val)
      Object.keys(newFav).forEach(k => { if (newFav[k] === pos) delete newFav[k] })
      newFav[agentId] = pos
    }
    saveFavoris(newFav)
  }

  useEffect(() => {
    fetch('/api/usage')
      .then(r => r.ok ? r.json() : null)
      .then(d => setUsage(d))
      .catch(() => {})
  }, [])

  useEffect(() => {
    const fetchHistory = () => {
      fetch('/api/history/recent?n=20')
        .then(r => r.ok ? r.json() : { entries: [] })
        .then(d => setPromptHistory(d.entries || []))
        .catch(() => {})
    }
    fetchHistory()
    const iv = setInterval(fetchHistory, 5000)
    return () => clearInterval(iv)
  }, [])

  const agentMap = {}
  agents.forEach(a => { agentMap[a.id] = a })

  const triangleWorkerIds = new Set(Object.keys(triangles || {}))

  // Build root agents: non-compound agents + virtual entries for x45 groups with running agents
  const hiddenIds = new Set(['001', '002'])
  const x45GroupIds = new Set(Object.keys(triangles || {}))
  const nonCompound = agents.filter(a => !a.id.includes('-') && !hiddenIds.has(a.id))
  const seenBareIds = new Set(nonCompound.map(a => a.id))
  // Add virtual root for x45 groups that have at least one running agent
  const virtualRoots = []
  x45GroupIds.forEach(gid => {
    if (seenBareIds.has(gid)) return
    const hasRunning = agents.some(a => a.id.startsWith(gid + '-'))
    if (hasRunning) virtualRoots.push({ id: gid, status: 'stopped' })
  })
  const rootAgents = [...nonCompound, ...virtualRoots]
    .sort((a, b) => parseInt(a.id) - parseInt(b.id))

  // Compute composite colors for a triangle (all agents)
  const getTriangleColors = (workerId) => {
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

  const handleLogsClick = (agentId) => {
    const id = agentId || (selectedTri?.worker) || selectedTriangle
    if (!id) return
    onFileClick(`logs/${id}/bridge.log`)
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

  const topLabel = hoveredTop ? getShortLabel(hoveredTop, agentNames) : null

  const hoverLabel = (h) => {
    if (!h) return null
    if (typeof h === 'string' && h.includes('/')) return h
    return getShortLabel(h, agentNames)
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
    if (!selectedTri) return (
      <>
        <div className="prompt-history">
          {promptHistory.length === 0
            ? <div className="x45-empty">{'\u00A0'}</div>
            : promptHistory.map((e, i) => (
              <div key={i} className="prompt-history-line">
                <span className="ph-time">{e.time}</span>
                <span className="ph-agent">{e.agent}</span>
                <span className="ph-text">{e.text}</span>
              </div>
            ))
          }
        </div>
      </>
    )
    const wid = selectedTriangle
    const mainId = selectedTri.worker || wid

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
              onClick={handleSatelliteClick}
              onHover={setHoveredMid} onLeave={() => setHoveredMid(null)} />
          })()}
          <div />
          {selectedTri.tri_architect
            ? <LabeledCell {...mkSatCell(selectedTri.tri_architect, 'Architect', setHoveredMid)} />
            : <div />}
          <div />
          <div className="tri-logs-btn"
            onClick={() => handleLogsClick()}
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
            <AgentCell {...mkCell(mainId, true, setHoveredMid)} />
          </div>
          <div className="tri-garrow" style={{ gridRow: 'span 2' }} />
          <div className="tri-dir" style={{ gridRow: 'span 2' }}>OUTPUT</div>

          {/* R5: MEMORY → [345 cont.] */}
          <FileBox {...mkFile(fp(mainId, 'memory'), 'MEMORY', setHoveredMid)} />
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

        {/* z21: Contextes button — full width below triangle */}
        {selectedTri?.type === 'z21' && (
          <div
            className={`z21-ctx-toggle ${showContexts ? 'tri-btn-active' : ''}`}
            onClick={() => { setShowContexts(!showContexts); setSelectedSatellite(null) }}
          >contextes</div>
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
    const mainId = selectedTri.worker || wid
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
      outputEl = <FileBox {...mkFile(fp(mainId, 'memory'), `${wid}-memory`, setHoveredBot)} />
    } else if (role === 'coach') {
      input1El = <InfoBox lines={[`${sfx(selectedTri.observer) || '545'}`, 'bilans']} />
      outputEl = <FileBox {...mkFile(fp(mainId, 'methodology'), `${wid}-method.`, setHoveredBot)} />
    } else if (role === 'master') {
      input1El = <InfoBox lines={['project', 'config']} />
      outputEl = <InfoBox lines={['dispatch', 'pipeline']} />
    } else if (role === 'tri_architect') {
      const outputFiles = []
      if (selectedTri.indexer) outputFiles.push({ path: fp(selectedTri.indexer, 'system'), label: `${sfx(selectedTri.indexer)}-sys` })
      if (selectedTri.curator) outputFiles.push({ path: fp(selectedTri.curator, 'system'), label: `${sfx(selectedTri.curator)}-sys` })
      outputFiles.push({ path: fp(mainId, 'system'), label: `${wid}-sys` })
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

  // Sorted favoris entries for the favoris bar
  const favEntries = Object.entries(favoris)
    .sort((a, b) => a[1] - b[1])
    .slice(0, 6)

  // Favoris config mode: list of active agents with label + select (no/1-6)
  const renderFavorisConfig = () => {
    const activeIds = new Set()
    agents.forEach(a => {
      const base = a.id.split('-')[0]
      if (!hiddenIds.has(base)) activeIds.add(base)
    })
    const allAgents = [...activeIds].sort((a, b) => parseInt(a) - parseInt(b))

    return (
      <div className="fav-config">
        {allAgents.map(aid => {
          const label = getShortLabel(aid, agentNames)
          const truncated = label.length > 20 ? label.slice(0, 20) + '…' : label
          const curVal = favoris[aid] || 'no'
          return (
            <div key={aid} className="fav-config-row">
              <span className="fav-config-label" onClick={() => handleTopClick(aid)}>{truncated}</span>
              <select value={curVal} onChange={e => handleFavChange(aid, e.target.value)} className="fav-config-select">
                <option value="no">no</option>
                <option value="1">1</option>
                <option value="2">2</option>
                <option value="3">3</option>
                <option value="4">4</option>
                <option value="5">5</option>
                <option value="6">6</option>
              </select>
            </div>
          )
        })}
      </div>
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
            onChange={e => {
              const p = e.target.value
              if (p === '__new__') {
                // Create project "new" and enter config mode immediately
                const newName = 'new'
                fetch(api('api/config/favoris'), {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ user: username, project: newName, favoris: {} })
                })
                  .then(r => r.ok ? r.json() : null)
                  .then(d => {
                    if (!d) return
                    setProject(d.project)
                    projectRef.current = d.project
                    setProjectInput(d.project)
                    setFavoris({})
                    localStorage.setItem(`fav_project_${username}`, d.project)
                    refreshProjects()
                    setFavorisMode(true)
                  })
                  .catch(() => {})
                return
              }
              setProject(p)
              projectRef.current = p
              localStorage.setItem(`fav_project_${username}`, p)
            }}
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
        renderFavorisConfig()
      ) : (
        <>
          {/* TOP */}
          <div className="x45-third">
            {/* Favoris bar */}
            {favEntries.length > 0 && (
              <>
                <div className="fav-bar">
                  {favEntries.map(([aid, pos]) => {
                    const isTriangle = triangleWorkerIds.has(aid)
                    const { fillColor, borderColor, isPulsing } = isTriangle
                      ? getTriangleColors(aid)
                      : (() => { const _a = agentMap[aid]; const _ctx = _a?.ctx ?? -1; return { fillColor: getStatusColor(_a?.status), borderColor: _ctx === 0 || _a?.status === 'context_compacted' || _a?.status === 'error' || _a?.status === 'blocked' ? 'border-red' : (_ctx >= 1 && _ctx <= 10) || _a?.status === 'context_warning' ? 'border-orange' : '', isPulsing: _a?.status === 'context_compacted' } })()
                    const isSelected = aid === selectedTriangle || aid === selectedAgent || aid === controlAgent
                    return (
                      <div key={aid}
                        className={`agent-cell ${fillColor} ${borderColor} ${isSelected ? 'selected' : ''} ${isPulsing ? 'pulsing' : ''}`}
                        onMouseDown={e => e.preventDefault()}
                        onClick={() => handleTopClick(aid)}
                        onMouseEnter={() => setHoveredTop(aid)}
                        onMouseLeave={() => setHoveredTop(null)}
                        title={getShortLabel(aid, agentNames)}
                      >{aid}</div>
                    )
                  })}
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
                {row.map(a => {
                  const isTriangle = triangleWorkerIds.has(a.id)
                  const { fillColor, borderColor, isPulsing } = isTriangle
                    ? getTriangleColors(a.id)
                    : (() => { const _ctx = a.ctx ?? -1; return { fillColor: getStatusColor(a.status), borderColor: _ctx === 0 || a.status === 'context_compacted' || a.status === 'error' || a.status === 'blocked' ? 'border-red' : (_ctx >= 1 && _ctx <= 10) || a.status === 'context_warning' ? 'border-orange' : '', isPulsing: a.status === 'context_compacted' } })()
                  const isSelected = a.id === selectedTriangle || a.id === selectedAgent || a.id === controlAgent
                  return (
                    <div key={a.id}
                      className={`agent-cell ${fillColor} ${borderColor} ${isSelected ? 'selected' : ''} ${isPulsing ? 'pulsing' : ''}`}
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
            ) : selectedSatellite && selectedTri ? renderBottom() : chatElement}
          </div>
        </>
      )}
    </div>
  )
}

export default AgentSidebarX45
