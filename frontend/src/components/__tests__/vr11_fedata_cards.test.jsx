import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('../../hooks/useApi', () => ({ useApi: vi.fn(), apiPost: vi.fn() }))
vi.mock('../../contexts/DataContext', () => ({ useWatchlistData: vi.fn() }))
vi.mock('../Toast', () => ({ useToast: () => vi.fn() }))

import { useApi } from '../../hooks/useApi'
import { useWatchlistData } from '../../contexts/DataContext'
import StockScoreCard from '../StockScoreCard'
import BucketComparisonBar from '../BucketComparisonBar'
import FactorExposureCard from '../FactorExposureCard'
import TickerLogo from '../TickerLogo'

const IDLE = { data: null, loading: false, error: null, refetch: vi.fn() }

// Antworten je Endpunkt; alles andere liefert "nichts geladen".
function mockApi(byEndpoint = {}) {
  useApi.mockImplementation((endpoint, options = {}) => (
    options.skip ? IDLE : { ...IDLE, ...(byEndpoint[endpoint] || {}) }
  ))
}

function optionsFor(endpoint) {
  const call = useApi.mock.calls.find(([e]) => e === endpoint)
  expect(call, `useApi(${endpoint}) nicht aufgerufen`).toBeTruthy()
  return call[1] || {}
}

const SCORE = {
  name: 'Apple Inc.',
  sector: 'Technology',
  price: 200,
  currency: 'USD',
  score: 12,
  max_score: 18,
  signal: 'WATCHLIST',
  signal_label: 'Warten auf Breakout',
  criteria: [],
  alerts: [],
}

beforeEach(() => {
  useApi.mockReset()
  mockApi()
  useWatchlistData.mockReset()
  useWatchlistData.mockReturnValue({ data: { items: [] }, refetch: vi.fn() })
})

describe('StockScoreCard: Score der Seite statt eigenem Request (K050, K068)', () => {
  it('lädt den Score nicht selbst, solange die Seite ihn lädt', () => {
    render(<StockScoreCard ticker="AAPL" scoreData={null} scoreLoading scoreError={null} />)

    expect(optionsFor('/analysis/score/AAPL').skip).toBe(true)
    expect(screen.getByText(/Kriterien werden geprüft/)).toBeTruthy()
  })

  it('zeigt den Fehler des Score-Requests der Seite', () => {
    render(<StockScoreCard ticker="AAPL" scoreData={null} scoreLoading={false} scoreError="HTTP 404" />)

    expect(screen.getByText('Fehler bei Analyse von AAPL: HTTP 404')).toBeTruthy()
    expect(screen.queryByText('Kauf-Checkliste')).toBeNull()
  })

  it('rendert die Checkliste aus den Daten der Seite', () => {
    render(<StockScoreCard ticker="AAPL" scoreData={SCORE} scoreLoading={false} scoreError={null} />)

    expect(screen.getByText('Kauf-Checkliste')).toBeTruthy()
    expect(optionsFor('/analysis/score/AAPL').skip).toBe(true)
  })

  it('lädt ohne scoreData-Prop weiterhin selbst', () => {
    mockApi({ '/analysis/score/AAPL': { data: SCORE } })
    render(<StockScoreCard ticker="AAPL" />)

    expect(optionsFor('/analysis/score/AAPL').skip).toBe(false)
    expect(screen.getByText('Kauf-Checkliste')).toBeTruthy()
  })

  it('liest die Watchlist aus dem DataContext statt sie selbst zu laden', () => {
    useWatchlistData.mockReturnValue({ data: { items: [{ ticker: 'AAPL' }] }, refetch: vi.fn() })
    render(<StockScoreCard ticker="AAPL" scoreData={SCORE} />)

    expect(useApi.mock.calls.some(([e]) => e === '/analysis/watchlist')).toBe(false)
    expect(screen.getByText('In Watchlist')).toBeTruthy()
  })

  it('kodiert den Ticker in den API-Pfaden (K166)', () => {
    render(<StockScoreCard ticker="EURUSD=X" />)

    const endpoints = useApi.mock.calls.map(([e]) => e)
    expect(endpoints).toContain('/analysis/score/EURUSD%3DX')
    expect(endpoints).toContain('/stock/EURUSD%3DX/profile')
  })
})

describe('BucketComparisonBar: Daten der Seite statt eigener Requests (K068)', () => {
  const PAGE_DATA = {
    buckets: { buckets: [{ id: 'b1', name: 'Core', kind: 'user', color: '#5b8def' }] },
    allocations: { items: [{ bucket_id: 'b1', value_chf: 1000, pct: 50 }] },
    summary: { total_market_value_chf: 2000 },
    totalReturn: { ytd_pct: 5, total_return_pct: 10 },
  }
  const PAGE_ENDPOINTS = [
    '/portfolio/buckets',
    '/portfolio/buckets/allocations',
    '/portfolio/summary',
    '/portfolio/total-return',
  ]

  it('lädt mit Props keinen der vier Seiten-Endpunkte', () => {
    render(<BucketComparisonBar {...PAGE_DATA} />)

    PAGE_ENDPOINTS.forEach((endpoint) => expect(optionsFor(endpoint).skip).toBe(true))
    expect(screen.getByText('Core')).toBeTruthy()
    expect(screen.getByText('Total')).toBeTruthy()
  })

  it('lädt auch dann nicht, wenn total-return der Seite noch aussteht', () => {
    render(<BucketComparisonBar {...PAGE_DATA} totalReturn={null} />)

    expect(optionsFor('/portfolio/total-return').skip).toBe(true)
    expect(screen.getByText('Core')).toBeTruthy()
  })

  it('lädt ohne Props weiterhin selbst', () => {
    mockApi({
      '/portfolio/buckets': { data: PAGE_DATA.buckets },
      '/portfolio/buckets/allocations': { data: PAGE_DATA.allocations },
    })
    render(<BucketComparisonBar />)

    PAGE_ENDPOINTS.forEach((endpoint) => expect(optionsFor(endpoint).skip).toBe(false))
    expect(screen.getByText('Core')).toBeTruthy()
  })
})

describe('FactorExposureCard: Daten der Seite statt eigenem Request (K068)', () => {
  const FACTORS = { factors: { SPY: { beta: 0.9, t_stat: 12 } }, missing_factors: [] }

  it('lädt mit data-Prop nicht selbst und zeigt die Betas', () => {
    render(<FactorExposureCard data={FACTORS} loading={false} error={null} />)

    expect(optionsFor('/analysis/factor-decomposition').skip).toBe(true)
    expect(screen.getByText('Markt')).toBeTruthy()
  })

  it('zeigt den Ladezustand der Seite', () => {
    const { container } = render(<FactorExposureCard data={null} loading error={null} />)

    expect(container.querySelector('.animate-pulse')).toBeTruthy()
    expect(optionsFor('/analysis/factor-decomposition').skip).toBe(true)
  })

  it('unterscheidet den Fehler der Seite', () => {
    const { rerender } = render(<FactorExposureCard data={null} loading={false} error="HTTP 503" />)
    expect(screen.getByText('Faktordaten momentan nicht abrufbar.')).toBeTruthy()

    rerender(<FactorExposureCard data={null} loading={false} error="HTTP 422" />)
    expect(screen.getByText(/Zu wenig Historie/)).toBeTruthy()
  })

  it('lädt die Bucket-Variante weiterhin selbst', () => {
    mockApi({ '/analysis/factor-decomposition?bucket_id=b1': { data: FACTORS } })
    render(<FactorExposureCard bucketId="b1" />)

    expect(optionsFor('/analysis/factor-decomposition?bucket_id=b1').skip).toBe(false)
    expect(screen.getByText('Markt')).toBeTruthy()
  })
})

describe('TickerLogo: kein Referrer an das Logo-CDN (K167)', () => {
  it('setzt referrerpolicy=no-referrer', () => {
    const { container } = render(<TickerLogo ticker="AAPL" />)

    expect(container.querySelector('img').getAttribute('referrerpolicy')).toBe('no-referrer')
  })
})
