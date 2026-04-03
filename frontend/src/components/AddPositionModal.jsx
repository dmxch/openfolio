import { useState } from 'react'
import { X, Check, Loader2 } from 'lucide-react'
import useEscClose from '../hooks/useEscClose'
import useScrollLock from '../hooks/useScrollLock'
import useFocusTrap from '../hooks/useFocusTrap'
import { apiPost } from '../hooks/useApi'

const ASSET_TYPES = [
  { value: 'cash', label: 'Cash / Konto' },
  { value: 'pension', label: 'Vorsorge (3a/PK)' },
  { value: 'real_estate', label: 'Immobilie' },
  { value: 'stock', label: 'Aktie' },
  { value: 'etf', label: 'ETF' },
  { value: 'crypto', label: 'Krypto' },
  { value: 'commodity', label: 'Rohstoff' },
]

const inputClass = 'w-full bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-primary/50 focus:border-primary'

export default function AddPositionModal({ onClose, onSaved, allowedTypes = null }) {
  useScrollLock(true)
  const trapRef = useFocusTrap(true)
  const visibleTypes = allowedTypes
    ? ASSET_TYPES.filter(t => allowedTypes.includes(t.value))
    : ASSET_TYPES
  const defaultType = allowedTypes?.length === 1 ? allowedTypes[0] : 'cash'
  const [form, setForm] = useState({
    name: '',
    ticker: '',
    type: defaultType,
    currency: 'CHF',
    cost_basis_chf: '',
    pricing_mode: 'manual',
    shares: 1,
    notes: '',
    bank_name: '',
    label: '',
    iban: '',
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  useEscClose(onClose)

  const set = (key, val) => setForm((f) => ({ ...f, [key]: val }))

  const isManualType = ['cash', 'pension', 'real_estate'].includes(form.type)

  const isCash = form.type === 'cash'

  const handleSave = async () => {
    // Auto-generate name for cash accounts: Bank - Bezeichnung - Währung
    let name = form.name.trim()
    if (isCash && !name) {
      const bank = form.bank_name?.trim()
      const label = form.label?.trim()
      if (bank && label) {
        name = `${bank} - ${label} - ${form.currency}`
      } else if (bank) {
        name = `${bank} - ${form.currency}`
      } else if (label) {
        name = `${label} - ${form.currency}`
      } else {
        name = `${form.currency} Konto`
      }
    }
    if (!name) { setError('Name ist erforderlich'); return }
    setSaving(true)
    setError(null)
    try {
      const payload = {
        name,
        ticker: form.ticker.trim() || `CASH_${name.toUpperCase().replace(/[^A-Z0-9]/g, '_')}`,
        type: form.type,
        currency: form.currency,
        cost_basis_chf: Number(form.cost_basis_chf) || 0,
        pricing_mode: isManualType ? 'manual' : 'auto',
        shares: isManualType ? 1 : Number(form.shares) || 0,
        current_price: isManualType ? Number(form.cost_basis_chf) || 0 : null,
        notes: form.notes || null,
        bank_name: form.bank_name?.trim() || null,
        iban: form.iban?.replace(/\s/g, '') || null,
      }
      await apiPost('/portfolio/positions', payload)
      onSaved()
      onClose()
    } catch (e) {
      const msg = e.message || ''
      setError(msg.includes('500') || msg.includes('unique') || msg.includes('duplicate')
        ? 'Ein Konto mit diesem Namen existiert bereits.'
        : msg)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div
        ref={trapRef}
        role="dialog"
        aria-modal="true"
        aria-label="Neue Position"
        className="bg-card border border-border rounded-xl shadow-2xl w-full max-w-lg flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <h2 className="text-lg font-bold text-text-primary">{isCash ? 'Neues Konto' : form.type === 'pension' ? 'Neue Vorsorge' : 'Neue Position'}</h2>
          <button onClick={onClose} className="text-text-muted hover:text-text-primary transition-colors" aria-label="Schliessen">
            <X size={20} />
          </button>
        </div>

        <div className="p-6 space-y-4">
          {/* Type selector — only if multiple types allowed */}
          {visibleTypes.length > 1 && (
            <div>
              <label htmlFor="add-type" className="block text-xs text-text-secondary mb-1.5">Typ</label>
              <select id="add-type" className={inputClass} value={form.type} onChange={(e) => set('type', e.target.value)}>
                {visibleTypes.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
            </div>
          )}

          {isCash ? (
            /* ── Cash-specific form ── */
            <>
              <div>
                <label htmlFor="add-bank" className="block text-xs text-text-secondary mb-1.5">Bank</label>
                <input id="add-bank" className={inputClass} value={form.bank_name} onChange={(e) => set('bank_name', e.target.value)} placeholder="z.B. UBS, ZKB, Swissquote" autoFocus />
              </div>
              <div>
                <label htmlFor="add-label" className="block text-xs text-text-secondary mb-1.5">Bezeichnung <span className="text-text-muted/50">(optional)</span></label>
                <input id="add-label" className={inputClass} value={form.label} onChange={(e) => set('label', e.target.value)} placeholder="z.B. Lohnkonto, Sparkonto" />
              </div>
              <div>
                <label htmlFor="add-iban" className="block text-xs text-text-secondary mb-1.5">IBAN</label>
                <input id="add-iban" className={inputClass} value={form.iban} onChange={(e) => set('iban', e.target.value)} placeholder="CH00 0000 0000 0000 0" />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label htmlFor="add-cash-currency" className="block text-xs text-text-secondary mb-1.5">Währung</label>
                  <select id="add-cash-currency" className={inputClass} value={form.currency} onChange={(e) => set('currency', e.target.value)}>
                    {['CHF','EUR','USD','CAD','GBP','JPY'].map(c => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
                <div>
                  <label htmlFor="add-cash-amount" className="block text-xs text-text-secondary mb-1.5">{`Betrag ${form.currency}`}</label>
                  <input id="add-cash-amount" type="number" step="any" className={inputClass} value={form.cost_basis_chf} onChange={(e) => set('cost_basis_chf', e.target.value)} placeholder="0" />
                </div>
              </div>
              <div>
                <label htmlFor="add-cash-notes" className="block text-xs text-text-secondary mb-1.5">Notizen</label>
                <textarea id="add-cash-notes" className={inputClass + ' h-16 resize-none'} value={form.notes} onChange={(e) => set('notes', e.target.value)} />
              </div>
            </>
          ) : form.type === 'pension' ? (
            /* ── Pension-specific form ── */
            <>
              <div>
                <label htmlFor="add-pension-name" className="block text-xs text-text-secondary mb-1.5">Name</label>
                <input id="add-pension-name" className={inputClass} value={form.name} onChange={(e) => set('name', e.target.value)} placeholder="z.B. VIAC - Säule 3a" autoFocus />
              </div>
              <div>
                <label htmlFor="add-pension-provider" className="block text-xs text-text-secondary mb-1.5">Anbieter</label>
                <input id="add-pension-provider" className={inputClass} value={form.bank_name} onChange={(e) => set('bank_name', e.target.value)} placeholder="z.B. VIAC, frankly, finpension" />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label htmlFor="add-pension-currency" className="block text-xs text-text-secondary mb-1.5">Währung</label>
                  <select id="add-pension-currency" className={inputClass} value={form.currency} onChange={(e) => set('currency', e.target.value)}>
                    {['CHF','EUR','USD','CAD','GBP','JPY'].map(c => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
                <div>
                  <label htmlFor="add-pension-amount" className="block text-xs text-text-secondary mb-1.5">{`Betrag ${form.currency}`}</label>
                  <input id="add-pension-amount" type="number" step="any" className={inputClass} value={form.cost_basis_chf} onChange={(e) => set('cost_basis_chf', e.target.value)} placeholder="0" />
                </div>
              </div>
              <div>
                <label htmlFor="add-pension-notes" className="block text-xs text-text-secondary mb-1.5">Notizen</label>
                <textarea id="add-pension-notes" className={inputClass + ' h-16 resize-none'} value={form.notes} onChange={(e) => set('notes', e.target.value)} placeholder="z.B. 100% Aktien" />
              </div>
            </>
          ) : (
            /* ── Generic position form ── */
            <>
              <div>
                <label htmlFor="add-gen-currency" className="block text-xs text-text-secondary mb-1.5">Währung</label>
                <select id="add-gen-currency" className={inputClass} value={form.currency} onChange={(e) => set('currency', e.target.value)}>
                  {['CHF','EUR','USD','CAD','GBP','JPY'].map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
              <div>
                <label htmlFor="add-gen-name" className="block text-xs text-text-secondary mb-1.5">Name</label>
                <input id="add-gen-name" className={inputClass} value={form.name} onChange={(e) => set('name', e.target.value)} placeholder="z.B. Sparkonto ZKB" autoFocus />
              </div>
              {!isManualType && (
                <div>
                  <label htmlFor="add-ticker" className="block text-xs text-text-secondary mb-1.5">Ticker</label>
                  <input id="add-ticker" className={inputClass} value={form.ticker} onChange={(e) => set('ticker', e.target.value)} placeholder="z.B. AAPL" />
                </div>
              )}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label htmlFor="add-cost-basis" className="block text-xs text-text-secondary mb-1.5">
                    {isManualType ? `Betrag ${form.currency}` : `Einstandswert ${form.currency}`}
                  </label>
                  <input id="add-cost-basis" type="number" step="any" className={inputClass} value={form.cost_basis_chf} onChange={(e) => set('cost_basis_chf', e.target.value)} placeholder="0" />
                </div>
                {!isManualType && (
                  <div>
                    <label htmlFor="add-shares" className="block text-xs text-text-secondary mb-1.5">Anteile</label>
                    <input id="add-shares" type="number" step="any" className={inputClass} value={form.shares} onChange={(e) => set('shares', e.target.value)} />
                  </div>
                )}
              </div>
              <div>
                <label htmlFor="add-gen-notes" className="block text-xs text-text-secondary mb-1.5">Notizen</label>
                <textarea id="add-gen-notes" className={inputClass + ' h-16 resize-none'} value={form.notes} onChange={(e) => set('notes', e.target.value)} />
              </div>
            </>
          )}
        </div>

        <div className="flex items-center justify-between px-6 py-4 border-t border-border">
          <div>{error && <span role="alert" className="text-danger text-sm">{error}</span>}</div>
          <div className="flex gap-3">
            <button onClick={onClose} className="px-4 py-2 text-sm rounded-lg border border-border text-text-secondary hover:bg-card-alt transition-colors">
              Abbrechen
            </button>
            <button
              onClick={handleSave}
              disabled={saving || (!isCash && !form.name.trim())}
              className="px-4 py-2 text-sm rounded-lg bg-primary text-white font-medium hover:bg-primary/90 transition-colors disabled:opacity-50 flex items-center gap-2"
            >
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
              Erstellen
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
