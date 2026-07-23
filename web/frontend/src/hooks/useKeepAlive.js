import { useState, useEffect, useCallback } from 'react'
import { api } from '../basePath'
import { createLogger } from '../lib/logger'

const log = createLogger('App')

// État + actions du panneau Keep Alive (api/config/keepalive + api/usage).
// `show` déclenche le fetch initial, comme l'ancien effet inline de App.jsx.
export function useKeepAlive(show) {
  const [keepAliveEntries, setKeepAliveEntries] = useState([])
  const [keepAliveInfo, setKeepAliveInfo] = useState({})
  const [keepAliveUsage, setKeepAliveUsage] = useState({})
  const [selectedKeepAlive, setSelectedKeepAlive] = useState(null)

  const kaProbe = async (profile) => {
    try {
      const res = await fetch(api('api/config/keepalive/probe'), {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ profile })
      })
      if (res.ok) {
        const data = await res.json()
        return data.info || {}
      }
    } catch (err) { console.error('probe:', err) }
    return {}
  }

  const fetchKeepAlive = useCallback(async () => {
    let entries = []
    let profiles = {}
    try {
      const res = await fetch(api('api/config/keepalive'))
      const data = await res.json()
      entries = data.entries || []
      setKeepAliveEntries(entries)
    } catch (err) { console.error('keepalive fetch:', err) }

    try {
      const res = await fetch(api('api/usage'))
      const data = await res.json()
      profiles = data.plan?.profiles || {}
    } catch (err) { console.error('usage fetch:', err) }

    // Un snapshot complet remplace le précédent. Les caches disque d'une
    // session arrêtée ne doivent jamais survivre dans l'état React.
    const running = entries.filter(e => e.running)
    const probed = await Promise.all(running.map(async e => [e.profile, await kaProbe(e.profile)]))
    const nextInfo = Object.fromEntries(probed.filter(([, info]) => Object.keys(info).length))
    const nextUsage = Object.fromEntries(
      running
        .filter(e => profiles[e.profile]?.bars?.length
          && profiles[e.profile]?.source_session === `agent-002-${e.profile}`)
        .map(e => [e.profile, profiles[e.profile]])
    )
    setKeepAliveInfo(nextInfo)
    setKeepAliveUsage(nextUsage)
  }, [])

  useEffect(() => {
    if (!show) return undefined
    fetchKeepAlive()
    // Les comptes peuvent être réauthentifiés hors dashboard. Rafraîchir les
    // cartes sans conserver les anciens snapshots React.
    const timer = window.setInterval(fetchKeepAlive, 15000)
    return () => window.clearInterval(timer)
  }, [show, fetchKeepAlive])

  const kaStart = async (profile) => {
    log.action('keepalive-start', { profile })
    await fetch(api('api/config/keepalive/start'), {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ profile })
    })
    fetchKeepAlive()
  }

  const kaStop = async (profile) => {
    log.action('keepalive-stop', { profile })
    await fetch(api('api/config/keepalive/stop'), {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ profile })
    })
    fetchKeepAlive()
  }

  return {
    keepAliveEntries, keepAliveInfo, keepAliveUsage,
    selectedKeepAlive, setSelectedKeepAlive,
    kaStart, kaStop,
  }
}
