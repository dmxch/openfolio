import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'

import { renderHook, waitFor, act } from '@testing-library/react'
import { loadRegistrationInfo, resetRegistrationInfoCache, useRegistrationInfo } from '../legalLinks'

beforeEach(() => {
  resetRegistrationInfoCache()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('loadRegistrationInfo', () => {
  it('cacht eine Fehlerantwort nicht, der naechste Aufruf laedt neu', async () => {
    const legal = { terms_url: 'https://example.com/agb', privacy_url: null, imprint_url: null }
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 429, json: async () => ({ detail: 'Too many requests' }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ mode: 'open', legal }) })
    vi.stubGlobal('fetch', fetchMock)

    await expect(loadRegistrationInfo()).rejects.toThrow(/429/)
    const info = await loadRegistrationInfo()

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(info.legal.terms_url).toBe('https://example.com/agb')
  })
})

describe('useRegistrationInfo', () => {
  const ok = (mode) => ({ ok: true, json: async () => ({ mode, legal: { terms_url: 'https://example.com/agb' } }) })

  it('meldet einen Ladefehler als error und nicht als leere Links', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 502, json: async () => ({}) }))
    const { result } = renderHook(() => useRegistrationInfo())

    await waitFor(() => expect(result.current.loaded).toBe(true))
    expect(result.current.error).toBe(true)
  })

  it('retry laedt neu und hebt den Fehler auf', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 429, json: async () => ({}) })
      .mockResolvedValueOnce(ok('open'))
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useRegistrationInfo())
    await waitFor(() => expect(result.current.error).toBe(true))

    act(() => result.current.retry())

    await waitFor(() => expect(result.current.loaded).toBe(true))
    expect(result.current.error).toBe(false)
    expect(result.current.legal.terms_url).toBe('https://example.com/agb')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('refresh laedt trotz Cache neu und uebernimmt den neuen Modus', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(ok('open')).mockResolvedValueOnce(ok('invite_only'))
    vi.stubGlobal('fetch', fetchMock)
    await loadRegistrationInfo()

    const { result } = renderHook(() => useRegistrationInfo({ refresh: true }))
    expect(result.current.mode).toBe('open')
    await waitFor(() => expect(result.current.mode).toBe('invite_only'))
  })
})
