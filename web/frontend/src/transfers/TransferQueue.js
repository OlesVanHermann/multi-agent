// ============================================
//  TransferQueue — Pure JS singleton engine
//  Manages upload/download queues with
//  concurrency limits and execution strategies
// ============================================

const SETTINGS_KEY = 'transfer_settings'
const THROTTLE_MS = 250
const SPEED_WINDOW_MS = 3000
const LARGE_FILE_THRESHOLD = 500 * 1024 * 1024 // 500 MB

let _id = 0
function nextId() {
  return `xfer_${Date.now()}_${++_id}`
}

/**
 * @typedef {'upload'|'download'} TransferDirection
 * @typedef {'queued'|'active'|'completed'|'error'|'cancelled'} TransferStatus
 * @typedef {'simultaneous'|'round-robin'|'down-first'|'up-first'} ExecutionStrategy
 *
 * @typedef {Object} TransferSettings
 * @property {number} maxConcurrentUploads
 * @property {number} maxConcurrentDownloads
 * @property {ExecutionStrategy} strategy
 *
 * @typedef {Object} TransferItem
 * @property {string} id
 * @property {TransferDirection} direction
 * @property {string} fileName
 * @property {number} fileSize
 * @property {string} mimeType
 * @property {string} serviceId
 * @property {string} serviceLabel
 * @property {TransferStatus} status
 * @property {number} progress
 * @property {number} loaded
 * @property {number} speed
 * @property {string|null} error
 * @property {number} createdAt
 * @property {number|null} startedAt
 * @property {number|null} completedAt
 */

const DEFAULT_SETTINGS = {
  maxConcurrentUploads: 2,
  maxConcurrentDownloads: 2,
  strategy: 'simultaneous',
}

class TransferQueue {
  constructor() {
    /** @type {TransferItem[]} */
    this._uploads = []
    /** @type {TransferItem[]} */
    this._downloads = []
    /** @type {TransferSettings} */
    this._settings = this._loadSettings()
    /** @type {Set<Function>} */
    this._listeners = new Set()
    /** @type {Map<string, XMLHttpRequest|AbortController>} */
    this._abortables = new Map()
    /** @type {Map<string, Array<{time: number, loaded: number}>>} */
    this._speedSamples = new Map()
    /** @type {Map<string, Function>} */
    this._callbacks = new Map()

    this._notifyTimeout = null
    this._roundRobinNext = 'upload' // for round-robin strategy
  }

  // ---- Settings persistence ----

  _loadSettings() {
    try {
      const raw = localStorage.getItem(SETTINGS_KEY)
      if (raw) {
        const parsed = JSON.parse(raw)
        return { ...DEFAULT_SETTINGS, ...parsed }
      }
    } catch (e) { /* ignore */ }
    return { ...DEFAULT_SETTINGS }
  }

  _saveSettings() {
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(this._settings))
    } catch (e) { /* ignore */ }
  }

  // ---- Subscriber pattern ----

  subscribe(listener) {
    this._listeners.add(listener)
    return () => this._listeners.delete(listener)
  }

  _notify() {
    if (this._notifyTimeout) return
    this._notifyTimeout = setTimeout(() => {
      this._notifyTimeout = null
      const state = this.getState()
      this._listeners.forEach(fn => {
        try { fn(state) } catch (e) { console.error('[TransferQueue] listener error:', e) }
      })
    }, THROTTLE_MS)
  }

  _notifyImmediate() {
    if (this._notifyTimeout) {
      clearTimeout(this._notifyTimeout)
      this._notifyTimeout = null
    }
    const state = this.getState()
    this._listeners.forEach(fn => {
      try { fn(state) } catch (e) { console.error('[TransferQueue] listener error:', e) }
    })
  }

  // ---- State snapshot ----

  getState() {
    return {
      uploads: [...this._uploads],
      downloads: [...this._downloads],
      settings: { ...this._settings },
    }
  }

  // ---- Speed calculation (sliding window) ----

  _updateSpeed(id, loaded) {
    const now = Date.now()
    let samples = this._speedSamples.get(id)
    if (!samples) {
      samples = []
      this._speedSamples.set(id, samples)
    }
    samples.push({ time: now, loaded })

    // Remove old samples outside window
    const cutoff = now - SPEED_WINDOW_MS
    while (samples.length > 0 && samples[0].time < cutoff) {
      samples.shift()
    }

    if (samples.length < 2) return 0

    const oldest = samples[0]
    const newest = samples[samples.length - 1]
    const timeDiff = (newest.time - oldest.time) / 1000
    if (timeDiff <= 0) return 0

    return (newest.loaded - oldest.loaded) / timeDiff
  }

  // ---- Item helpers ----

  _getItem(id) {
    return this._uploads.find(u => u.id === id) || this._downloads.find(d => d.id === id)
  }

  _updateItem(id, updates) {
    this._uploads = this._uploads.map(u => u.id === id ? { ...u, ...updates } : u)
    this._downloads = this._downloads.map(d => d.id === id ? { ...d, ...updates } : d)
  }

  // ---- Enqueue upload ----

  /**
   * @param {Object} opts
   * @param {File} opts.file
   * @param {string} opts.url
   * @param {string} opts.serviceId
   * @param {string} opts.serviceLabel
   * @param {Object} [opts.formDataFields]
   * @param {Function} [opts.onComplete]
   * @param {Function} [opts.onError]
   * @returns {string} transfer id
   */
  enqueueUpload(opts) {
    const id = nextId()
    const item = {
      id,
      direction: 'upload',
      fileName: opts.file.name,
      fileSize: opts.file.size,
      mimeType: opts.file.type || 'application/octet-stream',
      serviceId: opts.serviceId,
      serviceLabel: opts.serviceLabel,
      status: 'queued',
      progress: 0,
      loaded: 0,
      speed: 0,
      error: null,
      createdAt: Date.now(),
      startedAt: null,
      completedAt: null,
    }
    this._uploads.push(item)

    // Store callbacks and file reference
    this._callbacks.set(id, {
      file: opts.file,
      url: opts.url,
      formDataFields: opts.formDataFields || {},
      onComplete: opts.onComplete || null,
      onError: opts.onError || null,
    })

    this._notifyImmediate()
    this._processQueue()
    return id
  }

  // ---- Enqueue download ----

  /**
   * @param {Object} opts
   * @param {string} opts.url
   * @param {string} opts.fileName
   * @param {number} [opts.fileSize]
   * @param {string} [opts.mimeType]
   * @param {string} opts.serviceId
   * @param {string} opts.serviceLabel
   * @param {Function} [opts.onComplete]
   * @param {Function} [opts.onError]
   * @returns {string} transfer id
   */
  enqueueDownload(opts) {
    const id = nextId()
    const item = {
      id,
      direction: 'download',
      fileName: opts.fileName,
      fileSize: opts.fileSize || 0,
      mimeType: opts.mimeType || 'application/octet-stream',
      serviceId: opts.serviceId,
      serviceLabel: opts.serviceLabel,
      status: 'queued',
      progress: 0,
      loaded: 0,
      speed: 0,
      error: null,
      createdAt: Date.now(),
      startedAt: null,
      completedAt: null,
    }
    this._downloads.push(item)

    this._callbacks.set(id, {
      url: opts.url,
      onComplete: opts.onComplete || null,
      onError: opts.onError || null,
    })

    this._notifyImmediate()
    this._processQueue()
    return id
  }

  // ---- Cancel ----

  cancel(id) {
    const item = this._getItem(id)
    if (!item) return

    if (item.status === 'active') {
      const abortable = this._abortables.get(id)
      if (abortable) {
        if (abortable instanceof XMLHttpRequest) {
          abortable.abort()
        } else if (abortable.abort) {
          abortable.abort()
        }
        this._abortables.delete(id)
      }
    }

    this._updateItem(id, { status: 'cancelled', completedAt: Date.now() })
    this._speedSamples.delete(id)
    this._callbacks.delete(id)
    this._notifyImmediate()
    this._processQueue()
  }

  // ---- Retry ----

  retry(id) {
    const item = this._getItem(id)
    if (!item || (item.status !== 'error' && item.status !== 'cancelled')) return

    this._updateItem(id, {
      status: 'queued',
      progress: 0,
      loaded: 0,
      speed: 0,
      error: null,
      startedAt: null,
      completedAt: null,
    })
    this._speedSamples.delete(id)
    this._notifyImmediate()
    this._processQueue()
  }

  // ---- Clear completed ----

  clearCompleted(direction) {
    const isDone = (item) =>
      item.status === 'completed' || item.status === 'error' || item.status === 'cancelled'

    if (!direction || direction === 'upload') {
      this._uploads = this._uploads.filter(u => !isDone(u))
    }
    if (!direction || direction === 'download') {
      this._downloads = this._downloads.filter(d => !isDone(d))
    }
    this._notifyImmediate()
  }

  // ---- Update settings ----

  updateSettings(partial) {
    this._settings = { ...this._settings, ...partial }
    // Clamp values
    this._settings.maxConcurrentUploads = Math.max(1, Math.min(5, this._settings.maxConcurrentUploads))
    this._settings.maxConcurrentDownloads = Math.max(1, Math.min(5, this._settings.maxConcurrentDownloads))
    this._saveSettings()
    this._notifyImmediate()
    this._processQueue()
  }

  // ---- Queue processing ----

  _processQueue() {
    const activeUploads = this._uploads.filter(u => u.status === 'active').length
    const activeDownloads = this._downloads.filter(d => d.status === 'active').length
    const queuedUploads = this._uploads.filter(u => u.status === 'queued')
    const queuedDownloads = this._downloads.filter(d => d.status === 'queued')

    const { maxConcurrentUploads, maxConcurrentDownloads, strategy } = this._settings

    switch (strategy) {
      case 'simultaneous':
        this._startUploads(queuedUploads, maxConcurrentUploads - activeUploads)
        this._startDownloads(queuedDownloads, maxConcurrentDownloads - activeDownloads)
        break

      case 'up-first':
        // Only start downloads if no uploads are queued/active
        this._startUploads(queuedUploads, maxConcurrentUploads - activeUploads)
        if (activeUploads === 0 && queuedUploads.length === 0) {
          this._startDownloads(queuedDownloads, maxConcurrentDownloads - activeDownloads)
        }
        break

      case 'down-first':
        // Only start uploads if no downloads are queued/active
        this._startDownloads(queuedDownloads, maxConcurrentDownloads - activeDownloads)
        if (activeDownloads === 0 && queuedDownloads.length === 0) {
          this._startUploads(queuedUploads, maxConcurrentUploads - activeUploads)
        }
        break

      case 'round-robin': {
        // Alternate between starting one upload and one download
        const canUp = maxConcurrentUploads - activeUploads
        const canDown = maxConcurrentDownloads - activeDownloads

        if (this._roundRobinNext === 'upload') {
          if (canUp > 0 && queuedUploads.length > 0) {
            this._startUploads(queuedUploads, 1)
          }
          if (canDown > 0 && queuedDownloads.length > 0) {
            this._startDownloads(queuedDownloads, 1)
          }
          this._roundRobinNext = 'download'
        } else {
          if (canDown > 0 && queuedDownloads.length > 0) {
            this._startDownloads(queuedDownloads, 1)
          }
          if (canUp > 0 && queuedUploads.length > 0) {
            this._startUploads(queuedUploads, 1)
          }
          this._roundRobinNext = 'upload'
        }
        break
      }
    }
  }

  _startUploads(queued, count) {
    for (let i = 0; i < Math.min(count, queued.length); i++) {
      this._executeUpload(queued[i].id)
    }
  }

  _startDownloads(queued, count) {
    for (let i = 0; i < Math.min(count, queued.length); i++) {
      this._executeDownload(queued[i].id)
    }
  }

  // ---- Execute upload (XHR for progress) ----

  _executeUpload(id) {
    const cb = this._callbacks.get(id)
    if (!cb) return

    this._updateItem(id, { status: 'active', startedAt: Date.now() })
    this._notify()

    const formData = new FormData()
    formData.append('file', cb.file)
    if (cb.formDataFields) {
      Object.entries(cb.formDataFields).forEach(([k, v]) => {
        formData.append(k, v)
      })
    }

    const xhr = new XMLHttpRequest()
    this._abortables.set(id, xhr)

    xhr.open('POST', cb.url)

    xhr.upload.addEventListener('progress', (e) => {
      if (e.lengthComputable) {
        const progress = Math.round((e.loaded / e.total) * 100)
        const speed = this._updateSpeed(id, e.loaded)
        this._updateItem(id, { progress, loaded: e.loaded, speed })
        this._notify()
      }
    })

    xhr.onload = () => {
      this._abortables.delete(id)
      this._speedSamples.delete(id)

      if (xhr.status >= 200 && xhr.status < 300) {
        this._updateItem(id, {
          status: 'completed',
          progress: 100,
          completedAt: Date.now(),
        })
        if (cb.onComplete) {
          try { cb.onComplete(xhr.responseText) } catch (e) { console.error('[TransferQueue] onComplete error:', e) }
        }
      } else {
        const errMsg = `HTTP ${xhr.status}: ${xhr.statusText}`
        this._updateItem(id, {
          status: 'error',
          error: errMsg,
          completedAt: Date.now(),
        })
        if (cb.onError) {
          try { cb.onError(errMsg) } catch (e) { /* ignore */ }
        }
      }
      this._notifyImmediate()
      this._processQueue()
    }

    xhr.onerror = () => {
      this._abortables.delete(id)
      this._speedSamples.delete(id)
      const errMsg = 'Network error during upload'
      this._updateItem(id, {
        status: 'error',
        error: errMsg,
        completedAt: Date.now(),
      })
      if (cb.onError) {
        try { cb.onError(errMsg) } catch (e) { /* ignore */ }
      }
      this._notifyImmediate()
      this._processQueue()
    }

    xhr.onabort = () => {
      this._abortables.delete(id)
      this._speedSamples.delete(id)
      // Status already set to 'cancelled' in cancel()
      this._notifyImmediate()
      this._processQueue()
    }

    xhr.send(formData)
  }

  // ---- Execute download (fetch + ReadableStream for progress) ----

  async _executeDownload(id) {
    const cb = this._callbacks.get(id)
    if (!cb) return

    const item = this._getItem(id)
    if (!item) return

    // For large files (>500MB), use simple <a> tag download (no progress tracking)
    if (item.fileSize > LARGE_FILE_THRESHOLD) {
      this._updateItem(id, { status: 'active', startedAt: Date.now() })
      this._notify()

      const a = document.createElement('a')
      a.href = cb.url
      a.download = item.fileName
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)

      this._updateItem(id, {
        status: 'completed',
        progress: 100,
        completedAt: Date.now(),
      })
      if (cb.onComplete) {
        try { cb.onComplete(null) } catch (e) { /* ignore */ }
      }
      this._notifyImmediate()
      this._processQueue()
      return
    }

    this._updateItem(id, { status: 'active', startedAt: Date.now() })
    this._notify()

    const controller = new AbortController()
    this._abortables.set(id, controller)

    try {
      const response = await fetch(cb.url, { signal: controller.signal })
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }

      const contentLength = response.headers.get('Content-Length')
      const totalSize = contentLength ? parseInt(contentLength, 10) : item.fileSize

      // Update fileSize if we got it from the response
      if (totalSize && totalSize !== item.fileSize) {
        this._updateItem(id, { fileSize: totalSize })
      }

      const reader = response.body.getReader()
      const chunks = []
      let receivedBytes = 0

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        chunks.push(value)
        receivedBytes += value.length

        const progress = totalSize > 0 ? Math.round((receivedBytes / totalSize) * 100) : 0
        const speed = this._updateSpeed(id, receivedBytes)
        this._updateItem(id, { progress, loaded: receivedBytes, speed })
        this._notify()
      }

      this._abortables.delete(id)
      this._speedSamples.delete(id)

      const blob = new Blob(chunks)
      const blobUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = blobUrl
      a.download = item.fileName
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)

      // Cleanup blob URL after a short delay
      setTimeout(() => URL.revokeObjectURL(blobUrl), 10000)

      this._updateItem(id, {
        status: 'completed',
        progress: 100,
        loaded: receivedBytes,
        completedAt: Date.now(),
      })

      if (cb.onComplete) {
        try { cb.onComplete(blob) } catch (e) { /* ignore */ }
      }
    } catch (err) {
      this._abortables.delete(id)
      this._speedSamples.delete(id)

      if (err.name === 'AbortError') {
        // Cancelled — status already set
        this._notifyImmediate()
        this._processQueue()
        return
      }

      const errMsg = err.message || 'Download failed'
      this._updateItem(id, {
        status: 'error',
        error: errMsg,
        completedAt: Date.now(),
      })
      if (cb.onError) {
        try { cb.onError(errMsg) } catch (e) { /* ignore */ }
      }
    }

    this._notifyImmediate()
    this._processQueue()
  }
}

// Singleton
let _instance = null
export function getTransferQueue() {
  if (!_instance) {
    _instance = new TransferQueue()
  }
  return _instance
}

export default TransferQueue
