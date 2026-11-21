import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import LegalRedirect, { NoTermsPage } from '../LegalRedirect'
import { resetRegistrationInfoCache } from '../../lib/legalLinks'

function stubFetch(legal) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ json: async () => ({ mode: 'open', legal }) }))
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
})
