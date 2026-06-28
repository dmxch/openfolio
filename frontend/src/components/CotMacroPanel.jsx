import { useEffect, useState } from 'react'
import { AlertTriangle, RotateCcw } from 'lucide-react'
import { authFetch } from '../hooks/useApi'
import { formatNumber, formatDate, formatDateTime } from '../lib/format'
import G from './GlossarTooltip'
import Card from './ui/Card'
import TickerChip from './ui/TickerChip'

// COT Macro / Positioning Panel
// -----------------------------
// Isoliertes Makro-Panel fuer CFTC Commitments of Traders Daten.
// Kein Einfluss auf den Equity-Score — siehe SCOPE_SMART_MONEY_V4.md Block 1.

const EXTREME_LOW = 10
const EXTREME_HIGH = 90

function formatInt(value) {
  if (value === null || value === undefined) return '—'
  return formatNumber(Number(value))
}

function formatSigned(value) {
  if (value === null || value === undefined) return '—'
  const n = Number(value)
  const sign = n > 0 ? '+' : ''
  return `${sign}${formatNumber(n)}`
}

// Divergierender Balken um eine Mittellinie: positiv (net long) = gruen rechts,
// negativ (net short) = rot links. Magnitude relativ zum groessten |net| der Liste.
function DivergingBar({ value, max }) {
  if (value === null || value === undefined || !max) {
    return <div className="relative h-2 rounded bg-border-row" />
  }
  const pos = value >= 0
  const pct = Math.min(100, (Math.abs(value) / max) * 100)
  return (
    <div className="relative h-2 rounded bg-border-row overflow-hidden">
      <div className="absolute left-1/2 top-0 bottom-0 w-px bg-border-chip" />
      <div
        className="absolute top-0 bottom-0"
        style={{
          [pos ? 'left' : 'right']: '50%',
          width: `${pct / 2}%`,
          background: pos ? '#45c08a' : '#e8625a',
        }}
      />
    </div>
  )
}

function ExtremeBadge({ pct, label }) {
  if (pct === null || pct === undefined) return null
  const clamped = Math.max(0, Math.min(100, pct))
  if (clamped >= EXTREME_HIGH) {
    return <span className="font-mono text-[10px] uppercase tracking-wide text-danger" title={`${label}: ${clamped.toFixed(0)}% (52w)`}>Extr. +</span>
  }
  if (clamped <= EXTREME_LOW) {
    return <span className="font-mono text-[10px] uppercase tracking-wide text-success" title={`${label}: ${clamped.toFixed(0)}% (52w)`}>Extr. −</span>
  }
  return null
}

function pctText(value) {
  if (value === null || value === undefined) return '–'
  return `P${Math.max(0, Math.min(100, value)).toFixed(0)}`
}

export default function CotMacroPanel() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let active = true
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const res = await authFetch('/api/screening/macro/cot')
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`)
        }
        const json = await res.json()
        if (active) setData(json)
      } catch (e) {
        if (active) setError(e.message || 'Fehler beim Laden')
      } finally {
        if (active) setLoading(false)
      }
    }
    load()
    return () => { active = false }
  }, [])

  if (loading) {
    return (
      <Card className="p-12 text-center">
        <RotateCcw size={22} className="text-text-muted mx-auto mb-3 animate-spin" />
        <p className="text-text-muted text-sm">COT-Daten werden geladen...</p>
      </Card>
    )
  }

  if (error) {
    return (
      <div className="rounded-card border border-warning/30 bg-warning/10 px-4 py-3 flex items-start gap-3">
        <AlertTriangle size={16} className="text-warning mt-0.5 shrink-0" />
        <div className="text-sm text-text-secondary">
          COT-Daten konnten nicht geladen werden: {error}
        </div>
      </div>
    )
  }

  const instruments = data?.instruments || []
  const reportDate = data?.report_date
  const updatedAt = data?.updated_at
  const hasAnyData = instruments.some((i) => i.report_date)

  const maxAbs = instruments.reduce(
    (m, i) => Math.max(m, Math.abs(Number(i.commercial_net) || 0)),
    0,
  )

  return (
    <Card className="overflow-hidden flex flex-col">
      <div className="px-[18px] py-4 border-b border-border-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2.5 min-w-0">
          <span className="w-[9px] h-[9px] rounded-[3px]" style={{ background: '#5b8def' }} />
          <h3 className="text-sm font-semibold text-text-primary truncate"><G term="CFTC">COT</G>-Positionierung</h3>
        </div>
        {reportDate && (
          <span className="font-mono text-[10.5px] text-text-faint whitespace-nowrap" title={updatedAt ? `Aktualisiert: ${formatDateTime(updatedAt)}` : ''}>
            {formatDate(reportDate)}
          </span>
        )}
      </div>

      {!hasAnyData ? (
        <div className="p-8 text-center">
          <p className="text-text-secondary text-sm">
            Noch keine COT-Snapshots vorhanden. Der Worker lädt die Daten jeden Samstag um 09:00 Uhr.
          </p>
        </div>
      ) : (
        <div className="px-[18px] py-1">
          {instruments.map((row) => (
            <div key={row.code} className="py-3 border-b border-border-row2 last:border-0">
              <div className="flex items-center justify-between gap-2 mb-2">
                <div className="flex items-center gap-2 min-w-0">
                  <TickerChip>{row.code}</TickerChip>
                  <span className="text-[11.5px] text-text-muted truncate">{row.name}</span>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  <ExtremeBadge pct={row.commercial_net_pct_52w} label={`${row.code} Commercial`} />
                  <span className={`font-mono text-[12.5px] tabular-nums ${row.is_extreme_commercial ? 'font-semibold text-text-primary' : 'text-text-secondary'}`}>
                    {formatSigned(row.commercial_net)}
                  </span>
                </div>
              </div>
              <DivergingBar value={row.commercial_net} max={maxAbs} />
              <div className="flex items-center justify-between mt-1.5 font-mono text-[10.5px] text-text-faint tabular-nums">
                <span><G term="Commercial">Comm</G> {pctText(row.commercial_net_pct_52w)}</span>
                <span><G term="Managed Money">MM</G> {formatSigned(row.mm_net)} · {pctText(row.mm_net_pct_52w)}</span>
                <span><G term="Open Interest">OI</G> {formatInt(row.oi_total)}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="px-[18px] py-3 border-t border-border-2 mt-auto">
        <p className="text-[11px] text-text-muted leading-relaxed">
          <G term="CFTC">CFTC</G> Commitments of Traders — wöchentliche Positionierung von <G term="Commercial">Commercials</G> (Hedger)
          und <G term="Managed Money">Managed Money</G> (Spekulanten). Balken = Netto-Position der Commercials, Mittellinie = neutral.
          Isoliert vom Equity-Screener, fliesst nicht in den Score ein.
        </p>
      </div>
    </Card>
  )
}
