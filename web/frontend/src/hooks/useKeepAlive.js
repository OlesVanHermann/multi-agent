import { useState, useEffect } from 'react'
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
        setKeepAliveInfo(prev => ({ ...prev, [profile]: data.info }))
      }
    } catch (err) { console.error('probe:', err) }
  }

  const fetchKeepAlive = async () => {
    try {
      const res = await fetch(api('api/config/keepalive'))
      const data = await res.json()
      const entries = data.entries || []
      setKeepAliveEntries(entries)
      for (const e of entries) {
        if (e.running) kaProbe(e.profile)
      }
    } catch (err) { console.error('keepalive fetch:', err) }
    // Also fetch usage bars
    try {
      const res = await fetch(api('api/usage'))
      const data = await res.json()
      const profiles = data.plan?.profiles || {}
      setKeepAliveUsage(profiles)
      // Also fill info from static files if not already probed
      for (const [pname, pdata] of Object.entries(profiles)) {
        if (pdata.info && !keepAliveInfo[pname]) {
          setKeepAliveInfo(prev => ({ ...prev, [pname]: pdata.info }))
        }
      }
    } catch (err) { console.error('usage fetch:', err) }
  }

  useEffect(() => { if (show) fetchKeepAlive() }, [show])

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
