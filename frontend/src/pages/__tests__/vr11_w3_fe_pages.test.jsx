import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

vi.mock('../../hooks/useApi', () => ({ useApi: vi.fn() }))
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ register: vi.fn() }) }))
vi.mock('../../components/EpsThresholdSettings', () => ({ default: () => null }))
vi.mock('../../components/EpsTable', () => ({ default: () => null }))
vi.mock('../../components/EpsDetailModal', () => ({ default: () => null }))
vi.mock('../../components/SmartMoneyPagination', () => ({ default: () => null }))

import { useApi } from '../../hooks/useApi'
import EpsScanner from '../EpsScanner'
import Register from '../Register'

const RESULTS = { data: { results: [], total: 0 }, loading: false, error: null, refetch: vi.fn() }

// Alle Suchbegriffe, mit denen die Ergebnisliste bisher abgefragt wurde.
function searchedTerms() {
  return useApi.mock.calls
    .map(([endpoint]) => new URLSearchParams(endpoint.split('?')[1]).get('search'))
    .filter((term) => term !== null)
}

beforeEach(() => {
  useApi.mockReset()
  useApi.mockReturnValue(RESULTS)
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

// Die Seite fragt je Wert von filters.search einmal ab. Das Suchfeld
// (EpsFilters) schreibt diesen Wert erst 300 ms nach dem letzten Tastendruck.
describe('EPS-Scanner: Suche löst nicht je Tastendruck einen Request aus (D2)', () => {
  it('fragt erst nach der Tipp-Pause ab, und nur mit dem letzten Begriff', () => {
    vi.useFakeTimers()
    render(<MemoryRouter><EpsScanner /></MemoryRouter>)
    const input = screen.getByLabelText('Suche nach Ticker oder Name')

    for (const value of ['N', 'NV', 'NVD', 'NVDA']) {
      fireEvent.change(input, { target: { value } })
      act(() => { vi.advanceTimersByTime(100) })
    }
    expect(searchedTerms()).toEqual([])

    act(() => { vi.advanceTimersByTime(199) })
    expect(searchedTerms()).toEqual([])

    act(() => { vi.advanceTimersByTime(1) })
    expect(new Set(searchedTerms())).toEqual(new Set(['NVDA']))
  })

  it('sucht beim Deep-Link ?search= sofort', () => {
    render(<MemoryRouter initialEntries={['/eps-scanner?search=NVDA']}><EpsScanner /></MemoryRouter>)

    expect(searchedTerms()[0]).toBe('NVDA')
  })
})

describe('Register: Einladungscode bleibt, wie er eingegeben wurde (K088)', () => {
  it('wandelt die Eingabe nicht in Grossbuchstaben um', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ json: async () => ({ mode: 'invite_only' }) }))
    render(<MemoryRouter><Register /></MemoryRouter>)
    const input = await screen.findByLabelText('Einladungscode')

    fireEvent.change(input, { target: { value: 'OF-aB3dEf9hJk2mNp4q' } })

    expect(input.value).toBe('OF-aB3dEf9hJk2mNp4q')
    // Auch keine Darstellung in Versalien: der Code wäre sonst nicht prüfbar.
    expect(input.className).not.toMatch(/\buppercase\b/)
  })
})
