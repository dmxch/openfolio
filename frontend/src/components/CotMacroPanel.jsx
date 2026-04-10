import { useEffect, useState } from 'react'
import { AlertTriangle, RotateCcw } from 'lucide-react'
import { authFetch } from '../hooks/useApi'

// COT Macro / Positioning Panel
// -----------------------------
// Isoliertes Makro-Panel fuer CFTC Commitments of Traders Daten.
// Kein Einfluss auf den Equity-Score — siehe SCOPE_SMART_MONEY_V4.md Block 1.

const EXTREME_LOW = 10
const EXTREME_HIGH = 90

function formatInt(value) {
  if (value === null || value === undefined) return '—'
  return Number(value).toLocaleString('de-CH')
}

function formatSigned(value) {
  if (value === null || value === undefined) return '—'
  const n = Number(value)
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toLocaleString('de-CH')}`
}

function PercentileBar({ value, label }) {
  if (value === null || value === undefined) {
    return (
      <div className="flex items-center gap-2">
        <span className="text-xs text-text-muted w-10 text-right">—</span>
        <div className="flex-1 h-2 rounded bg-border" />
      </div>
    )
  }

  const clamped = Math.max(0, Math.min(100, value))
  const isExtremeLow = clamped <= EXTREME_LOW
  const isExtremeHigh = clamped >= EXTREME_HIGH
  const barColor = isExtremeHigh
    ? 'bg-danger'
    : isExtremeLow
      ? 'bg-success'
      : 'bg-primary/60'

  let zoneText = 'Neutral'
  if (isExtremeHigh) zoneText = 'Extrem hoch'
  else if (isExtremeLow) zoneText = 'Extrem tief'

  return (
    <div
      className="flex items-center gap-2"
      role="img"
      aria-label={`${label} 52-Wochen Perzentil: ${clamped.toFixed(1)} Prozent, Zone: ${zoneText}`}
    >
      <span className="text-xs font-mono text-text-secondary w-10 text-right tabular-nums">
        {clamped.toFixed(0)}
      </span>
      <div className="flex-1 h-2 rounded bg-border overflow-hidden">
        <div
          className={`h-full ${barColor}`}
          style={{ width: `${clamped}%` }}
        />
      </div>
      {(isExtremeHigh || isExtremeLow) && (
        <span className={`text-[10px] uppercase tracking-wide font-semibold ${isExtremeHigh ? 'text-danger' : 'text-success'}`}>
          {isExtremeHigh ? 'Extr. +' : 'Extr. −'}
        </span>
      )}
    </div>
  )
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
      <div className="bg-card border border-border rounded-xl p-12 text-center">
        <RotateCcw size={24} className="text-text-muted mx-auto mb-3 animate-spin" />
        <p className="text-text-muted text-sm">COT-Daten werden geladen...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-warning/10 border border-warning/30 rounded-lg px-4 py-3 flex items-start gap-3">
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

  const hasAnyData = instruments.some(i => i.report_date)

  return (
    <div className="space-y-4">
      {/* Header / Disclaimer */}
      <div className="bg-primary/5 border border-primary/20 rounded-lg px-4 py-3 space-y-1.5">
        <p className="text-sm text-text-primary font-medium">
          CFTC Commitments of Traders — Positionierung institutioneller Akteure
        </p>
        <p className="text-xs text-text-secondary">
          Woechentliche Positionierung von Commercials (Hedger) und Managed Money (Spekulanten) in
          Futures-Maerkten. Perzentil-Bars zeigen die relative Positionierung ueber die letzten 52 Wochen.
          Extremzonen (≤ 10 oder ≥ 90) sind farblich und textlich markiert. Dieses Panel ist isoliert
          vom Equity-Screener und fliesst nicht in den Score ein.
        </p>
      </div>

      {/* Status row */}
      <div className="flex items-center justify-between text-xs text-text-muted">
        <span>
          {reportDate ? `Report-Datum: ${new Date(reportDate).toLocaleDateString('de-CH')}` : 'Noch keine Daten geladen'}
        </span>
        {updatedAt && (
          <span>Zuletzt aktualisiert: {new Date(updatedAt).toLocaleString('de-CH')}</span>
        )}
      </div>

      {/* Empty state */}
      {!hasAnyData && (
        <div className="bg-card border border-border rounded-xl p-12 text-center">
          <p className="text-text-secondary">
            Noch keine COT-Snapshots vorhanden. Der Worker laedt die Daten jeden Samstag um 09:00 Uhr.
          </p>
        </div>
      )}

      {/* Table */}
      {hasAnyData && (
        <div className="bg-card border border-border rounded-xl overflow-hidden">
          <table
            className="w-full text-sm"
            role="table"
            aria-label="CFTC COT Positionierung pro Instrument"
          >
            <thead>
              <tr className="border-b border-border text-left text-text-muted">
                <th scope="col" className="px-4 py-3 font-medium">Instrument</th>
                <th scope="col" className="px-4 py-3 font-medium">Report</th>
                <th scope="col" className="px-4 py-3 font-medium text-right">Commercial Net</th>
                <th scope="col" className="px-4 py-3 font-medium w-64">Commercial 52w-Perzentil</th>
                <th scope="col" className="px-4 py-3 font-medium text-right">Managed Money Net</th>
                <th scope="col" className="px-4 py-3 font-medium w-64">Managed Money 52w-Perzentil</th>
                <th scope="col" className="px-4 py-3 font-medium text-right">Open Interest</th>
              </tr>
            </thead>
            <tbody>
              {instruments.map(row => (
                <tr key={row.code} className="border-b border-border/50 hover:bg-card-alt/30 transition-colors">
                  <td className="px-4 py-3">
                    <div className="font-mono font-semibold text-text-primary">{row.code}</div>
                    <div className="text-xs text-text-muted">{row.name}</div>
                  </td>
                  <td className="px-4 py-3 text-text-secondary text-xs">
                    {row.report_date ? new Date(row.report_date).toLocaleDateString('de-CH') : '—'}
                    {row.history_weeks != null && (
                      <div className="text-text-muted">{row.history_weeks}w History</div>
                    )}
                  </td>
                  <td className={`px-4 py-3 text-right font-mono tabular-nums ${row.is_extreme_commercial ? 'font-semibold' : ''}`}>
                    {formatSigned(row.commercial_net)}
                  </td>
                  <td className="px-4 py-3">
                    <PercentileBar value={row.commercial_net_pct_52w} label={`${row.code} Commercial`} />
                  </td>
                  <td className={`px-4 py-3 text-right font-mono tabular-nums ${row.is_extreme_mm ? 'font-semibold' : ''}`}>
                    {formatSigned(row.mm_net)}
                  </td>
                  <td className="px-4 py-3">
                    <PercentileBar value={row.mm_net_pct_52w} label={`${row.code} Managed Money`} />
                  </td>
                  <td className="px-4 py-3 text-right font-mono tabular-nums text-text-secondary">
                    {formatInt(row.oi_total)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
