import React, { useState, useRef } from 'react'
import { api } from '../basePath'
import { createLogger } from '../lib/logger'
import { useAuth } from '../AuthProvider'
import { useAgentWebSocket } from './terminal/useAgentWebSocket'
import TerminalHeader from './terminal/TerminalHeader'
import TerminalInput from './terminal/TerminalInput'

function Terminal({ agentId, focused, pollInterval = 1.0 }) {
  const log = createLogger(`Terminal:${agentId}`)
  const { ensureFreshToken } = useAuth()
  const [output, setOutput] = useState('')
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [paused, setPaused] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [historyLines, setHistoryLines] = useState(null)
  const [showNotes, setShowNotes] = useState(false)
  const [notesContent, setNotesContent] = useState('')
  const [uploading, setUploading] = useState(false)
  const outputRef = useRef(null)
  const inputRef = useRef(null)
  const fileRef = useRef(null)
  const lastSentInput = useRef('')
  const syncTimeoutRef = useRef(null)

  // Scroll/pause refs
  const userScrolledRef = useRef(false)
  const scrollPauseRef = useRef(null)
  const pendingOutputRef = useRef(null) // latest output while paused
  const selectingRef = useRef(false) // true while user is selecting text
  const selectResumeRef = useRef(null)

  // Sync coordination refs (avoid stale closures in WebSocket handler)
  const lastLocalEditRef = useRef(0)
  const lastSubmitRef = useRef(0)
  const inputValueRef = useRef('')

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
  React.useEffect(() => {
    if (focused && inputRef.current) {
      inputRef.current.focus()
    }
  }, [focused])

  // Auto-scroll when output changes (only fires when not paused)
  // Double rAF ensures layout is computed before scrolling (avoids oscillation)
  React.useEffect(() => {
    if (userScrolledRef.current) return
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        if (outputRef.current && !userScrolledRef.current) {
          outputRef.current.scrollTop = outputRef.current.scrollHeight
        }
      })
    })
  }, [output])

  // --- WebSocket lifecycle (delegated to useAgentWebSocket) ---
  const handlersRef = useRef({})
  handlersRef.current = {
    onReset: () => {
      setOutput('Loading...')
      setPaused(false)
      setInput('')
      inputValueRef.current = ''
      lastSentInput.current = ''
      lastLocalEditRef.current = 0
      lastSubmitRef.current = 0
      userScrolledRef.current = false
      pendingOutputRef.current = null
    },
    fetchInitial: async () => {
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
    },
    onOutput: (text) => {
      if (userScrolledRef.current || selectingRef.current) {
        pendingOutputRef.current = text
      } else {
        setOutput(text)
        pendingOutputRef.current = null
      }
    },
    onInputSync: (tmuxInput) => {
      const now = Date.now()
      if (now - lastLocalEditRef.current < 800) return
      if (now - lastSubmitRef.current < 3000) return
      if (document.activeElement === inputRef.current &&
          tmuxInput !== inputValueRef.current) return

      setInput(tmuxInput)
      inputValueRef.current = tmuxInput
      lastSentInput.current = tmuxInput
    },
    onError: (message) => setOutput(`Error: ${message}`),
    onCleanup: () => {
      if (syncTimeoutRef.current) clearTimeout(syncTimeoutRef.current)
      if (scrollPauseRef.current) clearTimeout(scrollPauseRef.current)
      if (selectResumeRef.current) clearTimeout(selectResumeRef.current)
      selectingRef.current = false
    },
  }

  const wsState = useAgentWebSocket({ agentId, pollInterval, ensureFreshToken, handlersRef })

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
      <TerminalHeader
        agentId={agentId}
        wsState={wsState}
        syncing={syncing}
        paused={paused}
        showHistory={showHistory}
        onToggleHistory={toggleHistory}
        showNotes={showNotes}
        onToggleNotes={toggleNotes}
        fileRef={fileRef}
        uploading={uploading}
        onUpload={handleUpload}
      />
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
      <TerminalInput
        inputRef={inputRef}
        input={input}
        onInputChange={handleInputChange}
        onKeyDown={handleKeyDown}
        onSubmit={handleSubmit}
        sendKeys={sendKeys}
        sending={sending}
      />
    </div>
  )
}

export default Terminal
