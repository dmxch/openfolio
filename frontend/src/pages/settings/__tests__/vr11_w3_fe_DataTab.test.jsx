import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'

vi.mock('../../../hooks/useApi', () => ({ authFetch: vi.fn() }))
vi.mock('../../../components/Toast', () => ({ useToast: () => vi.fn() }))
vi.mock('../../../contexts/AuthContext', () => ({ useAuth: () => ({ logout: vi.fn() }) }))
vi.mock('../../../components/ImportWizard', () => ({ default: () => null }))

import { authFetch } from '../../../hooks/useApi'
import DataTab from '../DataTab'

let downloads

beforeEach(() => {
  downloads = []
  authFetch.mockReset()
  authFetch.mockResolvedValue({ ok: true, blob: async () => new Blob(['a;b']) })
  URL.createObjectURL = vi.fn(() => 'blob:test')
  URL.revokeObjectURL = vi.fn()
  // jsdom navigiert bei a.click() nicht; der Dateiname wird am Element abgelesen.
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function click() {
    downloads.push(this.download)
  })
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('Einstellungen > Daten: Dateiname des CSV-Exports (D5)', () => {
  it('nutzt das lokale Datum, auch wenn UTC noch den Vortag zeigt', async () => {
    // Lokale Mitternacht plus 30 Minuten. Liegt die Zeitzone östlich von UTC,
    // nennt toISOString hier noch den 13.; westlich davon den 14. Der lokale
    // Kalendertag ist in jedem Fall der 14.
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date(2026, 10, 14, 0, 30, 0))
    render(<DataTab />)

    fireEvent.click(screen.getByRole('button', { name: 'Transaktionen (CSV)' }))

    await waitFor(() => expect(downloads).toEqual(['openfolio-transactions-2026-11-14.csv']))
    expect(authFetch).toHaveBeenCalledWith('/api/export/transactions')
  })

  it('nutzt das lokale Datum, auch wenn UTC schon den Folgetag zeigt', async () => {
    // Gegenstück für Zeitzonen westlich von UTC: später Abend lokal.
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date(2026, 0, 5, 23, 45, 0))
    render(<DataTab />)

    fireEvent.click(screen.getByRole('button', { name: 'Positionen (CSV)' }))

    await waitFor(() => expect(downloads).toEqual(['openfolio-positions-2026-01-05.csv']))
  })
})
