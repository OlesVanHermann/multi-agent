// Réglages terminal partagés par TOUTES les instances de <Terminal>.
// Le composant est monté à quatre endroits (App ×2, KeepAliveSplit,
// CrontabSplit) : le réglage ne peut donc pas être une prop d'une instance.
// Module-level store + abonnement, lu à l'appel dans les handlers pour qu'ils
// ne capturent jamais une valeur périmée.

import { api } from '../basePath'

// Doit rester aligné sur TMUX_AUTOSCROLL_DEFAULT (routers/config.py).
let autoScroll = true

const listeners = new Set()

/** Valeur courante. À lire DANS le handler, pas à capturer en closure. */
export function getAutoScroll() {
  return autoScroll
}

/** Met à jour localement et notifie les abonnés. Ne fait aucun appel réseau. */
export function setAutoScroll(value) {
  const next = value !== false
  if (next === autoScroll) return
  autoScroll = next
  listeners.forEach(fn => {
    try { fn(next) } catch { /* un abonné cassé n'empêche pas les autres */ }
  })
}

/** Abonnement ; renvoie la fonction de désabonnement. */
export function subscribeAutoScroll(fn) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

/** Charge la valeur persistée côté serveur. Silencieux en cas d'échec. */
export function loadTerminalPrefs() {
  return fetch(api('api/config/tmux-size'))
    .then(r => (r.ok ? r.json() : null))
    .then(d => { if (d && typeof d.autoscroll === 'boolean') setAutoScroll(d.autoscroll) })
    .catch(() => {})
}
