// Detect base path from current URL (works behind any reverse proxy)
// At /inception/ → BASE = '/inception'
// At / → BASE = ''
const BASE = window.location.pathname.replace(/\/+$/, '')

export const api = (path) => `${BASE}/${path}`
export const wsUrl = (path) => {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}${BASE}/${path}`
}

export default BASE
