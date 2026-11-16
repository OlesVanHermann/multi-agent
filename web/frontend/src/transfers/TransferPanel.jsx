// ============================================
//  TransferPanel — Full 2-column transfers page
//  Settings bar + Uploads column + Downloads column
// ============================================

import React, { useMemo } from 'react'
import { useTransfers } from './TransferContext'

// ---- Helpers ----

function formatBytes(bytes) {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

function formatSpeed(bytesPerSec) {
  if (bytesPerSec <= 0) return ''
  return formatBytes(bytesPerSec) + '/s'
}

const SERVICE_COLORS = {
  drive: '#ff9500',
  greffier: '#ff4444',
  email: '#44cc88',
}

function serviceColor(serviceId) {
  return SERVICE_COLORS[serviceId] || '#4a9eff'
}

const STRATEGY_LABELS = {
  simultaneous: 'Simultaneous',
  'round-robin': 'Round Robin',
  'down-first': 'Downloads First',
  'up-first': 'Uploads First',
}

// ---- Settings Bar ----

function SettingsBar({ settings, updateSettings, clearCompleted }) {
  const maxOptions = [1, 2, 3, 4, 5]

  return (
    <div style={{
      padding: '0.75rem 1rem',
      background: 'var(--bg-secondary)',
      borderBottom: '1px solid var(--border-color)',
      display: 'flex',
      flexWrap: 'wrap',
      alignItems: 'center',
      gap: '1rem',
      fontSize: '0.75rem',
    }}>
      {/* Max UP */}
      <span style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
        <span style={{ color: 'var(--text-secondary)', fontSize: '0.65rem', textTransform: 'uppercase' }}>
          Max UP
        </span>
        {maxOptions.map(n => (
          <button
            key={n}
            onClick={() => updateSettings({ maxConcurrentUploads: n })}
            style={{
              width: '22px',
              height: '22px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '0.65rem',
              borderRadius: '3px',
              cursor: 'pointer',
              border: settings.maxConcurrentUploads === n
                ? '1px solid #44cc88'
                : '1px solid var(--border-color)',
              background: settings.maxConcurrentUploads === n
                ? 'rgba(68, 204, 136, 0.15)'
                : 'var(--bg-panel)',
              color: settings.maxConcurrentUploads === n
                ? '#44cc88'
                : 'var(--text-secondary)',
              fontFamily: 'inherit',
            }}
          >
            {n}
          </button>
        ))}
      </span>

      {/* Max DOWN */}
      <span style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
        <span style={{ color: 'var(--text-secondary)', fontSize: '0.65rem', textTransform: 'uppercase' }}>
          Max DN
        </span>
        {maxOptions.map(n => (
          <button
            key={n}
            onClick={() => updateSettings({ maxConcurrentDownloads: n })}
            style={{
              width: '22px',
              height: '22px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '0.65rem',
              borderRadius: '3px',
              cursor: 'pointer',
              border: settings.maxConcurrentDownloads === n
                ? '1px solid #4a9eff'
                : '1px solid var(--border-color)',
              background: settings.maxConcurrentDownloads === n
                ? 'rgba(74, 158, 255, 0.12)'
                : 'var(--bg-panel)',
              color: settings.maxConcurrentDownloads === n
                ? '#4a9eff'
                : 'var(--text-secondary)',
              fontFamily: 'inherit',
            }}
          >
            {n}
          </button>
        ))}
      </span>

      {/* Strategy */}
      <span style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
        <span style={{ color: 'var(--text-secondary)', fontSize: '0.65rem', textTransform: 'uppercase' }}>
          Strategy
        </span>
        <select
          value={settings.strategy}
          onChange={e => updateSettings({ strategy: e.target.value })}
          className="poll-select"
          style={{ minWidth: '8rem' }}
        >
          {Object.entries(STRATEGY_LABELS).map(([k, v]) => (
            <option key={k} value={k}>{v}</option>
          ))}
        </select>
      </span>

      <span style={{ flex: 1 }} />

      {/* Clear completed */}
      <button
        onClick={() => clearCompleted()}
        style={{
          padding: '0.25rem 0.75rem',
          background: 'transparent',
          border: '1px solid var(--border-color)',
          color: 'var(--text-secondary)',
          cursor: 'pointer',
          fontFamily: 'inherit',
          fontSize: '0.7rem',
          borderRadius: '3px',
        }}
        onMouseEnter={e => {
          e.target.style.color = 'var(--text-primary)'
          e.target.style.borderColor = 'var(--blue)'
        }}
        onMouseLeave={e => {
          e.target.style.color = 'var(--text-secondary)'
          e.target.style.borderColor = 'var(--border-color)'
        }}
      >
        Clear completed
      </button>
    </div>
  )
}

// ---- Transfer Item Row ----

function TransferItemRow({ item, onCancel, onRetry }) {
  const isActive = item.status === 'active'
  const isQueued = item.status === 'queued'
  const isError = item.status === 'error'
  const isDone = item.status === 'completed'
  const isCancelled = item.status === 'cancelled'
  const color = item.direction === 'upload' ? '#44cc88' : '#4a9eff'

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      gap: '0.25rem',
      padding: '0.5rem 0.75rem',
      borderBottom: '1px solid rgba(51, 51, 51, 0.5)',
    }}>
      {/* Top row: service badge, filename, size, actions */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        {/* Service badge */}
        <span style={{
          fontSize: '0.55rem',
          padding: '0.1rem 0.35rem',
          borderRadius: '2px',
          background: `${serviceColor(item.serviceId)}22`,
          color: serviceColor(item.serviceId),
          border: `1px solid ${serviceColor(item.serviceId)}44`,
          flexShrink: 0,
        }}>
          {item.serviceLabel}
        </span>

        {/* Filename */}
        <span style={{
          fontSize: '0.75rem',
          color: 'var(--text-primary)',
          flex: 1,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}>
          {item.fileName}
        </span>

        {/* Size */}
        <span style={{
          fontSize: '0.65rem',
          color: 'var(--text-secondary)',
          fontFamily: 'inherit',
          flexShrink: 0,
        }}>
          {formatBytes(item.fileSize)}
        </span>

        {/* Speed */}
        {isActive && item.speed > 0 && (
          <span style={{
            fontSize: '0.6rem',
            color: color,
            fontFamily: 'inherit',
            flexShrink: 0,
          }}>
            {formatSpeed(item.speed)}
          </span>
        )}

        {/* Status icon */}
        {isDone && (
          <span style={{ color: '#44cc88', fontSize: '0.75rem', flexShrink: 0 }} title="Completed">
            &#10003;
          </span>
        )}
        {isError && (
          <span style={{ color: 'var(--red)', fontSize: '0.65rem', flexShrink: 0 }} title={item.error}>
            &#10007;
          </span>
        )}
        {isCancelled && (
          <span style={{ color: 'var(--text-secondary)', fontSize: '0.65rem', flexShrink: 0 }}>
            cancelled
          </span>
        )}

        {/* Actions */}
        {(isActive || isQueued) && (
          <button
            onClick={() => onCancel(item.id)}
            style={{
              background: 'transparent',
              border: '1px solid var(--border-color)',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              fontFamily: 'inherit',
              fontSize: '0.6rem',
              padding: '0.1rem 0.4rem',
              borderRadius: '3px',
              flexShrink: 0,
            }}
            onMouseEnter={e => {
              e.target.style.color = 'var(--red)'
              e.target.style.borderColor = 'var(--red)'
            }}
            onMouseLeave={e => {
              e.target.style.color = 'var(--text-secondary)'
              e.target.style.borderColor = 'var(--border-color)'
            }}
            title="Cancel transfer"
          >
            Cancel
          </button>
        )}
        {(isError || isCancelled) && (
          <button
            onClick={() => onRetry(item.id)}
            style={{
              background: 'transparent',
              border: '1px solid var(--border-color)',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              fontFamily: 'inherit',
              fontSize: '0.6rem',
              padding: '0.1rem 0.4rem',
              borderRadius: '3px',
              flexShrink: 0,
            }}
            onMouseEnter={e => {
              e.target.style.color = 'var(--blue)'
              e.target.style.borderColor = 'var(--blue)'
            }}
            onMouseLeave={e => {
              e.target.style.color = 'var(--text-secondary)'
              e.target.style.borderColor = 'var(--border-color)'
            }}
            title="Retry transfer"
          >
            Retry
          </button>
        )}
      </div>

      {/* Progress bar (active only) */}
      {isActive && (
        <div style={{
          width: '100%',
          height: '3px',
          background: 'rgba(51, 51, 51, 0.8)',
          borderRadius: '2px',
          overflow: 'hidden',
        }}>
          <div style={{
            height: '100%',
            width: `${item.progress}%`,
            background: color,
            borderRadius: '2px',
            transition: 'width 0.3s',
          }} />
        </div>
      )}

      {/* Error message */}
      {isError && item.error && (
        <div style={{
          fontSize: '0.6rem',
          color: 'var(--red)',
          fontFamily: 'inherit',
        }}>
          {item.error}
        </div>
      )}
    </div>
  )
}

// ---- Transfer Column ----

function TransferColumn({ title, color, items, cancel, retry }) {
  const sorted = useMemo(() => {
    const active = items.filter(i => i.status === 'active')
    const queued = items.filter(i => i.status === 'queued')
    const done = items
      .filter(i => i.status === 'completed' || i.status === 'error' || i.status === 'cancelled')
      .sort((a, b) => (b.completedAt || 0) - (a.completedAt || 0))
    return { active, queued, done }
  }, [items])

  const activeCount = sorted.active.length
  const queuedCount = sorted.queued.length
  const doneCount = sorted.done.length

  return (
    <div style={{
      flex: 1,
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
      minWidth: 0,
    }}>
      {/* Column header */}
      <div style={{
        padding: '0.5rem 0.75rem',
        background: 'var(--bg-secondary)',
        borderBottom: '1px solid var(--border-color)',
        fontSize: '0.8rem',
        fontWeight: 500,
        color: color,
        display: 'flex',
        alignItems: 'center',
        gap: '0.5rem',
      }}>
        <span>{title}</span>
        {(activeCount + queuedCount) > 0 && (
          <span style={{
            fontSize: '0.6rem',
            color: 'var(--text-secondary)',
            fontFamily: 'inherit',
          }}>
            {activeCount} active, {queuedCount} queued
          </span>
        )}
      </div>

      {/* Items list */}
      <div style={{
        flex: 1,
        overflowY: 'auto',
        overflowX: 'hidden',
      }}>
        {items.length === 0 ? (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            height: '100%',
            minHeight: '120px',
            color: 'var(--text-secondary)',
            fontSize: '0.75rem',
            fontStyle: 'italic',
          }}>
            No {title.toLowerCase()}
          </div>
        ) : (
          <>
            {/* Active section */}
            {sorted.active.length > 0 && (
              <>
                <div style={{
                  fontSize: '0.6rem',
                  textTransform: 'uppercase',
                  color: color,
                  padding: '0.5rem 0.75rem 0.25rem',
                  letterSpacing: '0.05em',
                }}>
                  In progress
                </div>
                {sorted.active.map(item => (
                  <TransferItemRow key={item.id} item={item} onCancel={cancel} onRetry={retry} />
                ))}
              </>
            )}

            {/* Queued section */}
            {sorted.queued.length > 0 && (
              <>
                <div style={{
                  fontSize: '0.6rem',
                  textTransform: 'uppercase',
                  color: 'var(--text-secondary)',
                  padding: '0.5rem 0.75rem 0.25rem',
                  letterSpacing: '0.05em',
                }}>
                  Queued ({sorted.queued.length})
                </div>
                {sorted.queued.map(item => (
                  <TransferItemRow key={item.id} item={item} onCancel={cancel} onRetry={retry} />
                ))}
              </>
            )}

            {/* Completed section */}
            {sorted.done.length > 0 && (
              <>
                <div style={{
                  fontSize: '0.6rem',
                  textTransform: 'uppercase',
                  color: 'var(--text-secondary)',
                  padding: '0.5rem 0.75rem 0.25rem',
                  letterSpacing: '0.05em',
                  opacity: 0.7,
                }}>
                  Completed ({sorted.done.length})
                </div>
                {sorted.done.map(item => (
                  <TransferItemRow key={item.id} item={item} onCancel={cancel} onRetry={retry} />
                ))}
              </>
            )}
          </>
        )}
      </div>
    </div>
  )
}

// ---- Main Panel ----

export default function TransferPanel() {
  const { uploads, downloads, settings, cancel, retry, clearCompleted, updateSettings } = useTransfers()

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      background: 'var(--bg-panel)',
    }}>
      {/* Settings */}
      <SettingsBar
        settings={settings}
        updateSettings={updateSettings}
        clearCompleted={clearCompleted}
      />

      {/* Two columns */}
      <div style={{
        flex: 1,
        display: 'flex',
        overflow: 'hidden',
      }}>
        <TransferColumn
          title="Uploads"
          color="#44cc88"
          items={uploads}
          cancel={cancel}
          retry={retry}
        />
        <div style={{
          width: '1px',
          background: 'var(--border-color)',
          flexShrink: 0,
        }} />
        <TransferColumn
          title="Downloads"
          color="#4a9eff"
          items={downloads}
          cancel={cancel}
          retry={retry}
        />
      </div>

      {/* Status bar */}
      <div style={{
        padding: '0.35rem 1rem',
        background: 'var(--bg-secondary)',
        borderTop: '1px solid var(--border-color)',
        fontSize: '0.7rem',
        color: 'var(--text-secondary)',
        display: 'flex',
        gap: '1.5rem',
      }}>
        <span>
          {uploads.filter(u => u.status === 'active' || u.status === 'queued').length} uploads pending
        </span>
        <span>
          {downloads.filter(d => d.status === 'active' || d.status === 'queued').length} downloads pending
        </span>
        <span style={{ flex: 1 }} />
        <span>
          Strategy: {STRATEGY_LABELS[settings.strategy]}
        </span>
      </div>
    </div>
  )
}
