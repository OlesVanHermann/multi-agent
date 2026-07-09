import { useState, useEffect } from 'react'
import { api } from '../basePath'

export function usePanelConfig() {
  const [panelConfig, setPanelConfig] = useState({})

  // Fetch panel config on mount
  useEffect(() => {
    fetch(api('api/config/panel'))
      .then(r => r.json())
      .then(d => setPanelConfig(d.overrides || {}))
      .catch(() => {})
  }, [])

  const handlePanelChange = (agentId, panel) => {
    setPanelConfig(prev => {
      const next = { ...prev }
      if (panel === '') {
        delete next[agentId]
      } else {
        next[agentId] = panel
      }
      return next
    })
  }

  return [panelConfig, handlePanelChange]
}
