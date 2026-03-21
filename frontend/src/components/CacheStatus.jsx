import { useState, useEffect, useCallback, useRef } from 'react'
import { RefreshCw } from 'lucide-react'
import { apiPost, authFetch } from '../hooks/useApi'
import { useToast } from './Toast'

const POLL_INTERVAL = 3000
const POLL_TIMEOUT = 90000

export default function CacheStatus() {
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(false)
  const [elapsed, setElapsed] = useState(null)
  const pollRef = useRef(null)
  const pollStartRef = useRef(null)
  const elapsedRef = useRef(null)
  const addToast = useToast()

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
    if (elapsedRef.current) {
      clearInterval(elapsedRef.current)
      elapsedRef.current = null
    }
    pollStartRef.current = null
    setElapsed(null)
  }, [])

  const fetchStatus = useCallback(async () => {
    try {
      const res = await authFetch('/api/cache/status')
      if (res.ok) {
        const data = await res.json()
        setStatus(data)

        if (data.status === 'refreshing' && data.elapsed_seconds != null) {
          setElapsed(data.elapsed_seconds)
        }

        // If we're polling and the refresh finished, stop
        if (pollRef.current && data.status !== 'refreshing') {
          stopPolling()
          setLoading(false)
        }

        // Safety: if polling too long, force stop
        if (pollStartRef.current && Date.now() - pollStartRef.current > POLL_TIMEOUT) {
          stopPolling()
          setLoading(false)
          setStatus((prev) => ({
            ...prev,
            status: prev?.status === 'refreshing' ? 'timeout' : prev?.status,
          }))
        }

        return data
      }
    } catch {
      /* ignore */
    }
    return null
  }, [stopPolling])

  // Initial fetch + slow background poll
  useEffect(() => {
    fetchStatus()
    const interval = setInterval(fetchStatus, 60000)
    return () => {
      clearInterval(interval)
      stopPolling()
    }
  }, [fetchStatus, stopPolling])

  const startPolling = useCallback(() => {
    stopPolling()
    pollStartRef.current = Date.now()
    pollRef.current = setInterval(fetchStatus, POLL_INTERVAL)
    // Tick elapsed every second locally
    elapsedRef.current = setInterval(() => {
      setElapsed((e) => (e != null ? e + 1 : 1))
    }, 1000)
  }, [fetchStatus, stopPolling])

  const handleRefresh = async () => {
    setLoading(true)
    setElapsed(0)
    try {
      const res = await authFetch('/api/cache/refresh', { method: 'POST' })
      const result = await res.json()

      if (res.status === 429) {
        addToast('Refresh läuft bereits...', 'info')
        startPolling()
        return
      }

      if (result.status === 'ok') {
        addToast(`${result.tickers_refreshed} Kurse aktualisiert`, 'success')
        setLoading(false)
        setElapsed(null)
        await fetchStatus()
      } else if (result.status === 'timeout') {
        addToast('Refresh Timeout — teilweise aktualisiert', 'warning')
        setLoading(false)
        setElapsed(null)
        await fetchStatus()
      } else {
        addToast('Refresh fehlgeschlagen', 'error')
        setLoading(false)
        setElapsed(null)
        await fetchStatus()
      }
    } catch {
      addToast('Refresh fehlgeschlagen', 'error')
      setLoading(false)
      setElapsed(null)
    }
  }

  // If we load and status is already "refreshing", start polling
  useEffect(() => {
    if (status?.status === 'refreshing' && !pollRef.current) {
      setLoading(true)
      setElapsed(status.elapsed_seconds ?? 0)
      startPolling()
    }
  }, [status?.status, startPolling])

  const getIndicator = () => {
    if (!status || status.status === 'never' || status.status === 'idle') {
      if (status?.last_refresh) {
        const time = new Date(status.last_refresh).toLocaleTimeString('de-CH', { hour: '2-digit', minute: '2-digit' })
        return { color: 'bg-success', label: `Kurse aktuell (${time})` }
      }
      return { color: 'bg-danger', label: 'Kurse veraltet' }
    }
    if (status.status === 'refreshing') {
      const secs = elapsed != null ? ` (${elapsed}s)` : ''
      return { color: 'bg-warning animate-pulse', label: `Aktualisiere...${secs}` }
    }
    if (status.status === 'timeout') {
      const time = status.last_refresh
        ? new Date(status.last_refresh).toLocaleTimeString('de-CH', { hour: '2-digit', minute: '2-digit' })
        : ''
      return { color: 'bg-warning', label: time ? `Timeout — Stand ${time}` : 'Timeout' }
    }
    if (status.status === 'error') {
      const time = status.last_refresh
        ? new Date(status.last_refresh).toLocaleTimeString('de-CH', { hour: '2-digit', minute: '2-digit' })
        : ''
      return { color: 'bg-danger', label: time ? `Fehler — Stand ${time}` : 'Fehler' }
    }
    const age = status.age_minutes
    if (age == null) return { color: 'bg-danger', label: 'Kurse veraltet' }
    if (age < 60) {
      const time = status.last_refresh
        ? new Date(status.last_refresh).toLocaleTimeString('de-CH', { hour: '2-digit', minute: '2-digit' })
        : ''
      return { color: 'bg-success', label: `Kurse aktuell (${time})` }
    }
    if (age < 720) {
      const time = status.last_refresh
        ? new Date(status.last_refresh).toLocaleTimeString('de-CH', { hour: '2-digit', minute: '2-digit' })
        : ''
      return { color: 'bg-warning', label: `Kurse von ${time}` }
    }
    return { color: 'bg-danger', label: 'Kurse veraltet' }
  }

  const { color, label } = getIndicator()

  return (
    <button
      onClick={handleRefresh}
      disabled={loading}
      className="flex items-center gap-2 w-full text-xs text-text-secondary hover:text-text-primary transition-colors group"
    >
      <span className={`w-2 h-2 rounded-full shrink-0 ${color}`} />
      <span className="flex-1 text-left truncate">{label}</span>
      <RefreshCw size={12} className={`text-text-muted group-hover:text-text-primary ${loading ? 'animate-spin' : ''}`} />
    </button>
  )
}
