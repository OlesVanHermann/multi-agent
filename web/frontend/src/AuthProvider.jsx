import React, { createContext, useContext, useState, useEffect, useRef, useCallback } from 'react'
import { createLogger } from './lib/logger'

const log = createLogger('Auth')
const AuthContext = createContext(null)

// Keycloak configuration
const KEYCLOAK_URL = '/auth'
const REALM = 'multi-agent'
const CLIENT_ID = 'multi-agent-web'

// Refresh token 60s before expiration
const REFRESH_MARGIN_S = 60

function decodeJwtPayload(token) {
  try {
    return JSON.parse(atob(token.split('.')[1]))
  } catch {
    return null
  }
}

function isTokenExpired(token) {
  const payload = decodeJwtPayload(token)
  if (!payload || !payload.exp) return true
  return Date.now() / 1000 >= payload.exp
}

function tokenExpiresInSec(token) {
  const payload = decodeJwtPayload(token)
  if (!payload || !payload.exp) return 0
  return Math.max(0, payload.exp - Date.now() / 1000)
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [token, setToken] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const refreshTimerRef = useRef(null)
  const inflightRefreshRef = useRef(null)

  const clearSession = useCallback(() => {
    log.action('logout')
    setToken(null)
    setUser(null)
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    localStorage.removeItem('user')
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current)
      refreshTimerRef.current = null
    }
  }, [])

  const applyTokens = useCallback((accessToken, refreshToken) => {
    const payload = decodeJwtPayload(accessToken)
    if (!payload) return false

    const userInfo = {
      username: payload.preferred_username,
      email: payload.email,
      name: payload.name,
      roles: payload.roles || payload.realm_access?.roles || [],
    }

    setToken(accessToken)
    setUser(userInfo)
    localStorage.setItem('access_token', accessToken)
    if (refreshToken) localStorage.setItem('refresh_token', refreshToken)
    localStorage.setItem('user', JSON.stringify(userInfo))

    // Schedule auto-refresh
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current)
    const expiresIn = tokenExpiresInSec(accessToken)
    const refreshIn = Math.max(10, (expiresIn - REFRESH_MARGIN_S)) * 1000
    refreshTimerRef.current = setTimeout(() => refreshAccessToken(), refreshIn)

    return true
  }, [])

  const refreshAccessToken = useCallback(async () => {
    if (inflightRefreshRef.current) return inflightRefreshRef.current
    const storedRefresh = localStorage.getItem('refresh_token')
    if (!storedRefresh) {
      clearSession()
      return false
    }

    const promise = (async () => {
      try {
        const response = await fetch(
          `${KEYCLOAK_URL}/realms/${REALM}/protocol/openid-connect/token`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({
              grant_type: 'refresh_token',
              client_id: CLIENT_ID,
              refresh_token: storedRefresh,
            }),
          }
        )

        if (response.status === 503) {
          log.warn('keycloak unreachable, retry in 30s')
          refreshTimerRef.current = setTimeout(() => refreshAccessToken(), 30000)
          return false
        }

        if (!response.ok) {
          log.warn('refresh token expired, forcing re-login')
          clearSession()
          return false
        }

        const data = await response.json()
        log.info('token refreshed')
        return applyTokens(data.access_token, data.refresh_token)
      } catch {
        log.error('token refresh network error')
        refreshTimerRef.current = setTimeout(() => refreshAccessToken(), 30000)
        return false
      } finally {
        inflightRefreshRef.current = null
      }
    })()

    inflightRefreshRef.current = promise
    return promise
  }, [clearSession, applyTokens])

  // Awaitable: resolves with a fresh access token (or null if refresh failed).
  // Used by WS code that must avoid the expired-token race at wake time.
  const ensureFreshToken = useCallback(async () => {
    const stored = localStorage.getItem('access_token')
    if (stored && !isTokenExpired(stored) && tokenExpiresInSec(stored) > REFRESH_MARGIN_S) {
      return stored
    }
    const ok = await refreshAccessToken()
    return ok ? localStorage.getItem('access_token') : null
  }, [refreshAccessToken])

  // Check for existing session on mount
  useEffect(() => {
    const storedToken = localStorage.getItem('access_token')

    if (storedToken) {
      if (isTokenExpired(storedToken)) {
        // Token expired — try refresh
        refreshAccessToken().finally(() => setLoading(false))
        return
      }
      applyTokens(storedToken, localStorage.getItem('refresh_token'))
    }
    setLoading(false)
  }, [])

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current)
    }
  }, [])

  // Refresh token when tab becomes visible / network returns / window focused
  // (protects against macOS sleep breaking the scheduled setTimeout)
  useEffect(() => {
    const handleWake = () => {
      const stored = localStorage.getItem('access_token')
      if (!stored) return
      if (isTokenExpired(stored) || tokenExpiresInSec(stored) < 30) {
        refreshAccessToken()
      }
    }

    const handleVisibility = () => {
      if (!document.hidden) handleWake()
    }

    document.addEventListener('visibilitychange', handleVisibility)
    window.addEventListener('online', handleWake)
    window.addEventListener('focus', handleWake)

    return () => {
      document.removeEventListener('visibilitychange', handleVisibility)
      window.removeEventListener('online', handleWake)
      window.removeEventListener('focus', handleWake)
    }
  }, [refreshAccessToken])

  const login = async (username, password) => {
    setError(null)
    setLoading(true)

    try {
      const response = await fetch(
        `${KEYCLOAK_URL}/realms/${REALM}/protocol/openid-connect/token`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
          body: new URLSearchParams({
            grant_type: 'password',
            client_id: CLIENT_ID,
            username,
            password,
          }),
        }
      )

      log.api('POST', '/auth/.../token', { grant: 'password', status: response.status })

      if (response.status === 503) {
        throw new Error('Keycloak is not reachable. Start Keycloak first.')
      }

      if (!response.ok) {
        const data = await response.json()
        throw new Error(data.error_description || 'Login failed')
      }

      const data = await response.json()
      log.action('login', { username })
      applyTokens(data.access_token, data.refresh_token)

      // Redirect to root after login
      if (window.location.pathname !== '/') {
        window.history.replaceState(null, '', '/')
      }

      return true
    } catch (err) {
      log.error('login failed', { username, error: err.message })
      setError(err.message)
      return false
    } finally {
      setLoading(false)
    }
  }

  const logout = () => clearSession()

  const hasRole = (role) => {
    return user?.roles?.includes(role) || false
  }

  const isAdmin = () => hasRole('admin')
  const isOperator = () => hasRole('operator') || isAdmin()
  const isViewer = () => hasRole('viewer') || isOperator()

  const value = {
    user,
    token,
    loading,
    error,
    login,
    logout,
    hasRole,
    isAdmin,
    isOperator,
    isViewer,
    isAuthenticated: !!token,
    ensureFreshToken,
  }

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}

// Login form component
export function LoginForm() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const { login, loading, error } = useAuth()

  const handleSubmit = async (e) => {
    e.preventDefault()
    await login(username, password)
  }

  return (
    <div className="login-container">
      <div className="login-box">
        <h1>MULTI-AGENT</h1>
        <h2>Dashboard Login</h2>

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="username">Username</label>
            <input
              type="text"
              id="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="dev1"
              required
              autoFocus
            />
          </div>

          <div className="form-group">
            <label htmlFor="password">Password</label>
            <input
              type="password"
              id="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Password"
              required
            />
          </div>

          {error && <div className="error-message">{error}</div>}

          <button type="submit" disabled={loading}>
            {loading ? 'Logging in...' : 'Login'}
          </button>
        </form>

        <div className="login-hint">
          Default: admin / changeme
        </div>
      </div>
    </div>
  )
}

export default AuthProvider
