import { useState, useMemo } from 'react'
import { Radar } from 'lucide-react'
import { useApi } from '../hooks/useApi'
import SmartMoneyGrid from '../components/SmartMoneyGrid'
import SmartMoneyFilters from '../components/SmartMoneyFilters'
import SmartMoneyDetailModal from '../components/SmartMoneyDetailModal'

function formatScannedAt(iso) {
  if (!iso) return 'Noch kein Scan'
  try {
    const d = new Date(iso)
    return d.toLocaleString('de-CH', { dateStyle: 'medium', timeStyle: 'short' })
  } catch {
    return iso
  }
}

export default function SmartMoney() {
  const { data, loading, error } = useApi('/screening/results?min_score=1&per_page=200')
  const [selected, setSelected] = useState(null)
  const [filters, setFilters] = useState({
    minScore: 30,
    sectors: new Set(),
    momentums: new Set(),
    signals: new Set(),
  })

  const allRows = data?.results ?? []

  const availableSectors = useMemo(() => {
    const set = new Set()
    allRows.forEach((r) => { if (r.sector) set.add(r.sector) })
    return Array.from(set).sort()
  }, [allRows])

  const rows = useMemo(() => {
    return allRows
      .filter((r) => (r.score_display ?? 0) >= filters.minScore)
      .filter((r) => filters.sectors.size === 0 || filters.sectors.has(r.sector))
      .filter((r) => filters.momentums.size === 0 || filters.momentums.has(r.sector_momentum || 'neutral'))
      .filter((r) => {
        if (filters.signals.size === 0) return true
        const sigs = Object.keys(r.signals || {})
        return sigs.some((s) => filters.signals.has(s))
      })
      .sort((a, b) => (b.score_display ?? 0) - (a.score_display ?? 0))
  }, [allRows, filters])

  return (
    <div className="p-6">
      <header className="mb-6">
        <div className="flex items-center gap-3 mb-1">
          <Radar size={24} className="text-primary" />
          <h1 className="text-2xl font-semibold">Smart Money</h1>
        </div>
        <p className="text-sm text-text-muted max-w-3xl">
          Aggregation aus 12 institutionellen Daten-Pipelines: Insider-Käufe, 13F-Konsens, Buybacks, Aktivisten,
          Kongress-Trades, SIX-Insider, Estimate-Revisions u.a. — pro Ticker zu einem Composite-Score 0–100 verdichtet.
          Quelle: letzter abgeschlossener Daily-Scan (09:30 CET).
        </p>
        <div className="mt-2 text-xs text-text-muted font-mono">
          Letzter Scan: {formatScannedAt(data?.scanned_at)}
          {data?.total != null && ` · ${data.total} Ticker im Scan`}
        </div>
      </header>

      {loading && <div className="text-text-muted">Lade Smart-Money-Daten…</div>}
      {error && (
        <div className="p-4 bg-danger/10 border border-danger/30 text-danger rounded">
          Fehler beim Laden: {error}. Falls noch kein Scan gelaufen ist, wartet der erste auf 09:30 CET — oder manuell über das alte Screening-Cockpit triggern.
        </div>
      )}

      {!loading && !error && (
        <div className="flex gap-6">
          <SmartMoneyFilters
            filters={filters}
            setFilters={setFilters}
            availableSectors={availableSectors}
          />
          <div className="flex-1 min-w-0">
            <div className="mb-2 text-xs text-text-muted font-mono">
              {rows.length} von {allRows.length} Tickern sichtbar
            </div>
            <SmartMoneyGrid rows={rows} onSelect={setSelected} />
          </div>
        </div>
      )}

      {selected && (
        <SmartMoneyDetailModal ticker={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  )
}
