// Base path is root (app served at /)
const BASE = ''

export const api = (path) => `/${path}`
export const wsUrl = (path) => {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const token = localStorage.getItem('access_token')
  const sep = path.includes('?') ? '&' : '?'
  const tokenParam = token ? `${sep}token=${token}` : ''
  return `${protocol}//${window.location.host}${BASE}/${path}${tokenParam}`
}

export default BASE
