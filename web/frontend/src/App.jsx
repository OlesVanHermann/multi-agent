import React, { useState } from 'react'
import './lib/fetchInterceptor'
import AgentGrid from './components/AgentGrid'
import AgentSidebarX45 from './components/AgentSidebarX45'
import Terminal from './components/Terminal'
import FileViewer from './components/FileViewer'
import LoginModelPanel from './components/LoginModelPanel'
import StatusBar from './components/StatusBar'
import DevChat from './components/DevChat'
import HeaderBar from './components/HeaderBar'
import ColorLegend from './components/ColorLegend'
import CrontabSplit from './components/CrontabSplit'
import KeepAliveSplit from './components/KeepAliveSplit'

import { useAuth, LoginForm } from './AuthProvider'
import { createLogger } from './lib/logger'
import { usePollSetting } from './hooks/usePollSetting'
import { useAgentsData } from './hooks/useAgentsData'
import { useStatusWebSocket } from './hooks/useStatusWebSocket'
import { usePanelConfig } from './hooks/usePanelConfig'
import { useCrontab } from './hooks/useCrontab'
import { useKeepAlive } from './hooks/useKeepAlive'

const log = createLogger('App')

function App() {
  const { user, logout, isOperator, isAuthenticated, ensureFreshToken } = useAuth()

  if (!isAuthenticated) return <LoginForm />
  const [selectedAgent, setSelectedAgent] = useState(null)
  const [controlPlane, setControlPlane] = useState('000') // Super-Master by default
  const [activePanel, setActivePanel] = useState('control') // 'control' or 'agent'
  const [selectedFile, setSelectedFile] = useState(null)
  // configPanel: null | 'loginModel' | 'couleurs' | 'crontab' | 'keepAlive'
  const [configPanel, setConfigPanel] = useState(null)

  const [agentPoll, setAgentPoll] = usePollSetting('agent', 1)
  const [statusPoll, setStatusPoll] = usePollSetting('status', 10)
  const [fetchSec, setFetchSec] = usePollSetting('fetch', 15)

  const {
    agents, mode, triangles, agentNames, lastUpdate, redisStatus,
    reconnecting, setReconnecting, applyUpdate, refetchAgentsRef,
  } = useAgentsData(fetchSec)

  useStatusWebSocket({ statusPoll, ensureFreshToken, applyUpdate, setReconnecting, refetchAgentsRef })

  const [panelConfig, handlePanelChange] = usePanelConfig()
  const crontab = useCrontab(configPanel === 'crontab', agents)
  const keepAlive = useKeepAlive(configPanel === 'keepAlive')

  const togglePanel = (key) => setConfigPanel(prev => (prev === key ? null : key))

  const handleAgentClick = (agentId) => {
    setSelectedFile(null) // clear file view when selecting an agent
    // Check panel override first
    const override = panelConfig[agentId]
    if (override) {
      if (override === 'control') {
        setControlPlane(agentId)
        setActivePanel('control')
        log.nav('control', { agentId })
      } else {
        setSelectedAgent(agentId)
        setActivePanel('agent')
        log.nav('agent', { agentId })
      }
      return
    }
    // Default logic
    const num = parseInt(agentId)
    // For compound IDs (341-141), use suffix to determine role
    const suffixNum = agentId.includes('-') ? parseInt(agentId.split('-')[1]) : num
    // x45: 0xx/1xx go to control (incl. master satellites); pipeline: 0xx/1xx + 900+
    const isControl = mode === 'x45' ? (suffixNum < 200) : (num < 200 || num >= 900)
    if (isControl) {
      setControlPlane(agentId)
      setActivePanel('control')
      log.nav('control', { agentId })
    } else {
      setSelectedAgent(agentId)
      setActivePanel('agent')
      log.nav('agent', { agentId })
    }
  }

  const handleFileClick = (filePath) => {
    log.action('file-click', { path: filePath })
    setSelectedFile(filePath)
    setActivePanel('agent')
  }

  const activeCount = agents.filter(a =>
    a.status === 'active' || a.status === 'busy' || a.status === 'idle'
  ).length
  const warningCount = agents.filter(a => a.status === 'context_warning').length
  const compactedCount = agents.filter(a => a.status === 'context_compacted').length

  return (
    <div className="app">
      <HeaderBar
        activeConfigPanel={configPanel}
        onTogglePanel={togglePanel}
        agentPoll={agentPoll} setAgentPoll={setAgentPoll}
        statusPoll={statusPoll} setStatusPoll={setStatusPoll}
        fetchSec={fetchSec} setFetchSec={setFetchSec}
        username={user?.username}
        onLogout={logout}
      />

      <main className="main">
        {/* Left column: Agent Grid or x45 Sidebar */}
        <section className="panel agents-panel">
          <h2>AGENTS ({agents.length})</h2>
          {mode === 'x45' ? (
            <AgentSidebarX45
              agents={agents}
              triangles={triangles}
              selectedAgent={selectedAgent}
              controlAgent={controlPlane}
              onAgentClick={handleAgentClick}
              onFileClick={handleFileClick}
              agentNames={agentNames}
              chatElement={<DevChat />}
              username={user?.username || 'default'}
            />
          ) : (
            <AgentGrid
              agents={agents}
              selectedAgent={selectedAgent}
              controlAgent={controlPlane}
              onAgentClick={handleAgentClick}
              agentNames={agentNames}
            />
          )}
          {mode !== 'x45' && <div style={{height:'180px',flexShrink:0,borderTop:'1px solid var(--border-color)'}}><DevChat /></div>}
        </section>

        {/* Center column: Control Plane Terminal */}
        <section
          className={`panel control-panel ${activePanel === 'control' ? 'panel-active' : ''}`}
          onMouseEnter={() => setActivePanel('control')}
        >
          <div className="panel-header">
            <h2>CONTROL ({controlPlane}) — {agentNames[controlPlane.split('-')[0]] || getAgentType(controlPlane)}</h2>
          </div>
          <Terminal agentId={controlPlane} focused={activePanel === 'control'} pollInterval={agentPoll} />
        </section>

        {/* Right column: Selected Agent Terminal */}
        <section
          className={`panel agent-panel ${activePanel === 'agent' ? 'panel-active' : ''}`}
          onMouseEnter={() => setActivePanel('agent')}
        >
          <div className="panel-header">
            <h2>AGENT {selectedAgent ? `(${selectedAgent}) — ${agentNames[selectedAgent.split('-')[0]] || getAgentType(selectedAgent)}` : '---'}</h2>
          </div>
          <LoginModelPanel hidden={configPanel !== 'loginModel'} mode={mode} panelConfig={panelConfig} onPanelChange={handlePanelChange} runningAgents={agents} />
          {configPanel === 'couleurs' && <ColorLegend />}
          {configPanel === 'crontab' && (
            <CrontabSplit crontab={crontab} agents={agents} focused={activePanel === 'agent'} pollInterval={agentPoll} />
          )}
          {configPanel === 'keepAlive' && (
            <KeepAliveSplit keepAlive={keepAlive} focused={activePanel === 'agent'} pollInterval={agentPoll} />
          )}
          {configPanel === null && (selectedFile ? (
            <FileViewer filePath={selectedFile} />
          ) : selectedAgent ? (
            <Terminal agentId={selectedAgent} focused={activePanel === 'agent'} pollInterval={agentPoll} />
          ) : (
            <div className="no-selection">
              Select an agent from the grid
            </div>
          ))}
        </section>
      </main>

      <StatusBar
        agentCount={agents.length}
        activeCount={activeCount}
        warningCount={warningCount}
        compactedCount={compactedCount}
        redisStatus={redisStatus}
        lastUpdate={lastUpdate}
        reconnecting={reconnecting}
      />
    </div>
  )
}

function getAgentType(id) {
  const num = parseInt(id)
  if (num < 100) return 'Super-Master'
  if (num < 200) return 'Master'
  if (num < 300) return 'Explorer'
  if (num < 400) return 'Developer'
  if (num < 500) return 'Integrator'
  if (num < 600) return 'Tester'
  if (num < 700) return 'Releaser'
  if (num < 800) return 'Documenter'
  if (num < 900) return 'Monitor'
  return 'Architect'
}

export default App
