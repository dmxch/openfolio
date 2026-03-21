import { useState, useEffect, useCallback } from 'react'
import { getAccessToken, setTokens, clearTokens } from '../contexts/AuthContext'

const API_BASE = '/api'

let isRefreshing = false
let refreshSubscribers = []

function onRefreshed() {
  refreshSubscribers.forEach((cb) => cb())
  refreshSubscribers = []
}

function addRefreshSubscriber(cb) {
  refreshSubscribers.push(cb)
}

async function tryRefresh() {
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
      if (ok) {
        onRefreshed()
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
      addRefreshSubscriber(() => {
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
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await authFetch(`${API_BASE}${endpoint}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setData(json)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [endpoint])

  useEffect(() => {
    if (options.skip) return
    fetchData()
  }, [fetchData, options.skip])

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
