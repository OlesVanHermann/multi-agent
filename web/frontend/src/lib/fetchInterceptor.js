import { getCsrfToken } from '../apiFetch'

// Save raw fetch BEFORE the CSRF interceptor so the logger can flush without
// going through the interceptor (avoids wrapper on /api/logs/frontend).
window.__maRawFetch = window.fetch

// Intercept all fetch() calls to inject the anti-CSRF header automatically.
// L'auth est portée par le cookie HttpOnly (B3) envoyé par le navigateur ;
// le double-submit ma_csrf protège les requêtes mutatives.
const _originalFetch = window.fetch
window.fetch = function(url, options = {}) {
  if (typeof url === 'string' && (url.startsWith('/api/') || url.includes('/api/'))) {
    const csrf = getCsrfToken()
    const headers = new Headers(options.headers || {})
    if (csrf && !headers.has('X-CSRF-Token')) {
      headers.set('X-CSRF-Token', csrf)
    }
    options = { credentials: 'same-origin', ...options, headers }
  }
  return _originalFetch.call(this, url, options)
}
