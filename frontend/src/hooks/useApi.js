import { useState, useEffect, useCallback, useRef } from 'react'
import { getAccessToken, setTokens, clearTokens, withRefreshLock } from '../contexts/AuthContext'
import { netFetch, isNetworkError, toNetworkError } from '../lib/netError'

const API_BASE = '/api'

// Ergebnis eines Refresh-Versuchs. 'network' ist bewusst KEIN Auth-Fehler:
// der Server hat nicht Nein gesagt, er war nur nicht erreichbar. In dem Fall
// bleibt die Session bestehen — sonst wirft ein kurzer Verbindungsabbruch
// (Tunnel, WLAN-Wechsel, Standby) den Nutzer dauerhaft aus der App.
// Dasselbe gilt fuer 429 und 5xx (Backend-Neustart, Rate-Limit): Nein sagt
// der Server nur mit 401 (K075).
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
      // Das Backend lehnt einen ungueltigen Refresh-Token immer mit 401 ab.
      // Jede andere Antwort (502 beim Neustart, 429, 503 vom Proxy) sagt
      // nichts ueber den Token: behalten, der naechste Request versucht es neu.
      if (res.status === 401) return endSession()
      if (!res.ok) {
        return { status: REFRESH_NETWORK_FAILED, error: toNetworkError(new Error(`HTTP ${res.status}`)) }
      }
      const data = await res.json()
      setTokens(data.access_token, data.refresh_token)
      localStorage.setItem('rf', data.refresh_token)
      return { status: REFRESH_OK }
    } catch (err) {
      // Netzfehler oder unlesbare Antwort (z.B. HTML eines Captive Portals):
      // Token behalten, kein Redirect. Der Aufrufer bekommt die uebersetzte
      // Meldung und kann es spaeter erneut versuchen.
      return { status: REFRESH_NETWORK_FAILED, error: isNetworkError(err) ? err : toNetworkError(err) }
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

async function authFetchInner(url, options = {}) {
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

// --- Geteilte GETs fuer useApi und DataContext (K068) -----------------------
// Mehrere Komponenten einer Seite fragen dieselben Endpunkte ab, teils gegen
// Limits von 5 Aufrufen je Minute. Laufende Requests werden deshalb je
// Endpunkt geteilt, fertige Antworten gelten SHARED_TTL_MS lang als frisch.
// Die TTL ist bewusst kurz: sie soll Mount-Kaskaden abdecken (Seite laedt,
// Kinder mounten und fragen dasselbe), nicht als Daten-Cache dienen.
const SHARED_TTL_MS = 5_000
const sharedGets = new Map()

function dropShared(entry) {
  if (sharedGets.get(entry.endpoint) === entry) sharedGets.delete(entry.endpoint)
}

function acquireShared(endpoint, force) {
  const now = Date.now()
  // Der Access-Token ist die Sitzungsmarke: nach Logout und Login eines
  // anderen Nutzers im selben Tab darf kein Eintrag des Vorgaengers passen.
  const token = getAccessToken()
  for (const [key, e] of sharedGets) {
    if (e.token !== token || (e.settled && now - e.at >= SHARED_TTL_MS)) sharedGets.delete(key)
  }
  let entry = force ? null : sharedGets.get(endpoint)
  if (!entry) {
    const controller = new AbortController()
    entry = { endpoint, token, controller, consumers: 0, settled: false, data: undefined, at: 0 }
    entry.promise = (async () => {
      const res = await authFetchInner(`${API_BASE}${endpoint}`, { signal: controller.signal })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return res.json()
    })().then(
      (json) => {
        entry.settled = true
        entry.data = json
        entry.at = Date.now()
        return json
      },
      (err) => {
        // Fehler werden nicht gecacht: der naechste Aufrufer versucht es neu.
        dropShared(entry)
        throw err
      },
    )
    sharedGets.set(endpoint, entry)
  }
  entry.consumers += 1
  return entry
}

// Der Request wird erst abgebrochen, wenn ihn niemand mehr braucht — so
// bleibt der Abbruch bei schnellem Filter-Wechsel erhalten, ohne einem
// zweiten Abnehmer die Antwort wegzunehmen.
function releaseShared(entry) {
  entry.consumers -= 1
  if (entry.consumers <= 0 && !entry.settled) {
    dropShared(entry)
    entry.controller.abort()
  }
}

/**
 * GET mit geteiltem Request je Endpunkt, fuer Abnehmer ausserhalb von useApi
 * (DataContext). Lehnt bei HTTP-Fehlern mit `HTTP <status>` ab. `force`
 * umgeht den Cache, zum Beispiel nach einer Mutation.
 */
export function fetchShared(endpoint, { force = false } = {}) {
  return acquireShared(endpoint, force).promise
}

async function authFetch(url, options = {}) {
  if ((options.method || 'GET').toUpperCase() === 'GET') return authFetchInner(url, options)
  try {
    return await authFetchInner(url, options)
  } finally {
    // Jede Mutation kann jede gecachte Antwort veralten lassen. Auch laufende
    // GETs fliegen aus der Map: sie koennen den Stand vor der Mutation tragen.
    sharedGets.clear()
  }
}

export { authFetch }

// --- Wiederholung bei 429/503 (X23) -----------------------------------------
// 429 kommt vom Rate-Limit des Backends, 503 vom limit_req des Proxys. Beides
// heisst "gleich nochmal", nicht "gibt es nicht". Ohne Wiederholung bleiben in
// langen Listen (ein Score-Request je Titel) die hinteren Zeilen leer.
const RETRY_STATUSES = new Set([429, 503])
const RETRY_FALLBACK_MS = 2_000
const RETRY_MAX_WAIT_MS = 60_000

function retryDelayMs(res) {
  const header = res.headers?.get?.('Retry-After')
  const seconds = header == null || header === '' ? NaN : Number(header)
  if (!Number.isFinite(seconds) || seconds < 0) return RETRY_FALLBACK_MS
  return Math.min(seconds * 1000, RETRY_MAX_WAIT_MS)
}

/**
 * authFetch fuer lesende Requests: wiederholt bei 429 und 503 nach
 * Retry-After (sonst 2 s), hoechstens `retries` Mal. Liefert danach die
 * letzte Antwort, auch wenn sie noch 429 oder 503 ist.
 */
export async function authFetchRetry(url, options = {}, { retries = 3 } = {}) {
  let res = await authFetch(url, options)
  for (let attempt = 0; attempt < retries && RETRY_STATUSES.has(res.status); attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, retryDelayMs(res)))
    res = await authFetch(url, options)
  }
  return res
}

// Gleiche Ressource = gleicher Pfad; nur der Query-String (Filter, Seite,
// Zeitraum) weicht ab.
function sameResource(a, b) {
  return a != null && b != null && a.split('?')[0] === b.split('?')[0]
}

const IDLE_STATE = { key: null, loading: false, error: null, data: null, dataKey: null }

export function useApi(endpoint, options = {}) {
  const skip = !!options.skip
  // Status und Daten tragen den Endpunkt, zu dem sie gehoeren (key, dataKey).
  // Geliefert wird nur, was zum aktuellen Endpunkt passt (K050): sonst stehen
  // nach einem Wechsel von /stock/A zu /stock/B die Daten von A unter B — und
  // bei einem Fehler von B bis zum Reload.
  const [state, setState] = useState(IDLE_STATE)
  // Aktives Abo auf einen geteilten Request. Eine spaetere Antwort eines
  // aelteren Endpunkts (schneller Filter-Wechsel) wird daran erkannt und
  // verworfen.
  const activeRef = useRef(null)

  const load = useCallback((force) => {
    if (activeRef.current) releaseShared(activeRef.current)
    const entry = acquireShared(endpoint, force)
    activeRef.current = entry
    if (entry.settled) {
      setState({ key: endpoint, loading: false, error: null, data: entry.data, dataKey: endpoint })
      return Promise.resolve()
    }
    setState((prev) => ({ ...prev, key: endpoint, loading: true, error: null }))
    return entry.promise.then(
      (json) => {
        if (activeRef.current !== entry) return
        setState({ key: endpoint, loading: false, error: null, data: json, dataKey: endpoint })
      },
      (err) => {
        if (activeRef.current !== entry) return
        setState((prev) => ({ ...prev, key: endpoint, loading: false, error: err.message }))
      },
    )
  }, [endpoint])

  useEffect(() => {
    if (!skip && endpoint) load(false)
    return () => {
      if (activeRef.current) {
        releaseShared(activeRef.current)
        activeRef.current = null
      }
    }
  }, [endpoint, skip, load])

  const refetch = useCallback(() => load(true), [load])

  const statusCurrent = state.key === endpoint
  const loading = !skip && (statusCurrent ? state.loading : true)
  const error = statusCurrent ? state.error : null
  // Daten eines anderen Query-Strings derselben Ressource bleiben nur stehen,
  // solange der neue Request laeuft (kein Flackern beim Blaettern und
  // Filtern). Nach einem Fehler und bei einem anderen Pfad gibt es nichts.
  let data = null
  if (state.dataKey === endpoint) data = state.data
  else if (loading && sameResource(state.dataKey, endpoint)) data = state.data

  return { data, loading, error, refetch }
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
