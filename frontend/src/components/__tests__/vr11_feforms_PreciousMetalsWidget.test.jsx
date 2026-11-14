import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const toast = vi.fn()

vi.mock('../../hooks/useApi', () => ({
  useApi: vi.fn(() => ({ data: null, loading: false, error: null, refetch: vi.fn() })),
  apiPost: vi.fn(),
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
  authFetch: vi.fn(),
}))
vi.mock('../Toast', () => ({ useToast: () => toast }))

import { apiPost, apiPut } from '../../hooks/useApi'
import { AddPreciousMetalModal } from '../PreciousMetalsWidget'

window.scrollTo = vi.fn()

beforeEach(() => {
  toast.mockReset()
  apiPost.mockReset()
  apiPut.mockReset()
  apiPost.mockResolvedValue({})
  apiPut.mockResolvedValue({})
})

function renderAdd() {
  const onClose = vi.fn()
  const onSaved = vi.fn()
  render(<AddPreciousMetalModal onClose={onClose} onSaved={onSaved} editItem={null} />)
  return { onClose, onSaved }
}

describe('Edelmetall erfassen: leere Pflichtfelder (GF07)', () => {
  it('speichert einen Barren ohne Kaufpreis nicht mit Einstand 0', async () => {
    renderAdd()
    fireEvent.change(screen.getByLabelText('Gewicht'), { target: { value: '100' } })
    fireEvent.click(screen.getByRole('button', { name: 'Erstellen' }))

    expect((await screen.findByRole('alert')).textContent).toBe('Bitte einen gültigen Kaufpreis eingeben')
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('prüft auch «Erstellen & weiteres Stück»', async () => {
    renderAdd()
    fireEvent.change(screen.getByLabelText('Gewicht'), { target: { value: '100' } })
    fireEvent.click(screen.getByRole('button', { name: /weiteres Stück/ }))

    await screen.findByRole('alert')
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('lehnt ein leeres Gewicht ab', async () => {
    renderAdd()
    fireEvent.change(screen.getByLabelText('Kaufpreis CHF'), { target: { value: '7500' } })
    fireEvent.click(screen.getByRole('button', { name: 'Erstellen' }))

    expect((await screen.findByRole('alert')).textContent).toBe('Bitte ein Gewicht grösser als 0 eingeben')
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('speichert mit Gewicht und Kaufpreis', async () => {
    const { onClose } = renderAdd()
    fireEvent.change(screen.getByLabelText('Gewicht'), { target: { value: '100' } })
    fireEvent.change(screen.getByLabelText('Kaufpreis CHF'), { target: { value: '7500.50' } })
    fireEvent.click(screen.getByRole('button', { name: 'Erstellen' }))

    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1))
    expect(apiPost.mock.calls[0][0]).toBe('/precious-metals')
    expect(apiPost.mock.calls[0][1]).toMatchObject({ weight_grams: 100, purchase_price_chf: 7500.5 })
    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })

  it('lässt einen eingetippten Kaufpreis von 0 zu (Geschenk, Erbe)', async () => {
    renderAdd()
    fireEvent.change(screen.getByLabelText('Gewicht'), { target: { value: '31.1' } })
    fireEvent.change(screen.getByLabelText('Kaufpreis CHF'), { target: { value: '0' } })
    fireEvent.click(screen.getByRole('button', { name: 'Erstellen' }))

    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1))
    expect(apiPost.mock.calls[0][1].purchase_price_chf).toBe(0)
  })

  it('wählt einen Hersteller-Vorschlag, ohne das Formular abzuschicken', async () => {
    renderAdd()
    const manufacturer = screen.getByLabelText('Hersteller')
    fireEvent.focus(manufacturer)
    fireEvent.change(manufacturer, { target: { value: 'Deg' } })
    fireEvent.click(screen.getByRole('button', { name: 'Degussa' }))

    expect(manufacturer.value).toBe('Degussa')
    expect(apiPost).not.toHaveBeenCalled()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('speichert beim Bearbeiten den vorhandenen Einstand', async () => {
    const editItem = {
      id: 'i1', metal_type: 'gold', form: 'bar', weight_grams: 100, fineness: '999.9',
      purchase_date: '2020-05-04', purchase_price_chf: 5400,
    }
    render(<AddPreciousMetalModal onClose={vi.fn()} onSaved={vi.fn()} editItem={editItem} />)
    fireEvent.click(screen.getByRole('button', { name: 'Speichern' }))

    await waitFor(() => expect(apiPut).toHaveBeenCalledTimes(1))
    expect(apiPut.mock.calls[0][0]).toBe('/precious-metals/i1')
    expect(apiPut.mock.calls[0][1]).toMatchObject({ purchase_price_chf: 5400, purchase_date: '2020-05-04' })
  })
})
