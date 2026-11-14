import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router'

const state = vi.hoisted(() => ({ mobile: false, scoreCardProps: null }))

vi.mock('../../hooks/useApi', () => ({ useApi: vi.fn(), apiPost: vi.fn(), authFetch: vi.fn() }))
vi.mock('../../hooks/useIsMobile', () => ({ default: () => state.mobile }))
vi.mock('../../contexts/DataContext', () => ({
  usePortfolioData: () => ({ data: { positions: [] } }),
  useWatchlistData: () => ({ data: { items: [] }, refetch: vi.fn() }),
}))
vi.mock('../../components/Toast', () => ({ useToast: () => vi.fn() }))
vi.mock('../../components/TradingViewChart', () => ({ default: () => null }))
vi.mock('../../components/FundamentalCharts', () => ({ default: () => null }))
vi.mock('../../components/EtfSectorPanel', () => ({ default: () => null }))
vi.mock('../../components/DisclaimerBanner', () => ({ default: () => null }))
vi.mock('../../components/SmartMoneyPanel', () => ({ default: () => null }))
vi.mock('../../components/EpsScannerPanel', () => ({ default: () => null }))
vi.mock('../../components/ConcentrationBanner', () => ({ default: () => null }))
vi.mock('../../components/StockScoreCard', () => ({
  default: (props) => {
    state.scoreCardProps = props
    return <div data-testid="score-card" />
  },
}))

import { useApi, authFetch } from '../../hooks/useApi'
import StockDetail from '../StockDetail'

const IDLE = { data: null, loading: false, error: null, refetch: vi.fn() }

function mockScore(score) {
  useApi.mockImplementation((endpoint) => (
    endpoint.startsWith('/analysis/score/') ? { ...IDLE, ...score } : IDLE
  ))
}

function renderAt(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/stock/:ticker" element={<StockDetail />} />
      </Routes>
    </MemoryRouter>
  )
}

beforeEach(() => {
  state.mobile = false
  state.scoreCardProps = null
  useApi.mockReset()
  authFetch.mockReset()
  authFetch.mockResolvedValue({ ok: false, status: 404 })
})

describe('StockDetail: Ticker in API-Pfaden kodiert (K166)', () => {
  it('kodiert den Routen-Ticker in allen eigenen Requests', async () => {
    mockScore({ data: { name: 'EUR/USD', criteria: [] } })
    renderAt('/stock/EURUSD%3DX')

    expect(useApi).toHaveBeenCalledWith('/analysis/score/EURUSD%3DX')
    await waitFor(() => expect(authFetch).toHaveBeenCalledTimes(4))
    const urls = authFetch.mock.calls.map(([url]) => url).sort()
    expect(urls).toEqual([
      '/api/analysis/breakouts/EURUSD%3DX?period=1y',
      '/api/analysis/heartbeat/EURUSD%3DX',
      '/api/analysis/levels/EURUSD%3DX',
      '/api/analysis/reversal/EURUSD%3DX',
    ])
  })
})

describe('StockDetail: Zustand des Score-Requests sichtbar (K050)', () => {
  it('reicht Lade- und Fehlerzustand an die StockScoreCard', () => {
    mockScore({ error: 'HTTP 404' })
    renderAt('/stock/NOPE')

    expect(screen.getByTestId('score-card')).toBeTruthy()
    expect(state.scoreCardProps).toMatchObject({
      ticker: 'NOPE',
      scoreData: null,
      scoreLoading: false,
      scoreError: 'HTTP 404',
    })
  })

  it('zeigt den Fehler auch in der Mobile-Ansicht', () => {
    state.mobile = true
    mockScore({ error: 'HTTP 429' })
    renderAt('/stock/AAPL')

    expect(screen.getByText('Fehler bei Analyse von AAPL: HTTP 429')).toBeTruthy()
  })

  it('zeigt ohne Fehler keine Fehlerbox', () => {
    state.mobile = true
    mockScore({ data: { name: 'Apple Inc.', criteria: [] } })
    renderAt('/stock/AAPL')

    expect(screen.queryByText(/Fehler bei Analyse/)).toBeNull()
    expect(screen.getByText('Apple Inc.')).toBeTruthy()
  })
})
