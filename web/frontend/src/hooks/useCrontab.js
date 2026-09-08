import { useState, useEffect } from 'react'
import { api } from '../basePath'
import { createLogger } from '../lib/logger'

const log = createLogger('App')

// État + actions du panneau Crontab (CRUD api/config/crontab).
// `show` déclenche le fetch initial, comme l'ancien effet inline de App.jsx.
export function useCrontab(show, agents) {
  const [crontabEntries, setCrontabEntries] = useState([])
  const [crontabForm, setCrontabForm] = useState(false)
  const [crontabEdit, setCrontabEdit] = useState(null) // {agent_id, period, prompt} or null
  const [cronAgent, setCronAgent] = useState('')
  const [cronPeriod, setCronPeriod] = useState(10)
  const [cronPrompt, setCronPrompt] = useState('')

  const fetchCrontab = async () => {
    try {
      const res = await fetch(api('api/config/crontab'))
      const data = await res.json()
      setCrontabEntries(data.entries || [])
    } catch (err) { console.error('crontab fetch:', err) }
  }

  useEffect(() => { if (show) fetchCrontab() }, [show])

  const cronCreate = async () => {
    if (!cronAgent) return alert('Selectionnez un agent')
    if (!cronPrompt.trim()) return alert('Le prompt ne peut pas etre vide')
    log.action('cron-create', { agent: cronAgent, period: cronPeriod })
    const res = await fetch(api('api/config/crontab'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent_id: cronAgent, period: cronPeriod, prompt: cronPrompt })
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      return alert(err.detail || 'Erreur creation')
    }
    setCrontabForm(false); setCronAgent(''); setCronPeriod(10); setCronPrompt('')
    fetchCrontab()
  }

  const cronUpdate = async () => {
    if (!crontabEdit) return
    if (!cronAgent) return alert('Selectionnez un agent')
    if (!cronPrompt.trim()) return alert('Le prompt ne peut pas etre vide')
    log.action('cron-update', { agent: cronAgent, period: cronPeriod })
    const agentChanged = cronAgent !== crontabEdit.agent_id
    const periodChanged = cronPeriod !== crontabEdit.period
    if (agentChanged || periodChanged) {
      // Agent or period changed: delete old + create new
      await fetch(api('api/config/crontab'), {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: crontabEdit.agent_id, period: crontabEdit.period })
      })
      const res = await fetch(api('api/config/crontab'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: cronAgent, period: cronPeriod, prompt: cronPrompt })
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        return alert(err.detail || 'Erreur modification')
      }
    } else {
      await fetch(api('api/config/crontab'), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: crontabEdit.agent_id, period: crontabEdit.period, prompt: cronPrompt })
      })
    }
    setCrontabEdit(null); setCrontabForm(false); setCronPrompt('')
    fetchCrontab()
  }

  const cronSuspendResume = async (entry) => {
    log.action(entry.suspended ? 'cron-resume' : 'cron-suspend', { agent: entry.agent_id })
    await fetch(api('api/config/crontab'), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent_id: entry.agent_id, period: entry.period, action: entry.suspended ? 'resume' : 'suspend' })
    })
    fetchCrontab()
  }

  const cronDelete = async (entry) => {
    log.action('cron-delete', { agent: entry.agent_id, period: entry.period })
    await fetch(api('api/config/crontab'), {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent_id: entry.agent_id, period: entry.period })
    })
    fetchCrontab()
  }

  const cronStartEdit = (entry) => {
    setCrontabEdit(entry)
    setCronAgent(entry.agent_id)
    setCronPeriod(entry.period)
    setCronPrompt(entry.prompt)
    setCrontabForm(true)
  }

  const cronStartCopy = (entry) => {
    setCrontabEdit(null)
    setCronAgent(entry.agent_id)
    setCronPeriod(entry.period)
    setCronPrompt(entry.prompt)
    setCrontabForm(true)
  }

  const cronStartNew = () => {
    setCrontabEdit(null)
    setCronAgent(agents.length > 0 ? agents[0].id : '')
    setCronPeriod(10)
    setCronPrompt('')
    setCrontabForm(true)
  }

  return {
    crontabEntries, crontabForm, setCrontabForm, crontabEdit, setCrontabEdit,
    cronAgent, setCronAgent, cronPeriod, setCronPeriod, cronPrompt, setCronPrompt,
    cronCreate, cronUpdate, cronSuspendResume, cronDelete,
    cronStartEdit, cronStartCopy, cronStartNew,
  }
}
