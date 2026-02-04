import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { AuthProvider, LoginForm, useAuth } from './AuthProvider'
import './index.css'

function Root() {
  const { isAuthenticated, loading } = useAuth()

  if (loading) {
    return (
      <div className="loading-screen">
        <div className="spinner"></div>
        <p>Loading...</p>
      </div>
    )
  }

  // For development: skip auth if VITE_SKIP_AUTH is set
  const skipAuth = import.meta.env.VITE_SKIP_AUTH === 'true'

  if (!isAuthenticated && !skipAuth) {
    return <LoginForm />
  }

  return <App />
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <AuthProvider>
      <Root />
    </AuthProvider>
  </React.StrictMode>
)
