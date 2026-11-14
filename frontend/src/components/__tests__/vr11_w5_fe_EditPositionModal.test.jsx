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
const setType = (value) => fireEvent.change(screen.getByLabelText('Typ'), { target: { value } })

beforeEach(() => {
  vi.resetAllMocks()
  authFetch.mockResolvedValue({ ok: false, status: 404, json: async () => ({}) })
  apiPut.mockResolvedValue({})
  apiDelete.mockResolvedValue(undefined)
})
afterEach(cleanup)

describe('EditPositionModal: Typ-Wechsel und zurück behält die CoinGecko-ID (R-frontend-4)', () => {
  it('sendet nach crypto → stock → crypto die ursprüngliche ID', async () => {
    const { onSaved } = renderModal(CRYPTO)

    setType('stock')
    setType('crypto')
    save()

    await waitFor(() => expect(onSaved).toHaveBeenCalled())
    const payload = apiPut.mock.calls[0][1]
    expect(payload.type).toBe('crypto')
    expect(payload.coingecko_id).toBe('bitcoin')
  })

  it('zeigt die ID nach dem Rückwechsel wieder im Feld', () => {
    renderModal(CRYPTO)

    setType('etf')
    setType('crypto')
    tab('Kursdaten')

    expect(screen.getByLabelText('CoinGecko ID').value).toBe('bitcoin')
  })

  it('sendet weiterhin null, wenn der Typ nicht Krypto bleibt (K019)', async () => {
    const { onSaved } = renderModal(CRYPTO)

    setType('stock')
    save()

    await waitFor(() => expect(onSaved).toHaveBeenCalled())
    const payload = apiPut.mock.calls[0][1]
    expect(payload.type).toBe('stock')
    expect(payload.coingecko_id).toBeNull()
  })

  it('sendet null für eine Nicht-Krypto-Position mit alter ID in den Daten', async () => {
    const { onSaved } = renderModal({ ...BASE, ticker: 'AAPL', type: 'stock', coingecko_id: 'bitcoin' })

    save()

    await waitFor(() => expect(onSaved).toHaveBeenCalled())
    expect(apiPut.mock.calls[0][1].coingecko_id).toBeNull()
  })
})
