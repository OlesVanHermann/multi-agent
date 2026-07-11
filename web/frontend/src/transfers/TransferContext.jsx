// ============================================
//  TransferContext — React Context + Provider
//  Wraps TransferQueue singleton, exposes
//  state + methods via useTransfers() hook
// ============================================

import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react'
import { getTransferQueue } from './TransferQueue'

const TransferContext = createContext(null)

const EMPTY_STATE = {
  uploads: [],
  downloads: [],
  settings: { maxConcurrentUploads: 2, maxConcurrentDownloads: 2, strategy: 'simultaneous' },
}

export function TransferProvider({ children }) {
  const queueRef = useRef(getTransferQueue())
  const [state, setState] = useState(() => queueRef.current.getState())

  useEffect(() => {
    const queue = queueRef.current
    const unsubscribe = queue.subscribe((newState) => {
      setState(newState)
    })
    return unsubscribe
  }, [])

  const enqueueUpload = useCallback((opts) => {
    return queueRef.current.enqueueUpload(opts)
  }, [])

  const enqueueDownload = useCallback((opts) => {
    return queueRef.current.enqueueDownload(opts)
  }, [])

  const cancel = useCallback((id) => {
    queueRef.current.cancel(id)
  }, [])

  const retry = useCallback((id) => {
    queueRef.current.retry(id)
  }, [])

  const clearCompleted = useCallback((direction) => {
    queueRef.current.clearCompleted(direction)
  }, [])

  const updateSettings = useCallback((partial) => {
    queueRef.current.updateSettings(partial)
  }, [])

  const value = {
    uploads: state.uploads,
    downloads: state.downloads,
    settings: state.settings,
    enqueueUpload,
    enqueueDownload,
    cancel,
    retry,
    clearCompleted,
    updateSettings,
  }

  return (
    <TransferContext.Provider value={value}>
      {children}
    </TransferContext.Provider>
  )
}

export function useTransfers() {
  const context = useContext(TransferContext)
  if (!context) {
    throw new Error('useTransfers must be used within a TransferProvider')
  }
  return context
}

export default TransferProvider
