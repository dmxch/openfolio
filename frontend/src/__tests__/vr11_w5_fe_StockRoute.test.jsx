import { Suspense } from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route, useParams } from 'react-router'

const portfolio = vi.hoisted(() => ({ current: null }))

vi.mock('../pages/Dashboard', () => ({ default: () => null }))
vi.mock('../pages/Login', () => ({ default: () => null }))
vi.mock('../components/Layout', () => ({ default: ({ children }) => children }))
vi.mock('../pages/StockDetail', () => ({
  default: function StockDetailStub() {
    const { ticker } = useParams()
    return <div data-testid="stock-detail">{ticker}</div>
  },
}))
vi.mock('../contexts/DataContext', () => ({
  DataProvider: ({ children }) => children,
  usePortfolioData: () => portfolio.current,
}))

import { StockRoute } from '../App'

const CASH_TICKER = 'CASH_RAIFFEISEN___LOHNKONTO___CHF'

function loaded(tickers) {
  const positions = tickers.map((ticker) => ({ ticker }))
  return { data: { positions }, positions, loading: false, error: null }
}

function tree(path) {
  return (
    <MemoryRouter initialEntries={[path]}>
      <Suspense fallback={<div>lädt</div>}>
        <Routes>
          <Route path="/stock/:ticker" element={<StockRoute />} />
        </Routes>
      </Suspense>
    </MemoryRouter>
  )
}

beforeEach(() => {
  portfolio.current = loaded([])
})

describe('StockRoute: Ticker eigener Positionen (R-frontend-2)', () => {
  it('zeigt die Detailseite für ein eigenes Cash-Konto mit 33 Zeichen', async () => {
    expect(CASH_TICKER.length).toBe(33)
    portfolio.current = loaded(['AAPL', CASH_TICKER])

    render(tree(`/stock/${encodeURIComponent(CASH_TICKER)}`))

    expect((await screen.findByTestId('stock-detail')).textContent).toBe(CASH_TICKER)
  })

  it('zeigt die Detailseite für eine eigene Altposition mit Leerzeichen im Ticker', async () => {
    portfolio.current = loaded(['ROCHE GS'])

    render(tree(`/stock/${encodeURIComponent('ROCHE GS')}`))

    expect((await screen.findByTestId('stock-detail')).textContent).toBe('ROCHE GS')
  })

  it('zeigt die Detailseite für einen eigenen Ticker mit 60 Zeichen', async () => {
    const ticker = 'CASH_' + 'X'.repeat(55)
    portfolio.current = loaded([ticker])

    render(tree(`/stock/${ticker}`))

    expect((await screen.findByTestId('stock-detail')).textContent).toBe(ticker)
  })

  it('zeigt 404 für denselben langen Ticker, wenn er keine eigene Position ist', async () => {
    portfolio.current = loaded(['AAPL'])

    render(tree(`/stock/${encodeURIComponent(CASH_TICKER)}`))

    expect(await screen.findByText('Seite nicht gefunden')).toBeTruthy()
    expect(screen.queryByTestId('stock-detail')).toBeNull()
  })

  it('wartet beim direkten Aufruf auf die Positionen, statt 404 zu zeigen', async () => {
    portfolio.current = { data: null, positions: [], loading: true, error: null }
    const path = `/stock/${encodeURIComponent(CASH_TICKER)}`

    const { rerender } = render(tree(path))

    expect(await screen.findByText('Lade...')).toBeTruthy()
    expect(screen.queryByText('Seite nicht gefunden')).toBeNull()
    expect(screen.queryByTestId('stock-detail')).toBeNull()

    portfolio.current = loaded([CASH_TICKER])
    rerender(tree(path))

    expect((await screen.findByTestId('stock-detail')).textContent).toBe(CASH_TICKER)
  })

  it('zeigt 404, wenn das Portfolio nicht geladen werden konnte', async () => {
    portfolio.current = { data: null, positions: [], loading: false, error: 'HTTP 502' }

    render(tree(`/stock/${encodeURIComponent(CASH_TICKER)}`))

    expect(await screen.findByText('Seite nicht gefunden')).toBeTruthy()
  })
})

describe('StockRoute: eigene Ticker ändern keinen API-Pfad (K166)', () => {
  it.each([
    ['../../auth/sessions', '/stock/..%2F..%2Fauth%2Fsessions'],
    ['A/B', '/stock/A%2FB'],
    ['A\\B', '/stock/A%5CB'],
    ['AAPL?x=1', '/stock/AAPL%3Fx%3D1'],
    ['AAPL#frag', '/stock/AAPL%23frag'],
    ['X'.repeat(61), '/stock/' + 'X'.repeat(61)],
  ])('zeigt 404 für den eigenen Ticker %s', async (ticker, path) => {
    portfolio.current = loaded([ticker])

    render(tree(path))

    expect(await screen.findByText('Seite nicht gefunden')).toBeTruthy()
    expect(screen.queryByTestId('stock-detail')).toBeNull()
  })

  it('wartet bei einem pfadverändernden Ticker nicht auf die Positionen', async () => {
    portfolio.current = { data: null, positions: [], loading: true, error: null }

    render(tree('/stock/..%2F..%2Fauth%2Fsessions'))

    expect(await screen.findByText('Seite nicht gefunden')).toBeTruthy()
  })
})
