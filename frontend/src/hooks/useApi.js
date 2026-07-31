import { useState, useEffect, useCallback, useRef } from 'react'
import { getAccessToken, setTokens, clearTokens, withRefreshLock } from '../contexts/AuthContext'
import { netFetch, isNetworkError } from '../lib/netError'

const API_BASE = '/api'

// Ergebnis eines Refresh-Versuchs. 'network' ist bewusst KEIN Auth-Fehler:
// der Server hat nicht Nein gesagt, er war nur nicht erreichbar. In dem Fall
// bleibt die Session bestehen — sonst wirft ein kurzer Verbindungsabbruch
// (Tunnel, WLAN-Wechsel, Standby) den Nutzer dauerhaft aus der App.
const REFRESH_OK = 'ok'
const REFRESH_AUTH_FAILED = 'auth'
const REFRESH_NETWORK_FAILED = 'network'

let isRefreshing = false
let refreshSubscribers = []

function onRefreshed(outcome) {
  refreshSubscribers.forEach((cb) => cb(outcome))
  refreshSubscribers = []
}

function addRefreshSubscriber(cb) {
  refreshSubscribers.push(cb)
}

function endSession() {
  clearTokens()
  localStorage.removeItem('rf')
  window.location.href = '/login'
  return { status: REFRESH_AUTH_FAILED }
}

async function tryRefresh() {
  if (!localStorage.getItem('rf')) {
    clearTokens()
    window.location.href = '/login'
    return { status: REFRESH_AUTH_FAILED }
  }

  // Cross-tab lock: concurrent rotation from multiple tabs trips the
  // backend's refresh-token reuse detection (revokes all sessions).
  return withRefreshLock(async () => {
    // Re-read after acquiring the lock — another tab may have rotated the
    // token in the meantime; use the fresh one instead of the stale value.
    const rf = localStorage.getItem('rf')
    if (!rf) {
      clearTokens()
      window.location.href = '/login'
      return { status: REFRESH_AUTH_FAILED }
    }

    try {
      const res = await netFetch(`${API_BASE}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: rf }),
      })
      if (!res.ok) return endSession()
      const data = await res.json()
      setTokens(data.access_token, data.refresh_token)
      localStorage.setItem('rf', data.refresh_token)
      return { status: REFRESH_OK }
    } catch (err) {
      // Netzfehler: Token behalten, kein Redirect. Der Aufrufer bekommt die
      // uebersetzte Meldung und kann es spaeter erneut versuchen.
      if (isNetworkError(err)) return { status: REFRESH_NETWORK_FAILED, error: err }
      return endSession()
    }
  })
}

function authHeaders() {
  const token = getAccessToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

// MFA-Policy-Gate: Der Backend-403 traegt X-MFA-Setup-Required, wenn der User
// laut globaler Policy erst MFA einrichten muss (z.B. Policy wurde mitten in der
// Session verschaerft). Hart auf die dedizierte Setup-Seite leiten. Wird auf
// JEDE finale Response angewandt — auch auf die nach einem 401-Refresh
// wiederholte, sonst bliebe ein Retry-403 unbehandelt.
function checkMfaGate(res) {
  if (
    res.status === 403 &&
    res.headers.get('X-MFA-Setup-Required') &&
    typeof window !== 'undefined' &&
    window.location.pathname !== '/mfa-setup'
  ) {
    window.location.href = '/mfa-setup'
  }
  return res
}

async function authFetch(url, options = {}) {
  const res = await netFetch(url, {
    ...options,
    headers: { ...options.headers, ...authHeaders() },
  })

  if (res.status === 401) {
    if (!isRefreshing) {
      isRefreshing = true
      let outcome
      try {
        outcome = await tryRefresh()
      } finally {
        isRefreshing = false
      }
      // Notify queued requests in every case — otherwise they hang forever
      // when the refresh fails.
      onRefreshed(outcome)
      if (outcome.status === REFRESH_OK) {
        // Retry original request
        return checkMfaGate(await netFetch(url, {
          ...options,
          headers: { ...options.headers, ...authHeaders() },
        }))
      }
      if (outcome.status === REFRESH_NETWORK_FAILED) throw outcome.error
      return res
    }
    // Wait for the ongoing refresh
    return new Promise((resolve, reject) => {
      addRefreshSubscriber((outcome) => {
        if (outcome.status === REFRESH_NETWORK_FAILED) {
          reject(outcome.error)
          return
        }
        if (outcome.status !== REFRESH_OK) {
          // Refresh failed — resolve with the original 401 response.
          resolve(res)
          return
        }
        resolve(
          netFetch(url, {
            ...options,
            headers: { ...options.headers, ...authHeaders() },
          }).then(checkMfaGate)
        )
      })
    })
  }

  return checkMfaGate(res)
}

export { authFetch }

export function useApi(endpoint, options = {}) {
  const skip = !!options.skip
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(!skip)
  const [error, setError] = useState(null)
  // Track which endpoint already fetched — so URL-Wechsel triggert refetch,
  // mehrfache Renders mit gleichem Endpoint aber nicht.
  const fetchedEndpoint = useRef(null)
  // AbortController fuer die aktive Request — bei schnellem Filter-Wechsel
  // (z.B. Slider + Sektor-Klick parallel) wird der vorige Call gecancelled,
  // damit nicht eine spaetere Response von einem aelteren Filter-State
  // ueberschrieben wird.
  const abortRef = useRef(null)

  const fetchData = useCallback(async () => {
    // Cancel any in-flight request for an older endpoint
    if (abortRef.current) {
      abortRef.current.abort()
    }
    const controller = new AbortController()
    abortRef.current = controller

    setLoading(true)
    setError(null)
    try {
      const res = await authFetch(`${API_BASE}${endpoint}`, { signal: controller.signal })
      if (controller.signal.aborted) return
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      if (controller.signal.aborted) return
      setData(json)
    } catch (err) {
      if (err.name === 'AbortError' || controller.signal.aborted) return
      setError(err.message)
    } finally {
      if (!controller.signal.aborted) setLoading(false)
    }
  }, [endpoint])

  useEffect(() => {
    if (skip || !endpoint) {
      fetchedEndpoint.current = null
      return
    }
    if (fetchedEndpoint.current === endpoint) return
    fetchedEndpoint.current = endpoint
    fetchData()
    return () => {
      if (abortRef.current) abortRef.current.abort()
    }
  }, [endpoint, skip, fetchData])

  return { data, loading, error, refetch: fetchData }
}

const ERROR_TRANSLATIONS = {
  'String should have at most': 'Text ist zu lang',
  'String should have at least': 'Text ist zu kurz',
  'Input should be greater than or equal to': 'Wert muss grösser oder gleich',
  'Input should be greater than': 'Wert muss grösser als',
  'Input should be less than or equal to': 'Wert muss kleiner oder gleich',
  'Field required': 'Pflichtfeld',
  'value is not a valid email': 'Ungültige E-Mail-Adresse',
  'Input should be a valid number': 'Ungültige Zahl',
}

function translateError(msg) {
  for (const [en, de] of Object.entries(ERROR_TRANSLATIONS)) {
    if (msg.includes(en)) return msg.replace(en, de)
  }
  return msg
}

function extractDetail(err, status) {
  const detail = err.detail
  if (!detail) return `HTTP ${status}`
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map(d => translateError(d.msg || JSON.stringify(d))).join('; ')
  }
  return JSON.stringify(detail)
}

export async function apiPost(endpoint, body) {
  const res = await authFetch(`${API_BASE}${endpoint}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(extractDetail(err, res.status))
  }
  if (res.status === 204) return null
  return res.json()
}

export async function apiPut(endpoint, body) {
  const res = await authFetch(`${API_BASE}${endpoint}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(extractDetail(err, res.status))
  }
  return res.json()
}

export async function apiPatch(endpoint, body) {
  const res = await authFetch(`${API_BASE}${endpoint}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(extractDetail(err, res.status))
  }
  return res.json()
}

export async function apiDelete(endpoint) {
  const res = await authFetch(`${API_BASE}${endpoint}`, { method: 'DELETE' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(extractDetail(err, res.status))
  }
}

export async function apiPostFormData(endpoint, formData) {
  const res = await authFetch(`${API_BASE}${endpoint}`, {
    method: 'POST',
    body: formData,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(extractDetail(body, res.status))
  }
  return res.json()
}
