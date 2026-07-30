import { useState, useEffect, useMemo } from 'react'
import { X, Check, Loader2, Shield, ClipboardCheck } from 'lucide-react'
import useEscClose from '../hooks/useEscClose'
import useScrollLock from '../hooks/useScrollLock'
import useFocusTrap from '../hooks/useFocusTrap'
import { apiPost } from '../hooks/useApi'
import { formatCHF } from '../lib/format'
import DateInput from './DateInput'

// Phase 3 (v0.40): Generische Kauf-Checkliste — keine Core/Satellite-Unterscheidung
// mehr. Trend- + Risiko-Items werden für alle Käufe geprüft; spezifische
// Risk-Rules kommen vom Bucket der Position.
const BUY_CHECKLIST = [
  { id: 'trend', label: 'Kurs über 150-DMA (Trend bestätigt)' },
  { id: 'macro', label: 'Makro-Gate bestanden (S&P 500 über 150-DMA, VIX < 20)' },
  { id: 'fundamental', label: 'Fundamentale Qualität geprüft (Umsatz, Marge, Verschuldung)' },
  { id: 'no_earnings', label: 'Keine Earnings in den nächsten 7 Tagen' },
  { id: 'sector', label: 'Sektor-Limit geprüft (max. 25%)' },
  { id: 'position_size', label: 'Positionsgrösse passt zur Bucket-Risk-Rule' },
  { id: 'stop', label: 'Stop-Loss gemäss Bucket-Konvention gesetzt' },
]

const STOP_METHODS = [
  { value: 'structural', label: 'Strukturell (Doppelboden)' },
  { value: 'trailing_pct', label: 'Trailing %' },
  { value: 'higher_low', label: 'Higher Low' },
  { value: 'ma_based', label: 'MA-basiert' },
]

// Der Dialog wird aus dem Kontextmenü für fünf Aktionen geöffnet. Vorher
// kannte er nur Kauf/Verkauf — "Dividende erfassen", "Einzahlung erfassen" und
// "Entnahme erfassen" landeten im Kauf-Dialog inkl. Kauf-Checkliste
// (Feedback 30.7.2026).
const TITLES = {
  buy: 'Kaufen',
  sell: 'Verkaufen',
  dividend: 'Dividende erfassen',
  deposit: 'Einzahlung erfassen',
  withdrawal: 'Entnahme erfassen',
}
const SUBMIT_LABELS = {
  buy: 'Kaufen',
  sell: 'Verkaufen',
  dividend: 'Dividende buchen',
  deposit: 'Einzahlung buchen',
  withdrawal: 'Entnahme buchen',
}
const CASH_MOVE_TYPES = ['deposit', 'withdrawal']
const DIVIDEND_POSITION_TYPES = ['stock', 'etf', 'bond']

export default function TransactionModal({ position, type: initialType, onClose, onSaved }) {
  useScrollLock(true)
  const trapRef = useFocusTrap(true)
  const today = new Date().toISOString().slice(0, 10)

  const [form, setForm] = useState({
    type: initialType || 'buy',
    date: today,
    shares: '',
    price_per_share: '',
    fx_rate_to_chf: 1.0,
    fees_chf: '',
    taxes_chf: '',
    amount_chf: '',
    stop_loss_price: '',
    stop_loss_method: '',
    stop_loss_confirmed: false,
  })
  const [checklist, setChecklist] = useState({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  const isSell = form.type === 'sell'
  const isBuy = form.type === 'buy'
  const isDividend = form.type === 'dividend'
  const isCashMove = CASH_MOVE_TYPES.includes(form.type)
  const isTrade = isBuy || isSell

  // Kurs vorbelegen nur beim Handel. Bei einer Dividende ist price_per_share
  // die Dividende PRO AKTIE — der aktuelle Kurs waere dort grob falsch.
  useEffect(() => {
    if (!isTrade) return
    if (position?.current_price != null) {
      setForm((f) => ({ ...f, price_per_share: position.current_price }))
    }
  }, [position, isTrade])

  // Dividende: Stückzahl mit dem aktuellen Bestand vorbelegen.
  useEffect(() => {
    if (!isDividend) return
    setForm((f) => (f.shares ? f : { ...f, shares: position?.shares ?? '' }))
  }, [isDividend, position])

  const set = (key, val) => setForm((f) => ({ ...f, [key]: val }))

  const subtotal = useMemo(() => {
    const shares = parseFloat(form.shares) || 0
    const price = parseFloat(form.price_per_share) || 0
    const fx = parseFloat(form.fx_rate_to_chf) || 1
    return shares * price * fx
  }, [form.shares, form.price_per_share, form.fx_rate_to_chf])

  const fees = parseFloat(form.fees_chf) || 0
  const taxes = parseFloat(form.taxes_chf) || 0
  const amount = parseFloat(form.amount_chf) || 0
  // Buchungsbetrag je Modus:
  //  Handel     — Brutto + Gebühren + Steuern (Cost-Basis-Konvention)
  //  Dividende  — Brutto − Quellensteuer − Spesen (total_chf IST das Netto,
  //               siehe total_return_service: dividends_net = SUM(total_chf))
  //  Cash-Move  — der eingegebene Betrag
  const totalChf = isCashMove ? amount : isDividend ? subtotal - taxes - fees : subtotal + fees + taxes

  useEscClose(onClose)

  if (!position) return null

  const maxShares = position.shares || 0
  const positionCurrency = position.price_currency || position.currency

  const handleSave = async () => {
    let payload
    if (isCashMove) {
      if (!amount || amount <= 0) {
        setError('Bitte Betrag eingeben')
        return
      }
      payload = {
        position_id: position.id,
        type: form.type,
        date: form.date,
        shares: 0,
        price_per_share: 0,
        currency: 'CHF',
        fx_rate_to_chf: 1,
        fees_chf: 0,
        taxes_chf: 0,
        total_chf: Math.round(amount * 100) / 100,
      }
    } else {
      const shares = parseFloat(form.shares)
      if (!shares || shares <= 0) {
        setError('Bitte Anzahl eingeben')
        return
      }
      if (isSell && shares > maxShares) {
        setError(`Max. ${maxShares} verfügbar`)
        return
      }
      const price = parseFloat(form.price_per_share)
      if (!price || price <= 0) {
        setError(isDividend ? 'Bitte Dividende pro Aktie eingeben' : 'Bitte Preis eingeben')
        return
      }
      if (isDividend && totalChf <= 0) {
        setError('Nettobetrag muss grösser als 0 sein')
        return
      }

      // Stop-loss validation for buy — Pflicht-Logik kommt vom Backend
      // (alert_service via bucket.risk_rules). Frontend prüft nur Plausibilität.
      const slPrice = parseFloat(form.stop_loss_price)
      if (isBuy && slPrice > 0 && slPrice >= price) {
        setError('Stop-Loss muss unter dem Kaufkurs liegen')
        return
      }
      // Checklist validation
      if (isBuy) {
        const allChecked = BUY_CHECKLIST.every((item) => checklist[item.id])
        if (!allChecked) {
          setError('Bitte alle Punkte der Kauf-Checkliste bestätigen')
          return
        }
      }

      payload = {
        position_id: position.id,
        type: form.type,
        date: form.date,
        shares,
        price_per_share: price,
        currency: positionCurrency,
        fx_rate_to_chf: parseFloat(form.fx_rate_to_chf) || 1,
        fees_chf: fees,
        taxes_chf: taxes,
        total_chf: Math.round(totalChf * 100) / 100,
      }
      if (isBuy && slPrice > 0) {
        payload.stop_loss_price = slPrice
        payload.stop_loss_method = form.stop_loss_method || null
        payload.stop_loss_confirmed_at_broker = form.stop_loss_confirmed
      }
    }

    setSaving(true)
    setError(null)
    try {
      await apiPost('/transactions', payload)
      onSaved?.()
      onClose()
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  const inputClass = 'w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors'
  const labelClass = 'block text-xs font-medium text-text-secondary mb-1.5'

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-[#04070c]/[0.72] backdrop-blur-sm p-4" role="presentation" onClick={onClose}>
      <div
        ref={trapRef}
        role="dialog"
        aria-modal="true"
        aria-label={TITLES[form.type] || 'Transaktion'}
        className="bg-modal border border-border-hover rounded-[14px] shadow-2xl w-full max-w-md flex flex-col max-h-[90vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border-2">
          <div>
            <h2 className="text-sm font-semibold text-text-primary">
              {TITLES[form.type] || 'Transaktion'}
            </h2>
            <span className="text-xs text-text-muted">
              {position.name} <span className="font-mono text-primary">({position.ticker})</span>
            </span>
          </div>
          <button
            onClick={onClose}
            className="w-[30px] h-[30px] rounded-lg bg-border-row border border-border-hover flex items-center justify-center text-text-muted hover:text-text-primary transition-colors shrink-0"
            aria-label="Schliessen"
          >
            <X size={16} />
          </button>
        </div>

        {/* Form */}
        <div className="px-5 py-4 space-y-4 overflow-y-auto">
          {/* Type Toggle — Cash/Vorsorge kennen nur Zu-/Abfluss, Wertschriften
              Kauf/Verkauf und (Aktien/ETF/Anleihen) Dividende. */}
          <div role="radiogroup" aria-label="Transaktionstyp" className="flex rounded-lg border border-border-2 overflow-hidden">
            {(isCashMove
              ? [
                  { value: 'deposit', label: 'Einzahlung', active: 'bg-success/20 text-success' },
                  { value: 'withdrawal', label: 'Entnahme', active: 'bg-warning/20 text-warning' },
                ]
              : [
                  { value: 'buy', label: 'Kaufen', active: 'bg-success/20 text-success' },
                  { value: 'sell', label: 'Verkaufen', active: 'bg-warning/20 text-warning' },
                  ...(isDividend || DIVIDEND_POSITION_TYPES.includes(position.type)
                    ? [{ value: 'dividend', label: 'Dividende', active: 'bg-primary/20 text-primary' }]
                    : []),
                ]
            ).map((tab, idx, tabs) => (
              <button
                key={tab.value}
                role="radio"
                aria-checked={form.type === tab.value}
                onClick={() =>
                  setForm((f) => {
                    // Kurs <-> Dividende pro Aktie sind verschiedene Groessen,
                    // und die Dividenden-Vorbelegung ist der VOLLE Bestand:
                    // beim Moduswechsel beide Felder leeren, sonst steht im
                    // Verkaufen-Dialog ungefragt der Gesamtbestand.
                    const crossesDividend = (tab.value === 'dividend') !== (f.type === 'dividend')
                    return {
                      ...f,
                      type: tab.value,
                      price_per_share: crossesDividend ? '' : f.price_per_share,
                      shares: crossesDividend ? '' : f.shares,
                    }
                  })
                }
                className={`flex-1 py-2 text-sm font-medium transition-colors ${
                  idx < tabs.length - 1 ? 'border-r border-border-2' : ''
                } ${form.type === tab.value ? tab.active : 'text-text-muted hover:text-text-primary'}`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Purchase Checklist (Buy only) */}
          {form.type === 'buy' && (() => {
            const items = BUY_CHECKLIST
            const checkedCount = items.filter((item) => checklist[item.id]).length
            const allDone = checkedCount === items.length
            return (
              <div className={`rounded-lg border p-4 space-y-2 ${allDone ? 'border-success/30 bg-success/5' : 'border-border-2 bg-card-2'}`}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-xs font-medium text-text-secondary">
                    <ClipboardCheck size={14} className={allDone ? 'text-success' : 'text-text-muted'} />
                    Kauf-Checkliste
                  </div>
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${allDone ? 'bg-success/15 text-success' : 'bg-surface text-text-muted'}`}>
                    {checkedCount}/{items.length}
                  </span>
                </div>
                {items.map((item) => (
                  <label key={item.id} className="flex items-start gap-2 cursor-pointer group">
                    <input
                      type="checkbox"
                      checked={checklist[item.id] || false}
                      onChange={(e) => setChecklist((prev) => ({ ...prev, [item.id]: e.target.checked }))}
                      className="accent-success w-3.5 h-3.5 mt-0.5 shrink-0"
                    />
                    <span className={`text-xs leading-relaxed ${checklist[item.id] ? 'text-text-secondary line-through opacity-60' : 'text-text-primary'}`}>
                      {item.label}
                    </span>
                  </label>
                ))}
              </div>
            )
          })()}

          {/* Date */}
          <div>
            <label htmlFor="txn-date" className={labelClass}>Datum</label>
            <DateInput
              id="txn-date"
              className={inputClass}
              value={form.date}
              onChange={(v) => set('date', v)}
            />
          </div>

          {/* Betrag (Einzahlung / Entnahme) */}
          {isCashMove && (
            <>
              <div>
                <label htmlFor="txn-amount" className={labelClass}>
                  Betrag CHF
                  {positionCurrency && positionCurrency !== 'CHF' && (
                    <span className="ml-1 text-text-muted">(Konto: {positionCurrency})</span>
                  )}
                </label>
                <input
                  id="txn-amount"
                  type="number"
                  step="any"
                  min="0"
                  className={inputClass}
                  value={form.amount_chf}
                  onChange={(e) => set('amount_chf', e.target.value)}
                  placeholder="0.00"
                  autoFocus
                />
              </div>
              <p className="text-xs text-text-secondary bg-primary/5 rounded p-2">
                Die Buchung geht in Cashflow und Renditerechnung ein. Der
                hinterlegte Saldo bleibt ein manuell gepflegter Wert — bitte
                über „Bearbeiten“ nachziehen.
              </p>
            </>
          )}

          {/* Shares */}
          {!isCashMove && (
            <div>
              <label htmlFor="txn-shares" className={labelClass}>
                Anzahl
                {isSell && <span className="ml-1 text-warning">(max. {maxShares})</span>}
                {isDividend && <span className="ml-1 text-text-muted">(Bestand am Ex-Datum)</span>}
              </label>
              <input
                id="txn-shares"
                type="number"
                step="any"
                min="0"
                max={isSell ? maxShares : undefined}
                className={inputClass}
                value={form.shares}
                onChange={(e) => set('shares', e.target.value)}
                placeholder="0"
                autoFocus
              />
            </div>
          )}

          {/* Price / Dividende pro Aktie */}
          {!isCashMove && (
            <div>
              <label htmlFor="txn-price" className={labelClass}>
                {isDividend
                  ? `Dividende pro Aktie (${positionCurrency})`
                  : `Preis pro Einheit (${positionCurrency})`}
              </label>
              <input
                id="txn-price"
                type="number"
                step="any"
                min="0"
                className={inputClass}
                value={form.price_per_share}
                onChange={(e) => set('price_per_share', e.target.value)}
              />
            </div>
          )}

          {/* FX Rate */}
          {!isCashMove && (
            <div>
              <label htmlFor="txn-fx-rate" className={labelClass}>FX-Kurs zu CHF</label>
              <input
                id="txn-fx-rate"
                type="number"
                step="any"
                min="0"
                className={inputClass}
                value={form.fx_rate_to_chf}
                onChange={(e) => set('fx_rate_to_chf', e.target.value)}
              />
            </div>
          )}

          {/* Fees & Taxes */}
          {!isCashMove && (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label htmlFor="txn-fees" className={labelClass}>
                  {isDividend ? 'Spesen CHF' : 'Gebühren CHF'}
                </label>
                <input
                  id="txn-fees"
                  type="number"
                  step="any"
                  min="0"
                  className={inputClass}
                  value={form.fees_chf}
                  onChange={(e) => set('fees_chf', e.target.value)}
                  placeholder="0"
                />
              </div>
              <div>
                <label htmlFor="txn-taxes" className={labelClass}>
                  {isDividend ? 'Quellensteuer CHF' : 'Steuern CHF'}
                </label>
                <input
                  id="txn-taxes"
                  type="number"
                  step="any"
                  min="0"
                  className={inputClass}
                  value={form.taxes_chf}
                  onChange={(e) => set('taxes_chf', e.target.value)}
                  placeholder="0"
                />
              </div>
            </div>
          )}

          {/* Stop-Loss (Buy only) */}
          {form.type === 'buy' && (
            <div className="rounded-lg border border-border-2 bg-card-2 p-4 space-y-3">
              <div className="flex items-center gap-2 text-xs font-medium text-text-secondary">
                <Shield size={14} />
                Stop-Loss
              </div>
              <div>
                <label htmlFor="txn-stop-loss" className={labelClass}>
                  Stop-Loss Kurs ({position.price_currency || position.currency})
                </label>
                <input
                  id="txn-stop-loss"
                  type="number"
                  step="any"
                  min="0"
                  className={inputClass}
                  value={form.stop_loss_price}
                  onChange={(e) => set('stop_loss_price', e.target.value)}
                  placeholder="0.00"
                />
              </div>
              <div>
                <label htmlFor="txn-stop-method" className={labelClass}>Methode</label>
                <select
                  id="txn-stop-method"
                  className={inputClass}
                  value={form.stop_loss_method}
                  onChange={(e) => set('stop_loss_method', e.target.value)}
                >
                  <option value="">Keine Angabe</option>
                  {STOP_METHODS.map((m) => (
                    <option key={m.value} value={m.value}>{m.label}</option>
                  ))}
                </select>
              </div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={form.stop_loss_confirmed}
                  onChange={(e) => set('stop_loss_confirmed', e.target.checked)}
                  className="accent-success w-4 h-4"
                />
                <span className="text-sm text-text-secondary">Stop-Loss bei Broker gesetzt</span>
              </label>
              <p className="text-xs text-text-secondary bg-primary/5 rounded p-2">
                Ob ein Stop-Loss Pflicht ist, hängt vom Bucket der Position ab.
                Buy-and-hold-Buckets brauchen keinen technischen Stop; aktive Buckets
                fordern einen Stop unter Higher Low bzw. unter strukturellem Support.
              </p>
            </div>
          )}

          {/* Totals */}
          <div className="rounded-lg bg-card-2 border border-border-2 px-4 py-3 space-y-1">
            {!isCashMove && (
              <div className="flex items-center justify-between text-xs text-text-secondary">
                <span>{isDividend ? 'Brutto' : 'Subtotal'}</span>
                <span className="tabular-nums">{formatCHF(subtotal)}</span>
              </div>
            )}
            {!isCashMove && fees > 0 && (
              <div className="flex items-center justify-between text-xs text-text-secondary">
                <span>{isDividend ? '− Spesen' : '+ Gebühren'}</span>
                <span className="tabular-nums">{formatCHF(fees)}</span>
              </div>
            )}
            {!isCashMove && taxes > 0 && (
              <div className="flex items-center justify-between text-xs text-text-secondary">
                <span>{isDividend ? '− Quellensteuer' : '+ Steuern'}</span>
                <span className="tabular-nums">{formatCHF(taxes)}</span>
              </div>
            )}
            <div className="flex items-center justify-between pt-1 border-t border-border-2">
              <span className="text-sm text-text-secondary font-medium">
                {isCashMove ? 'Buchungsbetrag CHF' : 'Netto-Total CHF'}
              </span>
              <span className="text-lg font-bold text-text-primary tabular-nums">
                {formatCHF(totalChf)}
              </span>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-5 py-4 border-t border-border-2">
          <div>
            {error && <span role="alert" className="text-danger text-sm">{error}</span>}
          </div>
          <div className="flex gap-3">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm rounded-lg bg-surface border border-border text-text-secondary hover:border-border-hover transition-colors"
            >
              Abbrechen
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className={`px-4 py-2 text-sm rounded-lg font-medium transition-colors disabled:opacity-50 flex items-center gap-2 ${
                isSell || form.type === 'withdrawal'
                  ? 'bg-warning text-black hover:bg-warning/90'
                  : isDividend
                    ? 'bg-primary-btn border border-primary-btn-border text-white font-semibold hover:bg-primary-btn-border'
                    : 'bg-success text-black hover:bg-success/90'
              }`}
            >
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
              {SUBMIT_LABELS[form.type] || 'Buchen'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
