import { useState, useEffect, useMemo } from 'react'
import { Radar } from 'lucide-react'
import { useApi } from '../hooks/useApi'
import useDebouncedValue from '../hooks/useDebouncedValue'
import SmartMoneyGrid from '../components/SmartMoneyGrid'
import SmartMoneyFilters from '../components/SmartMoneyFilters'
import SmartMoneyDetailModal from '../components/SmartMoneyDetailModal'
import SmartMoneyPagination from '../components/SmartMoneyPagination'

const PER_PAGE = 50

function formatScannedAt(iso) {
  if (!iso) return 'Noch kein Scan'
  try {
    const d = new Date(iso)
    return d.toLocaleString('de-CH', { dateStyle: 'medium', timeStyle: 'short' })
  } catch {
    return iso
  }
}

function buildQuery({ minScore, sectors, momentums, signals, page }) {
  const params = new URLSearchParams()
  params.set('per_page', String(PER_PAGE))
  params.set('page', String(page))
  if (minScore > 0) params.set('min_score_display', String(minScore))
  sectors.forEach((s) => params.append('sectors', s))
  momentums.forEach((m) => params.append('sector_momentums', m))
  signals.forEach((s) => params.append('signal_types', s))
  return params.toString()
}

export default function SmartMoney() {
  const [selected, setSelected] = useState(null)
  const [page, setPage] = useState(1)
  const [filters, setFilters] = useState({
    minScore: 30,
    sectors: new Set(),
    momentums: new Set(),
    signals: new Set(),
  })

  // Debounce nur den Slider — Checkbox-Klicks gehen sofort durch
  const debouncedMinScore = useDebouncedValue(filters.minScore, 300)

  // Stabile Query-Keys via sorted Array-Stringify
  const sectorsKey = useMemo(() => Array.from(filters.sectors).sort().join(','), [filters.sectors])
  const momentumsKey = useMemo(() => Array.from(filters.momentums).sort().join(','), [filters.momentums])
  const signalsKey = useMemo(() => Array.from(filters.signals).sort().join(','), [filters.signals])

  // Page-Reset bei Filter-Aenderung (debouncedMinScore + alle Multi-Sets)
  useEffect(() => {
    setPage(1)
  }, [debouncedMinScore, sectorsKey, momentumsKey, signalsKey])

  const query = useMemo(
    () =>
      buildQuery({
        minScore: debouncedMinScore,
        sectors: filters.sectors,
        momentums: filters.momentums,
        signals: filters.signals,
        page,
      }),
    [debouncedMinScore, sectorsKey, momentumsKey, signalsKey, page]
  )

  const { data, loading, error } = useApi(`/screening/results?${query}`)

  const rows = data?.results ?? []
  const total = data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PER_PAGE))
  const availableSectors = data?.all_sectors ?? []

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
        </p>
        <div className="mt-2 text-xs text-text-muted font-mono">
          Letzter Scan: {formatScannedAt(data?.scanned_at)}
          {total > 0 && ` · ${total} Ticker im Scan (nach Filter)`}
        </div>
      </header>

      {loading && rows.length === 0 && <div className="text-text-muted">Lade Smart-Money-Daten…</div>}
      {error && (
        <div className="p-4 bg-danger/10 border border-danger/30 text-danger rounded">
          Fehler beim Laden: {error}. Falls noch kein Scan gelaufen ist, wartet der erste auf den nächsten Daily-Cron um 09:30 CET.
        </div>
      )}

      {!error && (
        <div className="flex gap-6">
          <SmartMoneyFilters
            filters={filters}
            setFilters={setFilters}
            availableSectors={availableSectors}
          />
          <div className="flex-1 min-w-0">
            <SmartMoneyGrid rows={rows} onSelect={setSelected} />
            <SmartMoneyPagination
              currentPage={page}
              totalPages={totalPages}
              totalItems={total}
              onPageChange={setPage}
            />
          </div>
        </div>
      )}

      {selected && (
        <SmartMoneyDetailModal ticker={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  )
}
