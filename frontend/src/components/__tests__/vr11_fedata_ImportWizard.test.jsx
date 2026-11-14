import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('../../hooks/useApi', () => ({
  apiPostFormData: vi.fn(),
  apiPost: vi.fn(),
  authFetch: vi.fn(),
}))
vi.mock('../StopLossWizard', () => ({ default: () => null }))

import { apiPostFormData, apiPost, authFetch } from '../../hooks/useApi'
import ImportWizard from '../ImportWizard'

function txn(i) {
  return {
    date: '2024-01-02',
    type: 'buy',
    ticker: `T${i}`,
    name: `Titel ${i}`,
    shares: 1,
    price_per_share: 10,
    currency: 'CHF',
    fx_rate_to_chf: 1,
    fees_chf: 0,
    taxes_chf: 0,
    total_chf: 10,
    suggested_asset_type: 'stock',
    confidence: 1,
  }
}

// Direkte DOM-Abfragen statt getAllByRole/getAllByLabelText: bei 100 Zeilen
// mit je zehn Feldern kostet die Namensauflösung von jsdom sonst Sekunden.
let container

function tickerInputs() {
  return [...container.querySelectorAll('input[aria-label="Ticker"]')]
}

function buttons(label) {
  return [...container.querySelectorAll('button')].filter((b) => b.textContent.trim() === label)
}

function removeButtons() {
  return [...container.querySelectorAll('button[title="Entfernen"]')]
}

// Führt den Wizard bis zur Vorschau (Schritt 4) mit `count` Transaktionen.
async function openPreview(count) {
  apiPostFormData.mockImplementation(async (endpoint) => {
    if (endpoint === '/import/analyze') return { detected_broker: 'swissquote' }
    if (endpoint === '/import/parse') {
      return {
        source_type: 'csv',
        total_rows: count,
        transactions: Array.from({ length: count }, (_, i) => txn(i)),
        new_positions: [],
        warnings: [],
      }
    }
    throw new Error(`unexpected ${endpoint}`)
  })
  container = render(<ImportWizard onClose={vi.fn()} onSuccess={vi.fn()} />).container
  const file = new File(['a;b'], 'export.csv', { type: 'text/csv' })
  fireEvent.change(container.querySelector('input[type="file"]'), { target: { files: [file] } })
  await waitFor(() => expect(tickerInputs().length).toBeGreaterThan(0))
}

function tickers() {
  return tickerInputs().map((input) => input.value)
}

function clickNext() {
  fireEvent.click(buttons('Weiter')[0])
}

beforeEach(() => {
  apiPostFormData.mockReset()
  apiPost.mockReset()
  apiPost.mockResolvedValue({ created_transactions: 0 })
  authFetch.mockReset()
  authFetch.mockResolvedValue({ ok: false })
})

describe('ImportWizard: Vorschau in Seiten (K069)', { timeout: 20_000 }, () => {
  it('rendert höchstens 100 Zeilen auf einmal', async () => {
    await openPreview(250)

    expect(tickers()).toHaveLength(100)
    expect(tickers()[0]).toBe('T0')
    expect(tickers()[99]).toBe('T99')
    expect(screen.getAllByText('Seite 1 von 3')).toHaveLength(2)
  })

  it('blättert und zeigt auf der letzten Seite den Rest', async () => {
    await openPreview(250)

    clickNext()
    expect(tickers()[0]).toBe('T100')
    expect(tickers()).toHaveLength(100)

    clickNext()
    expect(tickers()).toHaveLength(50)
    expect(tickers()[49]).toBe('T249')
    expect(buttons('Weiter')).toHaveLength(2)
    buttons('Weiter').forEach((b) => expect(b.disabled).toBe(true))
  })

  it('ändert auf einer späteren Seite die richtige Zeile und importiert alle', async () => {
    await openPreview(250)
    clickNext()

    fireEvent.change(tickerInputs()[0], { target: { value: 'EDITED' } })
    expect(tickers()[0]).toBe('EDITED')

    fireEvent.click(buttons('250 Transaktionen importieren')[0])
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith('/import/confirm', expect.anything()))

    const payload = apiPost.mock.calls.find(([endpoint]) => endpoint === '/import/confirm')[1]
    expect(payload.transactions).toHaveLength(250)
    expect(payload.transactions[100].ticker).toBe('EDITED')
    expect(payload.transactions[0].ticker).toBe('T0')
  })

  it('entfernt auf einer späteren Seite die richtige Zeile', async () => {
    await openPreview(250)
    clickNext()

    fireEvent.click(removeButtons()[1])

    expect(tickers()[0]).toBe('T100')
    expect(tickers()[1]).toBe('T102')
    expect(buttons('249 Transaktionen importieren')).toHaveLength(1)
  })

  it('fällt auf die letzte vorhandene Seite zurück, wenn die Seite leer wird', async () => {
    await openPreview(101)
    clickNext()
    expect(tickers()).toEqual(['T100'])

    fireEvent.click(removeButtons()[0])

    expect(tickers()).toHaveLength(100)
    expect(tickers()[0]).toBe('T0')
    expect(screen.queryByText(/Seite \d+ von/)).toBeNull()
  })

  it('zeigt bei bis zu 100 Zeilen keine Seitenleiste', async () => {
    await openPreview(100)

    expect(tickers()).toHaveLength(100)
    expect(buttons('Weiter')).toHaveLength(0)
  })
})
