import React, { useState, useEffect, useRef } from 'react'
import { api } from '../basePath'
import { useAuth } from '../AuthProvider'

function DevChat() {
  const { user } = useAuth()
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const bottomRef = useRef(null)

  useEffect(() => {
    const poll = async () => {
      try {
        const res = await fetch(api('api/chat'))
        const data = await res.json()
        setMessages(data.lines || [])
      } catch {}
    }
    poll()
    const id = setInterval(poll, 2000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const send = async () => {
    const text = input.trim()
    if (!text) return
    setInput('')
    try {
      await fetch(api('api/chat'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, user: user?.username || 'anon' })
      })
      const res = await fetch(api('api/chat'))
      const data = await res.json()
      setMessages(data.lines || [])
    } catch {}
  }

  return (
    <div className="devchat">
      <div className="devchat-messages">
        {messages.map((m, i) => <div key={i} className="devchat-line">{m}</div>)}
        <div ref={bottomRef} />
      </div>
      <div className="devchat-input">
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') send() }}
          placeholder="message..."
        />
      </div>
    </div>
  )
}

export default DevChat
