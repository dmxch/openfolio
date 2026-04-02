import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react'
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

  const fetch = useCallback(async (force = false) => {
    // Skip if data is fresh (unless forced)
    if (!force && data && Date.now() - fetchedAt.current < STALE_MS) {
      return data
    }

    // Deduplicate concurrent fetches
    if (inFlight.current) return inFlight.current

    const promise = (async () => {
      try {
        const res = await authFetch(`/api${endpoint}`)
        if (res.ok) {
          const json = await res.json()
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
  }, [endpoint, data])

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

  // Background refresh every 30s
  useEffect(() => {
    if (!isAuthenticated) return
    const interval = setInterval(() => {
      portfolio.fetch()
      watchlist.fetch()
    }, STALE_MS)
    return () => clearInterval(interval)
  }, [isAuthenticated, portfolio.fetch, watchlist.fetch])

  const value = {
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
  }

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
