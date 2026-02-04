import React, { useState, useEffect, useRef } from 'react'

function Terminal({ agentId }) {
  const [lines, setLines] = useState([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const outputRef = useRef(null)
  const wsRef = useRef(null)

  // Auto-scroll to bottom
  useEffect(() => {
    if (outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight
    }
  }, [lines])

  // Subscribe to messages for this agent
  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/ws/messages`

    const connect = () => {
      wsRef.current = new WebSocket(wsUrl)

      wsRef.current.onmessage = (event) => {
        const data = JSON.parse(event.data)
        if (data.type === 'message') {
          // Show messages from or to this agent
          if (data.agent_id === agentId || data.data?.to_agent === agentId) {
            const timestamp = new Date().toLocaleTimeString()
            const from = data.agent_id
            const response = data.data?.response || ''

            // Truncate long responses for display
            const preview = response.length > 200
              ? response.substring(0, 200) + '...'
              : response

            setLines(prev => [...prev.slice(-100), {
              time: timestamp,
              type: 'response',
              from: from,
              text: preview
            }])
          }
        }
      }

      wsRef.current.onclose = () => {
        setTimeout(connect, 3000)
      }
    }

    connect()

    // Clear lines when agent changes
    setLines([{
      time: new Date().toLocaleTimeString(),
      type: 'system',
      text: `Connected to agent ${agentId}`
    }])

    return () => {
      if (wsRef.current) {
        wsRef.current.close()
      }
    }
  }, [agentId])

  const handleSend = async () => {
    if (!input.trim() || sending) return

    const message = input.trim()
    setInput('')
    setSending(true)

    // Add to local display
    setLines(prev => [...prev, {
      time: new Date().toLocaleTimeString(),
      type: 'command',
      text: `> ${message}`
    }])

    try {
      const res = await fetch(`/api/agent/${agentId}/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: message,
          from_agent: 'web'
        })
      })

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`)
      }

      setLines(prev => [...prev, {
        time: new Date().toLocaleTimeString(),
        type: 'system',
        text: `Sent to agent ${agentId}`
      }])
    } catch (err) {
      setLines(prev => [...prev, {
        time: new Date().toLocaleTimeString(),
        type: 'error',
        text: `Error: ${err.message}`
      }])
    } finally {
      setSending(false)
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleClear = () => {
    setLines([{
      time: new Date().toLocaleTimeString(),
      type: 'system',
      text: 'Cleared'
    }])
  }

  return (
    <div className="terminal">
      <div className="terminal-output" ref={outputRef}>
        {lines.map((line, i) => (
          <div key={i} className={`terminal-line ${line.type}`}>
            <span className="time">{line.time}</span>
            {line.from && <span className="from">[{line.from}]</span>}
            <span className="text">{line.text}</span>
          </div>
        ))}
      </div>
      <div className="terminal-input">
        <span className="prompt">$</span>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={`Send to agent ${agentId}...`}
          disabled={sending}
        />
        <button onClick={handleSend} disabled={sending || !input.trim()}>
          Send
        </button>
        <button onClick={handleClear}>Clear</button>
      </div>
    </div>
  )
}

export default Terminal
