import { AlertTriangle } from 'lucide-react'
import EpsQuarterCell from './EpsQuarterCell'
import EpsYoyBadge from './EpsYoyBadge'
import EpsStalenessTag, { stalenessLevel } from './EpsStalenessTag'
import TickerLogo from './TickerLogo'
import TickerChip from './ui/TickerChip'
import MiniChartTooltip from './MiniChartTooltip'

const DISPLAY_COLS = 8
const YOY_LAG = 4 // gleiche Quartalsdefinition wie Backend (4 Perioden zurueck)

// Per-Quartal-YoY clientseitig (nur pos->pos, sonst null) — gespiegelt zur
// Backend-/Detail-Logik, rein fuer die Heatmap-Faerbung der Zellen.
function withYoy(quarters) {
  return quarters.map((q, i) => {
    let yoy = null
    if (i >= YOY_LAG) {
      const base = quarters[i - YOY_LAG].eps
      if (base > 0 && q.eps > 0) yoy = ((q.eps - base) / Math.abs(base)) * 100
    }
    return { ...q, yoy }
  })
}

// Index-Badge: Large Cap (S&P 500) bleibt unmarkiert, um Rauschen zu reduzieren —
// markiert werden nur Mid/Small Cap, weil dort die EPS-Momentum-Signale am
// relevantesten sind.
const INDEX_BADGE = {
  sp400: { label: 'Mid', cls: 'bg-sky-500/15 text-sky-300', title: 'S&P 400 MidCap' },
  sp600: { label: 'Small', cls: 'bg-amber-500/15 text-amber-300', title: 'S&P 600 SmallCap' },
}

function IndexBadge({ index }) {
  const b = INDEX_BADGE[index]
  if (!b) return null
  return (
    <span className={`inline-flex items-center rounded-[5px] px-[6px] py-[2px] text-[10px] font-semibold leading-none ${b.cls}`} title={b.title} aria-label={b.title}>
      {b.label}
    </span>
  )
}

// Positionale Spalten-Header. Quartale verschiedener Firmen sind NICHT
// kalendarisch ausgerichtet (Fiskalquartal-Versatz, Doc OF-7) — daher
// relative Position; das konkrete Quartalsdatum steht je Zelle im aria-label.
function quarterHeaderLabel(idx) {
  if (idx === DISPLAY_COLS - 1) return 'Aktuell'
  return `Q−${DISPLAY_COLS - 1 - idx}`
}

const CHIP = 'inline-flex items-center rounded-[5px] px-[7px] py-[3px] text-[10.5px] font-medium leading-none'

function FlagChips({ row }) {
  const chips = []
  if (row.super_quarter) {
    chips.push(
      <span
        key="sq"
        className={`${CHIP} bg-primary/15 text-primary`}
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
        className={`${CHIP} gap-1 bg-success/15 text-success`}
        title="Record-Quartal — neues 8-Quartals-EPS-Hoch"
      >
        RQ
        {row.record_quarter_outlier && (
          <AlertTriangle size={11} className="text-warning" aria-label="möglicher Einmaleffekt" />
        )}
        {row.record_quarter_turnaround && (
          <span className="rounded-[4px] px-1 bg-violet-500/20 text-violet-300" title="Verlust → Gewinn">
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
        className={`${CHIP} gap-1 bg-warning/15 text-warning`}
        title="Möglicher Einmaleffekt — jüngstes EPS deutlich über dem Median der Vorquartale"
      >
        <AlertTriangle size={11} /> Outlier
      </span>
    )
  }
  if (row.turnaround) {
    chips.push(
      <span key="ta" className={`${CHIP} bg-violet-500/15 text-violet-300`} title="Turnaround: Verlust → Gewinn (im 8-Q-Fenster verlustig, jüngstes Quartal wieder profitabel)">
        TA
      </span>
    )
  }
  chips.push(<EpsStalenessTag key="stale" quarterCount={row.quarter_count} dataAgeDays={row.data_age_days} />)
  return <div className="flex flex-wrap items-center gap-1">{chips}</div>
}

function SortableHeader({ label, field, sortBy, sortAsc, onSort, align = 'left', className = '' }) {
  const active = sortBy === field
  const ariaSort = active ? (sortAsc ? 'ascending' : 'descending') : 'none'
  return (
    <th
      scope="col"
      aria-sort={ariaSort}
      className={`px-3 py-[11px] text-${align} font-medium ${className}`}
    >
      <button
        type="button"
        onClick={() => onSort(field)}
        className={`inline-flex items-center gap-1 hover:text-text-secondary focus:outline-none focus:ring-1 focus:ring-primary rounded ${active ? 'text-text-secondary' : ''}`}
      >
        {label}
        {active && <span aria-hidden="true">{sortAsc ? '▲' : '▼'}</span>}
      </button>
    </th>
  )
}

export default function EpsTable({ rows, sortBy, sortAsc, onSort, onSelect }) {
  if (!rows || rows.length === 0) {
    return (
      <div className="rounded-card border border-border bg-card p-12 text-center">
        <p className="text-text-muted text-sm">Keine Treffer für die aktuelle Filterung.</p>
      </div>
    )
  }
  return (
    <div className="rounded-card border border-border bg-card overflow-hidden">
      <div className="overflow-x-auto">
        <table role="table" className="w-full text-sm">
          <thead>
            <tr className="bg-table-head border-b border-border-2 font-mono text-[10px] uppercase tracking-[0.05em] text-text-faint">
              <SortableHeader label="Titel" field="ticker" sortBy={sortBy} sortAsc={sortAsc} onSort={onSort} className="pl-[18px]" />
              <th scope="col" className="px-3 py-[11px] text-left font-medium">Sektor</th>
              {Array.from({ length: DISPLAY_COLS }).map((_, i) => (
                <th key={i} scope="col" className="px-1.5 py-[11px] text-center font-medium whitespace-nowrap">
                  {quarterHeaderLabel(i)}
                </th>
              ))}
              <SortableHeader label="YoY" field="yoy_growth" sortBy={sortBy} sortAsc={sortAsc} onSort={onSort} align="right" />
              <SortableHeader label="Streak" field="streak_count" sortBy={sortBy} sortAsc={sortAsc} onSort={onSort} align="right" />
              <th scope="col" className="px-3 py-[11px] text-left font-medium">Flags</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const quarters = withYoy(row.quarters || [])
              const pad = Math.max(0, DISPLAY_COLS - quarters.length)
              const lvl = stalenessLevel(row.data_age_days)
              return (
                <tr
                  key={row.ticker}
                  onClick={() => onSelect?.(row)}
                  className="border-b border-border-row last:border-0 hover:bg-hover cursor-pointer transition-colors"
                >
                  <th scope="row" className="pl-[18px] pr-3 py-2.5 text-left whitespace-nowrap">
                    <div className="flex items-center gap-2.5 min-w-0">
                      <span
                        className="w-2 h-2 rounded-full shrink-0"
                        style={{ background: lvl ? lvl.color : '#7a8698' }}
                        title={lvl ? `Daten: ${lvl.label}` : 'Daten-Alter unbekannt'}
                        aria-label={lvl ? `Daten ${lvl.label}` : 'Daten-Alter unbekannt'}
                      />
                      <MiniChartTooltip ticker={row.ticker}>
                        <div className="flex items-center gap-2 min-w-0">
                          <TickerLogo ticker={row.ticker} size={18} />
                          <TickerChip>{row.ticker}</TickerChip>
                          <span className="text-text-muted text-xs truncate max-w-[160px] hidden xl:inline" title={row.name}>{row.name}</span>
                          <IndexBadge index={row.index} />
                        </div>
                      </MiniChartTooltip>
                    </div>
                  </th>
                  <td className="px-3 py-2.5 text-text-muted text-xs whitespace-nowrap">{row.sector || '—'}</td>
                  {Array.from({ length: pad }).map((_, i) => (
                    <td key={`pad-${i}`} className="px-1.5 py-2.5 text-center font-mono text-text-muted">—</td>
                  ))}
                  {quarters.map((q) => (
                    <EpsQuarterCell key={q.period_end} periodEnd={q.period_end} eps={q.eps} yoy={q.yoy} />
                  ))}
                  <td className="px-3 py-2.5 text-right">
                    <EpsYoyBadge yoyGrowthPct={row.yoy_growth_pct} yoyFlag={row.yoy_flag} />
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono tabular-nums text-text-secondary">
                    {row.streak_count ?? '—'}
                  </td>
                  <td className="px-3 py-2.5">
                    <FlagChips row={row} />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
