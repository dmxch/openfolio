import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'

vi.mock('../../hooks/useApi', () => ({ apiPut: vi.fn(), apiDelete: vi.fn(), authFetch: vi.fn() }))
vi.mock('../../hooks/useScrollLock', () => ({ default: () => {} }))
vi.mock('../BucketChangeConfirmModal', () => ({ default: () => null }))

import { apiPut, authFetch } from '../../hooks/useApi'
import EditPositionModal from '../EditPositionModal'

// Altbestand: T-Bill-ETF als Cash-Konto. Cash-Konten sind manuell bepreist.
const CASH_TBILL = {
  id: 'p1', ticker: 'IB01.L', name: 'Treasury Bond 0-1yr', type: 'cash', currency: 'USD',
  shares: 496, cost_basis_chf: 48640, pricing_mode: 'manual', price_source: 'yahoo',
}

// Aktie mit Live-Kurs.
const STOCK_AUTO = {
  id: 'p2', ticker: 'NESN.SW', name: 'Nestlé', type: 'stock', currency: 'CHF',
  shares: 10, cost_basis_chf: 900, current_price: 95, pricing_mode: 'auto', price_source: 'yahoo',
}

// Altbestand: früheres Cash-Konto, als Anleihe geführt. Modus manual, Kurs vom Worker.
const BOND_LEGACY = {
  id: 'p3', ticker: 'IB01.L', name: 'Treasury Bond 0-1yr', type: 'bond', currency: 'USD',
  shares: 330, cost_basis_chf: 32000, current_price: 118, pricing_mode: 'manual', price_source: 'yahoo',
}

beforeEach(() => {
  vi.resetAllMocks()
  authFetch.mockResolvedValue({ ok: false, status: 404, json: async () => ({}) })
  apiPut.mockResolvedValue({})
})
afterEach(cleanup)

const openKursdaten = () => fireEvent.click(screen.getByRole('button', { name: 'Kursdaten' }))
const HINT = /Der Kurs wird weiter automatisch geladen/

describe('EditPositionModal: «Als Anleihe führen» (R-pricecache-4)', () => {
  it('sendet keinen pricing_mode: die Position bleibt manual und im Recalc geschützt', async () => {
    const onSaved = vi.fn()
    render(<EditPositionModal position={CASH_TBILL} onClose={() => {}} onSaved={onSaved} />)

    fireEvent.click(screen.getByRole('button', { name: 'Als Anleihe führen (live bepreisen)' }))

    await waitFor(() => expect(onSaved).toHaveBeenCalled())
    expect(apiPut).toHaveBeenCalledWith(
      '/portfolio/positions/p1',
      { type: 'bond', count_as_cash: false },
    )
  })
})

describe('EditPositionModal: Modus und Preisquelle hängen zusammen (K109)', () => {
  it('Modus manual zieht die Preisquelle auf manual', () => {
    render(<EditPositionModal position={STOCK_AUTO} onClose={() => {}} onSaved={() => {}} />)
    openKursdaten()

    fireEvent.change(screen.getByLabelText('Pricing-Modus'), { target: { value: 'manual' } })

    expect(screen.getByLabelText('Preisquelle').value).toBe('manual')
    expect(screen.queryByText(HINT)).toBeNull()
  })

  it('Modus auto stellt die Preisquelle des Typs wieder her', () => {
    render(<EditPositionModal position={{ ...STOCK_AUTO, pricing_mode: 'manual', price_source: 'manual' }} onClose={() => {}} onSaved={() => {}} />)
    openKursdaten()

    fireEvent.change(screen.getByLabelText('Pricing-Modus'), { target: { value: 'auto' } })

    expect(screen.getByLabelText('Preisquelle').value).toBe('yahoo')
  })

  it('Krypto mit CoinGecko-ID behält die eigene Kursquelle', () => {
    const btc = {
      id: 'p4', ticker: 'BTC-USD', name: 'Bitcoin', type: 'crypto', currency: 'USD', coingecko_id: 'bitcoin',
      shares: 0.5, cost_basis_chf: 20000, current_price: 57000, pricing_mode: 'auto', price_source: 'coingecko',
    }
    render(<EditPositionModal position={btc} onClose={() => {}} onSaved={() => {}} />)
    openKursdaten()

    fireEvent.change(screen.getByLabelText('Pricing-Modus'), { target: { value: 'manual' } })

    expect(screen.getByLabelText('Preisquelle').value).toBe('coingecko')
    expect(screen.getByText(/gilt immer die eigene Kursquelle/)).toBeTruthy()
  })

  it('Altbestand mit Modus manual und Preisquelle yahoo zeigt den Hinweis', () => {
    render(<EditPositionModal position={BOND_LEGACY} onClose={() => {}} onSaved={() => {}} />)
    openKursdaten()

    expect(screen.getByLabelText('Pricing-Modus').value).toBe('manual')
    expect(screen.getByLabelText('Preisquelle').value).toBe('yahoo')
    expect(screen.getByText(HINT)).toBeTruthy()
  })
})
