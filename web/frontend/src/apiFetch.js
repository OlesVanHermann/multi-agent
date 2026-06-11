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

export function apiWsUrl(path) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  // B3 : plus de ?token= — le cookie HttpOnly accompagne le handshake WS
  return `${protocol}//${window.location.host}/${path}`
}
