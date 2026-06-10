import { useState, useMemo, useEffect } from 'react'
import { X, Check, Loader2, Info } from 'lucide-react'
import useEscClose from '../hooks/useEscClose'
import useScrollLock from '../hooks/useScrollLock'
import useFocusTrap from '../hooks/useFocusTrap'
import DateInput from './DateInput'
import { apiPost } from '../hooks/useApi'
import { formatNumber } from '../lib/format'

const INPUT = 'bg-card border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors'
const LABEL = 'block text-xs font-medium text-text-muted mb-1'

const PAY_DATE_TOOLTIP =
  'Vorschlag: Ex-Date + 2 Wochen. Das tatsächliche Pay-Date variiert je nach Emittent ' +
  '(1–4 Wochen nach Ex-Date) und ist für die Schweizer Steuererklärung relevant — ' +
  'bitte gegen Broker-Abrechnung prüfen.'

const CURRENCIES = ['CHF', 'USD', 'EUR', 'GBP', 'CAD', 'GBX']

function addDaysIso(isoDate, days) {
  if (!isoDate) return ''
  const d = new Date(isoDate + 'T00:00:00')
  if (isNaN(d.getTime())) return ''
  d.setDate(d.getDate() + days)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

/**
 * Modal zum Erfassen einer Pending-Dividende als Transaktion.
 *
 * Props:
 *   pendingDividend  — komplettes Item-Objekt aus /api/dividends/pending
 *   withholdingResolved — vom Server resolved Withholding-Pct (0.0–1.0)
 *   onClose          — Modal schliessen
 *   onSuccess        — nach erfolgreichem POST: Widget + Counter neu laden
 */
export default function ConfirmDividendModal({ pendingDividend: p, withholdingResolved = 0.35, onClose, onSuccess }) {
  useEscClose(onClose)
  useScrollLock(true)
  const trapRef = useFocusTrap(true)

  const defaultDate = useMemo(() => addDaysIso(p.ex_date, 14), [p.ex_date])
  const defaultGross = useMemo(() => {
    const v = p.expected_gross_chf_recomputed != null ? p.expected_gross_chf_recomputed : p.expected_gross_chf
    return v != null ? Number(v).toFixed(2) : ''
  }, [p.expected_gross_chf_recomputed, p.expected_gross_chf])
  const defaultWhPct = useMemo(() => Number((withholdingResolved * 100).toFixed(2)), [withholdingResolved])

  const [form, setForm] = useState({
    date: defaultDate,
    currency: p.currency || 'CHF',
    gross_chf: defaultGross,
    withholding_pct: String(defaultWhPct),
    net_chf: '',
    notes: '',
  })
  // Wenn der User Netto direkt überschreibt, soll Brutto/Withholding-Änderung
  // den Wert NICHT mehr ändern (Spec §8.3: keine Rückrechnung).
  const [netLocked, setNetLocked] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  // Initialer Netto-Wert berechnen
  useEffect(() => {
    if (netLocked) return
    const gross = parseFloat(form.gross_chf)
    const whPct = parseFloat(form.withholding_pct)
    if (!isNaN(gross) && !isNaN(whPct)) {
      const net = gross * (1 - whPct / 100)
      setForm((f) => ({ ...f, net_chf: net.toFixed(2) }))
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.gross_chf, form.withholding_pct, netLocked])

  const handleNetChange = (e) => {
    setNetLocked(true)
    setForm((f) => ({ ...f, net_chf: e.target.value }))
  }

  const handleGrossChange = (e) => {
    setNetLocked(false)
    setForm((f) => ({ ...f, gross_chf: e.target.value }))
  }

  const handleWhChange = (e) => {
    setNetLocked(false)
    setForm((f) => ({ ...f, withholding_pct: e.target.value }))
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError(null)

    const totalChf = parseFloat(form.net_chf)
    const grossChf = parseFloat(form.gross_chf)

    if (isNaN(totalChf) || totalChf <= 0) {
      setError('Nettobetrag muss grösser als 0 sein.')
      return
    }
    if (!form.date) {
      setError('Datum ist erforderlich.')
      return
    }

    setSaving(true)
    try {
      const payload = {
        date: form.date,
        total_chf: Number(totalChf.toFixed(2)),
        currency: form.currency,
        // Da Brutto und Netto bereits in CHF gepflegt werden, ist die FX-Umrechnung clientseitig 1:1.
        // Server kann anhand Pending-Eintrag eine historische Rate für das Audit nachhalten.
        fx_rate_to_chf: 1.0,
      }
      if (!isNaN(grossChf) && grossChf > 0) {
        payload.gross_amount = Number(grossChf.toFixed(2))
      }
      if (form.notes?.trim()) {
        payload.notes = form.notes.trim().slice(0, 2000)
      }
      await apiPost(`/dividends/${p.id}/confirm`, payload)
      if (onSuccess) onSuccess()
      onClose()
    } catch (err) {
      const msg = err?.message || 'Erfassen fehlgeschlagen.'
      // Backend gibt 409 bei bereits-confirmed/dismissed
      if (/HTTP 409|409|Conflict|already/i.test(msg)) {
        setError('Bereits erfasst oder ignoriert.')
      } else {
        setError(msg)
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-body/80 backdrop-blur-sm" onClick={onClose}>
      <div
        ref={trapRef}
        role="dialog"
        aria-modal="true"
        aria-label="Dividende erfassen"
        className="bg-card border border-border rounded-xl shadow-2xl w-full max-w-lg mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-border">
          <h3 className="text-lg font-bold text-text-primary">Dividende erfassen</h3>
          <button onClick={onClose} className="text-text-muted hover:text-text-primary transition-colors" aria-label="Schliessen">
            {/* aria-label "Schliessen" konsistent mit bestehendem Pattern (Schweizer ss). */}
            <X size={20} />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {/* Position read-only */}
          <div className="bg-card-alt/40 border border-border rounded-lg px-3 py-2">
            <div className="flex items-baseline gap-2">
              <span className="font-mono font-semibold text-text-primary">{p.ticker}</span>
              <span className="text-sm text-text-secondary">{p.position_name}</span>
            </div>
            <div className="text-xs text-text-muted mt-1">
              Ex-Date: {p.ex_date} · {formatNumber(Number(p.shares_at_ex_date), 3, { minDecimals: 0 })} Stück × {Number(p.dividend_per_share).toFixed(4)} {p.currency}
            </div>
          </div>

          {/* Datum (mit Tooltip) */}
          <div>
            <label htmlFor="confirm-div-date" className={LABEL}>
              <span className="inline-flex items-center gap-1">
                Datum (Buchungsdatum) *
                <span title={PAY_DATE_TOOLTIP} className="cursor-help" aria-label="Hinweis zum Pay-Date">
                  <Info size={12} className="text-text-muted" />
                </span>
              </span>
            </label>
            <DateInput
              id="confirm-div-date"
              value={form.date}
              onChange={(v) => setForm((f) => ({ ...f, date: v }))}
              className={`${INPUT} w-full`}
              required
              autoFocus
            />
            <p className="text-[11px] text-text-muted mt-1">
              Vorschlag: Ex-Date + 2 Wochen. Bitte gegen Broker-Abrechnung prüfen.
            </p>
          </div>

          {/* Währung + Brutto */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="confirm-div-ccy" className={LABEL}>Währung</label>
              <select
                id="confirm-div-ccy"
                value={form.currency}
                onChange={(e) => setForm((f) => ({ ...f, currency: e.target.value }))}
                className={`${INPUT} w-full`}
              >
                {CURRENCIES.map((c) => <option key={c}>{c}</option>)}
              </select>
            </div>
            <div>
              <label htmlFor="confirm-div-gross" className={LABEL}>Bruttobetrag (CHF)</label>
              <input
                id="confirm-div-gross"
                type="number"
                step="any"
                min="0"
                value={form.gross_chf}
                onChange={handleGrossChange}
                className={`${INPUT} w-full tabular-nums`}
                placeholder="0.00"
              />
            </div>
          </div>

          {/* Quellensteuer + Netto */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="confirm-div-wh" className={LABEL}>Quellensteuer (%)</label>
              <input
                id="confirm-div-wh"
                type="number"
                step="0.01"
                min="0"
                max="100"
                value={form.withholding_pct}
                onChange={handleWhChange}
                className={`${INPUT} w-full tabular-nums`}
              />
            </div>
            <div>
              <label htmlFor="confirm-div-net" className={LABEL}>
                Nettobetrag (CHF) *
              </label>
              <input
                id="confirm-div-net"
                type="number"
                step="any"
                min="0"
                value={form.net_chf}
                onChange={handleNetChange}
                aria-describedby="confirm-div-net-hint"
                className={`${INPUT} w-full font-medium tabular-nums`}
                required
              />
              <p id="confirm-div-net-hint" className="text-[11px] text-text-muted mt-1">
                Betrag nach Quellensteuer
              </p>
            </div>
          </div>

          {/* Notizen */}
          <div>
            <label htmlFor="confirm-div-notes" className={LABEL}>Notizen (optional)</label>
            <textarea
              id="confirm-div-notes"
              value={form.notes}
              onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
              maxLength={2000}
              rows={2}
              className={`${INPUT} w-full`}
              placeholder="Optional"
            />
          </div>

          {/* Error */}
          {error && (
            <div role="alert" className="text-sm text-danger bg-danger/10 border border-danger/30 rounded-lg px-3 py-2">
              {error}
            </div>
          )}

          {/* Actions */}
          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              disabled={saving}
              className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary transition-colors disabled:opacity-40"
            >
              Abbrechen
            </button>
            <button
              type="submit"
              disabled={saving || !form.date || !form.net_chf}
              className="flex items-center gap-2 bg-primary text-white rounded-lg px-5 py-2 text-sm font-medium hover:bg-primary/80 transition-colors disabled:opacity-40"
            >
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
              Transaktion anlegen
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
