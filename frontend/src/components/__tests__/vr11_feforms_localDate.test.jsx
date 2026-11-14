import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

// Festes «lokales Heute», das vom echten Datum abweicht: Ein Formular, das
// noch toISOString() nutzt, zeigt das echte (UTC-)Datum und fällt auf.
const LOCAL_TODAY = '2031-02-03'
const LOCAL_TODAY_DISPLAY = '03.02.2031'

vi.mock('../../lib/format', async (importOriginal) => ({
  ...(await importOriginal()),
  localDateStr: () => LOCAL_TODAY,
}))
vi.mock('../../hooks/useApi', () => ({
  useApi: vi.fn(() => ({ data: null, loading: false, error: null, refetch: vi.fn() })),
  authFetch: vi.fn(),
  apiPost: vi.fn(),
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
}))
vi.mock('../Toast', () => ({ useToast: () => vi.fn() }))

import { authFetch } from '../../hooks/useApi'
import TransactionModal from '../TransactionModal'
import TransactionCreateModal from '../TransactionCreateModal'
import PendingOrderFillModal from '../PendingOrderFillModal'
import { AddPreciousMetalModal } from '../PreciousMetalsWidget'

import transactionModalSrc from '../TransactionModal.jsx?raw'
import transactionCreateModalSrc from '../TransactionCreateModal.jsx?raw'
import pendingOrderFillModalSrc from '../PendingOrderFillModal.jsx?raw'
import preciousMetalsWidgetSrc from '../PreciousMetalsWidget.jsx?raw'
import immobilienWidgetSrc from '../ImmobilienWidget.jsx?raw'

window.scrollTo = vi.fn()

beforeEach(() => {
  authFetch.mockReset()
  authFetch.mockResolvedValue({ ok: true, json: async () => ({ buckets: [], rate: 0.8 }) })
})

describe('Vorbelegtes Datum ist das lokale Datum (GF06)', () => {
  it('im Kauf/Verkauf-Dialog', () => {
    const position = { id: 'p1', name: 'Nestlé', ticker: 'NESN', type: 'stock', shares: 5, currency: 'CHF' }
    render(<TransactionModal position={position} type="buy" onClose={vi.fn()} />)
    expect(screen.getByLabelText('Datum').value).toBe(LOCAL_TODAY_DISPLAY)
  })

  it('im Dialog «Neue Transaktion»', () => {
    render(<TransactionCreateModal positions={[]} onSave={vi.fn()} onClose={vi.fn()} />)
    expect(screen.getByLabelText('Datum *').value).toBe(LOCAL_TODAY_DISPLAY)
  })

  it('im Dialog «Order gefüllt»', () => {
    const order = { id: 'o1234567', shares: 10, limit_price: 50, currency: 'CHF' }
    render(<PendingOrderFillModal order={order} onSave={vi.fn()} onClose={vi.fn()} />)
    expect(screen.getByLabelText('Fill-Datum *').value).toBe(LOCAL_TODAY_DISPLAY)
  })

  it('im Dialog «Edelmetall hinzufügen»', () => {
    render(<AddPreciousMetalModal onClose={vi.fn()} onSaved={vi.fn()} editItem={null} />)
    expect(screen.getByLabelText('Kaufdatum').value).toBe(LOCAL_TODAY_DISPLAY)
  })

  // Verkaufs-, Ausgaben- und Einnahmen-Dialoge sind nicht exportiert. Der
  // Quelltext-Check deckt ihre Vorbelegung mit ab.
  it.each([
    ['TransactionModal.jsx', transactionModalSrc],
    ['TransactionCreateModal.jsx', transactionCreateModalSrc],
    ['PendingOrderFillModal.jsx', pendingOrderFillModalSrc],
    ['PreciousMetalsWidget.jsx', preciousMetalsWidgetSrc],
    ['ImmobilienWidget.jsx', immobilienWidgetSrc],
  ])('%s leitet kein Datum aus toISOString() ab', (_name, source) => {
    expect(source).toContain('localDateStr(')
    expect(source).not.toMatch(/toISOString\(\)\s*\.\s*(slice|split|substring)/)
  })
})
