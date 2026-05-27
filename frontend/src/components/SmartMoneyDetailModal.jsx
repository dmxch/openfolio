import { useEffect, useState, useRef } from 'react'
import { X, ExternalLink } from 'lucide-react'
import { authFetch } from '../hooks/useApi'
import { SIGNAL_CONFIG } from '../lib/screeningConfig'
import useEscClose from '../hooks/useEscClose'
import useFocusTrap from '../hooks/useFocusTrap'
import TradingViewMiniChart from './TradingViewMiniChart'
import TickerLogo from './TickerLogo'
import { toTradingViewSymbol } from '../lib/tradingview'
import { daysSince } from '../lib/format'

// Signal-Key → Feld, aus dem sich die Frische ableitet. Signale ohne Eintrag
// (congressional, superinvestor/dataroma, short_trend, unusual_volume, ftd)
// fuehren bewusst KEIN verlaessliches Datum — sie bekommen kein Badge, was
// die fehlende Frische-Garantie sichtbar macht.
const SIGNAL_DATE_FIELD = {
  insider_cluster: 'trade_date',
  large_buy: 'trade_date',
  buyback: 'filing_date',
  activist: 'filing_date',
  six_insider: 'latest_date',
}

// Liefert das relevante ISO-Datum eines Signals oder null.
function getSignalDate(signalKey, payload) {
  if (!payload) return null
  const field = SIGNAL_DATE_FIELD[signalKey]
  if (field) return payload[field] ?? null
  // 13F-Single: juengstes filing_date ueber alle Fonds
  if (signalKey === 'superinvestor_13f_single' && Array.isArray(payload.funds)) {
    const dates = payload.funds.map((f) => f?.filing_date).filter(Boolean).sort()
    return dates.length ? dates[dates.length - 1] : null
  }
  return null
}

function ageLabel(days) {
  if (days === 0) return 'heute'
  if (days === 1) return 'gestern'
  return `vor ${days} Tagen`
}

// Frische-Ampel: frisch (≤7d) gruen, normal (≤30d) neutral, alt (>30d) gelb.
function ageColor(days) {
  if (days <= 7) return 'text-success'
  if (days <= 30) return 'text-text-muted'
  return 'text-warning'
}

// Label-Mapping fuer haeufige Signal-Felder. Unbekannte Felder fallen
// auf snake_case → "Snake Case"-Titel zurueck.
const FIELD_LABELS = {
  trade_date: 'Trade-Datum',
  filing_date: 'Filing-Datum',
  latest_date: 'Letztes Datum',
  total_value: 'Total-Wert',
  total_amount_chf: 'Total CHF',
  value: 'Wert',
  price: 'Preis',
  insider_count: 'Anzahl Insider',
  num_investors: 'Anzahl Investoren',
  consensus_count: 'Konsens-Anzahl',
  transaction_count: 'Anzahl Transaktionen',
  investor: 'Investor',
  source: 'Quelle',
  form: 'Form',
  funds: 'Fonds',
  quarter: 'Quartal',
  quarter_status: 'Quartal-Status',
  quarter_ready_date: 'Bereit ab',
  action: 'Aktion',
  action_label: 'Aktion',
  letter_excerpt: 'Brief-Auszug',
  purpose_tags: 'Zweck',
  isin: 'ISIN',
  obligor_functions: 'Funktionen',
  score_applied: 'Score-Beitrag',
  change_pct: 'Aenderung %',
}

function titleCase(key) {
  return key.split('_').map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
}

function formatFieldValue(key, value) {
  if (value == null || value === '') return '—'
  // Datums-Felder
  if (key.endsWith('_date') || key === 'quarter_ready_date') {
    try {
      const d = new Date(value)
      if (!Number.isNaN(d.getTime())) {
        return d.toLocaleDateString('de-CH', { day: '2-digit', month: '2-digit', year: 'numeric' })
      }
    } catch { /* fall through */ }
  }
  // Currency-Felder (CHF)
  if (key === 'total_amount_chf') {
    return `CHF ${Number(value).toLocaleString('de-CH', { maximumFractionDigits: 0 })}`
  }
  // Currency-Felder (USD) — Insider-Daten sind in USD
  if (['total_value', 'value', 'price'].includes(key) && typeof value === 'number') {
    return `$${value.toLocaleString('de-CH', { maximumFractionDigits: 0 })}`
  }
  // Prozent
  if (key === 'change_pct' && typeof value === 'number') {
    return `${value.toFixed(1)} %`
  }
  // Arrays
  if (Array.isArray(value)) {
    if (value.length === 0) return '—'
    return value.join(', ')
  }
  // Strings/Numbers
  return String(value)
}

function SignalCard({ signalKey, payload }) {
  const cfg = SIGNAL_CONFIG[signalKey]
  const label = cfg?.label ?? titleCase(signalKey)
  const description = cfg?.description
  const weight = cfg?.weight ?? payload?.score_applied
  const weightColor = weight == null
    ? 'text-text-muted'
    : weight < 0 ? 'text-warning' : weight > 0 ? 'text-success' : 'text-text-muted'
  const weightLabel = weight == null ? '' : weight > 0 ? `+${weight}` : `${weight}`

  // Felder filtern — keine null/empty, kein score_applied (steht im Header)
  const entries = Object.entries(payload || {}).filter(
    ([k, v]) => v != null && v !== '' && k !== 'score_applied'
  )

  const signalDate = getSignalDate(signalKey, payload)
  const age = daysSince(signalDate)

  return (
    <li className="border border-border rounded-lg p-3 bg-card-alt/30">
      <div className="flex items-baseline justify-between mb-1">
        <div className="flex items-baseline gap-2 min-w-0">
          <span className="font-medium text-text-primary">{label}</span>
          {age != null && (
            <span
              className={`text-xs font-mono whitespace-nowrap ${ageColor(age)}`}
              title={`Signal-Datum: ${formatFieldValue('filing_date', signalDate)}`}
            >
              {ageLabel(age)}
            </span>
          )}
        </div>
        <span className={`text-sm font-mono ${weightColor}`}>{weightLabel}</span>
      </div>
      {description && <div className="text-xs text-text-muted mb-2">{description}</div>}
      {entries.length > 0 && (
        <dl className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-1 text-sm">
          {entries.map(([key, val]) => (
            <div key={key} className="contents">
              <dt className="text-text-muted">{FIELD_LABELS[key] ?? titleCase(key)}</dt>
              <dd className="text-text-primary font-mono break-all">{formatFieldValue(key, val)}</dd>
            </div>
          ))}
        </dl>
      )}
    </li>
  )
}

export default function SmartMoneyDetailModal({ ticker, onClose }) {
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const dialogRef = useRef(null)

  useEscClose(onClose)
  useFocusTrap(true)

  useEffect(() => {
    if (!ticker) return
    let active = true
    setLoading(true)
    setError(null)
    authFetch(`/api/screening/ticker/${ticker}`)
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then((json) => { if (active) { setDetail(json); setLoading(false) } })
      .catch((e) => { if (active) { setError(e.message); setLoading(false) } })
    return () => { active = false }
  }, [ticker])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
        className="bg-card border border-border rounded-lg shadow-xl w-full max-w-5xl max-h-[90vh] overflow-y-auto"
      >
        <div className="flex items-center justify-between p-4 border-b border-border sticky top-0 bg-card z-10">
          <div className="flex items-center gap-3">
            <TickerLogo ticker={ticker} size={28} />
            <div>
              <div className="font-mono text-lg font-semibold">{ticker}</div>
              {detail?.name && <div className="text-sm text-text-muted">{detail.name}</div>}
            </div>
          </div>
          <button onClick={onClose} aria-label="Schliessen" className="p-1 rounded hover:bg-card-hover">
            <X size={20} />
          </button>
        </div>

        <div className="p-4 space-y-5">
          {loading && <div className="text-text-muted">Lade Detail-Daten…</div>}
          {error && <div className="text-danger">Fehler: {error}</div>}

          {detail && (
            <>
              <section className="flex items-baseline gap-3">
                <h3 className="text-xs uppercase tracking-wide text-text-muted">Score</h3>
                <span className="font-mono text-3xl font-semibold text-primary leading-none">{detail.score_display}</span>
                <span className="text-sm text-text-muted">/100 (raw {detail.score})</span>
              </section>

              <section>
                <h3 className="text-xs uppercase tracking-wide text-text-muted mb-2">Signale</h3>
                <ul className="space-y-2">
                  {Object.entries(detail.signals || {}).map(([key, val]) => (
                    <SignalCard key={key} signalKey={key} payload={val} />
                  ))}
                </ul>
              </section>

              <section>
                <div className="flex items-baseline justify-between mb-2">
                  <h3 className="text-xs uppercase tracking-wide text-text-muted">Chart</h3>
                  <a
                    href={`https://www.tradingview.com/chart/?symbol=${encodeURIComponent(toTradingViewSymbol(ticker))}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-xs text-primary hover:text-primary/80 underline"
                  >
                    Auf TradingView öffnen
                    <ExternalLink size={12} />
                  </a>
                </div>
                <TradingViewMiniChart ticker={ticker} height={220} dateRange="12M" />
              </section>

              <section>
                <button
                  disabled
                  title="Kommt in Iteration 5 mit AI-Skill-Trigger"
                  className="w-full py-2 px-4 rounded bg-primary/30 text-text-muted cursor-not-allowed"
                >
                  Trade-Plan generieren (Iteration 5)
                </button>
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
