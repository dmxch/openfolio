import { createContext, useContext, useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { authFetch } from '../hooks/useApi'
import { useAuth } from './AuthContext'
import { configureFormats } from '../lib/format'

const DataContext = createContext(null)

const STALE_MS = 65_000 // 65s — slightly more than the 60s backend cache TTL to avoid stale-cache races

function useCachedFetch(endpoint) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const fetchedAt = useRef(0)
  const inFlight = useRef(null)
  // Aktuelle Daten als Ref, damit `fetch` referenzstabil bleibt (kein `data`
  // in den useCallback-Deps) — sonst wird das Refresh-Interval im Provider
  // nach jedem erfolgreichen Fetch abgerissen und neu erstellt.
  const dataRef = useRef(null)

  const fetch = useCallback(async (force = false) => {
    // Skip if data is fresh (unless forced)
    if (!force && dataRef.current && Date.now() - fetchedAt.current < STALE_MS) {
      return dataRef.current
    }

    // Deduplicate concurrent fetches. Ein FORCIERTER Refetch (nach einer
    // Mutation) darf aber nicht die Antwort eines bereits laufenden Polls
    // von VOR der Mutation zurückbekommen — er wartet ihn ab und lädt
    // danach garantiert frisch (Review-Fix 2026-07-02).
    if (inFlight.current) {
      if (!force) return inFlight.current
      const pending = inFlight.current
      return pending.then(() => fetch(true))
    }

    const promise = (async () => {
      try {
        const res = await authFetch(`/api${endpoint}`)
        if (res.ok) {
          const json = await res.json()
          dataRef.current = json
          setData(json)
          setError(null)
          fetchedAt.current = Date.now()
          return json
        }
        console.warn(`Fetch ${endpoint} failed with status ${res.status}`)
        setError(`HTTP ${res.status}`)
      } catch (err) {
        console.warn(`Fetch ${endpoint} failed:`, err)
        setError(err?.message || 'Netzwerkfehler')
      } finally {
        setLoading(false)
        inFlight.current = null
      }
      return null
    })()

    inFlight.current = promise
    return promise
  }, [endpoint])

  const invalidate = useCallback(() => {
    fetchedAt.current = 0
  }, [])

  return { data, loading, error, fetch, invalidate }
}

export function DataProvider({ children }) {
  const { isAuthenticated } = useAuth()

  const portfolio = useCachedFetch('/portfolio/summary')
  const watchlist = useCachedFetch('/analysis/watchlist')

  // Load user display settings and configure format module
  useEffect(() => {
    if (isAuthenticated) {
      authFetch('/api/settings')
        .then((r) => r.ok ? r.json() : null)
        .then((s) => {
          if (s) configureFormats({ number_format: s.number_format, date_format: s.date_format })
        })
        .catch(() => {})
    }
  }, [isAuthenticated])

  // Initial fetch when authenticated
  useEffect(() => {
    if (isAuthenticated) {
      portfolio.fetch()
      watchlist.fetch()
    }
  }, [isAuthenticated])

  // Background refresh alle STALE_MS (65s) — fetch-Referenzen sind stabil
  // (useCallback nur auf endpoint), das Interval lebt also durchgehend.
  // force=true: der Tick IST die beabsichtigte Kadenz — ohne force würde der
  // Freshness-Check (fetchedAt = Fetch-ABSCHLUSS) jeden zweiten Tick skippen
  // und die effektive Poll-Rate auf ~130s halbieren (Review-Fix 2026-07-02).
  useEffect(() => {
    if (!isAuthenticated) return
    const interval = setInterval(() => {
      portfolio.fetch(true)
      watchlist.fetch(true)
    }, STALE_MS)
    return () => clearInterval(interval)
  }, [isAuthenticated, portfolio.fetch, watchlist.fetch])

  // Context-value memoizen — sonst re-rendert jeder Provider-Render alle
  // Consumer (neue Objekt-Identitaet bei jedem Durchlauf).
  const value = useMemo(() => ({
    portfolio: {
      data: portfolio.data,
      loading: portfolio.loading,
      error: portfolio.error,
      positions: portfolio.data?.positions || [],
      refetch: () => portfolio.fetch(true),
      invalidate: portfolio.invalidate,
    },
    watchlist: {
      data: watchlist.data,
      loading: watchlist.loading,
      error: watchlist.error,
      items: watchlist.data?.items || [],
      refetch: () => watchlist.fetch(true),
      invalidate: watchlist.invalidate,
    },
  }), [
    portfolio.data, portfolio.loading, portfolio.error, portfolio.fetch, portfolio.invalidate,
    watchlist.data, watchlist.loading, watchlist.error, watchlist.fetch, watchlist.invalidate,
  ])

  return <DataContext.Provider value={value}>{children}</DataContext.Provider>
}

export function useData() {
  const ctx = useContext(DataContext)
  if (!ctx) throw new Error('useData must be used within DataProvider')
  return ctx
}

export function usePortfolioData() {
  return useData().portfolio
}

export function useWatchlistData() {
  return useData().watchlist
}
