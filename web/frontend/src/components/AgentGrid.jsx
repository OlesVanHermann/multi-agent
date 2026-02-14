import React, { useState } from 'react'

// Agent descriptions for tooltips
export const AGENT_LABELS = {
  '100': 'Master Studies - Orchestration pipeline',
  '300': 'Crawl - Téléchargement site web',
  '301': 'Extract Index - Structure & types de pages',
  '320': 'Templates - Analyse templates site',
  '321': 'Sémantique - Analyse sémantique contenu',
  '322': 'Liens - Maillage interne & countries.json',
  '323': 'Agrégation SEO Technique',
  '330': 'Trustpilot - Avis clients',
  '331': 'Reddit - Discussions & mentions',
  '332': 'WebHostingTalk - Forum hébergement',
  '333': 'G2 - Avis B2B',
  '334': 'YouTube - Chaîne & vidéos',
  '335': 'Forums - Autres forums',
  '336': 'Agrégation Réputation',
  '340': 'PageSpeed - Performance web',
  '341': 'Latence - Tests réseau multi-pays',
  '342': 'BGP - Infrastructure réseau & AS',
  '343': 'PTR - Reverse DNS',
  '344': 'Pricing - Tarifs multi-pays',
  '345': 'Infrastructure - Datacenters & tech',
  '346': 'Sécurité - Audit sécurité',
  '347': 'Agrégation Performance',
  '348': 'Price Tracker - Suivi prix',
  '349': 'PTR Analysis - Analyse reverse DNS',
  '350': 'Support - Analyse support client',
  '351': 'Offres Emploi - Recrutement',
  '352': 'Key People - Dirigeants',
  '353': 'LinkedIn - Profil entreprise',
  '354': 'Agrégation Entreprise',
  '355': 'X.com - Présence Twitter/X',
  '356': 'News - Actualités presse',
  '357': 'Mastodon - Présence Mastodon',
  '360': 'SimilarWeb - Trafic & audience',
  '364': 'Ahrefs - Backlinks & SEO',
  '368': 'Ubersuggest - Mots-clés',
  '373': 'SEO Google - Visibilité SERP',
  '374': 'Agrégation SEO',
  '390': 'Rapport Final - Génération rapport',
  '391': 'Diff JSON - Comparaison données',
  '392': 'Diff Changes - Alertes changements',
  '393': 'Diff History - Historique évolutions',
  '600': 'Release Studies - Publication PDF',
  '601': 'Diff - Release comparaisons',
  '900': 'Architect - Configuration système',
}

function AgentGrid({ agents, selectedAgent, controlAgent, onAgentClick }) {
  const [hoveredAgent, setHoveredAgent] = useState(null)

  // Get status color based on server-reported status
  const getStatusColor = (status) => {
    switch (status) {
      case 'busy': return 'green'
      case 'active': return 'gray'
      case 'idle': return 'gray'
      case 'stale': return 'gray'
      case 'starting': return 'blue'
      case 'context_warning': return 'orange'
      case 'context_compacted': return 'red'
      case 'error':
      case 'blocked': return 'orange'
      case 'stopped': return 'darkgray'
      default: return 'gray'
    }
  }

  // Label to display at top
  const displayId = hoveredAgent || selectedAgent || controlAgent
  const displayLabel = displayId
    ? `${displayId} - ${AGENT_LABELS[displayId] || 'Agent'}`
    : null

  // Group agents by hundred range (1XX, 2XX, 3XX...)
  const groups = []
  let currentGroup = []
  let currentRange = -1
  agents.forEach(agent => {
    const range = Math.floor(parseInt(agent.id) / 100)
    if (range !== currentRange) {
      if (currentGroup.length > 0) groups.push(currentGroup)
      currentGroup = []
      currentRange = range
    }
    currentGroup.push(agent)
  })
  if (currentGroup.length > 0) groups.push(currentGroup)

  return (
    <div className="agent-grid-container">
      {/* Hover/selected label */}
      <div className="agent-hover-label">
        {displayLabel || '\u00A0'}
      </div>

      {/* Visual grid grouped by range */}
      {groups.map((group, gi) => (
        <div key={gi} className="agent-grid-group">
          {group.map(agent => {
            const color = getStatusColor(agent.status)
            const isSelected = agent.id === selectedAgent || agent.id === controlAgent
            const isPulsing = agent.status === 'context_compacted'

            return (
              <div
                key={agent.id}
                className={`agent-cell ${color} ${isSelected ? 'selected' : ''} ${isPulsing ? 'pulsing' : ''}`}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => onAgentClick(agent.id)}
                onMouseEnter={() => setHoveredAgent(agent.id)}
                onMouseLeave={() => setHoveredAgent(null)}
              >
                {agent.id}
              </div>
            )
          })}
        </div>
      ))}
    </div>
  )
}

export default AgentGrid
