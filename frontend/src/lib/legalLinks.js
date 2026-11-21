import { useCallback, useEffect, useState } from 'react'

// Eine Quelle fuer /api/auth/registration-mode: Register und die Rechtsseiten
// brauchen dieselbe Antwort, der Request laeuft modulweit nur einmal.
const EMPTY_LEGAL = { terms_url: null, privacy_url: null, imprint_url: null }
const FALLBACK = { mode: null, smtp_configured: false, legal: EMPTY_LEGAL }

let cached = null
let pending = null

function normalize(data) {
  return {
    mode: data?.mode ?? null,
    smtp_configured: !!data?.smtp_configured,
    legal: { ...EMPTY_LEGAL, ...(data?.legal || {}) },
  }
}

export function loadRegistrationInfo() {
  if (cached) return Promise.resolve(cached)
  if (!pending) {
    pending = fetch('/api/auth/registration-mode')
      .then((r) => {
        // Eine Fehlerantwort (z.B. 429) darf nicht gecacht werden, sonst bliebe
        // die Seite bis zum Reload ohne Links.
        if (!r.ok) throw new Error(`registration-mode: HTTP ${r.status}`)
        return r.json()
      })
      .then((data) => {
        cached = normalize(data)
        return cached
      })
      .finally(() => {
        pending = null
      })
  }
  return pending
}

export function resetRegistrationInfoCache() {
  cached = null
  pending = null
}

// Ein Ladefehler ist ein eigener Zustand (error) und nicht dasselbe wie "keine
// Links konfiguriert": sonst fehlt Register die AGB-Checkbox und der Server
// lehnt die Anmeldung ohne erkennbaren Grund ab. Fehler werden nicht gecacht.
// refresh: laedt beim Mount neu, auch bei vorhandenem Cache, damit sich der
// Registrierungsmodus nicht bis zum Reload veraltet zeigt. Schlaegt das Auffrischen
// fehl, bleibt der gecachte Stand stehen.
export function useRegistrationInfo({ refresh = false } = {}) {
  const [state, setState] = useState(
    cached ? { info: cached, loaded: true, error: false } : { info: FALLBACK, loaded: false, error: false },
  )
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const isRetry = attempt > 0
    if (cached && !refresh && !isRetry) return undefined
    if (refresh || isRetry) resetRegistrationInfoCache()
    let active = true
    loadRegistrationInfo()
      .then((info) => active && setState({ info, loaded: true, error: false }))
      .catch(() => active && setState((prev) => (
        prev.loaded && !isRetry ? prev : { info: FALLBACK, loaded: true, error: true }
      )))
    return () => {
      active = false
    }
  }, [attempt, refresh])

  const retry = useCallback(() => {
    setState({ info: FALLBACK, loaded: false, error: false })
    setAttempt((n) => n + 1)
  }, [])

  return { ...state.info, loaded: state.loaded, error: state.error, retry }
}

export function useLegalLinks() {
  const { legal, loaded, error, retry } = useRegistrationInfo()
  return { terms: legal.terms_url, privacy: legal.privacy_url, imprint: legal.imprint_url, loaded, error, retry }
}
