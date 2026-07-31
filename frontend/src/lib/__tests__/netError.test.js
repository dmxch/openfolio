import { describe, it, expect, vi, afterEach } from 'vitest'
import {
  netFetch,
  toNetworkError,
  isNetworkError,
  isAbortError,
  OFFLINE_MESSAGE,
  UNREACHABLE_MESSAGE,
} from '../netError.js'

function setOnline(value) {
  Object.defineProperty(navigator, 'onLine', { value, configurable: true })
}

afterEach(() => {
  vi.unstubAllGlobals()
  setOnline(true)
})

// --- netFetch: Antworten unveraendert durchreichen ---
describe('netFetch', () => {
  it('reicht erfolgreiche Antworten unveraendert durch', async () => {
    const response = { ok: true, status: 200 }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))

    await expect(netFetch('/api/auth/login')).resolves.toBe(response)
  })

  it('reicht HTTP-Fehler durch, statt sie zu uebersetzen', async () => {
    // 401 heisst "Server hat Nein gesagt" — das gehoert dem Aufrufer
    // (falsches Passwort), nicht der Netzwerk-Uebersetzung.
    const response = { ok: false, status: 401 }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))

    await expect(netFetch('/api/auth/login')).resolves.toBe(response)
  })

  it('uebersetzt den nackten fetch-TypeError ins Deutsche', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    await expect(netFetch('/api/auth/login')).rejects.toMatchObject({
      message: UNREACHABLE_MESSAGE,
      isNetworkError: true,
    })
  })

  it('meldet fehlende Verbindung, wenn der Browser offline ist', async () => {
    setOnline(false)
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    await expect(netFetch('/api/auth/login')).rejects.toThrow(OFFLINE_MESSAGE)
  })

  it('laesst abgebrochene Requests unveraendert', async () => {
    const abort = Object.assign(new Error('aborted'), { name: 'AbortError' })
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(abort))

    await expect(netFetch('/api/data')).rejects.toBe(abort)
  })

  it('behaelt den Originalfehler als cause', async () => {
    const original = new TypeError('Load failed')
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(original))

    const err = await netFetch('/api/data').catch((e) => e)
    expect(err.cause).toBe(original)
  })
})

// --- Klassifizierung ---
describe('isNetworkError / isAbortError', () => {
  it('erkennt uebersetzte Netzfehler', () => {
    expect(isNetworkError(toNetworkError(new TypeError('Failed to fetch')))).toBe(true)
  })

  it('haelt gewoehnliche Fehler auseinander', () => {
    // Ein abgelehnter Login darf NICHT als Netzfehler gelten — sonst bliebe
    // eine ungueltige Session bestehen.
    expect(isNetworkError(new Error('Ungültige Anmeldedaten'))).toBe(false)
    expect(isNetworkError(undefined)).toBe(false)
  })

  it('erkennt Abbrueche', () => {
    expect(isAbortError(Object.assign(new Error('x'), { name: 'AbortError' }))).toBe(true)
    expect(isAbortError(new TypeError('Failed to fetch'))).toBe(false)
  })
})
