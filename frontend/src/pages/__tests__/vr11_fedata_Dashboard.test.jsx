import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

vi.mock('../../hooks/useApi', () => ({ useApi: vi.fn(), authFetch: vi.fn() }))
vi.mock('../../hooks/useIsMobile', () => ({ default: () => false }))
vi.mock('../../components/MarketClimate', () => ({ default: ({ data }) => <div data-testid="climate">{data.combined_label}</div> }))
vi.mock('../../components/UpcomingEarningsBanner', () => ({ default: () => <div data-testid="earnings" /> }))
vi.mock('../../components/PendingDividendsWidget', () => ({ default: () => <div data-testid="dividends" /> }))
vi.mock('../../components/CotMacroPanel', () => ({ default: () => <div data-testid="cot" /> }))
vi.mock('../../components/ChMacroCard', () => ({ default: () => <div data-testid="ch-macro" /> }))
vi.mock('../../components/DisclaimerBanner', () => ({ default: () => null }))

import { useApi, authFetch } from '../../hooks/useApi'
import Dashboard from '../Dashboard'

const INDEPENDENT_PANELS = ['earnings', 'dividends', 'cot', 'ch-macro']

function mockClimate(state) {
  useApi.mockImplementation((endpoint) => (
    endpoint === '/market/climate'
      ? { data: null, loading: false, error: null, refetch: vi.fn(), ...state }
      : { data: [], loading: false, error: null, refetch: vi.fn() }
  ))
}

beforeEach(() => {
  useApi.mockReset()
  authFetch.mockReset()
  authFetch.mockResolvedValue({ ok: true })
})

describe('Dashboard: Panels warten nicht auf /market/climate (K136)', () => {
  it('mountet Earnings, Dividenden und Makro-Panels, während das Klima lädt', () => {
    mockClimate({ loading: true })
    render(<Dashboard />)

    INDEPENDENT_PANELS.forEach((id) => expect(screen.getByTestId(id)).toBeTruthy())
    expect(screen.queryByTestId('climate')).toBeNull()
  })

  it('zeigt die Panels auch, wenn das Klima mit einem Fehler antwortet', () => {
    const refetch = vi.fn()
    mockClimate({ error: 'HTTP 429', refetch })
    render(<Dashboard />)

    INDEPENDENT_PANELS.forEach((id) => expect(screen.getByTestId(id)).toBeTruthy())
    expect(screen.getByText('Fehler beim Laden: HTTP 429')).toBeTruthy()
    expect(screen.queryByTestId('climate')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }))
    expect(refetch).toHaveBeenCalledTimes(1)
  })

  it('zeigt Klima und Pill, sobald die Antwort da ist', () => {
    mockClimate({ data: { combined_status: 'green', combined_label: 'Risk-on' } })
    render(<Dashboard />)

    expect(screen.getByTestId('climate').textContent).toBe('Risk-on')
    // Pill im Header und Klima-Block.
    expect(screen.getAllByText('Risk-on')).toHaveLength(2)
    INDEPENDENT_PANELS.forEach((id) => expect(screen.getByTestId(id)).toBeTruthy())
  })
})
