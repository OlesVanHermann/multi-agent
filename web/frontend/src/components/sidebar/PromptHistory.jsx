import React, { useState, useEffect } from 'react'

// Historique des prompts récents (api/history/recent), rafraîchi toutes
// les 5 s. Affiché au milieu de la sidebar quand aucun triangle n'est
// sélectionné.
function PromptHistory() {
  const [entries, setEntries] = useState([])

  useEffect(() => {
    const fetchHistory = () => {
      fetch('/api/history/recent?n=20')
        .then(r => r.ok ? r.json() : { entries: [] })
        .then(d => setEntries(d.entries || []))
        .catch(() => {})
    }
    fetchHistory()
    const iv = setInterval(fetchHistory, 5000)
    return () => clearInterval(iv)
  }, [])

  return (
    <div className="prompt-history">
      {entries.length === 0
        ? <div className="x45-empty">{'\u00A0'}</div>
        : entries.map((e, i) => (
          <div key={i} className="prompt-history-line">
            <span className="ph-time">{e.time}</span>
            <span className="ph-agent">{e.agent}</span>
            <span className="ph-text">{e.text}</span>
          </div>
        ))
      }
    </div>
  )
}

export default PromptHistory
