import { Fragment, useMemo, useState } from 'react'
import { ArrowDown, ArrowUp, ChevronDown, ChevronRight, ExternalLink, RefreshCw } from 'lucide-react'
import { useApi } from '../hooks/useApi'
import { formatAbbrevUSD, formatDateTime, formatPct, pnlColor } from '../lib/format'
import PageHeader from '../components/ui/PageHeader'
import StatTile from '../components/ui/StatTile'
import FilterChips from '../components/ui/FilterChips'
import Button from '../components/ui/Button'
import TickerChip from '../components/ui/TickerChip'
import Skeleton from '../components/Skeleton'

const TRADINGVIEW_INDUSTRY_URL = 'https://de.tradingview.com/markets/stocks-usa/sectorandindustry-industry'
const TRADINGVIEW_SYMBOL_URL = 'https://de.tradingview.com/symbols'

// Spaltenzahl der Haupttabelle: Branche + Intraday + Perioden + 5 Flow-Spalten
// (MCap, MCap-Δ, Turnover, RVOL, Konz.). Genutzt für colSpan der Drill-down-Zeile.
const COLUMN_COUNT = 2 + 6 + 5

const PERIODS = [
  { key: '1w', label: '1W', field: 'perf_1w' },
  { key: '1m', label: '1M', field: 'perf_1m' },
  { key: '3m', label: '3M', field: 'perf_3m' },
  { key: '6m', label: '6M', field: 'perf_6m' },
  { key: 'ytd', label: 'YTD', field: 'perf_ytd' },
  { key: '1y', label: '1J', field: 'perf_1y' },
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

// rel. Volumen gilt als erhöht (amber) ab 1.5× des 20-Tage-Schnitts.
const RVOL_HIGH_THRESHOLD = 1.5

// Quick-Filter modes
const QUICK_ALL = 'all'
const QUICK_TOP = 'top15'
const QUICK_BOTTOM = 'bottom15'

// MCap-Filter: $-Schwellen in USD.
const MCAP_FILTERS = [
  { key: 'all', label: 'Alle', value: null },
  { key: '500m', label: '≥ $500M', value: 500_000_000 },
  { key: '1b', label: '≥ $1B', value: 1_000_000_000 },
  { key: '10b', label: '≥ $10B', value: 10_000_000_000 },
]

function formatScrapedAt(iso) {
  if (!iso) return '—'
  return formatDateTime(iso)
}

// Grün/rot-Tint nach Vorzeichen und Betrag (Heatmap-Zelle). Volle Intensität
// ab ~20% Bewegung. Liefert undefined bei null → Zelle bleibt neutral.
function heatStyle(v) {
  if (v == null) return undefined
  const mag = Math.min(Math.abs(v) / 20, 1)
  const a = (0.07 + mag * 0.33).toFixed(3)
  if (v > 0) return { background: `rgba(69,192,138,${a})` }
  if (v < 0) return { background: `rgba(232,98,90,${a})` }
  return undefined
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
  // Drill-down: genau eine Branche gleichzeitig aufgeklappt (begrenzt Live-Calls).
  const [expandedSlug, setExpandedSlug] = useState(null)

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

  const periodLabel = useMemo(
    () => PERIODS.find(p => p.key === period)?.label ?? 'YTD',
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

  // Summary-Kacheln — ausschliesslich aus den vorhandenen Branchen-Zeilen
  // abgeleitet (keine erfundenen Zahlen). Marktbreite = Anteil Branchen mit
  // positiver Rendite im gewählten Zeitraum.
  const stats = useMemo(() => {
    const withPerf = filtered.filter(r => r[perfField] != null)
    if (!withPerf.length) return null
    const up = withPerf.filter(r => r[perfField] > 0).length
    const breadth = (up / withPerf.length) * 100
    let strongest = withPerf[0]
    let weakest = withPerf[0]
    for (const r of withPerf) {
      if (r[perfField] > strongest[perfField]) strongest = r
      if (r[perfField] < weakest[perfField]) weakest = r
    }
    return { up, total: withPerf.length, breadth, strongest, weakest }
  }, [filtered, perfField])

  // Momentum-Heatmap: stärkste Branchen im gewählten Zeitraum.
  const momentum = useMemo(
    () => sortRows(filtered, perfField, 'desc').filter(r => r[perfField] != null).slice(0, 24),
    [filtered, perfField],
  )

  const maxAbs = useMemo(() => {
    const vals = filtered.map(r => r[perfField]).filter(v => v != null).map(Math.abs)
    return vals.length ? Math.max(...vals) : 1
  }, [filtered, perfField])

  const leaders = useMemo(
    () => sortRows(filtered, perfField, 'desc').filter(r => r[perfField] != null).slice(0, 4),
    [filtered, perfField],
  )
  const laggards = useMemo(
    () => sortRows(filtered, perfField, 'asc').filter(r => r[perfField] != null).slice(0, 4),
    [filtered, perfField],
  )

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

  const toggleExpand = (slug) => {
    setExpandedSlug(prev => (prev === slug ? null : slug))
  }

  const renderRsBar = (r) => {
    const v = r[perfField]
    const width = maxAbs ? Math.min((Math.abs(v) / maxAbs) * 100, 100) : 0
    return (
      <div key={r.slug} className="flex items-center gap-2.5">
        <span className="text-[11.5px] text-text-secondary truncate w-[40%]" title={r.name}>{r.name}</span>
        <div className="flex-1 h-[7px] rounded-full bg-card-2 overflow-hidden">
          <div
            className="h-full rounded-full"
            style={{ width: `${width}%`, background: v >= 0 ? '#45c08a' : '#e8625a' }}
          />
        </div>
        <span className={`font-mono text-[11.5px] tabular-nums w-[58px] text-right ${pnlColor(v)}`}>
          {formatPct(v)}
        </span>
      </div>
    )
  }

  const periodSelector = (
    <div className="flex items-center gap-0.5 bg-surface border border-border rounded-lg p-1">
      {PERIODS.map(p => (
        <button
          key={p.key}
          onClick={() => handlePeriodSwitch(p.key)}
          className={`font-mono text-[11px] px-2.5 py-[5px] rounded-md border transition-colors ${
            period === p.key
              ? 'bg-active-tint text-text-bright border-border-active'
              : 'border-transparent text-text-muted hover:text-text-primary'
          }`}
        >
          {p.label}
        </button>
      ))}
    </div>
  )

  const quickOptions = [
    { key: QUICK_ALL, label: 'Alle', count: filtered.length },
    { key: QUICK_TOP, label: 'Stark' },
    { key: QUICK_BOTTOM, label: 'Schwach' },
  ]
  const mcapOptions = MCAP_FILTERS.map(({ key, label }) => ({ key, label }))

  return (
    <div className="pb-10">
      <PageHeader
        title="Branchen"
        subtitle="Sektor- & Industrie-Analyse"
        actions={periodSelector}
        showBell={false}
      />

      <div className="flex flex-col gap-[18px]">
        {loading && (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-[14px]">
              {[1, 2, 3, 4].map(i => <Skeleton key={i} className="h-[92px] rounded-card" />)}
            </div>
            <Skeleton className="h-[420px] rounded-card" />
          </>
        )}

        {error && (
          <div className="rounded-card border border-danger/30 bg-danger/10 p-6 flex items-center justify-between">
            <span className="text-danger text-sm">Branchen-Daten nicht verfügbar.</span>
            <Button variant="primary" icon={RefreshCw} onClick={refetch}>Erneut versuchen</Button>
          </div>
        )}

        {!loading && !error && (
          <>
            {/* Summary-Tiles */}
            {stats && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-[14px]">
                <StatTile
                  label="Marktbreite"
                  value={`${stats.breadth.toFixed(0)}%`}
                  sub={`${stats.up} / ${stats.total} im Plus`}
                  tone={stats.breadth >= 55 ? 'success' : stats.breadth <= 45 ? 'danger' : 'warning'}
                  subTone="muted"
                />
                <StatTile
                  label="Stärkster Sektor"
                  value={formatPct(stats.strongest[perfField])}
                  sub={stats.strongest.name}
                  tone="success"
                  subTone="muted"
                />
                <StatTile
                  label="Schwächster Sektor"
                  value={formatPct(stats.weakest[perfField])}
                  sub={stats.weakest.name}
                  tone="danger"
                  subTone="muted"
                />
                <StatTile
                  label="Branchen"
                  value={filtered.length}
                  sub={`Stand ${formatScrapedAt(data?.scraped_at)}`}
                  tone="bright"
                  subTone="muted"
                />
              </div>
            )}

            {/* Haupt-Karte: Sektor-Performance & Flows */}
            <div className="bg-card border border-border rounded-card overflow-hidden">
              <div className="px-[18px] py-4 border-b border-border-2 flex items-center justify-between gap-4 flex-wrap">
                <div className="flex items-center gap-2.5">
                  <span className="w-[9px] h-[9px] rounded-[3px]" style={{ background: '#5b8def' }} />
                  <h3 className="text-sm font-semibold text-text-primary">Sektor-Performance &amp; Flows</h3>
                </div>
                <div className="flex items-center gap-3 flex-wrap">
                  <FilterChips options={quickOptions} value={quick} onChange={setQuick} />
                  <span className="w-px h-5 bg-border-2 hidden lg:block" />
                  <FilterChips options={mcapOptions} value={mcapFilter} onChange={setMcapFilter} />
                  <span className="w-px h-5 bg-border-2 hidden lg:block" />
                  <button
                    onClick={() => setHideConcentrated(v => !v)}
                    role="switch"
                    aria-checked={hideConcentrated}
                    title="Blendet Branchen mit Top-1 > 50% oder Eff-N < 5 aus (1-3 Ticker bestimmen die 'Branche')"
                    className="inline-flex items-center gap-2 text-[12px] text-text-muted hover:text-text-primary transition-colors"
                  >
                    <span className={`relative w-[34px] h-[18px] rounded-full transition-colors ${hideConcentrated ? 'bg-primary' : 'bg-border-hover'}`}>
                      <span className={`absolute top-[2px] w-[14px] h-[14px] rounded-full bg-white transition-all ${hideConcentrated ? 'left-[18px]' : 'left-[2px]'}`} />
                    </span>
                    Konzentrierte ausblenden
                  </button>
                </div>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-sm min-w-[1160px]">
                  <thead>
                    <tr className="bg-table-head border-b border-border-2 font-mono text-[10px] uppercase tracking-[0.05em] text-text-faint">
                      <th className="sticky left-0 z-20 bg-table-head text-left pl-[18px] pr-3 py-[11px] font-medium">Sektor</th>
                      <th className="px-3 py-[11px] font-medium text-right whitespace-nowrap">Intraday</th>
                      {PERIODS.map(p => {
                        const isSorted = sortKey === p.key
                        const isSel = period === p.key
                        return (
                          <th
                            key={p.key}
                            onClick={() => handleSort(p.key)}
                            title={`Nach ${p.label} sortieren`}
                            className={`px-2.5 py-[11px] font-medium text-center whitespace-nowrap cursor-pointer select-none transition-colors ${
                              isSorted ? 'text-text-primary' : 'hover:text-text-secondary'
                            } ${isSel ? 'border-x border-border-active bg-active-tint/40' : ''}`}
                          >
                            <span className="inline-flex items-center gap-1 justify-center">
                              {p.label}
                              {isSorted && (sortDir === 'desc' ? <ArrowDown size={11} /> : <ArrowUp size={11} />)}
                            </span>
                          </th>
                        )
                      })}
                      <SortHeader
                        label="MCap"
                        active={sortKey === 'mcap'}
                        direction={sortDir}
                        onClick={() => handleSort('mcap')}
                        title="Aggregierte Marktkapitalisierung der Branche"
                      />
                      <SortHeader
                        label="Δ MCap"
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
                        label="rel. Vol"
                        active={sortKey === 'rvol'}
                        direction={sortDir}
                        onClick={() => handleSort('rvol')}
                        title="Heute / 20-Tage-Durchschnitt. Markt-Kontext nicht normalisiert (FOMC/VIX-Spikes pushen alles)."
                      />
                      <SortHeader
                        label="Top-1"
                        active={sortKey === 'concentration'}
                        direction={sortDir}
                        onClick={() => handleSort('concentration')}
                        title="Top-1-Ticker + MCap-Anteil. Amber wenn Top-1 > 50% oder Eff-N < 5: dann ist die 'Branche' praktisch ein Einzelwert."
                      />
                    </tr>
                  </thead>
                  <tbody>
                    {visibleRows.map(row => (
                      <IndustryRow
                        key={row.slug}
                        row={row}
                        sortField={sortField}
                        selectedKey={period}
                        expanded={expandedSlug === row.slug}
                        onToggle={() => toggleExpand(row.slug)}
                        perfField={perfField}
                        periodLabel={periodLabel}
                        colSpan={COLUMN_COUNT}
                      />
                    ))}
                    {visibleRows.length === 0 && (
                      <tr>
                        <td colSpan={COLUMN_COUNT} className="px-6 py-12 text-center text-sm text-text-muted">
                          {filtered.length === 0 && enriched.length > 0
                            ? 'Keine Branchen für diese Filter.'
                            : 'Noch keine Branchen-Snapshots vorhanden. Der tägliche Scraper läuft um 01:30 CET.'}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Momentum + Relative Stärke */}
            {filtered.length > 0 && (
              <div className="grid grid-cols-1 xl:grid-cols-[1.6fr_1fr] gap-[18px]">
                <div className="bg-card border border-border rounded-card overflow-hidden">
                  <div className="px-[18px] py-4 border-b border-border-2 flex items-center justify-between">
                    <h3 className="text-sm font-semibold text-text-primary">Industrie-Momentum</h3>
                    <span className="font-mono text-[10.5px] tracking-[0.06em] uppercase text-text-label">{periodLabel}</span>
                  </div>
                  <div className="p-3 grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-4 gap-2">
                    {momentum.map(r => (
                      <div
                        key={r.slug}
                        className="rounded-lg border border-border-2 p-2.5"
                        style={heatStyle(r[perfField])}
                        title={r.name}
                      >
                        <div className="text-[11px] text-text-bright truncate">{r.name}</div>
                        <div className="font-mono text-[13px] tabular-nums font-semibold text-text-bright mt-1">
                          {formatPct(r[perfField])}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="bg-card border border-border rounded-card overflow-hidden">
                  <div className="px-[18px] py-4 border-b border-border-2">
                    <h3 className="text-sm font-semibold text-text-primary">Relative Stärke</h3>
                  </div>
                  <div className="p-[18px] flex flex-col gap-5">
                    <div>
                      <div className="font-mono text-[10.5px] tracking-[0.06em] uppercase text-success mb-3">Führend</div>
                      <div className="flex flex-col gap-2.5">
                        {leaders.map(renderRsBar)}
                      </div>
                    </div>
                    <div>
                      <div className="font-mono text-[10.5px] tracking-[0.06em] uppercase text-danger mb-3">Schwach</div>
                      <div className="flex flex-col gap-2.5">
                        {laggards.map(renderRsBar)}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function SortHeader({ label, active, direction, onClick, title }) {
  return (
    <th
      onClick={onClick}
      title={title}
      className={`px-3 py-[11px] font-medium text-right whitespace-nowrap cursor-pointer select-none transition-colors ${
        active ? 'text-text-primary' : 'hover:text-text-secondary'
      }`}
    >
      <span className="inline-flex items-center gap-1 justify-end">
        {label}
        {active && (direction === 'desc' ? <ArrowDown size={11} /> : <ArrowUp size={11} />)}
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

function IndustryRow({ row, sortField, selectedKey, expanded, onToggle, perfField, periodLabel, colSpan }) {
  const concentrated = isConcentrated(row)
  const highRvol = row.rvol != null && row.rvol >= RVOL_HIGH_THRESHOLD
  return (
    <Fragment>
      <tr className="border-b border-border-row hover:bg-hover transition-colors group">
        <td className={`sticky left-0 z-10 pl-[18px] pr-3 py-3 transition-colors ${expanded ? 'bg-hover' : 'bg-card'} group-hover:bg-hover`}>
          <div className="flex items-center gap-2">
            <button
              onClick={onToggle}
              className="text-text-muted hover:text-text-primary transition-colors shrink-0"
              title={expanded ? 'Aktien einklappen' : 'Aktien dieser Branche anzeigen'}
              aria-expanded={expanded}
              aria-controls={`industry-members-${row.slug}`}
            >
              {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>
            <a
              href={`${TRADINGVIEW_INDUSTRY_URL}/${row.slug}/`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-[12.5px] text-text-primary hover:text-primary transition-colors"
              title={`${row.name} auf TradingView öffnen`}
            >
              {row.name}
              <ExternalLink size={11} className="opacity-0 group-hover:opacity-50 transition-opacity" />
            </a>
          </div>
        </td>
        <td className={`px-3 py-3 text-right font-mono tabular-nums ${pnlColor(row.change_pct)}`}>
          {formatPct(row.change_pct)}
        </td>
        {PERIODS.map(p => {
          const v = row[p.field]
          const isSel = p.key === selectedKey
          return (
            <td
              key={p.key}
              className={`px-2.5 py-3 text-center font-mono tabular-nums ${
                v == null ? 'text-text-faint' : 'text-text-bright'
              } ${sortField === p.field ? 'font-semibold' : ''} ${isSel ? 'border-x border-border-active' : ''}`}
              style={heatStyle(v)}
            >
              {v == null ? '–' : formatPct(v)}
            </td>
          )
        })}
        <td className={`px-3 py-3 text-right font-mono tabular-nums ${sortField === 'market_cap' ? 'font-semibold text-text-primary' : 'text-text-secondary'}`}>
          {formatAbbrevUSD(row.market_cap)}
        </td>
        <td className={`px-3 py-3 text-right font-mono tabular-nums ${pnlColor(row.mcap_delta)} ${sortField === 'mcap_delta' ? 'font-semibold' : ''}`}>
          {formatAbbrevUSD(row.mcap_delta)}
        </td>
        <td className={`px-3 py-3 text-right font-mono tabular-nums ${sortField === 'turnover_ratio' ? 'font-semibold text-text-primary' : 'text-text-secondary'}`}>
          {formatTurnover(row.turnover_ratio)}
        </td>
        <td className={`px-3 py-3 text-right font-mono tabular-nums ${
          highRvol ? 'text-warning font-medium' : 'text-text-secondary'
        } ${sortField === 'rvol' ? 'font-semibold' : ''}`}>
          {formatRvol(row.rvol)}
        </td>
        <td
          className={`px-3 py-3 text-right font-mono tabular-nums ${
            concentrated ? 'text-warning font-medium' : 'text-text-secondary'
          } ${sortField === 'top1_weight' ? 'font-semibold' : ''}`}
          title={concentrated
            ? 'Konzentriert: Top-1 > 50% oder Eff-N < 5 — eher Einzelwert- als Branchen-Signal'
            : undefined}
        >
          {formatConcentration(row)}
        </td>
      </tr>
      {expanded && (
        <tr className="border-b border-border-row">
          <td colSpan={colSpan} className="p-0" id={`industry-members-${row.slug}`}>
            <IndustryMembers
              slug={row.slug}
              perfField={perfField}
              periodLabel={periodLabel}
              industryMcap={row.market_cap}
            />
          </td>
        </tr>
      )}
    </Fragment>
  )
}

function IndustryMembers({ slug, perfField, periodLabel, industryMcap }) {
  const { data, loading, error, refetch } = useApi(
    `/market/industries/${encodeURIComponent(slug)}/members?limit=50`,
  )

  if (loading) {
    return <div className="px-[18px] py-4 bg-card-2 text-xs text-text-muted">Aktien werden geladen…</div>
  }
  if (error) {
    return (
      <div className="px-[18px] py-4 bg-card-2 text-xs text-danger flex items-center gap-3">
        <span>Aktien dieser Branche nicht verfügbar.</span>
        <button
          onClick={refetch}
          className="px-2 py-0.5 rounded bg-danger/20 text-danger hover:bg-danger/30"
        >
          Erneut versuchen
        </button>
      </div>
    )
  }

  const members = data?.members ?? []
  if (members.length === 0) {
    return <div className="px-[18px] py-4 bg-card-2 text-xs text-text-muted">Keine Einzelaktien gefunden.</div>
  }

  return (
    <div className="px-[18px] py-4 bg-card-2">
      <div className="font-mono text-[10.5px] tracking-[0.06em] uppercase text-text-label mb-3">Grösste Titel</div>
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-2.5">
        {members.map(m => {
          const weight = industryMcap && m.market_cap != null ? (m.market_cap / industryMcap) * 100 : null
          const card = (
            <div className="bg-card border border-border rounded-lg p-3 hover:border-border-hover transition-colors h-full">
              <div className="flex items-center justify-between gap-2 mb-2">
                <TickerChip>{m.ticker}</TickerChip>
                <span className="font-mono text-[10.5px] text-text-muted tabular-nums">
                  {weight != null ? `${weight.toFixed(1)}%` : '—'}
                </span>
              </div>
              <div className="text-[11px] text-text-secondary truncate mb-2" title={m.name || ''}>
                {m.name ?? '—'}
              </div>
              <div className="flex items-center justify-between">
                <span className="font-mono text-[9.5px] uppercase tracking-[0.05em] text-text-faint">{periodLabel}</span>
                <span className={`font-mono text-[12px] tabular-nums font-medium ${pnlColor(m[perfField])}`}>
                  {formatPct(m[perfField])}
                </span>
              </div>
            </div>
          )
          return m.exchange ? (
            <a
              key={m.ticker}
              href={`${TRADINGVIEW_SYMBOL_URL}/${m.exchange}-${encodeURIComponent(m.ticker)}/`}
              target="_blank"
              rel="noopener noreferrer"
              title={`${m.ticker} auf TradingView öffnen`}
            >
              {card}
            </a>
          ) : (
            <div key={m.ticker}>{card}</div>
          )
        })}
      </div>
      {data?.count >= 50 && (
        <p className="text-[11px] text-text-muted mt-3">Sortiert nach Marktkapitalisierung (max. 50).</p>
      )}
    </div>
  )
}
