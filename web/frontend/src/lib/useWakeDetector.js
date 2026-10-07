import { useEffect, useRef } from 'react'

const TICK_MS = 1000
const DRIFT_THRESHOLD_MS = 5000
const HIDDEN_THRESHOLD_MS = 60000

export function useWakeDetector(onWake) {
  const handlerRef = useRef(onWake)
  useEffect(() => { handlerRef.current = onWake }, [onWake])

  useEffect(() => {
    let lastTick = Date.now()
    let hiddenSince = document.hidden ? Date.now() : null

    const fire = (reason, detail) => {
      try { handlerRef.current?.({ reason, ...detail }) } catch {}
    }

    const interval = setInterval(() => {
      const now = Date.now()
      const drift = now - lastTick - TICK_MS
      lastTick = now
      // Ignore drift on hidden tabs: Chrome throttles setInterval to 30-60s in background,
      // which looks like a wake event but isn't. Real OS wakes are caught by visibilitychange.
      if (drift > DRIFT_THRESHOLD_MS && !document.hidden) fire('drift', { driftMs: drift })
    }, TICK_MS)

    const onVisibility = () => {
      if (document.hidden) {
        hiddenSince = Date.now()
      } else if (hiddenSince) {
        const hiddenMs = Date.now() - hiddenSince
        hiddenSince = null
        if (hiddenMs > HIDDEN_THRESHOLD_MS) fire('visibility', { hiddenMs })
      }
    }

    const onOnline = () => fire('online', {})

    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('online', onOnline)

    return () => {
      clearInterval(interval)
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('online', onOnline)
    }
  }, [])
}
