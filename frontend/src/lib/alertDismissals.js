/**
 * Weggeklickte Alerts — geteilt zwischen Sidebar-Badge und Alerts-Banner.
 *
 * Eigenes Modul (nicht in AlertsBanner.jsx), damit AuthContext den Store beim
 * Logout leeren kann, ohne einen Import-Zyklus
 * AuthContext -> AlertsBanner -> useApi -> AuthContext zu bauen.
 *
 * Scope = Tab-Session: ein weggeklickter Alert bleibt bis zum Tab-Schluss
 * weg, aber nicht dauerhaft — Alerts sind Zustandsmeldungen, kein Postfach.
 */
const STORAGE_KEY = 'alerts_dismissed'

function load() {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    return new Set(raw ? JSON.parse(raw) : [])
  } catch {
    return new Set()
  }
}

function persist(keys) {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify([...keys]))
  } catch {
    // sessionStorage kann blockiert sein — Dismissal bleibt dann nur im RAM
  }
}

let dismissed = load()
const listeners = new Set()

function emit() {
  listeners.forEach((listener) => listener())
}

export function subscribeDismissals(listener) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function isDismissed(key) {
  return dismissed.has(key)
}

export function dismissAlert(key) {
  dismissed = new Set([...dismissed, key])
  persist(dismissed)
  emit()
}

/**
 * Beim Logout aufrufen — sonst erbt der naechste User im selben Tab die
 * weggeklickten Alerts (OpenFolio ist Multi-User).
 */
export function clearDismissedAlerts() {
  dismissed = new Set()
  try {
    sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    // ignore
  }
  emit()
}
