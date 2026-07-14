import { useState, useEffect } from 'react'
import { X, Check, Loader2 } from 'lucide-react'
import useEscClose from '../hooks/useEscClose'
import useScrollLock from '../hooks/useScrollLock'
import useFocusTrap from '../hooks/useFocusTrap'
import { apiPost, authFetch } from '../hooks/useApi'

const ASSET_TYPES = [
  { value: 'cash', label: 'Cash / Konto' },
  { value: 'pension', label: 'Vorsorge (3a/PK)' },
  { value: 'real_estate', label: 'Immobilie' },
  { value: 'stock', label: 'Aktie' },
  { value: 'etf', label: 'ETF' },
  { value: 'bond', label: 'Anleihen' },
  { value: 'crypto', label: 'Krypto' },
  { value: 'commodity', label: 'Rohstoff' },
]

const inputClass = 'w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors'
const labelClass = 'block text-xs font-medium text-text-secondary mb-1.5'

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
    bucket_id: '',
    count_as_cash: false,
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [buckets, setBuckets] = useState([])

  useEscClose(onClose)

  // Buckets laden — nur user-buckets + liquid_default sind fuer liquide Typen relevant.
  useEffect(() => {
    let cancelled = false
    async function loadBuckets() {
      try {
        const res = await authFetch('/api/portfolio/buckets')
        if (!res.ok) return
        const data = await res.json()
        if (cancelled) return
        const eligible = (data.buckets || []).filter(
          (b) =>
            !b.deleted_at &&
            (b.kind === 'user' || b.system_role === 'liquid_default'),
        )
        setBuckets(eligible)
        // Default: liquid_default
        const defaultBucket = eligible.find(
          (b) => b.system_role === 'liquid_default',
        )
        if (defaultBucket) {
          setForm((f) => ({ ...f, bucket_id: f.bucket_id || defaultBucket.id }))
        }
      } catch {
        // ignore
      }
    }
    loadBuckets()
    return () => {
      cancelled = true
    }
  }, [])

  const set = (key, val) => setForm((f) => ({ ...f, [key]: val }))

  const isManualType = ['cash', 'pension', 'real_estate'].includes(form.type)

  const isCash = form.type === 'cash'

  // Bucket-Dropdown nur fuer liquide Typen (PE/RE/Pension wandern auto in
  // System-Buckets) UND nur wenn mehr als 1 wahlbarer Bucket existiert.
  const isLiquidType = ['cash', 'stock', 'etf', 'bond', 'crypto', 'commodity'].includes(form.type)
  const showBucketSelector = isLiquidType && buckets.length > 1

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
        count_as_cash: form.type === 'etf' ? !!form.count_as_cash : false,
        notes: form.notes || null,
        bank_name: form.bank_name?.trim() || null,
        iban: form.iban?.replace(/\s/g, '') || null,
        bucket_id: isLiquidType && form.bucket_id ? form.bucket_id : null,
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
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-[#04070c]/[0.72] backdrop-blur-sm p-4" onClick={onClose}>
      <div
        ref={trapRef}
        role="dialog"
        aria-modal="true"
        aria-label="Neue Position"
        className="bg-modal border border-border-hover rounded-[14px] shadow-2xl w-full max-w-lg flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-border-2">
          <h2 className="text-sm font-semibold text-text-primary">{isCash ? 'Neues Konto' : form.type === 'pension' ? 'Neue Vorsorge' : 'Neue Position'}</h2>
          <button
            onClick={onClose}
            className="w-[30px] h-[30px] rounded-lg bg-border-row border border-border-hover flex items-center justify-center text-text-muted hover:text-text-primary transition-colors shrink-0"
            aria-label="Schliessen"
          >
            <X size={16} />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          {/* Type selector — only if multiple types allowed */}
          {visibleTypes.length > 1 && (
            <div>
              <label htmlFor="add-type" className={labelClass}>Typ</label>
              <select id="add-type" className={inputClass} value={form.type} onChange={(e) => set('type', e.target.value)}>
                {visibleTypes.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
            </div>
          )}

          {isCash ? (
            /* ── Cash-specific form ── */
            <>
              <div>
                <label htmlFor="add-bank" className={labelClass}>Bank</label>
                <input id="add-bank" className={inputClass} value={form.bank_name} onChange={(e) => set('bank_name', e.target.value)} placeholder="z.B. UBS, ZKB, Swissquote" autoFocus />
              </div>
              <div>
                <label htmlFor="add-label" className={labelClass}>Bezeichnung <span className="text-text-muted/50">(optional)</span></label>
                <input id="add-label" className={inputClass} value={form.label} onChange={(e) => set('label', e.target.value)} placeholder="z.B. Lohnkonto, Sparkonto" />
              </div>
              <div>
                <label htmlFor="add-iban" className={labelClass}>IBAN</label>
                <input id="add-iban" className={inputClass} value={form.iban} onChange={(e) => set('iban', e.target.value)} placeholder="CH00 0000 0000 0000 0" />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label htmlFor="add-cash-currency" className={labelClass}>Währung</label>
                  <select id="add-cash-currency" className={inputClass} value={form.currency} onChange={(e) => set('currency', e.target.value)}>
                    {['CHF','EUR','USD','CAD','GBP','JPY'].map(c => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
                <div>
                  <label htmlFor="add-cash-amount" className={labelClass}>{`Betrag ${form.currency}`}</label>
                  <input id="add-cash-amount" type="number" step="any" className={inputClass} value={form.cost_basis_chf} onChange={(e) => set('cost_basis_chf', e.target.value)} placeholder="0" />
                </div>
              </div>
              {showBucketSelector && (
                <div>
                  <label htmlFor="add-cash-bucket" className={labelClass}>Bucket</label>
                  <select id="add-cash-bucket" className={inputClass} value={form.bucket_id} onChange={(e) => set('bucket_id', e.target.value)}>
                    {buckets.map((b) => (
                      <option key={b.id} value={b.id}>{b.name}</option>
                    ))}
                  </select>
                </div>
              )}
              <div>
                <label htmlFor="add-cash-notes" className={labelClass}>Notizen</label>
                <textarea id="add-cash-notes" className={inputClass + ' h-16 resize-none'} value={form.notes} onChange={(e) => set('notes', e.target.value)} />
              </div>
            </>
          ) : form.type === 'pension' ? (
            /* ── Pension-specific form ── */
            <>
              <div>
                <label htmlFor="add-pension-name" className={labelClass}>Name</label>
                <input id="add-pension-name" className={inputClass} value={form.name} onChange={(e) => set('name', e.target.value)} placeholder="z.B. VIAC - Säule 3a" autoFocus />
              </div>
              <div>
                <label htmlFor="add-pension-provider" className={labelClass}>Anbieter</label>
                <input id="add-pension-provider" className={inputClass} value={form.bank_name} onChange={(e) => set('bank_name', e.target.value)} placeholder="z.B. VIAC, frankly, finpension" />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label htmlFor="add-pension-currency" className={labelClass}>Währung</label>
                  <select id="add-pension-currency" className={inputClass} value={form.currency} onChange={(e) => set('currency', e.target.value)}>
                    {['CHF','EUR','USD','CAD','GBP','JPY'].map(c => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
                <div>
                  <label htmlFor="add-pension-amount" className={labelClass}>{`Betrag ${form.currency}`}</label>
                  <input id="add-pension-amount" type="number" step="any" className={inputClass} value={form.cost_basis_chf} onChange={(e) => set('cost_basis_chf', e.target.value)} placeholder="0" />
                </div>
              </div>
              <div>
                <label htmlFor="add-pension-notes" className={labelClass}>Notizen</label>
                <textarea id="add-pension-notes" className={inputClass + ' h-16 resize-none'} value={form.notes} onChange={(e) => set('notes', e.target.value)} placeholder="z.B. 100% Aktien" />
              </div>
            </>
          ) : (
            /* ── Generic position form ── */
            <>
              <div>
                <label htmlFor="add-gen-currency" className={labelClass}>Währung</label>
                <select id="add-gen-currency" className={inputClass} value={form.currency} onChange={(e) => set('currency', e.target.value)}>
                  {['CHF','EUR','USD','CAD','GBP','JPY'].map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
              <div>
                <label htmlFor="add-gen-name" className={labelClass}>Name</label>
                <input id="add-gen-name" className={inputClass} value={form.name} onChange={(e) => set('name', e.target.value)} placeholder="z.B. Sparkonto ZKB" autoFocus />
              </div>
              {!isManualType && (
                <div>
                  <label htmlFor="add-ticker" className={labelClass}>Ticker</label>
                  <input id="add-ticker" className={inputClass} value={form.ticker} onChange={(e) => set('ticker', e.target.value)} placeholder="z.B. AAPL" />
                </div>
              )}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label htmlFor="add-cost-basis" className={labelClass}>
                    {isManualType ? `Betrag ${form.currency}` : `Einstandswert ${form.currency}`}
                  </label>
                  <input id="add-cost-basis" type="number" step="any" className={inputClass} value={form.cost_basis_chf} onChange={(e) => set('cost_basis_chf', e.target.value)} placeholder="0" />
                </div>
                {!isManualType && (
                  <div>
                    <label htmlFor="add-shares" className={labelClass}>Anteile</label>
                    <input id="add-shares" type="number" step="any" className={inputClass} value={form.shares} onChange={(e) => set('shares', e.target.value)} />
                  </div>
                )}
              </div>
              {form.type === 'etf' && (
                <div>
                  <label className="flex items-start gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={form.count_as_cash}
                      onChange={(e) => set('count_as_cash', e.target.checked)}
                      className="mt-0.5 rounded border-border text-primary focus:ring-primary/50"
                    />
                    <span className="text-sm text-text-secondary">
                      Als Cash zählen (Geldmarkt-/T-Bill-ETF)
                      <span className="block text-[11px] text-text-muted">
                        Wird live bepreist, in der Allokation und Cash-Quote aber als Cash geführt.
                      </span>
                    </span>
                  </label>
                </div>
              )}
              {showBucketSelector && (
                <div>
                  <label htmlFor="add-gen-bucket" className={labelClass}>Bucket</label>
                  <select id="add-gen-bucket" className={inputClass} value={form.bucket_id} onChange={(e) => set('bucket_id', e.target.value)}>
                    {buckets.map((b) => (
                      <option key={b.id} value={b.id}>{b.name}</option>
                    ))}
                  </select>
                </div>
              )}
              <div>
                <label htmlFor="add-gen-notes" className={labelClass}>Notizen</label>
                <textarea id="add-gen-notes" className={inputClass + ' h-16 resize-none'} value={form.notes} onChange={(e) => set('notes', e.target.value)} />
              </div>
            </>
          )}
        </div>

        <div className="flex items-center justify-between px-5 py-4 border-t border-border-2">
          <div>{error && <span role="alert" className="text-danger text-sm">{error}</span>}</div>
          <div className="flex gap-3">
            <button onClick={onClose} className="px-4 py-2 text-sm rounded-lg bg-surface border border-border text-text-secondary hover:border-border-hover transition-colors">
              Abbrechen
            </button>
            <button
              onClick={handleSave}
              disabled={saving || (!isCash && !form.name.trim())}
              className="px-4 py-2 text-sm rounded-lg bg-primary-btn border border-primary-btn-border text-white font-semibold hover:bg-primary-btn-border transition-colors disabled:opacity-50 flex items-center gap-2"
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
