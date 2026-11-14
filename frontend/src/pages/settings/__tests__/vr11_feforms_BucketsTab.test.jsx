import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const toast = vi.fn()

vi.mock('../../../hooks/useApi', () => ({
  authFetch: vi.fn(),
  useApi: vi.fn(() => ({ data: null, loading: false, error: null, refetch: vi.fn() })),
}))
vi.mock('../../../components/Toast', () => ({ useToast: () => toast }))

import { authFetch } from '../../../hooks/useApi'
import { BucketEditModal } from '../BucketsTab'

const BUCKET = {
  id: 'b1',
  name: 'Satellite',
  kind: 'user',
  color: '#5b8def',
  benchmark: '^GSPC',
  target_pct: 20,
  target_chf: null,
  risk_rules: { drawdown_brake_pct: 8, drawdown_brake_active: true },
}

function respondWith(bucket) {
  authFetch.mockResolvedValue({ ok: true, json: async () => bucket })
}

function renderModal(bucket = BUCKET) {
  const onSaved = vi.fn()
  render(<BucketEditModal bucket={bucket} onClose={vi.fn()} onSaved={onSaved} />)
  return { onSaved }
}

function save() {
  fireEvent.click(screen.getByRole('button', { name: 'Speichern' }))
}

function sentBody() {
  return JSON.parse(authFetch.mock.calls[0][1].body)
}

beforeEach(() => {
  toast.mockReset()
  authFetch.mockReset()
})

describe('BucketEditModal: Benchmark und Ziel entfernen (GF05)', () => {
  it('überträgt «Kein Benchmark» und ein geleertes Ziel ausdrücklich', async () => {
    respondWith({ ...BUCKET, benchmark: null, target_pct: null })
    const { onSaved } = renderModal()
    fireEvent.change(screen.getByLabelText('Benchmark'), { target: { value: '' } })
    fireEvent.change(screen.getByLabelText('Ziel-Allokation'), { target: { value: '' } })
    save()

    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1))
    expect(authFetch.mock.calls[0][0]).toBe('/api/portfolio/buckets/b1')
    expect(authFetch.mock.calls[0][1].method).toBe('PATCH')
    const body = sentBody()
    // Leerer String, nicht null: null liest der Server als «nicht ändern».
    expect(body.benchmark).toBe('')
    expect(body).toHaveProperty('target_pct', null)
    expect(body).toHaveProperty('target_chf', null)
    expect(toast).toHaveBeenCalledWith('Bucket aktualisiert', 'success')
  })

  it('meldet keinen Erfolg, wenn der Server Benchmark und Ziel behält', async () => {
    // Antwort eines Servers, der das Entfernen ignoriert.
    respondWith(BUCKET)
    const { onSaved } = renderModal()
    fireEvent.change(screen.getByLabelText('Benchmark'), { target: { value: '' } })
    fireEvent.change(screen.getByLabelText('Ziel-Allokation'), { target: { value: '' } })
    save()

    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1))
    expect(toast).toHaveBeenCalledTimes(1)
    const [message, type] = toast.mock.calls[0]
    expect(type).toBe('error')
    expect(message).toContain('Benchmark und Ziel-Allokation konnten nicht entfernt werden')
  })

  it('meldet Erfolg, wenn nichts zu entfernen war', async () => {
    respondWith(BUCKET)
    renderModal()
    save()

    await waitFor(() => expect(toast).toHaveBeenCalledWith('Bucket aktualisiert', 'success'))
    const body = sentBody()
    expect(body.benchmark).toBe('^GSPC')
    expect(body.target_pct).toBe(20)
    expect(body.risk_rules.drawdown_brake_pct).toBe(8)
  })
})

describe('BucketEditModal: Schwellwert der Drawdown-Bremse (GF05)', () => {
  it('speichert einen geleerten Schwellwert bei aktiver Bremse nicht als 0', async () => {
    respondWith(BUCKET)
    const { onSaved } = renderModal()
    fireEvent.change(screen.getByLabelText('Schwellwert (%)'), { target: { value: '' } })
    save()

    await waitFor(() => expect(toast).toHaveBeenCalledWith(
      'Bitte einen Schwellwert für die Drawdown-Bremse eingeben', 'error',
    ))
    expect(authFetch).not.toHaveBeenCalled()
    expect(onSaved).not.toHaveBeenCalled()
  })

  it('sendet bei inaktiver Bremse null statt 0', async () => {
    respondWith(BUCKET)
    renderModal()
    fireEvent.change(screen.getByLabelText('Schwellwert (%)'), { target: { value: '' } })
    fireEvent.click(screen.getByRole('switch', { name: 'Drawdown-Bremse aktiv' }))
    save()

    await waitFor(() => expect(authFetch).toHaveBeenCalledTimes(1))
    const rules = sentBody().risk_rules
    expect(rules.drawdown_brake_active).toBe(false)
    expect(rules.drawdown_brake_pct).toBeNull()
  })

  it('lässt eine eingetippte 0 zu', async () => {
    respondWith(BUCKET)
    renderModal()
    fireEvent.change(screen.getByLabelText('Schwellwert (%)'), { target: { value: '0' } })
    save()

    await waitFor(() => expect(authFetch).toHaveBeenCalledTimes(1))
    expect(sentBody().risk_rules.drawdown_brake_pct).toBe(0)
  })
})
