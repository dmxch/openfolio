import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, act } from '@testing-library/react'

vi.mock('../AuthContext', () => ({ useAuth: () => ({ isAuthenticated: true }) }))
vi.mock('../../hooks/useApi', () => ({ authFetch: vi.fn(), fetchShared: vi.fn() }))

import { authFetch, fetchShared } from '../../hooks/useApi'
import { DataProvider, usePortfolioData } from '../DataContext'

const POLL_MS = 65_000

let hidden = false
let summary
let renders = 0

function setHidden(value) {
  hidden = value
  document.dispatchEvent(new Event('visibilitychange'))
}

function Probe() {
  const { data } = usePortfolioData()
  renders += 1
  return <div data-testid="total">{data?.total ?? '–'}</div>
}

function callsTo(endpoint) {
  return fetchShared.mock.calls.filter(([e]) => e === endpoint)
}

async function renderProvider() {
  const view = render(<DataProvider><Probe /></DataProvider>)
  await act(async () => { await vi.advanceTimersByTimeAsync(0) })
  return view
}

beforeEach(() => {
  vi.useFakeTimers()
  hidden = false
  renders = 0
  summary = { total: 100 }
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
  authFetch.mockReset()
  authFetch.mockResolvedValue({ ok: false })
  fetchShared.mockReset()
  // Jede Antwort ist ein neues Objekt, wie nach res.json().
  fetchShared.mockImplementation(async (endpoint) => (
    endpoint === '/portfolio/summary' ? { ...summary } : { items: [] }
  ))
})

afterEach(() => {
  vi.useRealTimers()
  delete document.hidden
})

describe('DataProvider: Poll nur im sichtbaren Tab (K067)', () => {
  it('pollt im sichtbaren Tab alle 65 s mit force', async () => {
    await renderProvider()
    expect(callsTo('/portfolio/summary')).toHaveLength(1)

    await act(async () => { await vi.advanceTimersByTimeAsync(POLL_MS) })

    expect(callsTo('/portfolio/summary')).toHaveLength(2)
    expect(fetchShared).toHaveBeenLastCalledWith('/analysis/watchlist', { force: true })
  })

  it('pausiert im versteckten Tab', async () => {
    await renderProvider()

    await act(async () => { setHidden(true) })
    await act(async () => { await vi.advanceTimersByTimeAsync(10 * POLL_MS) })

    expect(callsTo('/portfolio/summary')).toHaveLength(1)
    expect(callsTo('/analysis/watchlist')).toHaveLength(1)
  })

  it('startet den Poll gar nicht, wenn der Tab versteckt geöffnet wird', async () => {
    hidden = true
    await renderProvider()

    await act(async () => { await vi.advanceTimersByTimeAsync(3 * POLL_MS) })

    // Nur der erste Abruf nach dem Login.
    expect(callsTo('/portfolio/summary')).toHaveLength(1)
  })

  it('lädt beim Sichtbarwerden einmal nach und pollt dann weiter', async () => {
    await renderProvider()
    await act(async () => { setHidden(true) })
    await act(async () => { await vi.advanceTimersByTimeAsync(10 * POLL_MS) })

    await act(async () => { setHidden(false) })
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(callsTo('/portfolio/summary')).toHaveLength(2)
    expect(callsTo('/analysis/watchlist')).toHaveLength(2)

    await act(async () => { await vi.advanceTimersByTimeAsync(POLL_MS) })
    expect(callsTo('/portfolio/summary')).toHaveLength(3)
  })

  it('lädt beim Sichtbarwerden nicht nach, solange die Daten frisch sind', async () => {
    await renderProvider()

    await act(async () => { setHidden(true) })
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000) })
    await act(async () => { setHidden(false) })
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })

    expect(callsTo('/portfolio/summary')).toHaveLength(1)
  })

  it('räumt Listener und Intervall beim Unmount ab', async () => {
    const view = await renderProvider()
    view.unmount()

    await act(async () => { setHidden(false) })
    await act(async () => { await vi.advanceTimersByTimeAsync(3 * POLL_MS) })

    expect(callsTo('/portfolio/summary')).toHaveLength(1)
  })
})

describe('DataProvider: unveränderte Antwort rendert nicht neu (K067)', () => {
  it('behält die Daten-Identität bei gleicher Antwort', async () => {
    const view = await renderProvider()
    expect(view.getByTestId('total').textContent).toBe('100')
    const before = renders

    await act(async () => { await vi.advanceTimersByTimeAsync(POLL_MS) })

    expect(callsTo('/portfolio/summary')).toHaveLength(2)
    expect(renders).toBe(before)
  })

  it('übernimmt eine geänderte Antwort', async () => {
    const view = await renderProvider()

    summary = { total: 250 }
    await act(async () => { await vi.advanceTimersByTimeAsync(POLL_MS) })

    expect(view.getByTestId('total').textContent).toBe('250')
  })
})
