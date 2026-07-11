import React, { useState, useEffect } from 'react'
import { api } from '../basePath'

function FileViewer({ filePath }) {
  const [content, setContent] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!filePath) return
    setContent(null)
    setError(null)
    const reverse = filePath.endsWith('LOGS.md') ? '&reverse=true' : ''
    fetch(api(`api/file?path=${encodeURIComponent(filePath)}${reverse}`))
      .then(r => r.json())
      .then(d => {
        if (d.error) setError(d.error)
        else setContent(d.content)
      })
      .catch(e => setError(e.message))
  }, [filePath])

  if (!filePath) return <div className="no-selection">Select a file</div>
  if (error) return <div className="terminal-output" style={{ color: 'var(--red)' }}>Error: {error}</div>
  if (content === null) return <div className="terminal-output" style={{ color: 'var(--text-secondary)' }}>Loading...</div>

  return (
    <div className="terminal">
      <div className="terminal-header">
        <span>{filePath}</span>
      </div>
      <div className="terminal-output">{content}</div>
    </div>
  )
}

export default FileViewer
