import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

vi.mock('../../hooks/useApi', async (importOriginal) => ({
  ...(await importOriginal()),
  authFetch: vi.fn(),
  authFetchRetry: vi.fn(),
}))
vi.mock('../Toast', () => ({ useToast: () => vi.fn() }))
vi.mock('../MiniChartTooltip', () => ({ default: ({ children }) => children }))
vi.mock('../../contexts/DataContext', () => ({ useWatchlistData: vi.fn() }))

import { authFetch, authFetchRetry } from '../../hooks/useApi'
import { useWatchlistData } from '../../contexts/DataContext'
import PortfolioTable from '../PortfolioTable'
import WatchlistTable from '../WatchlistTable'

const SCORE_URL = '/api/analysis/score/'

function scoreResponse(score = 12) {
  return { ok: true, status: 200, json: async () => ({ score, max_score: 18, criteria: [] }) }
}

// Score-Requests, die erst auf Zuruf antworten.
function pendingScores() {
  const waiting = new Map()
  authFetchRetry.mockImplementation((url) => new Promise((resolve) => {
    waiting.set(url, resolve)
  }))
  return {
    urls: () => [...waiting.keys()],
    resolve: async (ticker, res = scoreResponse()) => {
      const url = SCORE_URL + encodeURIComponent(ticker)
      const resolve = waiting.get(url)
      waiting.delete(url)
      await act(async () => { resolve(res) })
    },
  }
}

function scoreCallsFor(ticker) {
  return authFetchRetry.mock.calls.filter(([url]) => url === SCORE_URL + encodeURIComponent(ticker))
}

function position(ticker, extra = {}) {
  return {
    id: `id-${ticker}`,
    ticker,
    name: `${ticker} AG`,
    type: 'stock',
    shares: 10,
    currency: 'CHF',
    current_price: 100,
    market_value_chf: 1000,
    cost_basis_chf: 900,
    weight_pct: 10,
    pnl_pct: 11.1,
    pnl_chf: 100,
    ...extra,
  }
}

function renderTable(positions) {
  const ui = (list) => (
    <MemoryRouter>
      <PortfolioTable positions={list} />
    </MemoryRouter>
  )
  const view = render(ui(positions))
  return { ...view, rerenderWith: (list) => view.rerender(ui(list)) }
}

beforeEach(() => {
  authFetch.mockReset()
  authFetch.mockResolvedValue({ ok: true, status: 200, json: async () => [] })
  authFetchRetry.mockReset()
})

describe('PortfolioTable: Score-Lauf hängt an der Ticker-Menge (K066)', () => {
  it('startet bei einem neuen positions-Array mit denselben Titeln nicht neu', async () => {
    const scores = pendingScores()
    const list = [position('AAPL'), position('NESN.SW')]
    const view = renderTable(list)
    await waitFor(() => expect(authFetchRetry).toHaveBeenCalledTimes(2))

    // Die Seite reicht bei jedem Render ein neues Array herein.
    view.rerenderWith([...list])
    view.rerenderWith(list.map((p) => ({ ...p })))

    expect(authFetchRetry).toHaveBeenCalledTimes(2)

    // Die Antwort des laufenden Requests kommt trotzdem an.
    await scores.resolve('AAPL', scoreResponse(14))
    await scores.resolve('NESN.SW', scoreResponse(9))
    expect(view.getByText('14/18')).toBeTruthy()
    expect(view.getByText('9/18')).toBeTruthy()
    expect(view.container.querySelector('.animate-spin')).toBeNull()
  })

  it('fragt einen abgelehnten Ticker nicht erneut an', async () => {
    authFetchRetry.mockImplementation(async (url) => (
      url.endsWith('/DELISTED') ? { ok: false, status: 404 } : scoreResponse()
    ))
    const list = [position('AAPL'), position('DELISTED')]
    const view = renderTable(list)
    await waitFor(() => expect(view.getByText('12/18')).toBeTruthy())

    // Neue Ticker-Menge: nur der neue Titel wird geladen.
    view.rerenderWith([...list, position('MSFT')])
    await waitFor(() => expect(scoreCallsFor('MSFT')).toHaveLength(1))

    expect(scoreCallsFor('DELISTED')).toHaveLength(1)
    expect(scoreCallsFor('AAPL')).toHaveLength(1)
  })

  it('lädt bei geänderter Ticker-Menge nur, was fehlt und nicht schon läuft', async () => {
    const scores = pendingScores()
    const list = [position('AAPL'), position('MSFT')]
    const view = renderTable(list)
    await waitFor(() => expect(authFetchRetry).toHaveBeenCalledTimes(2))

    view.rerenderWith([...list, position('NVDA')])
    await waitFor(() => expect(scoreCallsFor('NVDA')).toHaveLength(1))

    expect(scoreCallsFor('AAPL')).toHaveLength(1)
    expect(scoreCallsFor('MSFT')).toHaveLength(1)
    await scores.resolve('AAPL')
    await scores.resolve('MSFT')
    await scores.resolve('NVDA')
    expect(view.container.querySelector('.animate-spin')).toBeNull()
  })

  it('kodiert den Ticker im API-Pfad und nutzt die Wiederholung bei 429/503 (K166, X23)', async () => {
    authFetchRetry.mockResolvedValue(scoreResponse())
    renderTable([position('EURUSD=X')])

    await waitFor(() => expect(authFetchRetry).toHaveBeenCalledWith('/api/analysis/score/EURUSD%3DX'))
    expect(authFetch).not.toHaveBeenCalledWith(expect.stringContaining('/analysis/score/'))
  })

  it('lädt ohne showScores keine Scores', async () => {
    render(
      <MemoryRouter>
        <PortfolioTable positions={[position('IB01', { type: 'bond' })]} showScores={false} />
      </MemoryRouter>
    )
    await act(async () => {})

    expect(authFetchRetry).not.toHaveBeenCalled()
  })
})

describe('WatchlistTable: wartende Scores nach Änderung der Liste (K118)', () => {
  function item(ticker) {
    return { id: `id-${ticker}`, ticker, name: `${ticker} Inc.`, price: 10, currency: 'USD', tags: [] }
  }

  function watchlist(tickers) {
    return { data: { items: tickers.map(item) }, loading: false, error: null, refetch: vi.fn() }
  }

  const ui = () => (
    <MemoryRouter>
      <WatchlistTable />
    </MemoryRouter>
  )

  it('lädt nach einer Änderung auch die Titel, die noch in der Warteschlange standen', async () => {
    const scores = pendingScores()
    useWatchlistData.mockReturnValue(watchlist(['T1', 'T2', 'T3', 'T4', 'T5']))
    const view = render(ui())
    // Drei laufen, T4 und T5 warten mit gesetztem Lade-Flag.
    await waitFor(() => expect(authFetchRetry).toHaveBeenCalledTimes(3))

    useWatchlistData.mockReturnValue(watchlist(['T1', 'T2', 'T3', 'T4', 'T5', 'T6']))
    view.rerender(ui())

    for (const ticker of ['T1', 'T2', 'T3', 'T4', 'T5', 'T6']) {
      await waitFor(() => expect(scoreCallsFor(ticker)).toHaveLength(1))
      await scores.resolve(ticker)
    }

    expect(authFetchRetry).toHaveBeenCalledTimes(6)
    // Kein Titel bleibt im Spinner.
    expect(view.container.querySelector('.animate-spin')).toBeNull()
    expect(view.getAllByText('12/18')).toHaveLength(6)
  })

  it('kodiert den Ticker im API-Pfad und nutzt die Wiederholung bei 429/503 (K166, X23)', async () => {
    authFetchRetry.mockResolvedValue(scoreResponse())
    useWatchlistData.mockReturnValue(watchlist(['^GSPC']))
    render(ui())

    await waitFor(() => expect(authFetchRetry).toHaveBeenCalledWith('/api/analysis/score/%5EGSPC'))
  })

  it('startet bei einer neuen data-Identität mit denselben Titeln nicht neu', async () => {
    const scores = pendingScores()
    useWatchlistData.mockReturnValue(watchlist(['T1', 'T2']))
    const view = render(ui())
    await waitFor(() => expect(authFetchRetry).toHaveBeenCalledTimes(2))

    useWatchlistData.mockReturnValue(watchlist(['T1', 'T2']))
    view.rerender(ui())

    expect(authFetchRetry).toHaveBeenCalledTimes(2)
    await scores.resolve('T1')
    await scores.resolve('T2')
    expect(view.container.querySelector('.animate-spin')).toBeNull()
  })
})
