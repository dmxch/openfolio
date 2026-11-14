import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'

vi.mock('../../hooks/useApi', () => ({
  useApi: vi.fn(),
  apiPost: vi.fn(),
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
  authFetch: vi.fn(),
  fetchShared: vi.fn(),
}))
vi.mock('../../contexts/DataContext', () => ({ usePortfolioData: vi.fn() }))
vi.mock('../../hooks/useScrollLock', () => ({ default: () => {} }))
vi.mock('../Toast', () => ({ useToast: () => vi.fn() }))
vi.mock('../GlossarTooltip', () => ({ default: ({ children }) => children }))

import { useApi, apiPut, apiDelete, authFetch, fetchShared } from '../../hooks/useApi'
import { usePortfolioData } from '../../contexts/DataContext'
import { formatDate } from '../../lib/format'
import EtfSectorPanel from '../EtfSectorPanel'
import EpsScannerPanel from '../EpsScannerPanel'
import SmartMoneyPanel from '../SmartMoneyPanel'
import AlertPopover from '../AlertPopover'
import FundamentalCharts from '../FundamentalCharts'
import AllocationCharts from '../AllocationCharts'
import CotMacroPanel from '../CotMacroPanel'
import TickerSearch from '../TickerSearch'
import DividendForecastCard from '../DividendForecastCard'

const IDLE = { data: null, loading: false, error: null, refetch: vi.fn() }

// Antworten je Endpunkt; alles andere liefert "nichts geladen".
function mockApi(byEndpoint = {}) {
  useApi.mockImplementation((endpoint) => ({ ...IDLE, ...(byEndpoint[endpoint] || {}) }))
}

function endpoints() {
  return useApi.mock.calls.map(([e]) => e)
}

beforeEach(() => {
  vi.resetAllMocks()
  mockApi()
  usePortfolioData.mockReturnValue({ data: { positions: [] } })
  authFetch.mockResolvedValue({ ok: false, status: 404, json: async () => ({}) })
  fetchShared.mockResolvedValue({ items: [] })
})
afterEach(cleanup)

describe('Ticker in API-Pfaden und Query-Strings kodieren (K166)', () => {
  it('EtfSectorPanel: Laden, Löschen und Speichern', async () => {
    const weights = { sectors: [{ sector: 'Technology', weight_pct: 100 }], is_complete: true }
    mockApi({ '/etf-sectors/A%26B': { data: weights } })
    render(<EtfSectorPanel ticker="A&B" />)

    expect(endpoints()).toContain('/etf-sectors/A%26B')

    fireEvent.click(screen.getByRole('button', { name: 'Löschen' }))
    await waitFor(() => expect(apiDelete).toHaveBeenCalledWith('/etf-sectors/A%26B'))

    fireEvent.click(screen.getByRole('button', { name: 'Bearbeiten' }))
    fireEvent.click(screen.getByRole('button', { name: 'Speichern' }))
    await waitFor(() => expect(apiPut).toHaveBeenCalledWith('/etf-sectors/A%26B', expect.anything()))
  })

  it('EpsScannerPanel und SmartMoneyPanel', () => {
    render(<><EpsScannerPanel ticker="EURUSD=X" /><SmartMoneyPanel ticker="EURUSD=X" /></>)

    expect(endpoints()).toContain('/eps-scanner/ticker/EURUSD%3DX')
    expect(endpoints()).toContain('/screening/ticker/EURUSD%3DX')
  })

  it('AlertPopover: der Ticker bricht den Query-String nicht', () => {
    render(<AlertPopover ticker="EURUSD=X" currency="USD" onClose={() => {}} />)

    expect(endpoints()).toEqual(expect.arrayContaining(['/price-alerts?ticker=EURUSD%3DX']))
    expect(endpoints()).not.toContain('/price-alerts?ticker=EURUSD=X')
  })

  it('AllocationCharts: Sektorgewichte je ETF', async () => {
    render(<AllocationCharts allocations={null} positions={[{ ticker: 'A&B', is_multi_sector: true }]} />)

    await waitFor(() => expect(authFetch).toHaveBeenCalledWith('/api/etf-sectors/A%26B'))
  })
})

describe('Geteilte Requests statt eigener Abrufe (K068)', () => {
  it('FundamentalCharts: Summary aus dem DataContext, Profil-Pfad wie in der StockScoreCard', () => {
    usePortfolioData.mockReturnValue({ data: { positions: [{ ticker: 'IB01.L', type: 'bond' }] } })
    render(<FundamentalCharts ticker="IB01.L" />)

    expect(endpoints()).not.toContain('/portfolio/summary')
    expect(endpoints()).toContain('/stock/IB01.L/profile')
    // Die Position aus dem Context bestimmt weiterhin den Fonds-Pfad.
    expect(screen.getByText('ETF Holdings & Zusammensetzung')).toBeTruthy()
  })

  it('FundamentalCharts: kodiert den Ticker im Profil-Pfad', () => {
    render(<FundamentalCharts ticker="EURUSD=X" />)

    expect(endpoints()).toContain('/stock/EURUSD%3DX/profile')
  })

  it('AllocationCharts: Bucket-Allokation über fetchShared', async () => {
    render(<AllocationCharts allocations={null} positions={[]} />)

    await waitFor(() => expect(fetchShared).toHaveBeenCalledWith('/portfolio/buckets/allocations'))
    expect(authFetch).not.toHaveBeenCalledWith('/api/portfolio/buckets/allocations')
  })

  it('AllocationCharts: ein HTTP-Fehler von fetchShared bleibt ohne Folgen', async () => {
    fetchShared.mockRejectedValue(new Error('HTTP 500'))
    const { container } = render(<AllocationCharts allocations={null} positions={[]} />)

    await waitFor(() => expect(fetchShared).toHaveBeenCalled())
    expect(container.textContent).toBe('')
  })
})

describe('CotMacroPanel: Hinweis auf veraltete Daten (K145)', () => {
  const row = (code, report_date, stale) => ({
    code, name: `${code} Future`, report_date, stale,
    commercial_net: 100, commercial_net_pct_52w: 50, mm_net: -50, mm_net_pct_52w: 50, oi_total: 1000,
    is_extreme_commercial: false, is_extreme_mm: false,
  })

  function renderPanel(payload) {
    authFetch.mockResolvedValue({ ok: true, status: 200, json: async () => payload })
    return render(<CotMacroPanel />)
  }

  it('nennt im Kopf den letzten Bericht, wenn alle Instrumente veraltet sind', async () => {
    renderPanel({
      stale: true, report_date: '2026-09-01', updated_at: null,
      instruments: [row('GC', '2026-09-01', true), row('SI', '2026-08-25', true)],
    })

    const hint = await screen.findByRole('status')
    expect(hint.textContent).toBe(`Daten veraltet, letzter Bericht vom ${formatDate('2026-09-01')}`)
    expect(hint.className).toContain('text-warning')
    // Das Datum steht im Hinweis, nicht ein zweites Mal daneben.
    expect(screen.queryByText(formatDate('2026-09-01'))).toBeNull()
  })

  it('zeigt bei aktuellen Daten nur das Berichtsdatum', async () => {
    renderPanel({
      stale: false, report_date: '2026-11-03', updated_at: null,
      instruments: [row('GC', '2026-11-03', false)],
    })

    expect(await screen.findByText(formatDate('2026-11-03'))).toBeTruthy()
    expect(screen.queryByRole('status')).toBeNull()
    expect(screen.queryByText(/veraltet/)).toBeNull()
  })

  it('markiert nur die betroffenen Zeilen, wenn einzelne Instrumente zurückhängen', async () => {
    renderPanel({
      stale: true, report_date: '2026-11-03', updated_at: null,
      instruments: [row('GC', '2026-11-03', false), row('SI', '2026-09-01', true), row('HG', null, true)],
    })

    const hint = await screen.findByRole('status')
    expect(hint.textContent).toBe('Daten teilweise veraltet')
    // Das Kopfdatum gilt für die aktuellen Instrumente und bleibt stehen.
    expect(screen.getByText(formatDate('2026-11-03'))).toBeTruthy()
    expect(screen.getByText(`veraltet, Bericht vom ${formatDate('2026-09-01')}`).className).toContain('text-warning')
    expect(screen.getByText('kein Bericht vorhanden')).toBeTruthy()
    expect(screen.getAllByText(/^veraltet, Bericht vom/)).toHaveLength(1)
  })

  it('bleibt ohne jeden Snapshot beim Leertext', async () => {
    renderPanel({
      stale: true, report_date: null, updated_at: null,
      instruments: [row('GC', null, true)],
    })

    expect(await screen.findByText(/Noch keine COT-Snapshots vorhanden/)).toBeTruthy()
    expect(screen.queryByRole('status')).toBeNull()
  })
})

describe('TickerSearch: Länge der Eingabe (D3)', () => {
  it('begrenzt die Eingabe auf die 64 Zeichen der Such-Route', () => {
    render(<TickerSearch value="" onChange={() => {}} />)

    expect(screen.getByRole('textbox').maxLength).toBe(64)
  })
})

describe('DividendForecastCard: Rate-Limit beim Neuberechnen (D4)', () => {
  const refetch = vi.fn()
  const forecast = { has_data: true, forecast_12m_chf: 1200, payer_count: 1, by_holding: [], by_month: [] }

  function renderCard() {
    refetch.mockReset()
    mockApi({ '/analysis/dividend-forecast': { data: forecast, refetch } })
    render(<DividendForecastCard />)
    return screen.getByTitle('Jetzt neu berechnen')
  }

  it('zeigt bei 429 eine Meldung und lädt nicht neu', async () => {
    authFetch.mockResolvedValue({ ok: false, status: 429, json: async () => ({ error: 'Rate limit exceeded' }) })
    const button = renderCard()

    fireEvent.click(button)

    const notice = await screen.findByRole('status')
    expect(notice.textContent).toMatch(/Zu viele Neuberechnungen/)
    expect(notice.textContent).toMatch(/warte eine Minute/)
    expect(notice.className).toContain('text-warning')
    expect(authFetch).toHaveBeenCalledWith('/api/analysis/dividend-forecast/refresh', { method: 'POST' })
    expect(refetch).not.toHaveBeenCalled()
    await waitFor(() => expect(button.disabled).toBe(false))
  })

  it('lädt nach einem erfolgreichen Lauf neu und räumt die Meldung weg', async () => {
    authFetch.mockResolvedValueOnce({ ok: false, status: 429, json: async () => ({}) })
    authFetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => forecast })
    const button = renderCard()

    fireEvent.click(button)
    await screen.findByRole('status')
    await waitFor(() => expect(button.disabled).toBe(false))

    fireEvent.click(button)
    await waitFor(() => expect(refetch).toHaveBeenCalledTimes(1))
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('bleibt bei anderen Fehlern still auf dem letzten Stand', async () => {
    authFetch.mockResolvedValue({ ok: false, status: 500, json: async () => ({}) })
    const button = renderCard()

    fireEvent.click(button)

    await waitFor(() => expect(authFetch).toHaveBeenCalled())
    await waitFor(() => expect(button.disabled).toBe(false))
    expect(screen.queryByRole('status')).toBeNull()
    expect(refetch).not.toHaveBeenCalled()
  })
})
