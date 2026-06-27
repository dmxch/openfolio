import { useApi } from '../hooks/useApi'
import { formatDate } from '../lib/format'
import { Globe, Loader2 } from 'lucide-react'

const CARD = "rounded-lg border border-white/[0.06] bg-card p-4 shadow-[0_1px_3px_rgba(0,0,0,0.3)]"

export default function EtfCountryLookthroughCard() {
  const { data, loading } = useApi('/analysis/country-lookthrough')

  if (loading) {
    return (
      <div className={CARD}>
        <div className="text-center py-6"><Loader2 size={18} className="animate-spin text-text-muted mx-auto" /></div>
      </div>
    )
  }
  // Kein Look-Through (keine ETFs oder keine Holdings-Daten) -> nichts anzeigen (kein Laerm).
  if (!data || !data.has_data) return null

  const countries = (data.countries || [])
  const maxPct = countries[0]?.pct || 100
  const etfs = data.etfs || []
  const withoutCount = (data.etfs_without_data || []).length
  // Juengster Quelle-Stichtag fuer den Coverage-Header.
  const asOf = etfs.map((e) => e.as_of).filter(Boolean).sort().slice(-1)[0]

  return (
    <div className={CARD}>
      <div className="flex items-center gap-2 mb-1">
        <Globe size={16} className="text-primary" />
        <h3 className="text-sm font-semibold text-text-primary">Geografische Verteilung (ETF-Durchsicht)</h3>
      </div>
      <p className="text-[11px] text-text-muted mb-3">
        Wo dein Kapital durch deine ETFs hindurch investiert ist
        {' '}— {etfs.length} ETF{etfs.length === 1 ? '' : 's'} mit Durchsicht
        {asOf ? `, Stand ${formatDate(asOf)}` : ''}
        {withoutCount > 0 ? `; ${withoutCount} ohne Look-Through-Daten` : ''}.
      </p>

      <div className="space-y-1.5">
        {countries.slice(0, 15).map((c) => (
          <div key={c.country} className="flex items-center gap-2 text-xs">
            <span className="w-36 text-text-secondary truncate" title={c.country}>{c.country}</span>
            <div className="flex-1 bg-card-alt rounded h-2 overflow-hidden">
              <div className="bg-primary h-full rounded" style={{ width: `${Math.min(100, (c.pct / maxPct) * 100)}%` }} />
            </div>
            <span className="w-12 text-right text-text-primary tabular-nums">{c.pct.toFixed(1)}%</span>
          </div>
        ))}
      </div>

      {etfs.length > 0 && (
        <div className="mt-3 pt-2 border-t border-border/50 text-[11px] text-text-muted flex flex-wrap gap-x-3 gap-y-0.5">
          {etfs.map((e) => (
            <span key={e.ticker}>
              {e.ticker} {e.coverage_pct}%{e.as_of ? ` (${formatDate(e.as_of)})` : ''}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
