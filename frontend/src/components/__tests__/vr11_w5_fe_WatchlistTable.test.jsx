import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

const refetch = vi.hoisted(() => vi.fn())

vi.mock('../../hooks/useApi', () => ({
  apiPost: vi.fn(), apiDelete: vi.fn(), authFetch: vi.fn(), authFetchRetry: vi.fn(),
}))
vi.mock('../../contexts/DataContext', () => ({
  useWatchlistData: () => ({ data: { items: [] }, loading: false, error: null, refetch }),
}))
vi.mock('../TickerSearch', () => ({
  default: ({ value, onChange }) => (
    <input aria-label="Ticker" value={value} onChange={(e) => onChange(e.target.value)} />
  ),
}))

import { apiPost, authFetch } from '../../hooks/useApi'
import WatchlistTable from '../WatchlistTable'

// So meldet apiPost den 422 der API: Pydantic-Text aus detail[].msg.
const PATTERN_422 = "String should match pattern '^[A-Za-z0-9.^=&_-]{1,30}$'"

function openForm() {
  render(<MemoryRouter><WatchlistTable /></MemoryRouter>)
  fireEvent.click(screen.getByText('Erste Aktie hinzufügen'))
}

function submit(ticker) {
  fireEvent.change(screen.getByLabelText('Ticker'), { target: { value: ticker } })
  fireEvent.click(screen.getByRole('button', { name: 'Hinzufügen' }))
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.spyOn(console, 'error').mockImplementation(() => {})
  authFetch.mockResolvedValue({ ok: true, status: 200, json: async () => [] })
  apiPost.mockResolvedValue({})
})
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('WatchlistTable: Ticker hinzufügen (R-yfanalysis-5)', () => {
  it('schneidet Rand-Leerzeichen ab, bevor der Ticker gesendet wird', async () => {
    openForm()

    submit(' aapl ')

    await waitFor(() => expect(refetch).toHaveBeenCalled())
    expect(apiPost).toHaveBeenCalledWith('/analysis/watchlist', { ticker: 'AAPL', name: 'AAPL', sector: null })
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('zeigt bei 422 wegen des Ticker-Musters eine verständliche Meldung', async () => {
    apiPost.mockRejectedValue(new Error(PATTERN_422))
    openForm()

    submit('Roche Holding')

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('Ticker darf keine Leerzeichen oder Kommas enthalten')
    expect(alert.textContent).not.toContain('should match pattern')
    // Das Formular bleibt offen, die Eingabe bleibt stehen.
    expect(screen.getByLabelText('Ticker').value).toBe('Roche Holding')
    expect(refetch).not.toHaveBeenCalled()
  })

  it('zeigt andere Fehler der API im Wortlaut', async () => {
    apiPost.mockRejectedValue(new Error('Watchlist-Limit erreicht (max. 200 Einträge)'))
    openForm()

    submit('MSFT')

    expect((await screen.findByRole('alert')).textContent).toBe('Watchlist-Limit erreicht (max. 200 Einträge)')
  })

  it('räumt die Meldung beim nächsten erfolgreichen Versuch weg', async () => {
    apiPost.mockRejectedValueOnce(new Error(PATTERN_422))
    openForm()
    submit('AAPL,MSFT')
    await screen.findByRole('alert')

    submit('AAPL')

    await waitFor(() => expect(refetch).toHaveBeenCalled())
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
