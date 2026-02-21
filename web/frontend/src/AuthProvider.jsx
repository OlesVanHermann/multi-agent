import React, { createContext, useContext, useState, useEffect } from 'react'

const AuthContext = createContext(null)

// Keycloak configuration
const KEYCLOAK_URL = '/auth'
const REALM = 'multi-agent'
const CLIENT_ID = 'multi-agent-web'

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [token, setToken] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Check for existing session on mount
  useEffect(() => {
    const storedToken = localStorage.getItem('access_token')
    const storedUser = localStorage.getItem('user')

    if (storedToken && storedUser) {
      setToken(storedToken)
      setUser(JSON.parse(storedUser))
    }
    setLoading(false)
  }, [])

  const login = async (username, password) => {
    setError(null)
    setLoading(true)

    try {
      const response = await fetch(
        `${KEYCLOAK_URL}/realms/${REALM}/protocol/openid-connect/token`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
          },
          body: new URLSearchParams({
            grant_type: 'password',
            client_id: CLIENT_ID,
            username,
            password,
          }),
        }
      )

      if (!response.ok) {
        const data = await response.json()
        throw new Error(data.error_description || 'Login failed')
      }

      const data = await response.json()

      // Decode JWT to get user info
      const payload = JSON.parse(atob(data.access_token.split('.')[1]))

      const userInfo = {
        username: payload.preferred_username,
        email: payload.email,
        name: payload.name,
        roles: payload.roles || payload.realm_access?.roles || [],
      }

      setToken(data.access_token)
      setUser(userInfo)

      localStorage.setItem('access_token', data.access_token)
      localStorage.setItem('refresh_token', data.refresh_token)
      localStorage.setItem('user', JSON.stringify(userInfo))

      // Redirect to root after login
      if (window.location.pathname !== '/') {
        window.history.replaceState(null, '', '/')
      }

      return true
    } catch (err) {
      setError(err.message)
      return false
    } finally {
      setLoading(false)
    }
  }

  const logout = () => {
    setToken(null)
    setUser(null)
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    localStorage.removeItem('user')
  }

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
              placeholder="octave"
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
          Default: octave / changeme
        </div>
      </div>
    </div>
  )
}

export default AuthProvider
