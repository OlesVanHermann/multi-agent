// Authenticated fetch wrapper — l'auth est portée par le cookie HttpOnly
// ma_access posé par le backend (B3) ; le JS ne voit plus le JWT.
// Les requêtes mutatives portent le header anti-CSRF (double-submit ma_csrf).
// All API calls should use apiFetch() instead of fetch()

import { api } from './basePath'

export function getCsrfToken() {
  const m = document.cookie.match(/(?:^|;\s*)ma_csrf=([^;]*)/)
  return m ? decodeURIComponent(m[1]) : ''
}

export function apiFetch(path, options = {}) {
  const headers = { ...(options.headers || {}) }
  const csrf = getCsrfToken()
  if (csrf && !headers['X-CSRF-Token']) {
    headers['X-CSRF-Token'] = csrf
  }
  return fetch(api(path), { credentials: 'same-origin', ...options, headers })
}

// B4 : ticket WS à usage unique (TTL 30 s) — le JWT ne passe jamais en URL.
export async function getWsTicket() {
  try {
    const r = await apiFetch('api/ws-ticket', { method: 'POST' })
    if (!r.ok) return null
    const data = await r.json()
    return data.ticket || null
  } catch {
    return null
  }
}
