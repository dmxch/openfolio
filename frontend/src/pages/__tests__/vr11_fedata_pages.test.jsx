import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

const seen = vi.hoisted(() => ({ tables: [], bucketBars: [], factorCards: [] }))

vi.mock('../../hooks/useApi', () => ({ useApi: vi.fn(), apiDelete: vi.fn(), authFetch: vi.fn() }))
vi.mock('../../hooks/useIsMobile', () => ({ default: () => false }))
vi.mock('../../contexts/DataContext', () => ({ usePortfolioData: () => ({ refetch: vi.fn() }) }))
vi.mock('../../components/Toast', () => ({ useToast: () => vi.fn() }))
vi.mock('../../components/GlossarTooltip', () => ({ default: ({ children }) => children }))

// Portfolio: nur die Tabelle interessiert, der Rest ist Beiwerk.
vi.mock('../../components/PortfolioTable', () => ({
  default: (props) => {
    seen.tables.push(props)
    return null
  },
}))
vi.mock('../../components/ImmobilienWidget', () => ({ default: () => null }))
vi.mock('../../components/PreciousMetalsWidget', () => ({ default: () => null }))
vi.mock('../../components/CryptoWidget', () => ({ default: () => null }))
vi.mock('../../components/PrivateEquityWidget', () => ({ default: () => null }))
vi.mock('../../components/AlertsBanner', () => ({ default: () => null, notifyAlertsChanged: vi.fn() }))
vi.mock('../../components/OnboardingChecklist', () => ({ default: () => null }))
vi.mock('../../components/EditPositionModal', () => ({ default: () => null }))
vi.mock('../../components/AddPositionModal', () => ({ default: () => null }))
vi.mock('../../components/TransactionModal', () => ({ default: () => null }))
vi.mock('../../components/StopLossModal', () => ({ default: () => null }))
vi.mock('../../components/ContextMenu', () => ({ default: () => null }))
vi.mock('../../components/RecalculateButton', () => ({ default: () => null }))
vi.mock('../../components/DeleteConfirm', () => ({ default: () => null }))

// Performance: BucketComparisonBar und FactorExposureCard halten ihre Props fest.
vi.mock('../../components/BucketComparisonBar', () => ({
  default: (props) => {
    seen.bucketBars.push(props)
    return null
  },
}))
vi.mock('../../components/FactorExposureCard', () => ({
  default: (props) => {
    seen.factorCards.push(props)
    return null
  },
}))
vi.mock('../../components/PerformanceChart', () => ({
  default: () => null,
  PERIODS: [{ label: '1M' }, { label: '3M' }, { label: '6M' }, { label: 'YTD' }, { label: '1Y' }, { label: 'ALL' }],
  BASE_BENCHMARKS: [{ value: '^GSPC', label: 'S&P 500' }],
}))
vi.mock('../../components/PerformanceCard', () => ({ default: () => null }))
vi.mock('../../components/RiskMetricsPanel', () => ({ default: () => null }))
vi.mock('../../components/AlphaValue', () => ({ default: () => null }))
vi.mock('../../components/AllocationDonutCard', () => ({ default: () => null }))
vi.mock('../../components/TopConcentrationCard', () => ({ default: () => null }))
vi.mock('../../components/ReturnContributionCard', () => ({ default: () => null }))
vi.mock('../../components/RollingDrawdownCard', () => ({ default: () => null }))
vi.mock('../../components/AllocationCharts', () => ({ default: () => null }))
vi.mock('../../components/HhiCard', () => ({ default: () => null }))
vi.mock('../../components/EtfCountryLookthroughCard', () => ({ default: () => null }))
vi.mock('../../components/RebalancingCard', () => ({ default: () => null }))
vi.mock('../../components/PositionRebalancingCard', () => ({ default: () => null }))
vi.mock('../../components/DividendYocCard', () => ({ default: () => null }))
vi.mock('../../components/DividendForecastCard', () => ({ default: () => null }))
vi.mock('../../components/NetWorthCard', () => ({ default: () => null }))
vi.mock('../../components/FireProjectionCard', () => ({ default: () => null }))
vi.mock('../../components/MonthlyHeatmap', () => ({ default: () => null }))
vi.mock('../../components/TopMovers', () => ({ default: () => null }))
vi.mock('../../components/RealizedGainsTable', () => ({ default: () => null }))
vi.mock('../../components/FeeSummary', () => ({ default: () => null }))
vi.mock('../../components/BucketSection', () => ({ default: () => null }))
vi.mock('../../components/BucketCorrelationCard', () => ({ default: () => null }))

import { useApi } from '../../hooks/useApi'
import Portfolio from '../Portfolio'
import Performance from '../Performance'

const IDLE = { data: null, loading: false, error: null, refetch: vi.fn() }

function pos(ticker, type, extra = {}) {
  return {
    id: `id-${ticker}`, ticker, name: ticker, type, shares: 1, currency: 'CHF',
    market_value_chf: 100, cost_basis_chf: 90, pnl_chf: 10, pnl_pct: 11, weight_pct: 10, ...extra,
  }
}

const SUMMARY = {
  total_market_value_chf: 400,
  total_fees_chf: 0,
  allocations: { by_type: [] },
  positions: [pos('AAPL', 'stock'), pos('VT', 'etf'), pos('IB01', 'bond'), pos('CHF', 'cash')],
}
const BUCKETS = { buckets: [{ id: 'b1', name: 'Core', kind: 'user' }] }
const ALLOCATIONS = { items: [{ bucket_id: 'b1', value_chf: 200, pct: 50 }] }
const TOTAL_RETURN = { ytd_pct: 5, total_return_pct: 10 }
const FACTORS = { factors: { SPY: { beta: 0.9, t_stat: 12 } }, alpha: null }

const RESPONSES = {
  '/portfolio/summary': SUMMARY,
  '/portfolio/buckets': BUCKETS,
  '/portfolio/buckets/allocations': ALLOCATIONS,
  '/portfolio/total-return': TOTAL_RETURN,
  '/analysis/factor-decomposition': FACTORS,
}

beforeEach(() => {
  seen.tables.length = 0
  seen.bucketBars.length = 0
  seen.factorCards.length = 0
  useApi.mockReset()
  // Dieselben Objekte bei jedem Render — wie der Hook zwischen zwei Antworten.
  useApi.mockImplementation((endpoint, options = {}) => (
    options.skip ? IDLE : { ...IDLE, data: RESPONSES[endpoint] ?? null }
  ))
})

describe('Portfolio: stabile Positions-Arrays für die Tabellen (K066)', () => {
  it('reicht bei erneutem Render dieselben Arrays weiter', () => {
    const ui = <MemoryRouter><Portfolio /></MemoryRouter>
    const view = render(ui)
    const first = seen.tables.slice()
    expect(first.map((p) => p.positions.map((x) => x.ticker))).toEqual([['AAPL', 'VT'], ['IB01']])

    seen.tables.length = 0
    view.rerender(<MemoryRouter><Portfolio /></MemoryRouter>)

    expect(seen.tables).toHaveLength(2)
    expect(seen.tables[0].positions).toBe(first[0].positions)
    expect(seen.tables[1].positions).toBe(first[1].positions)
  })
})

describe('Performance: geladene Daten gehen als Props an die Karten (K068)', () => {
  it('reicht Buckets, Allokation, Summary und Total-Return an die BucketComparisonBar', () => {
    render(<Performance />)

    expect(seen.bucketBars.length).toBeGreaterThan(0)
    expect(seen.bucketBars.at(-1)).toMatchObject({
      buckets: BUCKETS,
      allocations: ALLOCATIONS,
      summary: SUMMARY,
      totalReturn: TOTAL_RETURN,
    })
  })

  it('reicht die Faktor-Regression an die FactorExposureCard', () => {
    render(<Performance />)

    expect(seen.factorCards.length).toBeGreaterThan(0)
    expect(seen.factorCards.at(-1)).toMatchObject({ data: FACTORS, loading: false, error: null })
  })
})
