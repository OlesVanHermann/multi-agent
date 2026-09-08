// ============================================
//  TransferTopBarWidget — Compact UP/DOWN badges
//  Shown in header-right area when transfers active
// ============================================

import React from 'react'
import { useTransfers } from './TransferContext'

function formatBytes(bytes) {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

export default function TransferTopBarWidget({ onOpenTransfers }) {
  const { uploads, downloads } = useTransfers()

  const activeUploads = uploads.filter(u => u.status === 'active')
  const queuedUploads = uploads.filter(u => u.status === 'queued')
  const activeDownloads = downloads.filter(d => d.status === 'active')
  const queuedDownloads = downloads.filter(d => d.status === 'queued')

  const hasUp = activeUploads.length > 0 || queuedUploads.length > 0
  const hasDown = activeDownloads.length > 0 || queuedDownloads.length > 0

  if (!hasUp && !hasDown) return null

  const upItem = activeUploads[0]
  const downItem = activeDownloads[0]

  return (
    <span
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '0.5rem',
        cursor: 'pointer',
      }}
      onClick={onOpenTransfers}
      title="Open Transfers panel"
    >
      {hasUp && (
        <span style={{
          display: 'flex',
          alignItems: 'center',
          gap: '0.35rem',
          padding: '0.15rem 0.5rem',
          background: 'rgba(26, 138, 74, 0.15)',
          border: '1px solid rgba(26, 138, 74, 0.35)',
          borderRadius: '3px',
          fontSize: '0.65rem',
          color: '#44cc88',
        }}>
          <span>UP</span>
          {upItem ? (
            <>
              <span style={{
                width: '40px',
                height: '4px',
                background: 'rgba(26, 138, 74, 0.3)',
                borderRadius: '2px',
                overflow: 'hidden',
                display: 'inline-block',
              }}>
                <span style={{
                  display: 'block',
                  height: '100%',
                  width: `${upItem.progress}%`,
                  background: '#44cc88',
                  borderRadius: '2px',
                  transition: 'width 0.3s',
                }} />
              </span>
              <span style={{ fontFamily: 'inherit', minWidth: '2rem', textAlign: 'right' }}>
                {upItem.progress}%
              </span>
            </>
          ) : (
            <span style={{ color: 'rgba(68, 204, 136, 0.7)' }}>
              {queuedUploads.length} queued
            </span>
          )}
          {(activeUploads.length + queuedUploads.length) > 1 && (
            <span style={{ color: 'rgba(68, 204, 136, 0.5)', fontSize: '0.55rem' }}>
              +{activeUploads.length + queuedUploads.length - 1}
            </span>
          )}
        </span>
      )}

      {hasDown && (
        <span style={{
          display: 'flex',
          alignItems: 'center',
          gap: '0.35rem',
          padding: '0.15rem 0.5rem',
          background: 'rgba(74, 158, 255, 0.12)',
          border: '1px solid rgba(74, 158, 255, 0.3)',
          borderRadius: '3px',
          fontSize: '0.65rem',
          color: '#4a9eff',
        }}>
          <span>DN</span>
          {downItem ? (
            <>
              <span style={{
                width: '40px',
                height: '4px',
                background: 'rgba(74, 158, 255, 0.2)',
                borderRadius: '2px',
                overflow: 'hidden',
                display: 'inline-block',
              }}>
                <span style={{
                  display: 'block',
                  height: '100%',
                  width: `${downItem.progress}%`,
                  background: '#4a9eff',
                  borderRadius: '2px',
                  transition: 'width 0.3s',
                }} />
              </span>
              <span style={{ fontFamily: 'inherit', minWidth: '2rem', textAlign: 'right' }}>
                {downItem.progress}%
              </span>
            </>
          ) : (
            <span style={{ color: 'rgba(74, 158, 255, 0.7)' }}>
              {queuedDownloads.length} queued
            </span>
          )}
          {(activeDownloads.length + queuedDownloads.length) > 1 && (
            <span style={{ color: 'rgba(74, 158, 255, 0.5)', fontSize: '0.55rem' }}>
              +{activeDownloads.length + queuedDownloads.length - 1}
            </span>
          )}
        </span>
      )}
    </span>
  )
}
