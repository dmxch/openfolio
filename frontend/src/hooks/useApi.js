import { useState, useEffect, useCallback, useRef } from 'react'
import { getAccessToken, setTokens, clearTokens, withRefreshLock } from '../contexts/AuthContext'

const API_BASE = '/api'

let isRefreshing = false
let refreshSubscribers = []

function onRefreshed(ok) {
  refreshSubscribers.forEach((cb) => cb(ok))
  refreshSubscribers = []
}

function addRefreshSubscriber(cb) {
  refreshSubscribers.push(cb)
}

async function tryRefresh() {
  if (!localStorage.getItem('rf')) {
    clearTokens()
    window.location.href = '/login'
    return false
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
      return false
    }

    try {
      const res = await fetch(`${API_BASE}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: rf }),
      })
      if (!res.ok) {
        clearTokens()
        localStorage.removeItem('rf')
        window.location.href = '/login'
        return false
      }
      const data = await res.json()
      setTokens(data.access_token, data.refresh_token)
      localStorage.setItem('rf', data.refresh_token)
      return true
    } catch {
      clearTokens()
      localStorage.removeItem('rf')
      window.location.href = '/login'
      return false
    }
  })
}

function authHeaders() {
  const token = getAccessToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function authFetch(url, options = {}) {
  const res = await fetch(url, {
    ...options,
    headers: { ...options.headers, ...authHeaders() },
  })

  if (res.status === 401) {
    if (!isRefreshing) {
      isRefreshing = true
      const ok = await tryRefresh()
      isRefreshing = false
      // Notify queued requests in both cases — otherwise they hang forever
      // when the refresh fails.
      onRefreshed(ok)
      if (ok) {
        // Retry original request
        return fetch(url, {
          ...options,
          headers: { ...options.headers, ...authHeaders() },
        })
      }
      return res
    }
    // Wait for the ongoing refresh
    return new Promise((resolve) => {
      addRefreshSubscriber((ok) => {
        if (!ok) {
          // Refresh failed — resolve with the original 401 response.
          resolve(res)
          return
        }
        resolve(
          fetch(url, {
            ...options,
            headers: { ...options.headers, ...authHeaders() },
          })
        )
      })
    })
  }

  return res
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
