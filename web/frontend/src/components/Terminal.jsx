import React, { useState, useEffect, useRef } from 'react'
import { api, wsUrl } from '../basePath'

function Terminal({ agentId, focused }) {
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

    // Connect WebSocket
    const agentWsUrl = wsUrl(`ws/agent/${agentId}`)

    const connect = () => {
      const ws = new WebSocket(agentWsUrl)
      wsRef.current = ws

      ws.onopen = () => setConnected(true)

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data)

        if (data.type === 'output') {
          if (userScrolledRef.current) {
            // Paused: store latest but don't update view
            pendingOutputRef.current = data.output || ''
          } else {
            // Live: update view
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
        // Only reconnect if this WS is still the active one
        // (not replaced by a new connection after agent switch)
        if (wsRef.current === ws) {
          reconnectTimeoutRef.current = setTimeout(connect, 2000)
        }
      }

      ws.onerror = () => setConnected(false)
    }

    connect()

    return () => {
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current)
      if (wsRef.current) {
        wsRef.current.onclose = null  // Prevent reconnect on intentional close
        wsRef.current.close()
        wsRef.current = null
      }
      if (syncTimeoutRef.current) clearTimeout(syncTimeoutRef.current)
      if (scrollPauseRef.current) clearTimeout(scrollPauseRef.current)
    }
  }, [agentId])

  // Handle input change - sync to tmux with debounce
  const handleInputChange = (e) => {
    const newValue = e.target.value
    setInput(newValue)
    inputValueRef.current = newValue
    setSyncing(true)
    lastLocalEditRef.current = Date.now()

    if (syncTimeoutRef.current) clearTimeout(syncTimeoutRef.current)

    syncTimeoutRef.current = setTimeout(async () => {
      if (newValue !== lastSentInput.current) {
        try {
          await fetch(api(`api/agent/${agentId}/input`), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: newValue, submit: false })
          })
          lastSentInput.current = newValue
        } catch (err) {
          console.error('Sync error:', err)
        }
      }
      setSyncing(false)
    }, 150)
  }

  // Handle submit
  const handleSubmit = async () => {
    if (!input.trim() || sending) return

    const message = input.trim()
    setSending(true)
    lastSubmitRef.current = Date.now()

    if (syncTimeoutRef.current) {
      clearTimeout(syncTimeoutRef.current)
      syncTimeoutRef.current = null
      setSyncing(false)
    }

    try {
      await fetch(api(`api/agent/${agentId}/input`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: message, submit: true })
      })
      setInput('')
      inputValueRef.current = ''
      lastSentInput.current = ''
    } catch (err) {
      console.error('Submit error:', err)
    } finally {
      setSending(false)
      requestAnimationFrame(() => {
        if (inputRef.current) inputRef.current.focus()
      })
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  return (
    <div className="terminal">
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
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          placeholder={`Co-edit with tmux...`}
          disabled={sending}
        />
        <button onClick={handleSubmit} disabled={sending || !input.trim()}>
          ⏎
        </button>
      </div>
    </div>
  )
}

export default Terminal
