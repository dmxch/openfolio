import { useState, useEffect, useMemo } from 'react'
import { X, Check, Loader2, FlaskConical, Search } from 'lucide-react'
import useEscClose from '../hooks/useEscClose'
import useScrollLock from '../hooks/useScrollLock'
import useFocusTrap from '../hooks/useFocusTrap'
import { apiPut, apiDelete, authFetch } from '../hooks/useApi'
import { formatCHF, formatNumber } from '../lib/format'
import { INDUSTRY_TO_SECTOR, FINVIZ_SECTORS, SECTORS_WITH_INDUSTRIES, MULTI_SECTOR_INDUSTRIES } from '../lib/sectorMapping'

const TABS = [
  { key: 'stammdaten', label: 'Stammdaten' },
  { key: 'kursdaten', label: 'Kursdaten' },
  { key: 'historie', label: 'Transaktionen' },
]

const ASSET_TYPES = ['stock', 'etf', 'crypto', 'commodity', 'cash', 'pension', 'real_estate']
const PRICING_MODES = ['auto', 'manual']
const PRICE_SOURCES = ['yahoo', 'coingecko', 'gold_org', 'manual']

export default function EditPositionModal({ position, onClose, onSaved }) {
  useScrollLock(true)
  const [tab, setTab] = useState('stammdaten')
  const [form, setForm] = useState({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [testResult, setTestResult] = useState(null)
  const [testLoading, setTestLoading] = useState(false)
  const [history, setHistory] = useState(null)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [sectorWeights, setSectorWeights] = useState(() =>
    FINVIZ_SECTORS.map((s) => ({ sector: s, weight_pct: 0 }))
  )

  const isMultiSector = MULTI_SECTOR_INDUSTRIES.includes(form.industry)

  useEffect(() => {
    if (position) {
      setForm({
        ticker: position.ticker || '',
        name: position.name || '',
        type: position.type || 'stock',
        sector: position.sector || '',
        industry: position.industry || '',
        currency: position.currency || 'CHF',
        position_type: position.position_type || '',
        isin: position.isin || '',
        notes: position.notes || '',
        pricing_mode: position.pricing_mode || 'auto',
        price_source: position.price_source || 'yahoo',
        yfinance_ticker: position.yfinance_ticker || '',
        coingecko_id: position.coingecko_id || '',
        gold_org: position.gold_org || false,
        current_price: position.current_price ?? '',
        shares: position.shares ?? 0,
        cost_basis_chf: position.cost_basis_chf ?? 0,
        bank_name: position.bank_name || '',
        iban: position.iban || '',
      })
    }
  }, [position])

  // Load existing ETF sector weights
  useEffect(() => {
    if (!position?.ticker) return
    authFetch(`/api/etf-sectors/${position.ticker}`)
      .then((r) => r.ok ? r.json() : null)
      .then((data) => {
        if (data?.sectors?.length) {
          const map = {}
          for (const s of data.sectors) map[s.sector] = s.weight_pct
          setSectorWeights(FINVIZ_SECTORS.map((s) => ({ sector: s, weight_pct: map[s] || 0 })))
        }
      })
      .catch(() => {})
  }, [position?.ticker])

  useEffect(() => {
    if (tab === 'historie' && position && !history) {
      setHistoryLoading(true)
      authFetch(`/api/portfolio/positions/${position.id}/history`)
        .then((r) => r.json())
        .then(setHistory)
        .catch(() => setHistory([]))
        .finally(() => setHistoryLoading(false))
    }
  }, [tab, position, history])

  useEscClose(onClose)

  if (!position) return null

  const isCash = position.type === 'cash'
  const isPension = position.type === 'pension'
  const isSimpleType = isCash || isPension

  const set = (key, val) => setForm((f) => ({ ...f, [key]: val }))

  const sectorTotal = sectorWeights.reduce((s, w) => s + w.weight_pct, 0)
  const sectorAllEmpty = sectorWeights.every((w) => w.weight_pct === 0)
  const sectorValid = sectorAllEmpty || (sectorTotal >= 99.9 && sectorTotal <= 100.1)

  const handleSave = async () => {
    if (isMultiSector && !sectorValid) return
    setSaving(true)
    setError(null)
    try {
      const payload = {}
      for (const [k, v] of Object.entries(form)) {
        if (v === '') {
          payload[k] = null
        } else {
          payload[k] = v
        }
      }
      if (payload.shares != null) payload.shares = Number(payload.shares)
      if (payload.cost_basis_chf != null) payload.cost_basis_chf = Number(payload.cost_basis_chf)
      if (payload.current_price != null) payload.current_price = Number(payload.current_price)
      // For cash/pension: sync current_price with cost_basis (manual pricing)
      if (isSimpleType) {
        payload.current_price = Number(payload.cost_basis_chf) || 0
        payload.bank_name = payload.bank_name || null
        payload.iban = payload.iban || null
      }

      await apiPut(`/portfolio/positions/${position.id}`, payload)

      // Save or delete ETF sector weights for Multi-Sector positions
      if (isMultiSector) {
        if (sectorAllEmpty) {
          await apiDelete(`/etf-sectors/${form.ticker}`)
        } else {
          await apiPut(`/etf-sectors/${form.ticker}`, {
            sectors: sectorWeights.filter((w) => w.weight_pct > 0),
          })
        }
      }

      onSaved()
      onClose()
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  const handleTestPrice = async () => {
    const ticker = form.yfinance_ticker || form.ticker
    if (!ticker) return
    setTestLoading(true)
    setTestResult(null)
    try {
      const res = await authFetch(`/api/portfolio/positions/${position.id}/test-price?yfinance_ticker=${encodeURIComponent(ticker)}`)
      const data = await res.json()
      setTestResult(data)
    } catch {
      setTestResult({ ok: false, error: 'Netzwerkfehler' })
    } finally {
      setTestLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div
        ref={useFocusTrap(true)}
        role="dialog"
        aria-modal="true"
        aria-label={position.name}
        className="bg-card border border-border rounded-xl shadow-2xl w-full max-w-2xl max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <div>
            <h2 className="text-lg font-bold text-text-primary">
              {isSimpleType ? (isCash ? 'Konto bearbeiten' : 'Vorsorge bearbeiten') : position.name}
            </h2>
            {!isSimpleType && <span className="text-sm text-text-muted font-mono">{position.ticker}</span>}
          </div>
          <button onClick={onClose} className="text-text-muted hover:text-text-primary transition-colors" aria-label="Schliessen">
            <X size={20} />
          </button>
        </div>

        {/* Tabs — hidden for cash/pension */}
        {!isSimpleType && (
          <div className="flex border-b border-border px-6">
            {TABS.map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={`px-4 py-3 text-sm font-medium transition-colors border-b-2 -mb-px ${
                  tab === t.key
                    ? 'border-primary text-primary'
                    : 'border-transparent text-text-muted hover:text-text-primary'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
        )}

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {isSimpleType ? (
            <div className="space-y-4">
              <Field id="edit-name" label={isCash ? 'Kontoname' : 'Name'}>
                <input id="edit-name" className={inputClass} value={form.name} onChange={(e) => set('name', e.target.value)} />
              </Field>
              {isCash && (
                <div className="grid grid-cols-2 gap-4">
                  <Field id="edit-bank" label="Bank">
                    <input id="edit-bank" className={inputClass} value={form.bank_name} onChange={(e) => set('bank_name', e.target.value)} placeholder="z.B. St. Galler KB" />
                  </Field>
                  <Field id="edit-iban" label="IBAN">
                    <input id="edit-iban" className={inputClass} value={form.iban ? form.iban.replace(/(.{4})(?=.)/g, '$1 ') : ''} onChange={(e) => set('iban', e.target.value.replace(/\s/g, ''))} placeholder="CH00 0000 0000 0000 0" />
                  </Field>
                </div>
              )}
              {isPension && (
                <Field id="edit-provider" label="Anbieter">
                  <input id="edit-provider" className={inputClass} value={form.bank_name} onChange={(e) => set('bank_name', e.target.value)} placeholder="z.B. VIAC, frankly, Swissquote" />
                </Field>
              )}
              <div className="grid grid-cols-2 gap-4">
                <Field id="edit-currency" label="Währung">
                  <select id="edit-currency" className={selectClass} value={form.currency} onChange={(e) => set('currency', e.target.value)}>
                    {['CHF','USD','EUR','CAD','GBP','JPY'].map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </Field>
                <Field id="edit-balance" label={`Kontosaldo ${form.currency || 'CHF'}`}>
                  <input id="edit-balance" type="number" step="any" className={inputClass} value={form.cost_basis_chf} onChange={(e) => set('cost_basis_chf', e.target.value)} />
                </Field>
              </div>
              {!isPension && (
                <Field id="edit-notes" label="Notizen">
                  <textarea id="edit-notes" className={inputClass + ' h-16 resize-none'} value={form.notes} onChange={(e) => set('notes', e.target.value)} />
                </Field>
              )}
            </div>
          ) : (
            <>
              {tab === 'stammdaten' && (
                <StammdatenTab
                  form={form}
                  set={set}
                  isMultiSector={isMultiSector}
                  sectorWeights={sectorWeights}
                  setSectorWeights={setSectorWeights}
                  sectorTotal={sectorTotal}
                  sectorAllEmpty={sectorAllEmpty}
                />
              )}
              {tab === 'kursdaten' && (
                <KursdatenTab
                  form={form}
                  set={set}
                  onTestPrice={handleTestPrice}
                  testResult={testResult}
                  testLoading={testLoading}
                />
              )}
              {tab === 'historie' && <HistorieTab history={history} loading={historyLoading} />}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-border">
          <div>
            {error && <span role="alert" className="text-danger text-sm">{error}</span>}
          </div>
          <div className="flex gap-3">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm rounded-lg border border-border text-text-secondary hover:bg-card-alt transition-colors"
            >
              Abbrechen
            </button>
            <button
              onClick={handleSave}
              disabled={saving || (isMultiSector && !sectorValid)}
              className="px-4 py-2 text-sm rounded-lg bg-primary text-white font-medium hover:bg-primary/90 transition-colors disabled:opacity-50 flex items-center gap-2"
            >
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
              Speichern
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function Field({ id, label, children, className = '' }) {
  return (
    <div className={className}>
      <label htmlFor={id} className="block text-xs text-text-muted mb-1.5">{label}</label>
      {children}
    </div>
  )
}

const inputClass = 'w-full bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-primary/50 focus:border-primary'
const selectClass = inputClass

function IndustryDropdown({ value, onChange, legacySector }) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')

  const derivedSector = value ? INDUSTRY_TO_SECTOR[value] : null

  const filtered = useMemo(() => {
    if (!search) return SECTORS_WITH_INDUSTRIES
    const q = search.toLowerCase()
    const result = {}
    for (const [sector, industries] of Object.entries(SECTORS_WITH_INDUSTRIES)) {
      const matches = industries.filter((ind) =>
        ind.toLowerCase().includes(q) || sector.toLowerCase().includes(q)
      )
      if (matches.length > 0) result[sector] = matches
    }
    return result
  }, [search])

  const handleSelect = (industry) => {
    onChange(industry)
    setOpen(false)
    setSearch('')
  }

  const handleClear = () => {
    onChange('')
    setOpen(false)
    setSearch('')
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={`${inputClass} text-left flex items-center justify-between`}
      >
        <span className={value ? 'text-text-primary' : 'text-text-muted'}>
          {value || 'Branche wählen...'}
        </span>
        <Search size={14} className="text-text-muted shrink-0" />
      </button>

      {derivedSector && (
        <div className="mt-1.5 flex items-center gap-1.5">
          <span className="text-[11px] text-text-muted">Sektor:</span>
          <span className="text-[11px] font-medium text-primary bg-primary/10 px-2 py-0.5 rounded">{derivedSector}</span>
        </div>
      )}
      {!value && legacySector && (
        <div className="mt-1.5 flex items-center gap-1.5">
          <span className="text-[11px] text-warning">Bisheriger Sektor: {legacySector} — bitte Branche zuweisen</span>
        </div>
      )}

      {open && (
        <div className="absolute z-50 mt-1 w-full bg-card border border-border rounded-lg shadow-xl max-h-64 flex flex-col">
          <div className="p-2 border-b border-border">
            <input
              autoFocus
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Suchen..."
              aria-label="Branche suchen"
              className="w-full bg-body border border-border rounded px-2.5 py-1.5 text-xs text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
            />
          </div>
          <div className="overflow-y-auto flex-1">
            {value && (
              <button
                onClick={handleClear}
                className="w-full text-left px-3 py-1.5 text-xs text-text-muted hover:bg-card-alt italic"
              >
                — Keine Branche —
              </button>
            )}
            {Object.entries(filtered).map(([sector, industries]) => (
              <div key={sector}>
                <div className="px-3 py-1 text-[10px] font-bold text-text-muted uppercase tracking-wider bg-card-alt/50 sticky top-0">
                  {sector}
                </div>
                {industries.map((ind) => (
                  <button
                    key={ind}
                    onClick={() => handleSelect(ind)}
                    className={`w-full text-left px-3 py-1.5 text-xs hover:bg-card-alt transition-colors ${
                      ind === value ? 'text-primary font-medium bg-primary/5' : 'text-text-secondary'
                    }`}
                  >
                    {ind}
                  </button>
                ))}
              </div>
            ))}
            {Object.keys(filtered).length === 0 && (
              <div className="px-3 py-4 text-xs text-text-muted text-center">Keine Treffer</div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function StammdatenTab({ form, set, isMultiSector, sectorWeights, setSectorWeights, sectorTotal, sectorAllEmpty }) {
  const handleWeightChange = (index, val) => {
    const num = val === '' ? 0 : parseFloat(val)
    if (isNaN(num) || num < 0 || num > 100) return
    setSectorWeights((prev) => {
      const next = [...prev]
      next[index] = { ...next[index], weight_pct: num }
      return next
    })
  }

  return (
    <div className="grid grid-cols-2 gap-4">
      <Field id="edit-ticker" label="Ticker">
        <input id="edit-ticker" className={inputClass} value={form.ticker} onChange={(e) => set('ticker', e.target.value)} />
      </Field>
      <Field id="edit-pos-name" label="Name">
        <input id="edit-pos-name" className={inputClass} value={form.name} onChange={(e) => set('name', e.target.value)} />
      </Field>
      <Field id="edit-type" label="Typ">
        <select id="edit-type" className={selectClass} value={form.type} onChange={(e) => set('type', e.target.value)}>
          {ASSET_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </Field>
      <Field label="Branche">
        <IndustryDropdown
          value={form.industry || ''}
          legacySector={!form.industry && form.sector ? form.sector : null}
          onChange={(val) => {
            set('industry', val)
            if (val && INDUSTRY_TO_SECTOR[val]) {
              set('sector', INDUSTRY_TO_SECTOR[val])
            } else if (!val) {
              set('sector', '')
            }
          }}
        />
      </Field>
      {isMultiSector && (
        <Field label="Sektorverteilung" className="col-span-2">
          <div className="flex items-center justify-between mb-2">
            <span className={`text-xs font-bold tabular-nums ${
              sectorAllEmpty ? 'text-text-muted' : (sectorTotal >= 99.9 && sectorTotal <= 100.1) ? 'text-success' : 'text-danger'
            }`}>
              Total: {sectorTotal.toFixed(1)}%
            </span>
          </div>
          <div className="grid grid-cols-2 gap-x-6 gap-y-1.5">
            {sectorWeights.map((w, i) => (
              <div key={w.sector} className="flex items-center gap-2">
                <span className="text-xs text-text-secondary w-36 shrink-0 truncate">{w.sector}</span>
                <input
                  type="number"
                  step="0.1"
                  min="0"
                  max="100"
                  value={w.weight_pct || ''}
                  onChange={(e) => handleWeightChange(i, e.target.value)}
                  placeholder={'\u2014'}
                  className="w-16 px-2 py-1 text-xs text-right bg-body border border-border rounded text-text-primary tabular-nums focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary/50"
                />
                <span className="text-xs text-text-muted">%</span>
              </div>
            ))}
          </div>
          <p className="text-[11px] text-text-muted mt-2">Verteilung vom ETF-Anbieter übernehmen (z.B. iShares, Vanguard)</p>
        </Field>
      )}
      <Field id="edit-pos-currency" label="Währung">
        <select id="edit-pos-currency" className={selectClass} value={form.currency} onChange={(e) => set('currency', e.target.value)}>
          {['CHF','USD','EUR','CAD','GBP','JPY'].map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        {form.currency === 'CAD' && form.ticker && !form.ticker.endsWith('.TO') && !form.ticker.endsWith('.V') && (
          <p className="mt-1.5 text-[11px] text-warning">
            Kanadische Aktien handeln oft an der TSX. Meinst du {form.ticker}.TO?
          </p>
        )}
        {form.currency === 'GBP' && form.ticker && !form.ticker.endsWith('.L') && (
          <p className="mt-1.5 text-[11px] text-warning">
            Britische Aktien handeln an der LSE. Meinst du {form.ticker}.L?
          </p>
        )}
      </Field>
      {['stock', 'etf'].includes(form.type) && (
        <Field label="Positions-Typ">
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => set('position_type', 'core')}
              className={`flex-1 py-2 rounded-lg text-sm font-medium border transition-colors ${
                form.position_type === 'core'
                  ? 'bg-primary text-white border-primary'
                  : 'border-border text-text-muted hover:border-primary hover:text-primary'
              }`}
            >
              Core
            </button>
            <button
              type="button"
              onClick={() => set('position_type', 'satellite')}
              className={`flex-1 py-2 rounded-lg text-sm font-medium border transition-colors ${
                form.position_type === 'satellite'
                  ? 'bg-warning text-white border-warning'
                  : 'border-border text-text-muted hover:border-warning hover:text-warning'
              }`}
            >
              Satellite
            </button>
          </div>
        </Field>
      )}
      <Field id="edit-isin" label="ISIN">
        <input id="edit-isin" className={inputClass} value={form.isin} onChange={(e) => set('isin', e.target.value)} />
      </Field>
      <Field id="edit-shares" label="Anteile" className="col-span-1">
        <input id="edit-shares" type="number" step="any" className={inputClass} value={form.shares} onChange={(e) => set('shares', e.target.value)} />
      </Field>
      <Field id="edit-cost-basis" label="Einstandswert" className="col-span-1">
        <input id="edit-cost-basis" type="number" step="any" className={inputClass} value={form.cost_basis_chf} onChange={(e) => set('cost_basis_chf', e.target.value)} />
      </Field>
      <Field id="edit-pos-notes" label="Notizen" className="col-span-2">
        <textarea id="edit-pos-notes" className={inputClass + ' h-20 resize-none'} value={form.notes} onChange={(e) => set('notes', e.target.value)} />
      </Field>
    </div>
  )
}

function KursdatenTab({ form, set, onTestPrice, testResult, testLoading }) {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4">
        <Field id="edit-pricing-mode" label="Pricing-Modus">
          <select id="edit-pricing-mode" className={selectClass} value={form.pricing_mode} onChange={(e) => set('pricing_mode', e.target.value)}>
            {PRICING_MODES.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </Field>
        <Field id="edit-price-source" label="Preisquelle">
          <select id="edit-price-source" className={selectClass} value={form.price_source} onChange={(e) => set('price_source', e.target.value)}>
            {PRICE_SOURCES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </Field>
        <Field id="edit-yfinance-ticker" label="yFinance Ticker" className="col-span-2">
          <div className="flex gap-2">
            <input
              id="edit-yfinance-ticker"
              className={inputClass}
              value={form.yfinance_ticker}
              onChange={(e) => set('yfinance_ticker', e.target.value)}
              placeholder={form.ticker || 'z.B. PAAS.TO'}
            />
            <button
              onClick={onTestPrice}
              disabled={testLoading}
              className="flex items-center gap-1.5 px-3 py-2 text-xs rounded-lg bg-card-alt border border-border text-text-secondary hover:text-primary hover:border-primary/50 transition-colors whitespace-nowrap disabled:opacity-50"
            >
              {testLoading ? <Loader2 size={13} className="animate-spin" /> : <FlaskConical size={13} />}
              Testen
            </button>
          </div>
          {testResult && (
            <div className={`mt-2 text-xs px-3 py-2 rounded-lg border ${
              testResult.ok
                ? 'bg-success/10 border-success/30 text-success'
                : 'bg-danger/10 border-danger/30 text-danger'
            }`}>
              {testResult.ok
                ? `${testResult.currency} ${formatNumber(testResult.price, 4)}`
                : testResult.error}
            </div>
          )}
        </Field>
        <Field id="edit-coingecko-id" label="CoinGecko ID">
          <input id="edit-coingecko-id" className={inputClass} value={form.coingecko_id} onChange={(e) => set('coingecko_id', e.target.value)} placeholder="z.B. bitcoin" />
        </Field>
        <Field label="Gold.org Preis">
          <label className="flex items-center gap-2 mt-2 cursor-pointer">
            <input
              type="checkbox"
              checked={form.gold_org || false}
              onChange={(e) => set('gold_org', e.target.checked)}
              className="rounded border-border text-primary focus:ring-primary/50"
            />
            <span className="text-sm text-text-secondary">Gold.org API verwenden</span>
          </label>
        </Field>
      </div>

      {form.pricing_mode === 'manual' && (
        <Field id="edit-manual-price" label="Manueller Kurs">
          <input id="edit-manual-price" type="number" step="any" className={inputClass} value={form.current_price} onChange={(e) => set('current_price', e.target.value)} />
        </Field>
      )}

    </div>
  )
}

function HistorieTab({ history, loading }) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-text-muted">
        <Loader2 size={20} className="animate-spin mr-2" /> Lade Transaktionen...
      </div>
    )
  }

  if (!history || history.length === 0) {
    return <div className="text-center py-12 text-text-muted text-sm">Keine Transaktionen vorhanden</div>
  }

  const typeLabels = { buy: 'Kauf', sell: 'Verkauf', dividend: 'Dividende', fee: 'Gebühr', deposit: 'Einzahlung', withdrawal: 'Auszahlung' }
  const typeColors = { buy: 'text-success', sell: 'text-warning', dividend: 'text-primary', fee: 'text-danger' }

  return (
    <div className="overflow-x-auto -mx-6 px-6">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-text-muted">
            <th className="text-left py-2 pr-4 font-medium">Datum</th>
            <th className="text-left py-2 pr-4 font-medium">Typ</th>
            <th className="text-right py-2 pr-4 font-medium">Anteile</th>
            <th className="text-right py-2 pr-4 font-medium">Kurs</th>
            <th className="text-right py-2 font-medium">Total CHF</th>
          </tr>
        </thead>
        <tbody>
          {history.map((t) => (
            <tr key={t.id} className="border-b border-border/30">
              <td className="py-2 pr-4 text-text-secondary tabular-nums">{t.date}</td>
              <td className={`py-2 pr-4 font-medium ${typeColors[t.type] || 'text-text-secondary'}`}>
                {typeLabels[t.type] || t.type}
              </td>
              <td className="py-2 pr-4 text-right tabular-nums text-text-secondary">{formatNumber(t.shares, 4)}</td>
              <td className="py-2 pr-4 text-right tabular-nums text-text-secondary">
                {t.currency} {formatNumber(t.price_per_share, 2)}
              </td>
              <td className="py-2 text-right tabular-nums text-text-primary font-medium">{formatCHF(t.total_chf)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
