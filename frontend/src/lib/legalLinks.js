import { useEffect, useState } from 'react'

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

// loaded wird auch nach einem Fehler true; dann gelten die neutralen Defaults
// (ein Fehlschlag wird nicht gecacht, der naechste Aufruf versucht es neu).
export function useRegistrationInfo() {
  const [state, setState] = useState(cached ? { info: cached, loaded: true } : { info: FALLBACK, loaded: false })

  useEffect(() => {
    if (cached) return undefined
    let active = true
    loadRegistrationInfo()
      .then((info) => active && setState({ info, loaded: true }))
      .catch(() => active && setState({ info: FALLBACK, loaded: true }))
    return () => {
      active = false
    }
  }, [])

  return { ...state.info, loaded: state.loaded }
}

export function useLegalLinks() {
  const { legal, loaded } = useRegistrationInfo()
  return { terms: legal.terms_url, privacy: legal.privacy_url, imprint: legal.imprint_url, loaded }
}
