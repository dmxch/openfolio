import { useMemo, useState } from 'react'
import { ArrowDown, ArrowUp, ExternalLink } from 'lucide-react'
import { useApi } from '../hooks/useApi'
import { formatAbbrevUSD, formatPct, pnlColor } from '../lib/format'

const TRADINGVIEW_INDUSTRY_URL = 'https://de.tradingview.com/markets/stocks-usa/sectorandindustry-industry'

const PERIODS = [
  { key: '1w', label: '1W', field: 'perf_1w' },
  { key: '1m', label: '1M', field: 'perf_1m' },
  { key: '3m', label: '3M', field: 'perf_3m' },
  { key: '6m', label: '6M', field: 'perf_6m' },
  { key: 'ytd', label: 'YTD', field: 'perf_ytd' },
  { key: '1y', label: '1Y', field: 'perf_1y' },
]

// Flow-Dimensionen als eigene Sort-Keys (keine Perf-Spalte).
const FLOW_KEYS = {
  mcap: 'market_cap',
  mcap_delta: 'mcap_delta',
  turnover: 'turnover_ratio',
  rvol: 'rvol',
  concentration: 'top1_weight',
}

// Eine Branche gilt als "konzentriert" wenn der Top-1-Ticker >50% der MCap
// ausmacht ODER die effektive Mitgliederzahl (1/HHI) unter 5 liegt.
// Bei so einer Branche sind Flow-Metriken eher ein Einzelwert-Signal als
// ein echtes Branchen-Signal.
const CONCENTRATION_TOP1_THRESHOLD = 0.5
const CONCENTRATION_EFFN_THRESHOLD = 5
function isConcentrated(row) {
  if (row.top1_weight != null && row.top1_weight > CONCENTRATION_TOP1_THRESHOLD) return true
  if (row.effective_n != null && row.effective_n < CONCENTRATION_EFFN_THRESHOLD) return true
  return false
}

// Quick-Filter modes
const QUICK_ALL = 'all'
const QUICK_TOP = 'top15'
const QUICK_BOTTOM = 'bottom15'

// MCap-Filter: Millisekunde $-Schwellen in USD.
const MCAP_FILTERS = [
  { key: 'all', label: 'Alle', value: null },
  { key: '500m', label: '≥ $500M', value: 500_000_000 },
  { key: '1b', label: '≥ $1B', value: 1_000_000_000 },
  { key: '10b', label: '≥ $10B', value: 10_000_000_000 },
]

function formatScrapedAt(iso) {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    return d.toLocaleString('de-CH', {
      dateStyle: 'medium',
      timeStyle: 'short',
    })
  } catch {
    return iso
  }
}

function sortRows(rows, sortField, direction) {
  const multiplier = direction === 'asc' ? 1 : -1
  const withVal = []
  const withoutVal = []
  for (const r of rows || []) {
    const v = r[sortField]
    if (v == null) withoutVal.push(r)
    else withVal.push(r)
  }
  withVal.sort((a, b) => (a[sortField] - b[sortField]) * multiplier)
  return withVal.concat(withoutVal)
}

// Derive mcap_delta on the fly so it switches with the selected period.
function withDerivedFields(rows, perfField) {
  return (rows || []).map(r => ({
    ...r,
    mcap_delta: r.market_cap != null && r[perfField] != null
      ? r.market_cap * r[perfField] / 100
      : null,
  }))
}

export default function MarketIndustries() {
  const [period, setPeriod] = useState('ytd')
  const [quick, setQuick] = useState(QUICK_ALL)
  const [sortKey, setSortKey] = useState('ytd')
  const [sortDir, setSortDir] = useState('desc')
  const [mcapFilter, setMcapFilter] = useState('1b')
  const [hideConcentrated, setHideConcentrated] = useState(false)

  const mcapValue = useMemo(
    () => MCAP_FILTERS.find(f => f.key === mcapFilter)?.value ?? null,
    [mcapFilter],
  )

  // Server liefert alle 129 Branchen; MCap-Filter wird client-side angewendet
  // (konsistent mit dem client-side Perf-Period-Switcher).
  const { data, loading, error, refetch } = useApi('/market/industries?period=ytd')

  const perfField = useMemo(
    () => PERIODS.find(p => p.key === period)?.field ?? 'perf_ytd',
    [period],
  )

  const sortField = useMemo(() => {
    // Sort-Keys können Perioden-Keys (1w, 1m, …) ODER Flow-Keys sein.
    if (FLOW_KEYS[sortKey]) return FLOW_KEYS[sortKey]
    return PERIODS.find(p => p.key === sortKey)?.field ?? 'perf_ytd'
  }, [sortKey])

  const enriched = useMemo(
    () => withDerivedFields(data?.rows, perfField),
    [data, perfField],
  )

  const filtered = useMemo(() => {
    let out = enriched
    if (mcapValue != null) {
      out = out.filter(r => r.market_cap != null && r.market_cap >= mcapValue)
    }
    if (hideConcentrated) {
      out = out.filter(r => !isConcentrated(r))
    }
    return out
  }, [enriched, mcapValue, hideConcentrated])

  const visibleRows = useMemo(() => {
    const all = sortRows(filtered, sortField, sortDir)
    if (quick === QUICK_TOP) return all.slice(0, 15)
    if (quick === QUICK_BOTTOM) {
      const asc = sortRows(filtered, sortField, 'asc')
      return asc.slice(0, 15)
    }
    return all
  }, [filtered, sortField, sortDir, quick])

  const handleSort = (key) => {
    if (sortKey === key) {
      setSortDir(d => (d === 'desc' ? 'asc' : 'desc'))
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  const handlePeriodSwitch = (key) => {
    setPeriod(key)
    setSortKey(key)
    setSortDir('desc')
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-text-primary">Branchen-Rotation</h2>
          <p className="text-sm text-text-muted mt-1">
            US-Branchen ({filtered.length}{data?.count && data.count !== filtered.length ? ` von ${data.count}` : ''}) — Stand: {formatScrapedAt(data?.scraped_at)}
          </p>
        </div>
      </div>

      <div className="rounded-lg border border-border bg-card p-4 flex flex-wrap items-center gap-4">
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-muted">Zeitraum:</span>
          {PERIODS.map(p => (
            <button
              key={p.key}
              onClick={() => handlePeriodSwitch(p.key)}
              className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                period === p.key
                  ? 'bg-primary text-white'
                  : 'bg-card-alt text-text-secondary hover:text-text-primary'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
        <div className="h-6 w-px bg-border" />
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-muted">Quick:</span>
          {[
            { key: QUICK_ALL, label: `Alle${filtered.length ? ` (${filtered.length})` : ''}` },
            { key: QUICK_TOP, label: 'Top 15' },
            { key: QUICK_BOTTOM, label: 'Bottom 15' },
          ].map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setQuick(key)}
              className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                quick === key
                  ? 'bg-primary text-white'
                  : 'bg-card-alt text-text-secondary hover:text-text-primary'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="h-6 w-px bg-border" />
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-muted">MCap-Filter:</span>
          {MCAP_FILTERS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setMcapFilter(key)}
              className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                mcapFilter === key
                  ? 'bg-primary text-white'
                  : 'bg-card-alt text-text-secondary hover:text-text-primary'
              }`}
              title="Blendet Branchen unterhalb der MCap-Schwelle aus"
            >
              {label}
            </button>
          ))}
        </div>
        <div className="h-6 w-px bg-border" />
        <div className="flex items-center gap-2">
          <button
            onClick={() => setHideConcentrated(v => !v)}
            className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
              hideConcentrated
                ? 'bg-warning/20 text-warning border border-warning/40'
                : 'bg-card-alt text-text-secondary hover:text-text-primary'
            }`}
            title="Blendet Branchen mit Top-1 > 50% oder Eff-N < 5 aus (1-3 Ticker bestimmen die 'Branche')"
          >
            Konzentrierte ausblenden
          </button>
        </div>
      </div>

      {loading && (
        <div className="rounded-lg border border-border bg-card p-8 text-sm text-text-muted">
          Branchen werden geladen...
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-danger/30 bg-danger/10 p-5 text-sm text-danger flex items-center justify-between">
          <span>Branchen-Daten nicht verfügbar.</span>
          <button
            onClick={refetch}
            className="px-3 py-1 rounded bg-danger/20 text-danger hover:bg-danger/30 text-xs"
          >
            Erneut versuchen
          </button>
        </div>
      )}

      {!loading && !error && visibleRows.length > 0 && (
        <div className="rounded-lg border border-border bg-card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-text-muted">
                  <th className="text-left p-3 font-medium sticky left-0 bg-card">Branche</th>
                  <th className="text-right p-3 font-medium">Intraday</th>
                  {PERIODS.map(p => (
                    <SortHeader
                      key={p.key}
                      label={p.label}
                      active={sortKey === p.key}
                      direction={sortDir}
                      onClick={() => handleSort(p.key)}
                    />
                  ))}
                  <SortHeader
                    label="MCap"
                    active={sortKey === 'mcap'}
                    direction={sortDir}
                    onClick={() => handleSort('mcap')}
                    title="Aggregierte Marktkapitalisierung der Branche"
                  />
                  <SortHeader
                    label="MCap-Δ"
                    active={sortKey === 'mcap_delta'}
                    direction={sortDir}
                    onClick={() => handleSort('mcap_delta')}
                    title="Bewertungsveränderung im gewählten Zeitraum (MCap × Perf%). Nicht Kapitalzufluss."
                  />
                  <SortHeader
                    label="Turnover"
                    active={sortKey === 'turnover'}
                    direction={sortDir}
                    onClick={() => handleSort('turnover')}
                    title="Tages-Dollar-Volumen / MCap. 0.1–2% normal, >3% ungewöhnlich."
                  />
                  <SortHeader
                    label="RVOL"
                    active={sortKey === 'rvol'}
                    direction={sortDir}
                    onClick={() => handleSort('rvol')}
                    title="Heute / 20-Tage-Durchschnitt. Markt-Kontext nicht normalisiert (FOMC/VIX-Spikes pushen alles)."
                  />
                  <SortHeader
                    label="Konz."
                    active={sortKey === 'concentration'}
                    direction={sortDir}
                    onClick={() => handleSort('concentration')}
                    title="Top-1-Ticker + MCap-Anteil. Rot/orange wenn Top-1 > 50% oder Eff-N < 5: dann ist die 'Branche' praktisch ein Einzelwert."
                  />
                </tr>
              </thead>
              <tbody>
                {visibleRows.map(row => (
                  <IndustryRow key={row.slug} row={row} sortField={sortField} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!loading && !error && visibleRows.length === 0 && (
        <div className="rounded-lg border border-border bg-card p-8 text-sm text-text-muted">
          Noch keine Branchen-Snapshots vorhanden. Der tägliche Scraper läuft um 01:30 CET.
        </div>
      )}
    </div>
  )
}

function SortHeader({ label, active, direction, onClick, title }) {
  return (
    <th
      onClick={onClick}
      title={title}
      className={`text-right p-3 font-medium cursor-pointer select-none hover:text-text-primary ${
        active ? 'text-text-primary' : ''
      }`}
    >
      <span className="inline-flex items-center gap-1 justify-end">
        {label}
        {active && (direction === 'desc'
          ? <ArrowDown size={12} />
          : <ArrowUp size={12} />
        )}
      </span>
    </th>
  )
}

function formatTurnover(v) {
  if (v == null) return '—'
  return `${(v * 100).toFixed(3)}%`
}

function formatRvol(v) {
  if (v == null) return '—'
  return `${v.toFixed(1)}×`
}

function formatConcentration(row) {
  if (!row.top1_ticker || row.top1_weight == null) return '—'
  const pct = (row.top1_weight * 100).toFixed(0)
  const effN = row.effective_n != null ? ` · N${row.effective_n.toFixed(1)}` : ''
  return `${row.top1_ticker} ${pct}%${effN}`
}

function IndustryRow({ row, sortField }) {
  return (
    <tr className="border-b border-border/50 hover:bg-card-alt/50 transition-colors group">
      <td className="p-3 sticky left-0 bg-card group-hover:bg-card-alt/50">
        <a
          href={`${TRADINGVIEW_INDUSTRY_URL}/${row.slug}/`}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 text-text-primary hover:text-primary transition-colors"
          title={`${row.name} auf TradingView oeffnen`}
        >
          {row.name}
          <ExternalLink size={12} className="opacity-0 group-hover:opacity-60 transition-opacity" />
        </a>
      </td>
      <td className={`p-3 text-right ${pnlColor(row.change_pct)}`}>{formatPct(row.change_pct)}</td>
      {PERIODS.map(p => (
        <td
          key={p.key}
          className={`p-3 text-right ${pnlColor(row[p.field])} ${sortField === p.field ? 'font-semibold' : ''}`}
        >
          {formatPct(row[p.field])}
        </td>
      ))}
      <td
        className={`p-3 text-right text-text-secondary ${sortField === 'market_cap' ? 'font-semibold text-text-primary' : ''}`}
      >
        {formatAbbrevUSD(row.market_cap)}
      </td>
      <td
        className={`p-3 text-right ${pnlColor(row.mcap_delta)} ${sortField === 'mcap_delta' ? 'font-semibold' : ''}`}
      >
        {formatAbbrevUSD(row.mcap_delta)}
      </td>
      <td
        className={`p-3 text-right text-text-secondary ${sortField === 'turnover_ratio' ? 'font-semibold text-text-primary' : ''}`}
      >
        {formatTurnover(row.turnover_ratio)}
      </td>
      <td
        className={`p-3 text-right text-text-secondary ${sortField === 'rvol' ? 'font-semibold text-text-primary' : ''}`}
      >
        {formatRvol(row.rvol)}
      </td>
      <td
        className={`p-3 text-right tabular-nums ${
          isConcentrated(row) ? 'text-warning font-medium' : 'text-text-secondary'
        } ${sortField === 'top1_weight' ? 'font-semibold' : ''}`}
        title={isConcentrated(row)
          ? 'Konzentriert: Top-1 > 50% oder Eff-N < 5 — eher Einzelwert- als Branchen-Signal'
          : undefined}
      >
        {formatConcentration(row)}
      </td>
    </tr>
  )
}
