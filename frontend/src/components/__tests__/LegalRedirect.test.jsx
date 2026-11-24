import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import LegalRedirect, { NoTermsPage } from '../LegalRedirect'
import { resetRegistrationInfoCache } from '../../lib/legalLinks'

function stubFetch(legal) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ mode: 'open', legal }) }))
}

const originalLocation = window.location
let replaceMock

beforeEach(() => {
  resetRegistrationInfoCache()
  replaceMock = vi.fn()
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: { ...originalLocation, replace: replaceMock },
  })
})

afterEach(() => {
  Object.defineProperty(window, 'location', { configurable: true, value: originalLocation })
  vi.unstubAllGlobals()
})

describe('LegalRedirect', () => {
  it('leitet bei Ziel auf dieselbe Seite nicht weiter (Schleife) und zeigt den Fallback', async () => {
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: new URL('https://app.example.com/nutzungsbedingungen'),
    })
    window.location.replace = replaceMock
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    stubFetch({ terms_url: 'https://app.example.com/nutzungsbedingungen', privacy_url: null, imprint_url: null })
    render(<MemoryRouter><LegalRedirect linkKey="terms" fallback={<div>Neutral</div>} /></MemoryRouter>)

    expect(await screen.findByText('Neutral')).toBeTruthy()
    expect(replaceMock).not.toHaveBeenCalled()
    // Die Warnung kommt aus einem Effekt. React führt ihn nach dem Zeichnen aus,
    // also unter Last erst, nachdem findByText den Fallback schon gefunden hat.
    await waitFor(() => expect(warn).toHaveBeenCalled())
    warn.mockRestore()
  })

  it('zeigt den Fallback, wenn replace() wirft', async () => {
    replaceMock.mockImplementation(() => { throw new Error('blocked') })
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    stubFetch({ terms_url: 'https://example.com/agb', privacy_url: null, imprint_url: null })
    render(<MemoryRouter><LegalRedirect linkKey="terms" fallback={<div>Neutral</div>} /></MemoryRouter>)

    expect(await screen.findByText('Neutral')).toBeTruthy()
    warn.mockRestore()
  })

  it('leitet mit konfigurierter URL weiter', async () => {
    stubFetch({ terms_url: 'https://example.com/agb', privacy_url: null, imprint_url: null })
    render(<MemoryRouter><LegalRedirect linkKey="terms" fallback={<div>Neutral</div>} /></MemoryRouter>)

    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith('https://example.com/agb'))
    expect(screen.queryByText('Neutral')).toBeNull()
  })

  it('zeigt ohne URL die neutrale Seite und leitet nicht weiter', async () => {
    stubFetch({ terms_url: null, privacy_url: null, imprint_url: null })
    render(<MemoryRouter><LegalRedirect linkKey="terms" fallback={<NoTermsPage />} /></MemoryRouter>)

    expect(await screen.findByText(/keine Nutzungsbedingungen hinterlegt/)).toBeTruthy()
    expect(screen.getByText(/MIT-Lizenz/)).toBeTruthy()
    expect(replaceMock).not.toHaveBeenCalled()
  })

  it('nutzt den passenden Schluessel je Seite', async () => {
    stubFetch({ terms_url: null, privacy_url: 'https://example.com/datenschutz', imprint_url: null })
    render(<MemoryRouter><LegalRedirect linkKey="privacy" fallback={<div>Neutral</div>} /></MemoryRouter>)

    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith('https://example.com/datenschutz'))
  })

  it('zeigt bei Ladefehler einen Hinweis statt der neutralen Seite und laedt mit "Erneut laden" neu', async () => {
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 429, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ mode: 'open', legal: { terms_url: null, privacy_url: null, imprint_url: null } }) }))
    render(<MemoryRouter><LegalRedirect linkKey="terms" fallback={<div>Neutral</div>} /></MemoryRouter>)

    expect(await screen.findByText('Die Angaben dieser Instanz konnten nicht geladen werden.')).toBeTruthy()
    expect(screen.queryByText('Neutral')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }))
    expect(await screen.findByText('Neutral')).toBeTruthy()
  })
})
