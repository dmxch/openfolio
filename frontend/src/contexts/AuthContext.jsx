import { createContext, useContext, useState, useCallback, useEffect } from 'react'
import { clearDismissedAlerts } from '../lib/alertDismissals'
import { netFetch } from '../lib/netError'

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

// Wartezeiten zwischen den Versuchen, die Sitzung beim App-Start
// wiederherzustellen, wenn der Server nur voruebergehend nicht antwortet
// (zusammen gut zwei Minuten — so lange darf ein Backend-Neustart dauern).
const RESTORE_RETRY_DELAYS_MS = [2_000, 5_000, 10_000, 20_000, 30_000, 30_000, 30_000]

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [mfaRequired, setMfaRequired] = useState(false)
  const [pendingLogin, setPendingLogin] = useState(null)

  // Try to restore session from stored refresh token
  useEffect(() => {
    const stored = localStorage.getItem('rf')
    if (!stored) {
      setLoading(false)
      return undefined
    }
    refreshToken = stored
    let cancelled = false
    let timer = null
    let attempt = 0
    const attemptRestore = async () => {
      const outcome = await restoreSession()
      if (cancelled) return
      setLoading(false)
      // Voruebergehender Fehler (429, 5xx, kein Netz): der Token gilt noch.
      // Im Hintergrund weiter versuchen, sonst meldet sich der Nutzer auf der
      // Login-Seite neu an, obwohl seine Sitzung auf dem Server lebt (K075).
      if (!outcome.ok && outcome.retry && attempt < RESTORE_RETRY_DELAYS_MS.length) {
        timer = setTimeout(() => {
          // Inzwischen von Hand angemeldet: nichts mehr zu tun.
          if (cancelled || accessToken) return
          attemptRestore()
        }, RESTORE_RETRY_DELAYS_MS[attempt])
        attempt += 1
      }
    }
    attemptRestore()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [])

  async function refreshSession() {
    return (await restoreSession()).ok
  }

  async function restoreSession() {
    if (!refreshToken) return { ok: false, retry: false }
    return withRefreshLock(() => doRefreshSession())
  }

  // Liefert { ok, retry }. retry=true heisst: der Server hat den Token nicht
  // abgelehnt, er war nur nicht erreichbar oder ueberlastet.
  async function doRefreshSession() {
    // Another tab may have rotated the token while we waited for the lock —
    // use the freshest one from localStorage, the old one would trigger
    // the backend's reuse detection.
    const stored = localStorage.getItem('rf')
    if (stored && stored !== refreshToken) {
      refreshToken = stored
    }
    if (!refreshToken) return { ok: false, retry: false }
    try {
      const res = await netFetch('/api/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      })
      // Nur 401 heisst "Token abgelehnt" — so lehnt das Backend immer ab.
      // Ein 502 beim Neustart, ein 429 oder ein 503 vom Proxy sagt nichts
      // ueber den Token: behalten und spaeter erneut versuchen.
      if (res.status === 401) {
        clearTokens()
        localStorage.removeItem('rf')
        setUser(null)
        return { ok: false, retry: false }
      }
      if (!res.ok) return { ok: false, retry: true }
      const data = await res.json()
      accessToken = data.access_token
      refreshToken = data.refresh_token
      localStorage.setItem('rf', data.refresh_token)

      // Load user info
      const meRes = await netFetch('/api/auth/me', {
        headers: { Authorization: `Bearer ${accessToken}` },
      })
      if (meRes.ok) {
        setUser(await meRes.json())
        return { ok: true, retry: false }
      }
      // Token erneuert, Profil aber nicht geladen: ohne User bleibt die App
      // auf der Login-Seite stehen. Bei 429/5xx deshalb ebenfalls wiederholen.
      if (meRes.status === 401) return { ok: false, retry: false }
      // Ohne User gibt es keine nutzbare Sitzung. Der Access-Token faellt weg,
      // damit die Wiederholung ihn nicht fuer eine Anmeldung von Hand haelt.
      accessToken = null
      return { ok: false, retry: true }
    } catch {
      // Netzfehler oder unlesbare Antwort sind KEIN abgelehnter Token: den
      // Refresh-Token behalten, damit ein Start ohne Verbindung (Standby,
      // Zug, Captive Portal) die Session nicht dauerhaft loescht.
      return { ok: false, retry: true }
    }
  }

  const login = useCallback(async (email, password, totpCode = null) => {
    const body = { email, password }
    if (totpCode) body.totp_code = totpCode

    const res = await netFetch('/api/auth/login', {
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
    // Auch beim Login räumen, nicht nur beim Logout: eine Session endet oft
    // OHNE logout() (abgelaufener/abgelehnter Refresh-Token → Redirect auf
    // /login). Sonst erbt der nächste User im selben Tab die weggeklickten
    // Alerts — Kollisionen im Key (Kategorie:Ticker:Titel) sind real und
    // könnten kritische Stop-Loss-Meldungen verstecken.
    clearDismissedAlerts()
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

  const register = useCallback(async (email, password, invite_code, terms_accepted) => {
    const body = { email, password }
    if (invite_code) body.invite_code = invite_code
    if (terms_accepted) body.terms_accepted = true
    const res = await netFetch('/api/auth/register', {
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
    clearDismissedAlerts()
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
