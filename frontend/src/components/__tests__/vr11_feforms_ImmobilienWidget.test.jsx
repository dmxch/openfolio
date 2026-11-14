import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const toast = vi.fn()

vi.mock('../../hooks/useApi', () => ({
  useApi: vi.fn(() => ({ data: null, loading: false, error: null, refetch: vi.fn() })),
  apiPost: vi.fn(),
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
}))
vi.mock('../Toast', () => ({ useToast: () => toast }))

import { apiPost, apiPut } from '../../hooks/useApi'
import { AddPropertyModal, MortgageModal, PropertyEditModal } from '../ImmobilienWidget'

window.scrollTo = vi.fn()

beforeEach(() => {
  toast.mockReset()
  apiPost.mockReset()
  apiPut.mockReset()
  apiPost.mockResolvedValue({})
  apiPut.mockResolvedValue({})
})

function save() {
  fireEvent.click(screen.getByRole('button', { name: 'Speichern' }))
}

describe('Immobilien-Formulare: leere Datumsfelder (GF04)', () => {
  it('sendet beim Anlegen einer Immobilie ohne Kaufdatum null statt leerem String', async () => {
    render(<AddPropertyModal onClose={vi.fn()} onSaved={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'EFH Seeblick' } })
    fireEvent.change(screen.getByLabelText('Kaufpreis CHF'), { target: { value: '900000' } })
    save()

    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1))
    const [endpoint, payload] = apiPost.mock.calls[0]
    expect(endpoint).toBe('/properties')
    expect(payload.purchase_date).toBeNull()
    expect(payload.estimated_value_date).toBeNull()
  })

  it('sendet beim Bearbeiten leere Datumsfelder als null', async () => {
    const property = { id: 'pr1', name: 'EFH', property_type: 'efh', purchase_price: 900000, estimated_value: 950000 }
    render(<PropertyEditModal property={property} onClose={vi.fn()} onSaved={vi.fn()} />)
    save()

    await waitFor(() => expect(apiPut).toHaveBeenCalledTimes(1))
    const [endpoint, payload] = apiPut.mock.calls[0]
    expect(endpoint).toBe('/properties/pr1')
    expect(payload.purchase_date).toBeNull()
    expect(payload.estimated_value_date).toBeNull()
  })

  it('behält ein gesetztes Kaufdatum beim Bearbeiten', async () => {
    const property = {
      id: 'pr1', name: 'EFH', property_type: 'efh', purchase_price: 900000,
      purchase_date: '2015-06-01', estimated_value_date: '2024-01-01',
    }
    render(<PropertyEditModal property={property} onClose={vi.fn()} onSaved={vi.fn()} />)
    save()

    await waitFor(() => expect(apiPut).toHaveBeenCalledTimes(1))
    expect(apiPut.mock.calls[0][1]).toMatchObject({
      purchase_date: '2015-06-01', estimated_value_date: '2024-01-01',
    })
  })

  it('speichert eine SARON-Hypothek ohne Start- und Enddatum', async () => {
    render(<MortgageModal propertyId="pr1" mortgage={null} saronRate={0.25} onClose={vi.fn()} onSaved={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'SARON Tranche' } })
    fireEvent.change(screen.getByLabelText('Typ'), { target: { value: 'saron' } })
    fireEvent.change(screen.getByLabelText('Betrag'), { target: { value: '500000' } })
    fireEvent.change(screen.getByLabelText('Marge %'), { target: { value: '0.8' } })
    save()

    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1))
    const [endpoint, payload] = apiPost.mock.calls[0]
    expect(endpoint).toBe('/properties/pr1/mortgages')
    expect(payload.start_date).toBeNull()
    expect(payload.end_date).toBeNull()
    expect(payload.margin_rate).toBe(0.8)
    expect(payload.interest_rate).toBe(1.05)
  })
})

describe('Hypothek: leere Pflichtfelder (GF07)', () => {
  function fillFixed({ amount = '400000', rate } = {}) {
    render(<MortgageModal propertyId="pr1" mortgage={null} saronRate={0.25} onClose={vi.fn()} onSaved={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Festhypothek' } })
    if (amount !== null) fireEvent.change(screen.getByLabelText('Betrag'), { target: { value: amount } })
    if (rate !== undefined) fireEvent.change(screen.getByLabelText('Zinssatz %'), { target: { value: rate } })
  }

  it('speichert eine Festhypothek ohne Zinssatz nicht als 0 Prozent', async () => {
    fillFixed()
    save()

    await waitFor(() => expect(toast).toHaveBeenCalledWith('Bitte den Zinssatz eingeben', 'error'))
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('lehnt eine SARON-Hypothek ohne Marge ab', async () => {
    fillFixed()
    fireEvent.change(screen.getByLabelText('Typ'), { target: { value: 'saron' } })
    save()

    await waitFor(() => expect(toast).toHaveBeenCalledWith('Bitte die Marge eingeben', 'error'))
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('lehnt einen leeren Betrag ab', async () => {
    fillFixed({ amount: null, rate: '1.5' })
    save()

    await waitFor(() => expect(toast).toHaveBeenCalledWith('Bitte einen Betrag grösser als 0 eingeben', 'error'))
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('lässt einen eingetippten Zinssatz von 0 zu', async () => {
    fillFixed({ rate: '0' })
    save()

    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1))
    expect(apiPost.mock.calls[0][1]).toMatchObject({ amount: 400000, interest_rate: 0, margin_rate: null })
    expect(toast).not.toHaveBeenCalled()
  })

  it('zeigt eine bestehende Hypothek mit 0 Prozent und speichert sie unverändert', async () => {
    const mortgage = { id: 'm1', name: 'Familiendarlehen', type: 'fixed', amount: 100000, interest_rate: 0 }
    render(<MortgageModal propertyId="pr1" mortgage={mortgage} saronRate={0.25} onClose={vi.fn()} onSaved={vi.fn()} />)
    expect(screen.getByLabelText('Zinssatz %').value).toBe('0')
    save()

    await waitFor(() => expect(apiPut).toHaveBeenCalledTimes(1))
    expect(apiPut.mock.calls[0][0]).toBe('/properties/mortgages/m1')
    expect(apiPut.mock.calls[0][1].interest_rate).toBe(0)
  })

  it('speichert per Enter aus einem Eingabefeld', async () => {
    fillFixed({ rate: '1.5' })
    fireEvent.submit(screen.getByLabelText('Betrag').closest('form'))

    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1))
    expect(apiPost.mock.calls[0][1].interest_rate).toBe(1.5)
  })
})
