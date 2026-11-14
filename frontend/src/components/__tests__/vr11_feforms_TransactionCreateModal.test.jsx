import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('../../hooks/useApi', () => ({ authFetch: vi.fn() }))

import { authFetch } from '../../hooks/useApi'
import TransactionCreateModal from '../TransactionCreateModal'

const FX_TODAY = 0.8

// USD-Kauf von 2024: historischer Kurs 0.88, Total inklusive 15 CHF Gebühren.
const USD_BUY = {
  id: 't1',
  position_id: 'p1',
  ticker: 'AAPL',
  position_name: 'Apple',
  type: 'buy',
  date: '2024-03-01',
  shares: 100,
  price_per_share: 100,
  currency: 'USD',
  fx_rate_to_chf: 0.88,
  fees_chf: 15,
  total_chf: 8815,
  notes: '',
}

function fxCalls() {
  return authFetch.mock.calls.map(([url]) => url).filter((url) => url.includes('/api/market/fx/'))
}

function renderEdit(initial = USD_BUY) {
  const onSave = vi.fn().mockResolvedValue(undefined)
  const onClose = vi.fn()
  render(<TransactionCreateModal positions={[]} initial={initial} onSave={onSave} onClose={onClose} />)
  return { onSave, onClose }
}

beforeEach(() => {
  authFetch.mockReset()
  authFetch.mockImplementation(async (url) => {
    if (url.includes('/api/market/fx/')) return { ok: true, json: async () => ({ rate: FX_TODAY }) }
    return { ok: true, json: async () => ({ buckets: [] }) }
  })
})

describe('TransactionCreateModal im Edit-Modus (GF01)', () => {
  it('lädt beim Öffnen keinen Tageskurs und lässt FX und Total stehen', async () => {
    renderEdit()
    // Der Bucket-Abruf läuft beim Öffnen; danach sind alle Effekte durch.
    await waitFor(() => expect(authFetch).toHaveBeenCalledWith('/api/portfolio/buckets'))

    expect(fxCalls()).toEqual([])
    expect(screen.getByLabelText(/FX → CHF/).value).toBe('0.88')
    expect(screen.getByLabelText('Total CHF').value).toBe('8815')
  })

  it('sendet beim Ergänzen einer Notiz nur die Notiz', async () => {
    const { onSave } = renderEdit()
    fireEvent.change(screen.getByLabelText('Notizen'), { target: { value: 'Nachtrag' } })
    fireEvent.click(screen.getByRole('button', { name: 'Speichern' }))

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1))
    expect(onSave).toHaveBeenCalledWith({ notes: 'Nachtrag' })
    expect(fxCalls()).toEqual([])
  })

  it('schliesst ohne Request, wenn nichts geändert wurde', async () => {
    const { onSave, onClose } = renderEdit()
    fireEvent.click(screen.getByRole('button', { name: 'Speichern' }))

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
    expect(onSave).not.toHaveBeenCalled()
  })

  it('lässt bei einem CHF-Kauf die Gebühren im Total', async () => {
    const { onSave } = renderEdit({
      ...USD_BUY, currency: 'CHF', fx_rate_to_chf: 1, total_chf: 10015,
    })
    await waitFor(() => expect(authFetch).toHaveBeenCalled())
    expect(screen.getByLabelText('Total CHF').value).toBe('10015')

    fireEvent.change(screen.getByLabelText('Notizen'), { target: { value: 'x' } })
    fireEvent.click(screen.getByRole('button', { name: 'Speichern' }))
    await waitFor(() => expect(onSave).toHaveBeenCalledWith({ notes: 'x' }))
  })

  it('rechnet das Total neu, wenn der Nutzer die Stückzahl ändert', async () => {
    const { onSave } = renderEdit()
    fireEvent.change(screen.getByLabelText('Anzahl'), { target: { value: '110' } })
    await waitFor(() => expect(screen.getByLabelText('Total CHF').value).toBe('9680.00'))

    fireEvent.click(screen.getByRole('button', { name: 'Speichern' }))
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1))
    // Mit dem gespeicherten Kurs 0.88, nicht mit dem Tageskurs.
    expect(onSave).toHaveBeenCalledWith({ shares: 110, total_chf: 9680 })
    expect(fxCalls()).toEqual([])
  })

  it('stellt das gespeicherte Total wieder her, wenn die Stückzahl zurückgesetzt wird', async () => {
    renderEdit()
    const shares = screen.getByLabelText('Anzahl')
    fireEvent.change(shares, { target: { value: '110' } })
    await waitFor(() => expect(screen.getByLabelText('Total CHF').value).toBe('9680.00'))

    fireEvent.change(shares, { target: { value: '100' } })
    await waitFor(() => expect(screen.getByLabelText('Total CHF').value).toBe('8815'))
  })

  it('lädt den Kurs erst, wenn der Nutzer die Währung wechselt', async () => {
    const { onSave } = renderEdit()
    fireEvent.change(screen.getByLabelText('Währung'), { target: { value: 'EUR' } })

    await waitFor(() => expect(fxCalls()).toEqual(['/api/market/fx/EUR']))
    await waitFor(() => expect(screen.getByLabelText('Total CHF').value).toBe('8000.00'))

    fireEvent.click(screen.getByRole('button', { name: 'Speichern' }))
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1))
    expect(onSave).toHaveBeenCalledWith({ currency: 'EUR', fx_rate_to_chf: FX_TODAY, total_chf: 8000 })
  })

  it('setzt beim Zurückwechseln der Währung den gespeicherten Kurs wieder ein', async () => {
    renderEdit()
    const currency = screen.getByLabelText('Währung')
    fireEvent.change(currency, { target: { value: 'EUR' } })
    await waitFor(() => expect(screen.getByLabelText(/FX → CHF/).value).toBe('0.8'))

    fireEvent.change(currency, { target: { value: 'USD' } })
    await waitFor(() => expect(screen.getByLabelText(/FX → CHF/).value).toBe('0.88'))
    await waitFor(() => expect(screen.getByLabelText('Total CHF').value).toBe('8815'))
    expect(fxCalls()).toEqual(['/api/market/fx/EUR'])
  })
})

describe('TransactionCreateModal im Erstellen-Modus', () => {
  it('lädt den Kurs weiterhin beim Wechsel auf eine Fremdwährung', async () => {
    render(<TransactionCreateModal positions={[]} onSave={vi.fn()} onClose={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Währung'), { target: { value: 'USD' } })

    await waitFor(() => expect(fxCalls()).toEqual(['/api/market/fx/USD']))
    await waitFor(() => expect(screen.getByLabelText(/FX → CHF/).value).toBe('0.8'))
  })
})
