import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('../../hooks/useApi', () => ({ authFetch: vi.fn(), apiPost: vi.fn() }))

import { authFetch, apiPost } from '../../hooks/useApi'
import TransactionModal from '../TransactionModal'

const USD_STOCK = {
  id: 'p1',
  name: 'Apple',
  ticker: 'AAPL',
  type: 'stock',
  shares: 10,
  currency: 'USD',
  price_currency: 'USD',
  current_price: 200,
}

function renderModal(position = USD_STOCK, type = 'buy') {
  const onClose = vi.fn()
  const onSaved = vi.fn()
  render(<TransactionModal position={position} type={type} onClose={onClose} onSaved={onSaved} />)
  return { onClose, onSaved }
}

// Die Tabs oben heissen wie der Speichern-Knopf; der Knopf steht zuletzt.
function submitButton(label) {
  return screen.getAllByRole('button', { name: label }).at(-1)
}

function confirmChecklist() {
  screen.getAllByRole('checkbox').forEach((box) => {
    if (!box.checked) fireEvent.click(box)
  })
}

beforeEach(() => {
  authFetch.mockReset()
  apiPost.mockReset()
  apiPost.mockResolvedValue({})
})

describe('TransactionModal: FX-Kurs für Fremdwährungen (GF03)', () => {
  it('lädt den Kurs der Positionswährung und bucht damit', async () => {
    authFetch.mockResolvedValue({ ok: true, json: async () => ({ rate: 0.8 }) })
    renderModal()

    await waitFor(() => expect(screen.getByLabelText(/FX-Kurs zu CHF/).value).toBe('0.8'))
    expect(authFetch).toHaveBeenCalledWith('/api/market/fx/USD')

    fireEvent.change(screen.getByLabelText(/Anzahl/), { target: { value: '50' } })
    confirmChecklist()
    fireEvent.click(submitButton('Kaufen'))

    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1))
    const [endpoint, payload] = apiPost.mock.calls[0]
    expect(endpoint).toBe('/transactions')
    expect(payload.currency).toBe('USD')
    expect(payload.fx_rate_to_chf).toBe(0.8)
    // 50 × 200 USD × 0.8, nicht 10'000 mit FX 1.
    expect(payload.total_chf).toBe(8000)
  })

  it('sperrt das Speichern, solange der Kurs lädt', async () => {
    authFetch.mockReturnValue(new Promise(() => {}))
    renderModal()

    expect(screen.getByLabelText(/FX-Kurs zu CHF/).value).toBe('')
    fireEvent.change(screen.getByLabelText(/Anzahl/), { target: { value: '50' } })
    confirmChecklist()

    const button = submitButton('Kaufen')
    expect(button.disabled).toBe(true)
    fireEvent.click(button)
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('verlangt den Kurs von Hand, wenn der Abruf scheitert', async () => {
    authFetch.mockResolvedValue({ ok: false, status: 502, json: async () => ({}) })
    renderModal()

    await screen.findByText(/Der Kurs USD\/CHF konnte nicht geladen werden/)
    expect(submitButton('Kaufen').disabled).toBe(true)

    fireEvent.change(screen.getByLabelText(/FX-Kurs zu CHF/), { target: { value: '0.85' } })
    fireEvent.change(screen.getByLabelText(/Anzahl/), { target: { value: '10' } })
    confirmChecklist()
    expect(submitButton('Kaufen').disabled).toBe(false)
    fireEvent.click(submitButton('Kaufen'))

    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1))
    expect(apiPost.mock.calls[0][1].fx_rate_to_chf).toBe(0.85)
    expect(apiPost.mock.calls[0][1].total_chf).toBe(1700)
  })

  it('überschreibt einen von Hand gesetzten Kurs nicht mit dem geladenen', async () => {
    let resolveFx
    authFetch.mockReturnValue(new Promise((resolve) => { resolveFx = resolve }))
    renderModal()

    fireEvent.change(screen.getByLabelText(/FX-Kurs zu CHF/), { target: { value: '0.9' } })
    resolveFx({ ok: true, json: async () => ({ rate: 0.8 }) })

    await waitFor(() => expect(submitButton('Kaufen').disabled).toBe(false))
    expect(screen.getByLabelText(/FX-Kurs zu CHF/).value).toBe('0.9')
  })

  it('lädt für CHF-Positionen keinen Kurs und bucht mit 1', async () => {
    renderModal({ ...USD_STOCK, ticker: 'NESN', currency: 'CHF', price_currency: 'CHF', current_price: 90 })

    expect(authFetch).not.toHaveBeenCalled()
    fireEvent.change(screen.getByLabelText(/Anzahl/), { target: { value: '10' } })
    confirmChecklist()
    fireEvent.click(submitButton('Kaufen'))

    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1))
    expect(apiPost.mock.calls[0][1].fx_rate_to_chf).toBe(1)
    expect(apiPost.mock.calls[0][1].total_chf).toBe(900)
  })

  it('braucht für Einzahlungen auf ein Fremdwährungskonto keinen Kurs', async () => {
    renderModal({ id: 'c1', name: 'USD-Konto', ticker: 'CASH-USD', type: 'cash', currency: 'USD' }, 'deposit')

    expect(authFetch).not.toHaveBeenCalled()
    fireEvent.change(screen.getByLabelText(/Betrag CHF/), { target: { value: '500' } })
    const button = submitButton('Einzahlung buchen')
    expect(button.disabled).toBe(false)
    fireEvent.click(button)

    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1))
    expect(apiPost.mock.calls[0][1]).toMatchObject({ currency: 'CHF', fx_rate_to_chf: 1, total_chf: 500 })
  })
})
