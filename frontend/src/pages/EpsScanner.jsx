import { useState, useEffect, useMemo } from 'react'
import { TrendingUp } from 'lucide-react'
import { useApi } from '../hooks/useApi'
import EpsFilters from '../components/EpsFilters'
import EpsTable from '../components/EpsTable'
import SmartMoneyPagination from '../components/SmartMoneyPagination'
import { formatDateTime } from '../lib/format'

const PER_PAGE = 50

function formatRefreshedAt(iso) {
  if (!iso) return 'Noch kein Lauf'
  return formatDateTime(iso)
}

function buildQuery({ superQuarterOnly, recordQuarterOnly, minQuarters, sectors, sortBy, sortAsc, page }) {
  const params = new URLSearchParams()
  params.set('per_page', String(PER_PAGE))
  params.set('page', String(page))
  params.set('min_quarters', String(minQuarters))
  params.set('sort_by', sortBy)
  params.set('sort_asc', sortAsc ? 'true' : 'false')
  if (superQuarterOnly) params.set('super_quarter_only', 'true')
  if (recordQuarterOnly) params.set('record_quarter_only', 'true')
  sectors.forEach((s) => params.append('sector', s))
  return params.toString()
}

export default function EpsScanner() {
  const [page, setPage] = useState(1)
  const [filters, setFilters] = useState({
    superQuarterOnly: false,
    recordQuarterOnly: false,
    minQuarters: 6,
    sectors: new Set(),
    sortBy: 'yoy_growth',
    sortAsc: false,
  })

  const sectorsKey = useMemo(() => Array.from(filters.sectors).sort().join(','), [filters.sectors])

  useEffect(() => {
    setPage(1)
  }, [filters.superQuarterOnly, filters.recordQuarterOnly, filters.minQuarters, sectorsKey, filters.sortBy, filters.sortAsc])

  const query = useMemo(
    () =>
      buildQuery({
        superQuarterOnly: filters.superQuarterOnly,
        recordQuarterOnly: filters.recordQuarterOnly,
        minQuarters: filters.minQuarters,
        sectors: filters.sectors,
        sortBy: filters.sortBy,
        sortAsc: filters.sortAsc,
        page,
      }),
    [filters.superQuarterOnly, filters.recordQuarterOnly, filters.minQuarters, sectorsKey, filters.sortBy, filters.sortAsc, page]
  )

  const { data, loading, error, refetch } = useApi(`/eps-scanner/results?${query}`)

  const rows = data?.results ?? []
  const total = data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PER_PAGE))
  const thresholds = data?.thresholds ?? null
  const availableSectors = useMemo(() => {
    const set = new Set()
    rows.forEach((r) => { if (r.sector) set.add(r.sector) })
    return Array.from(set).sort()
  }, [rows])

  const onSort = (field) => {
    setFilters((f) => {
      if (f.sortBy === field) return { ...f, sortAsc: !f.sortAsc }
      return { ...f, sortBy: field, sortAsc: field === 'ticker' }
    })
  }

  return (
    <div className="p-6">
      <header className="mb-6">
        <div className="flex items-center gap-3 mb-1">
          <TrendingUp size={24} className="text-primary" />
          <h1 className="text-2xl font-semibold">EPS-Scanner</h1>
        </div>
        <p className="text-sm text-text-muted max-w-3xl">
          Scannt das S&P-500-Universum auf Quartals-Gewinn-Momentum (Reported EPS). Das
          <span className="text-primary"> Super-Quartal</span> misst relative YoY-Beschleunigung, das
          <span className="text-success"> Record-Quartal</span> ein neues absolutes 8-Quartals-EPS-Hoch.
        </p>
        <div className="mt-2 text-xs text-text-muted font-mono">
          Zuletzt aktualisiert: {formatRefreshedAt(data?.data_refreshed_at)}
          {total > 0 && ` · ${total} Ticker (nach Filter)`}
        </div>
      </header>

      {loading && rows.length === 0 && <div className="text-text-muted">Lade EPS-Daten…</div>}
      {error && (
        <div className="p-4 bg-danger/10 border border-danger/30 text-danger rounded">
          Fehler beim Laden: {error}. Falls noch kein Worker-Lauf erfolgt ist, wartet der erste auf den nächsten
          Daily-Cron um 04:00 CET.
        </div>
      )}

      {!error && (
        <div className="flex gap-6">
          <EpsFilters
            filters={filters}
            setFilters={setFilters}
            availableSectors={availableSectors}
            thresholds={thresholds}
            onThresholdsSaved={refetch}
          />
          <div className="flex-1 min-w-0">
            <EpsTable rows={rows} sortBy={filters.sortBy} sortAsc={filters.sortAsc} onSort={onSort} />
            <SmartMoneyPagination
              currentPage={page}
              totalPages={totalPages}
              totalItems={total}
              onPageChange={setPage}
            />
          </div>
        </div>
      )}
    </div>
  )
}
