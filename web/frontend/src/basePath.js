// Base path is root (app served at /)
const BASE = ''

export const api = (path) => `/${path}`
export const wsUrl = (path) => {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}${BASE}/${path}`
}

export default BASE
