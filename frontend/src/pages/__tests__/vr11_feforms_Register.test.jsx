import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

const registerMock = vi.fn()
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ register: registerMock }) }))

import Register from '../Register'
import { resetRegistrationInfoCache } from '../../lib/legalLinks'

const LEGAL = { terms_url: 'https://example.com/agb', privacy_url: null, imprint_url: null }
const NO_LEGAL = { terms_url: null, privacy_url: null, imprint_url: null }

function stubFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, json: async () => payload })
  vi.stubGlobal('fetch', fn)
  return fn
}

beforeEach(() => {
  resetRegistrationInfoCache()
  registerMock.mockReset().mockResolvedValue({})
})

afterEach(() => {
  vi.unstubAllGlobals()
})

async function fillForm() {
  fireEvent.change(screen.getByLabelText('E-Mail'), { target: { value: 'a@example.com' } })
  fireEvent.change(screen.getByLabelText('Passwort'), { target: { value: 'TestPassw0rd!2026' } })
  fireEvent.change(screen.getByLabelText('Passwort bestätigen'), { target: { value: 'TestPassw0rd!2026' } })
}

describe('Register: Einladungscode (K088)', () => {
  it('zeigt als Platzhalter das Format der neuen Codes', async () => {
    stubFetch({ mode: 'invite_only', legal: NO_LEGAL })
    render(<MemoryRouter><Register /></MemoryRouter>)

    const input = await screen.findByLabelText('Einladungscode')
    // Codes lauten seit K088 «OF-<Zufall>», nicht mehr «OPEN-FO-<Jahr>-XXXX».
    expect(input.placeholder).toMatch(/^OF-/)
    expect(input.placeholder).not.toContain('OPEN-FO')
  })
})

describe('Register: AGB des Betreibers', () => {
  it('zeigt mit terms_url die Pflicht-Checkbox mit externem Link und sendet terms_accepted', async () => {
    const fetchMock = stubFetch({ mode: 'open', legal: LEGAL })
    render(<MemoryRouter><Register /></MemoryRouter>)

    const checkbox = await screen.findByLabelText(/Ich habe die AGB gelesen und akzeptiere sie/)
    const link = screen.getByRole('link', { name: 'AGB' })
    expect(link.getAttribute('href')).toBe('https://example.com/agb')
    expect(link.getAttribute('target')).toBe('_blank')
    expect(link.getAttribute('rel')).toBe('noopener noreferrer')

    await fillForm()
    const submit = screen.getByRole('button', { name: 'Konto erstellen' })
    expect(submit.disabled).toBe(true)

    fireEvent.click(checkbox)
    await waitFor(() => expect(submit.disabled).toBe(false))
    fireEvent.click(submit)

    await waitFor(() => expect(registerMock).toHaveBeenCalledTimes(1))
    expect(registerMock).toHaveBeenCalledWith('a@example.com', 'TestPassw0rd!2026', undefined, true)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('zeigt ohne terms_url keine Checkbox, sondern den Haftungsausschluss-Hinweis', async () => {
    stubFetch({ mode: 'open', legal: NO_LEGAL })
    render(<MemoryRouter><Register /></MemoryRouter>)

    expect(await screen.findByText(/nimmst du den/)).toBeTruthy()
    expect(screen.queryByRole('checkbox')).toBeNull()
    expect(screen.getByRole('link', { name: 'Haftungsausschluss' }).getAttribute('href')).toBe('/disclaimer')

    await fillForm()
    const submit = screen.getByRole('button', { name: 'Konto erstellen' })
    await waitFor(() => expect(submit.disabled).toBe(false))
    fireEvent.click(submit)

    await waitFor(() => expect(registerMock).toHaveBeenCalledTimes(1))
    expect(registerMock).toHaveBeenCalledWith('a@example.com', 'TestPassw0rd!2026', undefined, undefined)
  })
})

describe('Register: Ladefehler', () => {
  it('sperrt den Knopf, zeigt Hinweis und laedt mit "Erneut laden" neu', async () => {
    const fn = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 502, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ mode: 'open', legal: LEGAL }) })
    vi.stubGlobal('fetch', fn)
    render(<MemoryRouter><Register /></MemoryRouter>)

    expect(await screen.findByText('Die Angaben dieser Instanz konnten nicht geladen werden.')).toBeTruthy()
    await fillForm()
    expect(screen.getByRole('button', { name: 'Konto erstellen' }).disabled).toBe(true)

    fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }))

    expect(await screen.findByLabelText(/AGB/)).toBeTruthy()
    expect(screen.queryByText('Die Angaben dieser Instanz konnten nicht geladen werden.')).toBeNull()
  })

  it('zeigt einen inzwischen gewechselten Modus ohne Reload', async () => {
    const fn = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ mode: 'open', legal: NO_LEGAL }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ mode: 'invite_only', legal: NO_LEGAL }) })
    vi.stubGlobal('fetch', fn)
    const first = render(<MemoryRouter><Register /></MemoryRouter>)
    await screen.findByLabelText('E-Mail')
    first.unmount()

    render(<MemoryRouter><Register /></MemoryRouter>)
    expect(await screen.findByLabelText('Einladungscode')).toBeTruthy()
  })
})
