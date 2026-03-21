import { createContext, useContext, useState, useCallback, useEffect } from 'react'

const AuthContext = createContext()

export function useAuth() {
  return useContext(AuthContext)
}

// In-memory token storage (not localStorage for security)
let accessToken = null
let refreshToken = null

export function getAccessToken() {
  return accessToken
}

export function setTokens(access, refresh) {
  accessToken = access
  refreshToken = refresh
}

export function clearTokens() {
  accessToken = null
  refreshToken = null
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [mfaRequired, setMfaRequired] = useState(false)
  const [pendingLogin, setPendingLogin] = useState(null)

  // Try to restore session from stored refresh token
  useEffect(() => {
    const stored = localStorage.getItem('rf')
    if (stored) {
      refreshToken = stored
      refreshSession().finally(() => setLoading(false))
    } else {
      setLoading(false)
    }
  }, [])

  async function refreshSession() {
    if (!refreshToken) return false
    try {
      const res = await fetch('/api/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      })
      if (!res.ok) {
        clearTokens()
        localStorage.removeItem('rf')
        setUser(null)
        return false
      }
      const data = await res.json()
      accessToken = data.access_token
      refreshToken = data.refresh_token
      localStorage.setItem('rf', data.refresh_token)

      // Load user info
      const meRes = await fetch('/api/auth/me', {
        headers: { Authorization: `Bearer ${accessToken}` },
      })
      if (meRes.ok) {
        setUser(await meRes.json())
      }
      return true
    } catch {
      clearTokens()
      localStorage.removeItem('rf')
      setUser(null)
      return false
    }
  }

  const login = useCallback(async (email, password, totpCode = null) => {
    const body = { email, password }
    if (totpCode) body.totp_code = totpCode

    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })

    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || 'Anmeldung fehlgeschlagen')
    }

    const data = await res.json()

    if (data.mfa_required) {
      setMfaRequired(true)
      setPendingLogin({ email, password })
      return { mfaRequired: true }
    }

    accessToken = data.access_token
    refreshToken = data.refresh_token
    localStorage.setItem('rf', data.refresh_token)
    setUser(data.user)
    setMfaRequired(false)
    setPendingLogin(null)
    return { success: true, user: data.user }
  }, [])

  const loginWithMfa = useCallback(async (totpCode) => {
    if (!pendingLogin) throw new Error('Kein ausstehender Login')
    return login(pendingLogin.email, pendingLogin.password, totpCode)
  }, [pendingLogin, login])

  const register = useCallback(async (email, password, invite_code) => {
    const body = { email, password }
    if (invite_code) body.invite_code = invite_code
    const res = await fetch('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || 'Registrierung fehlgeschlagen')
    }
    return res.json()
  }, [])

  const logout = useCallback(async () => {
    try {
      if (accessToken && refreshToken) {
        await fetch('/api/auth/logout', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${accessToken}`,
          },
          body: JSON.stringify({ refresh_token: refreshToken }),
        })
      }
    } catch {
      // Ignore logout errors
    }
    clearTokens()
    localStorage.removeItem('rf')
    setUser(null)
  }, [])

  const value = {
    user,
    loading,
    login,
    logout,
    register,
    mfaRequired,
    loginWithMfa,
    refreshSession,
    isAuthenticated: !!user,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
