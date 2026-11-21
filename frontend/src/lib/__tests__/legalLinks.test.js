import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'

import { loadRegistrationInfo, resetRegistrationInfoCache } from '../legalLinks'

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
