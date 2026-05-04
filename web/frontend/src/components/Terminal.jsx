import React, { useState, useEffect, useRef } from 'react'
import { api, wsUrl } from '../basePath'
import { createLogger } from '../lib/logger'
import { useWakeDetector } from '../lib/useWakeDetector'
import { useAuth } from '../AuthProvider'

function UsageBars({ usage }) {
  if (!usage) return null
  return (
    <span className="usage-bars">
      <span className="usage-bar-name">{usage.login}</span>
      {usage.bars?.length ? usage.bars.map((b, i) => (
        <span key={i} className="usage-bar-item" title={`${b.label}: ${b.percent}% used${b.resets ? ' — Resets ' + b.resets : ''}`}>
          <span className="usage-bar-track">
            <span className="usage-bar-fill" style={{width: `${Math.min(b.percent, 100)}%`}} />
          </span>
          <span className="usage-bar-pct">{b.percent}%</span>
        </span>
      )) : <span className="usage-bar-pct" title="Usage data unavailable (personal account)">N/A</span>}
    </span>
  )
}

function Terminal({ agentId, focused, pollInterval = 1.0 }) {
  const log = createLogger(`Terminal:${agentId}`)
  const { ensureFreshToken } = useAuth()
  const [output, setOutput] = useState('')
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [connected, setConnected] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [paused, setPaused] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [historyLines, setHistoryLines] = useState(null)
  const [showNotes, setShowNotes] = useState(false)
  const [notesContent, setNotesContent] = useState('')
  const [planUsage, setPlanUsage] = useState(null)
  const outputRef = useRef(null)
  const wsRef = useRef(null)
  const inputRef = useRef(null)
  const fileRef = useRef(null)
  const lastSentInput = useRef('')
  const syncTimeoutRef = useRef(null)
  const wakeReconnectRef = useRef(null)

  // Fetch plan usage for this agent's login
  useEffect(() => {
    if (!agentId) return
    fetch(api(`api/usage/${agentId}`))
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d?.login) setPlanUsage(d) })
      .catch(() => {})
  }, [agentId])

  // Scroll/pause refs
  const userScrolledRef = useRef(false)
  const scrollPauseRef = useRef(null)
  const pendingOutputRef = useRef(null) // latest output while paused
  const selectingRef = useRef(false) // true while user is selecting text

  // Sync coordination refs (avoid stale closures in WebSocket handler)
  const lastLocalEditRef = useRef(0)
  const lastSubmitRef = useRef(0)
  const inputValueRef = useRef('')

  // WebSocket lifecycle ref
  const reconnectTimeoutRef = useRef(null)

  // Resume syncing: apply pending output and scroll to bottom
  const resumeSync = () => {
    userScrolledRef.current = false
    setPaused(false)
    if (pendingOutputRef.current !== null) {
      setOutput(pendingOutputRef.current)
      pendingOutputRef.current = null
    }
    requestAnimationFrame(() => {
      if (outputRef.current) {
        outputRef.current.scrollTop = outputRef.current.scrollHeight
      }
    })
  }

  // Detect user scroll
  const handleScroll = () => {
    const el = outputRef.current
    if (!el) return
    const isAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 50

    if (!isAtBottom) {
      userScrolledRef.current = true
      setPaused(true)
      // Reset the 5s timer on every scroll movement
      if (scrollPauseRef.current) clearTimeout(scrollPauseRef.current)
      scrollPauseRef.current = setTimeout(resumeSync, 5000)
    } else {
      // User scrolled back to bottom manually - resume immediately
      if (userScrolledRef.current) {
        if (scrollPauseRef.current) clearTimeout(scrollPauseRef.current)
        resumeSync()
      }
    }
  }

  // Focus input when this terminal becomes active
  useEffect(() => {
    if (focused && inputRef.current) {
      inputRef.current.focus()
    }
  }, [focused])

  // Auto-scroll when output changes (only fires when not paused)
  // Double rAF ensures layout is computed before scrolling (avoids oscillation)
  useEffect(() => {
    if (userScrolledRef.current) return
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        if (outputRef.current && !userScrolledRef.current) {
          outputRef.current.scrollTop = outputRef.current.scrollHeight
        }
      })
    })
  }, [output])

  // Load and connect
  useEffect(() => {
    if (!agentId) return

    setOutput('Loading...')
    setConnected(false)
    setPaused(false)
    setInput('')
    inputValueRef.current = ''
    lastSentInput.current = ''
    lastLocalEditRef.current = 0
    lastSubmitRef.current = 0
    userScrolledRef.current = false
    pendingOutputRef.current = null
    if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current)

    // Fetch initial output
    const fetchOutput = async () => {
      try {
        const res = await fetch(api(`api/agent/${agentId}/output`))
        if (res.ok) {
          const data = await res.json()
          setOutput(data.output || '(empty)')
          if (data.current_input) {
            setInput(data.current_input)
            inputValueRef.current = data.current_input
            lastSentInput.current = data.current_input
          }
          // Force scroll to bottom after initial load
          requestAnimationFrame(() => {
            requestAnimationFrame(() => {
              if (outputRef.current) {
                outputRef.current.scrollTop = outputRef.current.scrollHeight
              }
            })
          })
        }
      } catch (err) {
        console.error('Failed to fetch output:', err)
        setOutput('Error loading output')
      }
    }

    fetchOutput()

    // Connect WebSocket (pauses when tab is hidden)
    let intentionalClose = false
    let pingTimer = null
    let pongTimer = null

    const clearHeartbeat = () => {
      if (pingTimer) { clearInterval(pingTimer); pingTimer = null }
      if (pongTimer) { clearTimeout(pongTimer); pongTimer = null }
    }

    const startHeartbeat = (ws) => {
      clearHeartbeat()
      pingTimer = setInterval(() => {
        if (ws.readyState !== WebSocket.OPEN) return
        try { ws.send(JSON.stringify({ type: 'ping' })) } catch {}
        if (pongTimer) clearTimeout(pongTimer)
        pongTimer = setTimeout(() => {
          log.ws('pong-miss', { agentId })
          try { ws.close() } catch {}
        }, 5000)
      }, 25000)
    }

    const connect = async () => {
      if (document.hidden) return  // Don't connect if tab is hidden
      const token = await ensureFreshToken()
      if (!token) {
        reconnectTimeoutRef.current = setTimeout(() => connect(), 1000)
        return
      }
      intentionalClose = false
      // Re-read token on every reconnect (token may have been refreshed)
      const freshWsUrl = wsUrl(`ws/agent/${agentId}?poll=${pollInterval}`)
      const ws = new WebSocket(freshWsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        if (wsRef.current !== ws) {
          // This WS is stale (component changed agentId or unmounted while connecting)
          ws.close()
          return
        }
        setConnected(true)
        log.ws('open', { agentId })
        startHeartbeat(ws)
      }

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data)

        if (data.type === 'pong') {
          if (pongTimer) { clearTimeout(pongTimer); pongTimer = null }
          return
        }
        if (data.type === 'output') {
          if (userScrolledRef.current || selectingRef.current) {
            pendingOutputRef.current = data.output || ''
          } else {
            setOutput(data.output || '')
            pendingOutputRef.current = null
          }
        }
        else if (data.type === 'input_sync') {
          const now = Date.now()
          const tmuxInput = data.current_input || ''

          if (now - lastLocalEditRef.current < 800) return
          if (now - lastSubmitRef.current < 3000) return
          if (document.activeElement === inputRef.current &&
              tmuxInput !== inputValueRef.current) return

          setInput(tmuxInput)
          inputValueRef.current = tmuxInput
          lastSentInput.current = tmuxInput
        }
        else if (data.type === 'error') {
          setOutput(`Error: ${data.message}`)
        }
      }

      const scheduleReconnect = () => {
        clearHeartbeat()
        if (intentionalClose) return  // prevent zombie reconnects after cleanup
        if (reconnectTimeoutRef.current) return  // already scheduled, avoid double-fire
        reconnectTimeoutRef.current = setTimeout(() => {
          reconnectTimeoutRef.current = null
          connect()
        }, 2000)
      }

      ws.onclose = () => {
        setConnected(false)
        log.ws('close', { agentId })
        if (wsRef.current === ws) wsRef.current = null  // clear stale ref so handleVisibility can reconnect
        scheduleReconnect()
      }

      ws.onerror = () => {
        setConnected(false)
        log.ws('error', { agentId })
        // onclose always fires after onerror — reconnect handled there
      }
    }

    // Force-close current WS and reconnect (used by wake detector and watchdog).
    // intentionalClose=true *before* close() suppresses the stale onclose →
    // scheduleReconnect path that would race the fresh socket.
    const forceReconnect = async () => {
      log.ws('force-reconnect', { agentId })
      if (reconnectTimeoutRef.current) { clearTimeout(reconnectTimeoutRef.current); reconnectTimeoutRef.current = null }
      clearHeartbeat()
      const ws = wsRef.current
      wsRef.current = null
      setConnected(false)
      if (ws) {
        intentionalClose = true
        try { ws.close() } catch {}
      }
      await connect()             // connect() resets intentionalClose=false
    }
    wakeReconnectRef.current = forceReconnect

    // Live = present AND CONNECTING/OPEN. Do not gate on truthiness alone:
    // CLOSING/CLOSED refs without onclose firing would block reconnects.
    const isLive = (ws) => ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)

    const handleVisibility = () => {
      if (document.hidden) {
        intentionalClose = true
        clearHeartbeat()
        if (reconnectTimeoutRef.current) { clearTimeout(reconnectTimeoutRef.current); reconnectTimeoutRef.current = null }
        // Only close OPEN sockets immediately; CONNECTING ones are handled in onopen to avoid Chrome warning
        if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
          wsRef.current.close()
          wsRef.current = null
        }
        setConnected(false)
      } else {
        intentionalClose = false
        if (!isLive(wsRef.current) && !reconnectTimeoutRef.current) forceReconnect()
      }
    }

    // Reconnect immediately when network comes back (only if no active/pending connection)
    const handleOnline = () => {
      if (!isLive(wsRef.current) && !reconnectTimeoutRef.current) forceReconnect()
    }

    document.addEventListener('visibilitychange', handleVisibility)
    window.addEventListener('online', handleOnline)
    connect()

    return () => {
      document.removeEventListener('visibilitychange', handleVisibility)
      window.removeEventListener('online', handleOnline)
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current)
      intentionalClose = true
      clearHeartbeat()
      wakeReconnectRef.current = null
      if (wsRef.current) {
        // Only close OPEN sockets; CONNECTING ones will be closed in onopen via stale check
        if (wsRef.current.readyState === WebSocket.OPEN) {
          wsRef.current.close()
        }
        wsRef.current = null
      }
      if (syncTimeoutRef.current) clearTimeout(syncTimeoutRef.current)
      if (scrollPauseRef.current) clearTimeout(scrollPauseRef.current)
      if (selectResumeRef.current) clearTimeout(selectResumeRef.current)
      selectingRef.current = false
    }
  }, [agentId, pollInterval, ensureFreshToken])

  // Wake handler: trigger force-reconnect on wake event
  useWakeDetector(() => {
    if (wakeReconnectRef.current) wakeReconnectRef.current()
  })

  // WS health watchdog (per terminal). Recovers from broken reconnect chains
  // (suspended setTimeout, onclose never firing). 30s cadence.
  useEffect(() => {
    if (!agentId) return
    const tick = () => {
      if (document.hidden) return
      const ws = wsRef.current
      const live = ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)
      if (live) return
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
        reconnectTimeoutRef.current = null
      }
      if (wakeReconnectRef.current) {
        log.info('watchdog: no live ws, forcing reconnect')
        wakeReconnectRef.current()
      }
    }
    const id = setInterval(tick, 30000)
    return () => clearInterval(id)
  }, [agentId])

  // Sync mutex: prevent concurrent syncs that interleave in tmux
  const syncInFlightRef = useRef(false)
  const pendingSyncValueRef = useRef(null)

  const doSyncToTmux = async (value) => {
    if (syncInFlightRef.current) {
      pendingSyncValueRef.current = value
      return
    }
    if (value === lastSentInput.current) {
      setSyncing(false)
      return
    }
    syncInFlightRef.current = true
    try {
      await fetch(api(`api/agent/${agentId}/input`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: value, previous: lastSentInput.current, submit: false })
      })
      lastSentInput.current = value
    } catch (err) {
      console.error('Sync error:', err)
    } finally {
      syncInFlightRef.current = false
      // Process queued value if any
      const pending = pendingSyncValueRef.current
      if (pending !== null && pending !== value) {
        pendingSyncValueRef.current = null
        doSyncToTmux(pending)
      } else {
        pendingSyncValueRef.current = null
        setSyncing(false)
      }
    }
  }

  // Handle input change - sync to tmux with debounce
  const handleInputChange = (e) => {
    const newValue = e.target.value
    setInput(newValue)
    inputValueRef.current = newValue
    setSyncing(true)
    lastLocalEditRef.current = Date.now()

    if (syncTimeoutRef.current) clearTimeout(syncTimeoutRef.current)

    syncTimeoutRef.current = setTimeout(() => {
      doSyncToTmux(newValue)
    }, 150)
  }

  // Send raw tmux keys
  const sendKeys = async (...keys) => {
    log.action('send-keys', { agentId, keys: keys.join(',') })
    try {
      await fetch(api(`api/agent/${agentId}/keys`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ keys })
      })
      lastSubmitRef.current = Date.now()
    } catch (err) {
      console.error('Send keys error:', err)
    }
  }

  // Handle submit
  const handleSubmit = async () => {
    if (sending) return

    setSending(true)
    lastSubmitRef.current = Date.now()

    if (syncTimeoutRef.current) {
      clearTimeout(syncTimeoutRef.current)
      syncTimeoutRef.current = null
      setSyncing(false)
    }

    try {
      const message = input.trim()
      if (message) {
        log.action('submit', { agentId, len: message.length })
        await fetch(api(`api/agent/${agentId}/input`), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: message, previous: lastSentInput.current, submit: true })
        })
      } else {
        // Empty input: just send Enter
        log.action('enter', { agentId })
        await sendKeys('Enter')
      }
      setInput('')
      inputValueRef.current = ''
      lastSentInput.current = ''
    } catch (err) {
      console.error('Submit error:', err)
    } finally {
      setSending(false)
      requestAnimationFrame(() => {
        if (inputRef.current) {
          inputRef.current.style.height = 'auto'
          inputRef.current.focus()
        }
      })
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  // Pause updates while selecting text in terminal output
  const selectResumeRef = useRef(null)
  const handleOutputMouseDown = () => {
    selectingRef.current = true
    setPaused(true)
    if (selectResumeRef.current) clearTimeout(selectResumeRef.current)
  }
  const handleOutputMouseUp = () => {
    // Delay resume so user can copy selected text
    if (selectResumeRef.current) clearTimeout(selectResumeRef.current)
    selectResumeRef.current = setTimeout(() => {
      selectingRef.current = false
      if (!userScrolledRef.current) resumeSync()
    }, 3000)
  }

  // Clean wrapped URLs on copy: Claude Code hard-wraps at terminal width
  // producing "...type=c  \n  ode&..." — rejoin those fragments
  const handleOutputCopy = (e) => {
    const sel = window.getSelection()?.toString()
    if (!sel || !/https?:\/\//.test(sel)) return
    // Remove newline + surrounding spaces within URL text
    const cleaned = sel.replace(/\s*\n\s*/g, '')
    if (cleaned !== sel) {
      e.preventDefault()
      navigator.clipboard.writeText(cleaned)
    }
  }

  // Click anywhere in terminal → focus input (unless selecting text)
  const handleTerminalClick = (e) => {
    // Don't steal focus from buttons or if user is selecting text
    if (e.target.closest('button') || e.target.closest('textarea')) return
    if (window.getSelection()?.toString()) return
    inputRef.current?.focus()
  }

  const [uploading, setUploading] = useState(false)

  const handleUpload = async (e) => {
    const files = e.target.files
    if (!files || files.length === 0) return
    setUploading(true)
    try {
      let paths = ''
      for (const file of files) {
        const form = new FormData()
        form.append('file', file)
        const res = await fetch(api('api/upload'), { method: 'POST', body: form })
        if (!res.ok) {
          const err = await res.json().catch(() => ({}))
          alert(`Upload failed: ${err.detail || res.statusText}`)
          continue
        }
        const data = await res.json()
        paths += data.path + ' '
      }
      if (paths) {
        log.action('upload', { agentId, fileCount: files.length })
        setInput(prev => prev + paths)
        inputValueRef.current += paths
        lastLocalEditRef.current = Date.now()
        setSyncing(true)
        if (syncTimeoutRef.current) clearTimeout(syncTimeoutRef.current)
        syncTimeoutRef.current = setTimeout(() => doSyncToTmux(inputValueRef.current), 150)
      }
    } catch (err) {
      log.error('upload failed', { agentId, error: err.message })
      alert(`Upload error: ${err.message}`)
    } finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  const toggleHistory = async () => {
    if (showHistory) {
      setShowHistory(false)
      return
    }
    log.action('toggle-history', { agentId, show: true })
    setShowNotes(false)
    try {
      const res = await fetch(api(`api/agent/${agentId}/history`))
      const data = await res.json()
      setHistoryLines(data.lines || [])
      setShowHistory(true)
      setTimeout(() => { if (outputRef.current) outputRef.current.scrollTop = outputRef.current.scrollHeight }, 50)
    } catch {
      setHistoryLines(['(erreur lecture historique)'])
      setShowHistory(true)
    }
  }

  const toggleNotes = async () => {
    if (showNotes) {
      log.action('toggle-notes', { agentId, show: false })
      try {
        await fetch(api(`api/agent/${agentId}/notes`), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content: notesContent }),
        })
      } catch {}
      setShowNotes(false)
      return
    }
    log.action('toggle-notes', { agentId, show: true })
    setShowHistory(false)
    try {
      const res = await fetch(api(`api/agent/${agentId}/notes`))
      const data = await res.json()
      setNotesContent(data.content || '')
      setShowNotes(true)
    } catch {
      setNotesContent('')
      setShowNotes(true)
    }
  }

  return (
    <div className="terminal" onClick={handleTerminalClick}>
      <div className="terminal-header">
        <span className={`status-dot ${connected ? 'green' : 'red'}`}></span>
        Agent {agentId} {connected ? '(live)' : '(disconnected)'}
        {syncing && <span className="sync-indicator"> ⟳</span>}
        {paused && <span className="pause-indicator"> ⏸</span>}
        <UsageBars usage={planUsage} />
        <button onClick={toggleHistory} className={`config-btn${showHistory ? ' config-btn-active' : ''}`}
          title="Voir historique des prompts">{showHistory ? 'terminal' : 'historique'}</button>
        <button onClick={toggleNotes} className={`config-btn${showNotes ? ' config-btn-active' : ''}`}
          title="Notes de l'agent">notes</button>
        <input type="file" ref={fileRef} hidden multiple onChange={handleUpload} />
        <button onClick={() => fileRef.current?.click()} className="config-btn" title="Upload file to /tmp" disabled={uploading}>
          {uploading ? '...' : 'upload'}</button>
      </div>
      {showNotes ? (
        <textarea className="terminal-notes" value={notesContent}
          onChange={(e) => setNotesContent(e.target.value)}
          placeholder="Notes pour cet agent..." />
      ) : (
        <pre className="terminal-output" ref={outputRef} onScroll={handleScroll}
          onMouseDown={handleOutputMouseDown} onMouseUp={handleOutputMouseUp} onCopy={handleOutputCopy}>
          {showHistory ? (historyLines && historyLines.length > 0 ? historyLines.join('\n') : '(aucun historique)') : output}
        </pre>
      )}
      <div className="terminal-input">
        <span className="prompt">❯</span>
        <textarea
          ref={inputRef}
          rows={1}
          value={input}
          onChange={(e) => {
            handleInputChange(e)
            // Auto-resize: reset then grow to fit content
            e.target.style.height = 'auto'
            e.target.style.height = e.target.scrollHeight + 'px'
          }}
          onKeyDown={handleKeyDown}
          placeholder={`Co-edit with tmux...`}
          disabled={sending}
        />
        <span className="key-group">
          <button onClick={handleSubmit} disabled={sending} title="Send (Enter)">⏎</button>
          <button onClick={() => sendKeys('Escape')} className="key-btn" title="Escape">Esc</button>
          <button onClick={() => sendKeys('C-c')} className="key-btn danger" title="Ctrl+C">^C</button>
        </span>
        <span className="key-group">
          <button onClick={() => sendKeys('Left')} className="key-btn" title="Left arrow">←</button>
          <button onClick={() => sendKeys('Down')} className="key-btn" title="Down arrow">↓</button>
          <button onClick={() => sendKeys('Right')} className="key-btn" title="Right arrow">→</button>
          <button onClick={() => sendKeys('S-Tab')} className="key-btn" title="Shift+Tab (cycle permission mode)">⇧⇥</button>
        </span>
      </div>
    </div>
  )
}

export default Terminal
