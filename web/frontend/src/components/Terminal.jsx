import React, { useState, useEffect, useRef } from 'react'
import { api, wsUrl } from '../basePath'

function Terminal({ agentId, focused, pollInterval = 1.0 }) {
  const [output, setOutput] = useState('')
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [connected, setConnected] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [paused, setPaused] = useState(false)
  const outputRef = useRef(null)
  const wsRef = useRef(null)
  const inputRef = useRef(null)
  const lastSentInput = useRef('')
  const syncTimeoutRef = useRef(null)

  // Scroll/pause refs
  const userScrolledRef = useRef(false)
  const scrollPauseRef = useRef(null)
  const pendingOutputRef = useRef(null) // latest output while paused

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
  useEffect(() => {
    requestAnimationFrame(() => {
      if (outputRef.current && !userScrolledRef.current) {
        outputRef.current.scrollTop = outputRef.current.scrollHeight
      }
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
        }
      } catch (err) {
        console.error('Failed to fetch output:', err)
        setOutput('Error loading output')
      }
    }

    fetchOutput()

    // Connect WebSocket (pauses when tab is hidden)
    const agentWsUrl = wsUrl(`ws/agent/${agentId}?poll=${pollInterval}`)
    let intentionalClose = false

    const connect = () => {
      if (document.hidden) return  // Don't connect if tab is hidden
      intentionalClose = false
      const ws = new WebSocket(agentWsUrl)
      wsRef.current = ws

      ws.onopen = () => setConnected(true)

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data)

        if (data.type === 'output') {
          if (userScrolledRef.current) {
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

      ws.onclose = () => {
        setConnected(false)
        if (wsRef.current === ws && !intentionalClose) {
          reconnectTimeoutRef.current = setTimeout(connect, 2000)
        }
      }

      ws.onerror = () => setConnected(false)
    }

    const handleVisibility = () => {
      if (document.hidden) {
        intentionalClose = true
        if (wsRef.current) { wsRef.current.close(); wsRef.current = null }
        setConnected(false)
      } else {
        if (!wsRef.current) connect()
      }
    }

    document.addEventListener('visibilitychange', handleVisibility)
    connect()

    return () => {
      document.removeEventListener('visibilitychange', handleVisibility)
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current)
      intentionalClose = true
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
      if (syncTimeoutRef.current) clearTimeout(syncTimeoutRef.current)
      if (scrollPauseRef.current) clearTimeout(scrollPauseRef.current)
    }
  }, [agentId, pollInterval])

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
        await fetch(api(`api/agent/${agentId}/input`), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: message, previous: lastSentInput.current, submit: true })
        })
      } else {
        // Empty input: just send Enter
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

  // Click anywhere in terminal → focus input (unless selecting text)
  const handleTerminalClick = (e) => {
    // Don't steal focus from buttons or if user is selecting text
    if (e.target.closest('button') || e.target.closest('textarea')) return
    if (window.getSelection()?.toString()) return
    inputRef.current?.focus()
  }

  return (
    <div className="terminal" onClick={handleTerminalClick}>
      <div className="terminal-header">
        <span className={`status-dot ${connected ? 'green' : 'red'}`}></span>
        Agent {agentId} {connected ? '(live)' : '(disconnected)'}
        {syncing && <span className="sync-indicator"> ⟳</span>}
        {paused && <span className="pause-indicator"> ⏸</span>}
      </div>
      <pre className="terminal-output" ref={outputRef} onScroll={handleScroll}>
        {output}
      </pre>
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
        <button onClick={handleSubmit} disabled={sending} title="Send (Enter)">
          ⏎
        </button>
        <button onClick={() => sendKeys('Escape')} className="key-btn" title="Escape">
          Esc
        </button>
        <button onClick={() => sendKeys('C-c')} className="key-btn danger" title="Ctrl+C">
          ^C
        </button>
      </div>
    </div>
  )
}

export default Terminal
