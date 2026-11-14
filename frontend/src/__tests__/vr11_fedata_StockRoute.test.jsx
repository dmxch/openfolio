import { Suspense, useEffect } from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter, Routes, Route, useNavigate, useParams } from 'react-router'

const mounts = vi.hoisted(() => [])

vi.mock('../pages/Dashboard', () => ({ default: () => null }))
vi.mock('../pages/Login', () => ({ default: () => null }))
vi.mock('../components/Layout', () => ({ default: ({ children }) => children }))
// StockRoute lässt neben Markt-Tickern die Ticker eigener Positionen zu
// (R-frontend-2). Hier: Portfolio geladen, keine Position.
vi.mock('../contexts/DataContext', () => ({
  DataProvider: ({ children }) => children,
  usePortfolioData: () => ({ data: { positions: [] }, positions: [], loading: false, error: null }),
}))
vi.mock('../pages/StockDetail', () => ({
  default: function StockDetailStub() {
    const { ticker } = useParams()
    // Zählt Mounts, nicht Renders: ein Remount je Ticker ist der Zweck von key={ticker}.
    useEffect(() => { mounts.push(ticker) }, [])
    return <div data-testid="stock-detail">{ticker}</div>
  },
}))

import { StockRoute } from '../App'

function Go({ to }) {
  const navigate = useNavigate()
  return <button onClick={() => navigate(to)}>go</button>
}

function renderAt(path, extra = null) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      {extra}
      <Suspense fallback={<div>lädt</div>}>
        <Routes>
          <Route path="/stock/:ticker" element={<StockRoute />} />
        </Routes>
      </Suspense>
    </MemoryRouter>
  )
}

beforeEach(() => {
  mounts.length = 0
})

describe('StockRoute: Routen-Ticker prüfen (K166)', () => {
  it.each([
    ['/stock/AAPL', 'AAPL'],
    ['/stock/BRK.B', 'BRK.B'],
    ['/stock/NESN.SW', 'NESN.SW'],
    ['/stock/%5EGSPC', '^GSPC'],
    ['/stock/EURUSD%3DX', 'EURUSD=X'],
    ['/stock/BTC-USD', 'BTC-USD'],
  ])('rendert die Detailseite für %s', async (path, ticker) => {
    renderAt(path)

    expect((await screen.findByTestId('stock-detail')).textContent).toBe(ticker)
  })

  it.each([
    '/stock/..%2F..%2Fauth%2Fsessions',
    '/stock/..%252F..%252Fauth%252Fsessions',
    '/stock/AAPL%3Fx%3D1',
    '/stock/AAPL%23frag',
    '/stock/' + 'A'.repeat(31),
    '/stock/a%20b',
  ])('zeigt 404 für %s', async (path) => {
    renderAt(path)

    expect(await screen.findByText('Seite nicht gefunden')).toBeTruthy()
    expect(screen.queryByTestId('stock-detail')).toBeNull()
    expect(mounts).toEqual([])
  })
})

describe('StockRoute: Ticker-Wechsel mountet die Seite neu (K050)', () => {
  it('mountet beim Wechsel von /stock/AAPL nach /stock/MSFT neu', async () => {
    renderAt('/stock/AAPL', <Go to="/stock/MSFT" />)
    await screen.findByTestId('stock-detail')

    fireEvent.click(screen.getByText('go'))

    expect((await screen.findByTestId('stock-detail')).textContent).toBe('MSFT')
    expect(mounts).toEqual(['AAPL', 'MSFT'])
  })
})
