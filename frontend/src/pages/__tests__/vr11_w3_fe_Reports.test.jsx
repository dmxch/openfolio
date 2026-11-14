import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'

// Stabile Objekte: ReportViewer hängt einen Effekt an `data`; ein neues Objekt
// je Render liefe in eine Endlosschleife.
const api = vi.hoisted(() => ({
  list: {
    data: {
      results: [{ id: 7, title: 'Wochenbericht', category: 'macro', tags: [] }],
      categories: [],
      all_tags: [],
      total: 1,
    },
    loading: false,
    error: null,
    refetch: () => {},
  },
  detail: {
    loading: false,
    error: null,
    data: { id: 7, title: 'Wochenbericht', category: 'macro', tags: [], body: 'Text' },
  },
  toast: vi.fn(),
}))

vi.mock('../../hooks/useApi', () => ({
  useApi: (endpoint) => (endpoint.startsWith('/reports?') ? api.list : api.detail),
  authFetch: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}))
vi.mock('../../components/Toast', () => ({ useToast: () => api.toast }))

import { authFetch } from '../../hooks/useApi'
import Reports from '../Reports'

function errorResponse(status, body) {
  return {
    ok: false,
    status,
    json: body === undefined ? async () => { throw new Error('kein JSON') } : async () => body,
  }
}

beforeEach(() => {
  authFetch.mockReset()
  api.toast.mockReset()
})
afterEach(cleanup)

describe('Report-Vault: PDF-Export meldet den Grund (K027)', () => {
  it.each([
    [422, 'Der Report ist für den PDF-Export zu gross.'],
    [429, 'Es läuft bereits ein PDF-Export. Bitte warte, bis er fertig ist.'],
    [503, 'Der PDF-Export ist gerade ausgelastet. Bitte versuche es gleich erneut.'],
  ])('zeigt bei %i den Text aus detail', async (status, detail) => {
    authFetch.mockResolvedValue(errorResponse(status, { detail }))
    render(<Reports />)

    fireEvent.click(screen.getByRole('button', { name: 'PDF' }))

    await waitFor(() => expect(api.toast).toHaveBeenCalledWith(`PDF-Export fehlgeschlagen: ${detail}`, 'error'))
  })

  it('fällt ohne lesbaren Body auf den Statuscode zurück', async () => {
    authFetch.mockResolvedValue(errorResponse(502))
    render(<Reports />)

    fireEvent.click(screen.getByRole('button', { name: 'PDF' }))

    await waitFor(() => expect(api.toast).toHaveBeenCalledWith('PDF-Export fehlgeschlagen: HTTP 502', 'error'))
  })

  it('fällt bei detail ohne Text auf den Statuscode zurück', async () => {
    authFetch.mockResolvedValue(errorResponse(422, { detail: [{ msg: 'x' }] }))
    render(<Reports />)

    fireEvent.click(screen.getByRole('button', { name: 'PDF' }))

    await waitFor(() => expect(api.toast).toHaveBeenCalledWith('PDF-Export fehlgeschlagen: HTTP 422', 'error'))
  })

  it('sperrt den PDF-Knopf, solange der Export läuft', async () => {
    let finish
    authFetch.mockReturnValue(new Promise((resolve) => { finish = resolve }))
    render(<Reports />)
    const button = screen.getByRole('button', { name: 'PDF' })

    fireEvent.click(button)
    await waitFor(() => expect(button.disabled).toBe(true))
    fireEvent.click(button)
    expect(authFetch).toHaveBeenCalledTimes(1)

    finish(errorResponse(503, { detail: 'ausgelastet' }))
    await waitFor(() => expect(button.disabled).toBe(false))
  })
})

describe('Report-Vault: Suchfeld (K028)', () => {
  it('begrenzt die Eingabe auf die 64 Zeichen der API', () => {
    render(<Reports />)

    expect(screen.getByLabelText('Reports durchsuchen').maxLength).toBe(64)
  })
})
