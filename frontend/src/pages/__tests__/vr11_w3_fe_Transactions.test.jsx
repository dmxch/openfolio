import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

vi.mock('../../hooks/useApi', () => ({
  useApi: vi.fn(),
  apiPost: vi.fn(),
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
}))
vi.mock('../../contexts/DataContext', () => ({ usePortfolioData: () => ({ refetch: vi.fn() }) }))
vi.mock('../../components/GlossarTooltip', () => ({ default: ({ children }) => children }))
vi.mock('../../components/ImportWizard', () => ({ default: () => null }))
vi.mock('../../components/TransactionCreateModal', () => ({ default: () => null }))
vi.mock('../../components/DateInput', () => ({ default: () => null }))

import { useApi } from '../../hooks/useApi'
import { formatCHFExact } from '../../lib/format'
import Transactions from '../Transactions'

const IDLE = { data: null, loading: false, error: null, refetch: vi.fn() }

// Eine Zeile der geladenen Seite: ihre Beträge dürfen in keiner Kachel stehen.
const ITEM = {
  id: 't1', type: 'buy', date: '2026-11-03', ticker: 'AAPL', position_name: 'Apple',
  shares: 1, price_per_share: 111.11, currency: 'CHF', fx_rate_to_chf: 1,
  fees_chf: 1.11, taxes_chf: 0, total_chf: 111.11, notes: null,
}

function page(summary) {
  return { items: [ITEM], total: 240, page: 1, per_page: 50, pages: 5, ...(summary ? { summary } : {}) }
}

function renderPage(data) {
  useApi.mockImplementation((endpoint) => (
    endpoint.startsWith('/transactions?') ? { ...IDLE, data } : IDLE
  ))
  return render(<MemoryRouter><Transactions /></MemoryRouter>)
}

// Wert einer Kachel; «Gebühren» steht auch im Typ-Filter, deshalb über die Label-Klasse.
function tile(label) {
  const el = screen.getAllByText(label).find((n) => n.className.includes('text-text-label'))
  expect(el, `Kachel ${label} fehlt`).toBeTruthy()
  return el.parentElement.textContent
}

beforeEach(() => {
  useApi.mockReset()
})

describe('Transaktionen: Kacheln zeigen die Summen des Filters (K119)', () => {
  it('liest Käufe, Verkäufe, Dividenden und Gebühren aus data.summary', () => {
    renderPage(page({
      total_chf_by_type: { buy: 12345.5, sell: 2000, dividend: 300.25, deposit: 9999 },
      fees_chf: 88.8,
    }))

    expect(tile('Transaktionen')).toContain('240')
    expect(tile('Käufe')).toContain(formatCHFExact(12345.5))
    expect(tile('Verkäufe')).toContain(formatCHFExact(2000))
    expect(tile('Dividenden')).toContain(formatCHFExact(300.25))
    expect(tile('Gebühren')).toContain(formatCHFExact(88.8))
  })

  it('rechnet nicht mehr aus den Zeilen der geladenen Seite', () => {
    renderPage(page({ total_chf_by_type: { buy: 5000 }, fees_chf: 40 }))

    expect(tile('Käufe')).not.toContain(formatCHFExact(ITEM.total_chf))
    expect(tile('Gebühren')).not.toContain(formatCHFExact(ITEM.fees_chf))
  })

  it('zeigt 0 für einen Typ ohne Treffer', () => {
    renderPage(page({ total_chf_by_type: { buy: 5000 }, fees_chf: 0 }))

    expect(tile('Verkäufe')).toContain(formatCHFExact(0))
    expect(tile('Dividenden')).toContain(formatCHFExact(0))
  })

  it('bleibt ohne summary-Feld stehen und zeigt 0', () => {
    renderPage(page(null))

    expect(tile('Käufe')).toContain(formatCHFExact(0))
    expect(tile('Gebühren')).toContain(formatCHFExact(0))
  })
})

describe('Transaktionen: Ticker-Filter im Query-String (K166)', () => {
  it('kodiert Sonderzeichen des Tickers', () => {
    renderPage(page({ total_chf_by_type: {}, fees_chf: 0 }))

    fireEvent.click(screen.getByRole('button', { name: /Filter/ }))
    fireEvent.change(screen.getByLabelText('Ticker filtern'), { target: { value: 'EURUSD=X' } })

    const endpoints = useApi.mock.calls.map(([e]) => e)
    expect(endpoints.some((e) => e.includes('ticker=EURUSD%3DX'))).toBe(true)
    expect(endpoints.some((e) => e.includes('ticker=EURUSD=X'))).toBe(false)
  })
})
