import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'

vi.mock('../../hooks/useApi', () => ({ apiPut: vi.fn(), apiDelete: vi.fn(), authFetch: vi.fn() }))
vi.mock('../../hooks/useScrollLock', () => ({ default: () => {} }))
vi.mock('../BucketChangeConfirmModal', () => ({ default: () => null }))

import { apiPut, apiDelete, authFetch } from '../../hooks/useApi'
import EditPositionModal from '../EditPositionModal'

const BASE = {
  id: 'p1', name: 'Testposition', currency: 'USD', shares: 1, cost_basis_chf: 100,
  pricing_mode: 'auto', price_source: 'yahoo',
}
const CRYPTO = { ...BASE, ticker: 'BTC-USD', type: 'crypto', coingecko_id: 'bitcoin' }

function renderModal(position) {
  const onSaved = vi.fn()
  render(<EditPositionModal position={position} onClose={() => {}} onSaved={onSaved} />)
  return { onSaved }
}

const tab = (label) => fireEvent.click(screen.getByRole('button', { name: label }))
const save = () => fireEvent.click(screen.getByRole('button', { name: 'Speichern' }))

beforeEach(() => {
  vi.resetAllMocks()
  authFetch.mockResolvedValue({ ok: false, status: 404, json: async () => ({}) })
  apiPut.mockResolvedValue({})
  apiDelete.mockResolvedValue(undefined)
})
afterEach(cleanup)

describe('EditPositionModal: CoinGecko-ID nur beim Typ Krypto (K019)', () => {
  it('zeigt das Feld bei einer Krypto-Position', () => {
    renderModal(CRYPTO)
    tab('Kursdaten')

    expect(screen.getByLabelText('CoinGecko ID').value).toBe('bitcoin')
  })

  it('blendet das Feld bei anderen Typen aus', () => {
    renderModal({ ...BASE, ticker: 'AAPL', type: 'stock' })
    tab('Kursdaten')

    expect(screen.queryByLabelText('CoinGecko ID')).toBeNull()
    // Die übrigen Kursfelder bleiben.
    expect(screen.getByLabelText('yFinance Ticker')).toBeTruthy()
  })

  it('leert die ID beim Wechsel weg von Krypto und sendet null', async () => {
    const { onSaved } = renderModal(CRYPTO)

    fireEvent.change(screen.getByLabelText('Typ'), { target: { value: 'stock' } })
    tab('Kursdaten')
    expect(screen.queryByLabelText('CoinGecko ID')).toBeNull()

    save()
    await waitFor(() => expect(onSaved).toHaveBeenCalled())
    const [endpoint, payload] = apiPut.mock.calls[0]
    expect(endpoint).toBe('/portfolio/positions/p1')
    expect(payload.type).toBe('stock')
    expect(payload.coingecko_id).toBeNull()
  })

  it('behält die ID, solange der Typ Krypto bleibt', async () => {
    const { onSaved } = renderModal(CRYPTO)

    save()
    await waitFor(() => expect(onSaved).toHaveBeenCalled())
    expect(apiPut.mock.calls[0][1].coingecko_id).toBe('bitcoin')
  })
})

describe('EditPositionModal: Ticker in den Sektor-Pfaden kodieren (K166)', () => {
  const ETF = { ...BASE, ticker: 'A&B', type: 'etf', industry: 'Broad Market ETF' }

  it('lädt die Sektorgewichte mit kodiertem Ticker', async () => {
    renderModal(ETF)

    await waitFor(() => expect(authFetch).toHaveBeenCalledWith('/api/etf-sectors/A%26B'))
  })

  it('löscht leere Sektorgewichte mit kodiertem Ticker', async () => {
    const { onSaved } = renderModal(ETF)

    save()
    await waitFor(() => expect(onSaved).toHaveBeenCalled())
    expect(apiDelete).toHaveBeenCalledWith('/etf-sectors/A%26B')
  })

  it('speichert Sektorgewichte mit kodiertem Ticker', async () => {
    authFetch.mockImplementation(async (url) => (
      url.startsWith('/api/etf-sectors/')
        ? { ok: true, status: 200, json: async () => ({ sectors: [{ sector: 'Technology', weight_pct: 100 }] }) }
        : { ok: false, status: 404, json: async () => ({}) }
    ))
    const { onSaved } = renderModal(ETF)
    // Erst speichern, wenn die geladenen Gewichte im Formular stehen.
    await screen.findByDisplayValue('100')

    save()
    await waitFor(() => expect(onSaved).toHaveBeenCalled())
    expect(apiPut).toHaveBeenCalledWith('/etf-sectors/A%26B', { sectors: [{ sector: 'Technology', weight_pct: 100 }] })
  })
})
