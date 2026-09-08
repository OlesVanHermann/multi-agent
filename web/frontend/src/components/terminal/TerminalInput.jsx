import React from 'react'

// Ligne de saisie co-éditée avec tmux + boutons de touches brutes.
function TerminalInput({ inputRef, input, onInputChange, onKeyDown, onSubmit, sendKeys, sending }) {
  return (
    <div className="terminal-input">
      <span className="prompt">❯</span>
      <textarea
        ref={inputRef}
        rows={1}
        value={input}
        onChange={(e) => {
          onInputChange(e)
          // Auto-resize: reset then grow to fit content
          e.target.style.height = 'auto'
          e.target.style.height = e.target.scrollHeight + 'px'
        }}
        onKeyDown={onKeyDown}
        placeholder={`Co-edit with tmux...`}
        disabled={sending}
      />
      <span className="key-group">
        <button onClick={onSubmit} disabled={sending} title="Send (Enter)">⏎</button>
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
  )
}

export default TerminalInput
