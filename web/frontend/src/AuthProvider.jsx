import React, { createContext, useContext, useState, useEffect, useRef, useCallback } from 'react'
import { createLogger } from './lib/logger'

const log = createLogger('Auth')
const AuthContext = createContext(null)

// Keycloak configuration — proxied by the backend, which owns the tokens:
// depuis B3 les jetons vivent dans des cookies HttpOnly (ma_access/ma_refresh)
// posés par le proxy /auth/* ; le JS ne voit jamais le JWT.
const KEYCLOAK_URL = '/auth'
const REALM = 'multi-agent'
const CLIENT_ID = 'multi-agent-web'
const TOKEN_ENDPOINT = `${KEYCLOAK_URL}/realms/${REALM}/protocol/openid-connect/token`
const LOGOUT_ENDPOINT = `${KEYCLOAK_URL}/realms/${REALM}/protocol/openid-connect/logout`

// Refresh session 60s before expiration
const REFRESH_MARGIN_S = 60

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const refreshTimerRef = useRef(null)
  const inflightRefreshRef = useRef(null)
  const expiresAtRef = useRef(0) // epoch (s) d'expiration du cookie d'accès

  const clearSession = useCallback((notifyServer = true) => {
    log.action('logout')
    setUser(null)
    expiresAtRef.current = 0
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current)
      refreshTimerRef.current = null
    }
    if (notifyServer) {
      // Le backend invalide la session Keycloak et efface les cookies HttpOnly
      fetch(LOGOUT_ENDPOINT, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({ client_id: CLIENT_ID }),
      }).catch(() => {})
    }
  }, [])

  const applySession = useCallback((data) => {
    if (!data || !data.user || !data.user.username) return false

    setUser(data.user)
    const expiresIn = Number(data.expires_in) || 300
    expiresAtRef.current = Date.now() / 1000 + expiresIn

    // Schedule auto-refresh
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current)
    const refreshIn = Math.max(10, expiresIn - REFRESH_MARGIN_S) * 1000
    refreshTimerRef.current = setTimeout(() => refreshSession(), refreshIn)

    return true
  }, [])

  const refreshSession = useCallback(async () => {
    if (inflightRefreshRef.current) return inflightRefreshRef.current

    const promise = (async () => {
      try {
        // Pas de refresh_token dans le corps : le backend l'injecte depuis
        // le cookie HttpOnly ma_refresh (B3).
        const response = await fetch(TOKEN_ENDPOINT, {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
          body: new URLSearchParams({
            grant_type: 'refresh_token',
            client_id: CLIENT_ID,
          }),
        })

        if (response.status === 503) {
          log.warn('keycloak unreachable, retry in 30s')
          refreshTimerRef.current = setTimeout(() => refreshSession(), 30000)
          return false
        }

        if (!response.ok) {
          log.warn('session refresh failed, forcing re-login')
          clearSession(false)
          return false
        }

        const data = await response.json()
        log.info('session refreshed')
        return applySession(data)
      } catch {
        log.error('session refresh network error')
        refreshTimerRef.current = setTimeout(() => refreshSession(), 30000)
        return false
      } finally {
        inflightRefreshRef.current = null
      }
    })()

    inflightRefreshRef.current = promise
    return promise
  }, [clearSession, applySession])

  // Awaitable: resolves truthy when the session cookie is fresh (or null).
  // Used by WS code that must avoid the expired-cookie race at wake time.
  const ensureFreshToken = useCallback(async () => {
    if (expiresAtRef.current - Date.now() / 1000 > REFRESH_MARGIN_S) {
      return true
    }
    const ok = await refreshSession()
    return ok ? true : null
  }, [refreshSession])

  // Check for existing session on mount: le cookie ma_refresh HttpOnly
  // (s'il existe) permet au backend de restaurer la session.
  useEffect(() => {
    refreshSession().finally(() => setLoading(false))
  }, [])

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current)
    }
  }, [])

  // Refresh session when tab becomes visible / network returns / window focused
  // (protects against macOS sleep breaking the scheduled setTimeout)
  useEffect(() => {
    const handleWake = () => {
      if (expiresAtRef.current === 0) return
      if (expiresAtRef.current - Date.now() / 1000 < 30) {
        refreshSession()
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
  }, [refreshSession])

  const login = async (username, password) => {
    setError(null)
    setLoading(true)

    try {
      const response = await fetch(TOKEN_ENDPOINT, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({
          grant_type: 'password',
          client_id: CLIENT_ID,
          username,
          password,
        }),
      })

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
      applySession(data)

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
    loading,
    error,
    login,
    logout,
    hasRole,
    isAdmin,
    isOperator,
    isViewer,
    isAuthenticated: !!user,
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
