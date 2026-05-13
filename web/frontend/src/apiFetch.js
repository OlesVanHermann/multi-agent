// Authenticated fetch wrapper — injects JWT Bearer token from localStorage
// All API calls should use apiFetch() instead of fetch()

import { api } from './basePath'

export function apiFetch(path, options = {}) {
  const token = localStorage.getItem('access_token')
  const headers = { ...(options.headers || {}) }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  return fetch(api(path), { ...options, headers })
}

export function apiWsUrl(path) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const token = localStorage.getItem('access_token')
  const sep = path.includes('?') ? '&' : '?'
  const tokenParam = token ? `${sep}token=${encodeURIComponent(token)}` : ''
  return `${protocol}//${window.location.host}/${path}${tokenParam}`
}
