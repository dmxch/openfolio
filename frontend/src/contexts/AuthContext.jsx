import { createContext, useContext, useState, useCallback, useEffect } from 'react'

const AuthContext = createContext()

export function useAuth() {
  return useContext(AuthContext)
}

// Access token lives only in memory. The refresh token is mirrored to
// localStorage ('rf') so the session survives reloads and is shared
// across tabs.
let accessToken = null
let refreshToken = null

// Cross-tab lock around refresh-token rotation: if multiple tabs refresh
// concurrently, the backend's reuse detection revokes all sessions.
// Falls back to the unguarded behavior when the Web Locks API is missing.
export async function withRefreshLock(fn) {
  if (typeof navigator !== 'undefined' && navigator.locks?.request) {
    return navigator.locks.request('openfolio-token-refresh', fn)
  }
  return fn()
}

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
    return withRefreshLock(() => doRefreshSession())
  }

  async function doRefreshSession() {
    // Another tab may have rotated the token while we waited for the lock —
    // use the freshest one from localStorage, the old one would trigger
    // the backend's reuse detection.
    const stored = localStorage.getItem('rf')
    if (stored && stored !== refreshToken) {
      refreshToken = stored
    }
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

  // Drop the buffered plaintext credentials when the MFA step is aborted.
  const cancelMfa = useCallback(() => {
    setMfaRequired(false)
    setPendingLogin(null)
  }, [])

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
    setMfaRequired(false)
    setPendingLogin(null)
  }, [])

  const value = {
    user,
    loading,
    login,
    logout,
    register,
    mfaRequired,
    loginWithMfa,
    cancelMfa,
    refreshSession,
    isAuthenticated: !!user,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
