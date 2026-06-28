import { useState, useEffect, useMemo } from 'react'
import { useApi } from '../hooks/useApi'
import useDebouncedValue from '../hooks/useDebouncedValue'
import SmartMoneyGrid from '../components/SmartMoneyGrid'
import SmartMoneyFilters from '../components/SmartMoneyFilters'
import SmartMoneyDetailModal from '../components/SmartMoneyDetailModal'
import SmartMoneyPagination from '../components/SmartMoneyPagination'
import PageHeader from '../components/ui/PageHeader'
import Skeleton from '../components/Skeleton'
import { formatDateTime } from '../lib/format'

const PER_PAGE = 50

function formatScannedAt(iso) {
  if (!iso) return 'Noch kein Scan'
  return formatDateTime(iso)
}

function buildQuery({ minScore, sectors, momentums, signals, schwur1, schwur2, schwur3, page }) {
  const params = new URLSearchParams()
  params.set('per_page', String(PER_PAGE))
  params.set('page', String(page))
  if (minScore > 0) params.set('min_score_display', String(minScore))
  sectors.forEach((s) => params.append('sectors', s))
  momentums.forEach((m) => params.append('sector_momentums', m))
  signals.forEach((s) => params.append('signal_types', s))
  if (schwur1) params.set('schwur1_only', 'true')
  if (schwur2) params.set('schwur2_only', 'true')
  if (schwur3) params.set('schwur3_only', 'true')
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
    schwur1: false,
    schwur2: false,
    schwur3: false,
  })

  // Debounce nur den Slider — Checkbox-Klicks gehen sofort durch
  const debouncedMinScore = useDebouncedValue(filters.minScore, 300)

  // Stabile Query-Keys via sorted Array-Stringify
  const sectorsKey = useMemo(() => Array.from(filters.sectors).sort().join(','), [filters.sectors])
  const momentumsKey = useMemo(() => Array.from(filters.momentums).sort().join(','), [filters.momentums])
  const signalsKey = useMemo(() => Array.from(filters.signals).sort().join(','), [filters.signals])

  // Page-Reset bei Filter-Aenderung (debouncedMinScore + alle Multi-Sets + Schwur-Toggles)
  useEffect(() => {
    setPage(1)
  }, [debouncedMinScore, sectorsKey, momentumsKey, signalsKey, filters.schwur1, filters.schwur2, filters.schwur3])

  const query = useMemo(
    () =>
      buildQuery({
        minScore: debouncedMinScore,
        sectors: filters.sectors,
        momentums: filters.momentums,
        signals: filters.signals,
        schwur1: filters.schwur1,
        schwur2: filters.schwur2,
        schwur3: filters.schwur3,
        page,
      }),
    [debouncedMinScore, sectorsKey, momentumsKey, signalsKey, filters.schwur1, filters.schwur2, filters.schwur3, page]
  )

  const { data, loading, error } = useApi(`/screening/results?${query}`)

  const rows = data?.results ?? []
  const total = data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PER_PAGE))
  const availableSectors = data?.all_sectors ?? []

  return (
    <div className="pb-10">
      <PageHeader
        title="Smart Money"
        subtitle="13F · Insider · Buyback · Aktivist · Congress · Estimates"
        showBell={false}
        actions={
          <div className="hidden md:flex items-center gap-3 font-mono text-[11.5px] tabular-nums">
            <span className="text-text-faint">Scan: {formatScannedAt(data?.scanned_at)}</span>
            <span className="text-text-secondary">{total} Signale</span>
          </div>
        }
      />

      {error ? (
        <div className="rounded-card border border-danger/30 bg-danger/10 p-6">
          <p className="text-danger text-sm">
            Fehler beim Laden: {error}. Falls noch kein Scan gelaufen ist, wartet der erste auf den
            nächsten Daily-Cron um 09:30 CET.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-[236px_1fr] gap-6">
          <SmartMoneyFilters
            filters={filters}
            setFilters={setFilters}
            availableSectors={availableSectors}
          />
          <div className="min-w-0">
            {loading && rows.length === 0 ? (
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-[14px]">
                {Array.from({ length: 9 }).map((_, i) => (
                  <Skeleton key={i} className="h-[168px] rounded-card" />
                ))}
              </div>
            ) : (
              <>
                <SmartMoneyGrid rows={rows} onSelect={setSelected} />
                <SmartMoneyPagination
                  currentPage={page}
                  totalPages={totalPages}
                  totalItems={total}
                  onPageChange={setPage}
                />
              </>
            )}
          </div>
        </div>
      )}

      {selected && (
        <SmartMoneyDetailModal ticker={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  )
}
