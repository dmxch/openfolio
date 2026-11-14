import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'

vi.mock('../../hooks/useApi', () => ({ apiPost: vi.fn() }))
vi.mock('../../hooks/useScrollLock', () => ({ default: () => {} }))

import { apiPost } from '../../hooks/useApi'
import ConfirmDividendModal from '../ConfirmDividendModal'

function pending(exDate) {
  return {
    id: 'pd1', ticker: 'NESN.SW', position_name: 'Nestlé', ex_date: exDate,
    shares_at_ex_date: 10, dividend_per_share: 3, currency: 'CHF', expected_gross_chf: 30,
  }
}

function renderModal(exDate) {
  const onSuccess = vi.fn()
  render(<ConfirmDividendModal pendingDividend={pending(exDate)} onClose={() => {}} onSuccess={onSuccess} />)
  return { onSuccess }
}

const dateField = () => document.getElementById('confirm-div-date')

beforeEach(() => {
  vi.resetAllMocks()
  apiPost.mockResolvedValue({})
  // Nur die Uhr stellen: Timer und Promises laufen echt weiter.
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 10, 14, 12, 0, 0)) // 14.11.2026, Ortszeit
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe('ConfirmDividendModal: Vorschlag für das Buchungsdatum (R-importtx-1)', () => {
  it.each([
    ['2026-11-14', 'Ex-Date heute'],
    ['2026-11-13', 'Ex-Date gestern'],
    ['2026-11-11', 'Ex-Date vor 3 Tagen'],
    ['2026-11-02', 'Ex-Date vor 12 Tagen'],
    ['2026-11-01', 'Ex-Date vor 13 Tagen'],
  ])('schlägt heute vor, solange Ex-Date + 14 Tage in der Zukunft liegt (%s, %s)', (exDate) => {
    renderModal(exDate)

    expect(dateField().value).toBe('14.11.2026')
  })

  it.each([
    ['2026-10-31', '14.11.2026'],
    ['2026-10-15', '29.10.2026'],
    ['2026-03-20', '03.04.2026'],
  ])('schlägt Ex-Date + 14 Tage vor, wenn das Datum nicht in der Zukunft liegt (%s)', (exDate, expected) => {
    renderModal(exDate)

    expect(dateField().value).toBe(expected)
  })

  it('sendet beim Bestätigen des Vorschlags kein Datum in der Zukunft', async () => {
    const { onSuccess } = renderModal('2026-11-11')

    fireEvent.click(screen.getByRole('button', { name: 'Transaktion anlegen' }))

    await waitFor(() => expect(onSuccess).toHaveBeenCalled())
    const [endpoint, payload] = apiPost.mock.calls[0]
    expect(endpoint).toBe('/dividends/pd1/confirm')
    expect(payload.date).toBe('2026-11-14')
    expect(payload.total_chf).toBe(19.5)
  })

  it('lässt das Feld leer, wenn das Ex-Date fehlt', () => {
    renderModal(null)

    expect(dateField().value).toBe('')
  })

  it('nennt die Grenze im Hinweistext', () => {
    renderModal('2026-11-11')

    expect(screen.getByText(/Vorschlag: Ex-Date \+ 2 Wochen, spätestens heute\./)).toBeTruthy()
  })
})
