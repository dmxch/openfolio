import { AlertTriangle } from 'lucide-react'
import EpsQuarterCell from './EpsQuarterCell'
import EpsYoyBadge from './EpsYoyBadge'
import EpsStalenessTag from './EpsStalenessTag'
import TickerLogo from './TickerLogo'
import MiniChartTooltip from './MiniChartTooltip'

const DISPLAY_COLS = 8

// Positionale Spalten-Header. Quartale verschiedener Firmen sind NICHT
// kalendarisch ausgerichtet (Fiskalquartal-Versatz, Doc OF-7) — daher
// relative Position; das konkrete Quartalsdatum steht je Zelle im aria-label.
function quarterHeaderLabel(idx) {
  if (idx === DISPLAY_COLS - 1) return 'Aktuell'
  return `Q−${DISPLAY_COLS - 1 - idx}`
}

function FlagChips({ row }) {
  const chips = []
  if (row.super_quarter) {
    chips.push(
      <span
        key="sq"
        className="inline-block px-1.5 py-0.5 rounded text-xs bg-primary/15 text-primary"
        title="Super-Quartal-Kriterien erfüllt. Schwellenwerte (25% / +5pp) sind Arbeits-Defaults, noch nicht durch Forward-Return-Backtest validiert."
      >
        SQ
      </span>
    )
  }
  if (row.record_quarter) {
    chips.push(
      <span
        key="rq"
        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs bg-success/15 text-success"
        title="Record-Quartal — neues 8-Quartals-EPS-Hoch"
      >
        RQ
        {row.record_quarter_outlier && (
          <AlertTriangle size={11} className="text-warning" aria-label="möglicher Einmaleffekt" />
        )}
        {row.record_quarter_turnaround && (
          <span className="px-1 rounded bg-violet-500/20 text-violet-300" title="Verlust → Gewinn">
            Turnaround
          </span>
        )}
      </span>
    )
  }
  if (row.outlier_flag && !row.record_quarter_outlier) {
    chips.push(
      <span
        key="out"
        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs bg-warning/15 text-warning"
        title="Möglicher Einmaleffekt — jüngstes EPS deutlich über dem Median der Vorquartale"
      >
        <AlertTriangle size={11} /> Outlier
      </span>
    )
  }
  if (row.turnaround) {
    chips.push(
      <span key="ta" className="inline-block px-1.5 py-0.5 rounded text-xs bg-violet-500/15 text-violet-300" title="Turnaround: Verlust → Gewinn (im 8-Q-Fenster verlustig, jüngstes Quartal wieder profitabel)">
        TA
      </span>
    )
  }
  chips.push(<EpsStalenessTag key="stale" quarterCount={row.quarter_count} dataAgeDays={row.data_age_days} />)
  return <div className="flex flex-wrap items-center gap-1">{chips}</div>
}

function SortableHeader({ label, field, sortBy, sortAsc, onSort, align = 'left' }) {
  const active = sortBy === field
  const ariaSort = active ? (sortAsc ? 'ascending' : 'descending') : 'none'
  return (
    <th
      scope="col"
      aria-sort={ariaSort}
      className={`px-2 py-2 text-${align} font-medium text-text-secondary`}
    >
      <button
        type="button"
        onClick={() => onSort(field)}
        className="inline-flex items-center gap-1 hover:text-text-primary focus:outline-none focus:ring-2 focus:ring-primary rounded"
      >
        {label}
        {active && <span aria-hidden="true">{sortAsc ? '▲' : '▼'}</span>}
      </button>
    </th>
  )
}

export default function EpsTable({ rows, sortBy, sortAsc, onSort, onSelect }) {
  if (!rows || rows.length === 0) {
    return <div className="text-text-muted p-6">Keine Treffer für die aktuelle Filterung.</div>
  }
  return (
    <div className="overflow-x-auto border border-border rounded-lg">
      <table role="table" className="min-w-full text-sm">
        <thead className="bg-card-alt border-b border-border">
          <tr>
            <SortableHeader label="Ticker" field="ticker" sortBy={sortBy} sortAsc={sortAsc} onSort={onSort} />
            <th scope="col" className="px-2 py-2 text-left font-medium text-text-secondary">Name</th>
            {Array.from({ length: DISPLAY_COLS }).map((_, i) => (
              <th key={i} scope="col" className="px-2 py-2 text-right font-medium text-text-secondary whitespace-nowrap">
                {quarterHeaderLabel(i)}
              </th>
            ))}
            <SortableHeader label="YoY%" field="yoy_growth" sortBy={sortBy} sortAsc={sortAsc} onSort={onSort} align="right" />
            <SortableHeader label="Streak" field="streak_count" sortBy={sortBy} sortAsc={sortAsc} onSort={onSort} align="right" />
            <th scope="col" className="px-2 py-2 text-left font-medium text-text-secondary">Flags</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const quarters = row.quarters || []
            const pad = Math.max(0, DISPLAY_COLS - quarters.length)
            return (
              <tr
                key={row.ticker}
                onClick={() => onSelect?.(row)}
                className="border-b border-border last:border-0 hover:bg-card-alt/40 cursor-pointer transition-colors"
              >
                <th scope="row" className="px-2 py-1.5 text-left whitespace-nowrap">
                  <MiniChartTooltip ticker={row.ticker}>
                    <div className="flex items-center gap-2">
                      <TickerLogo ticker={row.ticker} size={18} />
                      <span className="font-mono font-semibold text-text-primary">{row.ticker}</span>
                    </div>
                  </MiniChartTooltip>
                </th>
                <td className="px-2 py-1.5 text-text-secondary truncate max-w-[12rem]" title={row.name}>
                  {row.name}
                </td>
                {Array.from({ length: pad }).map((_, i) => (
                  <td key={`pad-${i}`} className="px-2 py-1.5 text-right text-text-muted">—</td>
                ))}
                {quarters.map((q) => (
                  <EpsQuarterCell key={q.period_end} periodEnd={q.period_end} eps={q.eps} />
                ))}
                <td className="px-2 py-1.5 text-right">
                  <EpsYoyBadge yoyGrowthPct={row.yoy_growth_pct} yoyFlag={row.yoy_flag} />
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums text-text-secondary">
                  {row.streak_count ?? '—'}
                </td>
                <td className="px-2 py-1.5">
                  <FlagChips row={row} />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
