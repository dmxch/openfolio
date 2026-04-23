import { useMemo, useState } from 'react'
import { ArrowDown, ArrowUp, ExternalLink } from 'lucide-react'
import { useApi } from '../hooks/useApi'
import { formatPct, pnlColor } from '../lib/format'

const TRADINGVIEW_INDUSTRY_URL = 'https://de.tradingview.com/markets/stocks-usa/sectorandindustry-industry'

const PERIODS = [
  { key: '1w', label: '1W', field: 'perf_1w' },
  { key: '1m', label: '1M', field: 'perf_1m' },
  { key: '3m', label: '3M', field: 'perf_3m' },
  { key: '6m', label: '6M', field: 'perf_6m' },
  { key: 'ytd', label: 'YTD', field: 'perf_ytd' },
  { key: '1y', label: '1Y', field: 'perf_1y' },
]

// Quick-Filter modes
const QUICK_ALL = 'all'
const QUICK_TOP = 'top15'
const QUICK_BOTTOM = 'bottom15'

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

export default function MarketIndustries() {
  const [period, setPeriod] = useState('ytd')
  const [quick, setQuick] = useState(QUICK_ALL)
  const [sortKey, setSortKey] = useState('ytd')
  const [sortDir, setSortDir] = useState('desc')

  const { data, loading, error, refetch } = useApi(`/market/industries?period=${period}`)

  const sortField = useMemo(
    () => PERIODS.find(p => p.key === sortKey)?.field ?? 'perf_ytd',
    [sortKey],
  )

  const visibleRows = useMemo(() => {
    const all = sortRows(data?.rows ?? [], sortField, sortDir)
    if (quick === QUICK_TOP) return all.slice(0, 15)
    if (quick === QUICK_BOTTOM) {
      // "Bottom 15" always means worst by current sort field regardless of dir.
      const asc = sortRows(data?.rows ?? [], sortField, 'asc')
      return asc.slice(0, 15)
    }
    return all
  }, [data, sortField, sortDir, quick])

  // Clicking a column header toggles sort direction or selects a new column.
  const handleSort = (periodKey) => {
    if (sortKey === periodKey) {
      setSortDir(d => (d === 'desc' ? 'asc' : 'desc'))
    } else {
      setSortKey(periodKey)
      setSortDir('desc')
    }
  }

  // Period-switcher also sets the sort column (intuitive: switching the
  // "period of interest" sorts the table by that column).
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
            US-Branchen ({data?.count ?? '—'}) — Stand: {formatScrapedAt(data?.scraped_at)}
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
          <span className="text-xs text-text-muted">Filter:</span>
          {[
            { key: QUICK_ALL, label: `Alle${data?.count ? ` (${data.count})` : ''}` },
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

function SortHeader({ label, active, direction, onClick }) {
  return (
    <th
      onClick={onClick}
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
    </tr>
  )
}
