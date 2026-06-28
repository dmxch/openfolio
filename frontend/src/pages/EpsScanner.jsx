import { useState, useEffect, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import EpsFilters from '../components/EpsFilters'
import EpsTable from '../components/EpsTable'
import EpsDetailModal from '../components/EpsDetailModal'
import SmartMoneyPagination from '../components/SmartMoneyPagination'
import { STALENESS_LEVELS } from '../components/EpsStalenessTag'
import PageHeader from '../components/ui/PageHeader'
import { formatDateTime } from '../lib/format'

const PER_PAGE = 50

const DEFAULT_FILTERS = {
  superQuarterOnly: false,
  recordQuarterOnly: false,
  turnaroundOnly: false,
  minQuarters: 6,
  sectors: new Set(),
  indices: new Set(),
  search: '',
  sortBy: 'yoy_growth',
  sortAsc: false,
}

function formatRefreshedAt(iso) {
  if (!iso) return 'Noch kein Lauf'
  return formatDateTime(iso)
}

function StalenessLegend() {
  return (
    <div className="hidden lg:flex items-center gap-3.5">
      {STALENESS_LEVELS.map((l) => (
        <span key={l.key} className="inline-flex items-center gap-1.5 text-[11px] text-text-muted">
          <span className="w-2 h-2 rounded-full" style={{ background: l.color }} />
          {l.label}
        </span>
      ))}
    </div>
  )
}

function buildQuery({ superQuarterOnly, recordQuarterOnly, turnaroundOnly, minQuarters, sectors, indices, search, sortBy, sortAsc, page }) {
  const params = new URLSearchParams()
  params.set('per_page', String(PER_PAGE))
  params.set('page', String(page))
  params.set('min_quarters', String(minQuarters))
  params.set('sort_by', sortBy)
  params.set('sort_asc', sortAsc ? 'true' : 'false')
  if (superQuarterOnly) params.set('super_quarter_only', 'true')
  if (recordQuarterOnly) params.set('record_quarter_only', 'true')
  if (turnaroundOnly) params.set('turnaround_only', 'true')
  if (search && search.trim()) params.set('search', search.trim())
  sectors.forEach((s) => params.append('sector', s))
  indices.forEach((i) => params.append('index', i))
  return params.toString()
}

export default function EpsScanner() {
  const [searchParams] = useSearchParams()
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState(null)
  const [filters, setFilters] = useState({
    ...DEFAULT_FILTERS,
    sectors: new Set(),
    indices: new Set(),
    // Deep-Link vom EPS-Scanner-Kontext-Widget: ?search=TICKER vorfiltern.
    search: searchParams.get('search') || '',
  })

  const sectorsKey = useMemo(() => Array.from(filters.sectors).sort().join(','), [filters.sectors])
  const indicesKey = useMemo(() => Array.from(filters.indices).sort().join(','), [filters.indices])

  useEffect(() => {
    setPage(1)
  }, [filters.superQuarterOnly, filters.recordQuarterOnly, filters.turnaroundOnly, filters.minQuarters, sectorsKey, indicesKey, filters.search, filters.sortBy, filters.sortAsc])

  const query = useMemo(
    () =>
      buildQuery({
        superQuarterOnly: filters.superQuarterOnly,
        recordQuarterOnly: filters.recordQuarterOnly,
        turnaroundOnly: filters.turnaroundOnly,
        minQuarters: filters.minQuarters,
        sectors: filters.sectors,
        indices: filters.indices,
        search: filters.search,
        sortBy: filters.sortBy,
        sortAsc: filters.sortAsc,
        page,
      }),
    [filters.superQuarterOnly, filters.recordQuarterOnly, filters.turnaroundOnly, filters.minQuarters, sectorsKey, indicesKey, filters.search, filters.sortBy, filters.sortAsc, page]
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

  const handleReset = () => {
    setFilters({ ...DEFAULT_FILTERS, sectors: new Set(), indices: new Set() })
  }

  return (
    <div className="pb-10">
      <PageHeader
        title="EPS-Scanner"
        subtitle="Quartals-Gewinn-Screening"
        actions={<StalenessLegend />}
        showBell={false}
      />

      <div className="flex flex-col gap-[18px]">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <p className="text-[12px] text-text-muted max-w-3xl leading-relaxed">
            Scannt das S&amp;P 1500 (500 + 400 MidCap + 600 SmallCap) plus deine Positionen &amp; Watchlist auf
            Quartals-Gewinn-Momentum (Reported EPS). Das
            <span className="text-primary"> Super-Quartal</span> misst relative YoY-Beschleunigung, das
            <span className="text-success"> Record-Quartal</span> ein neues absolutes 8-Quartals-EPS-Hoch.
          </p>
          <span className="font-mono text-[10.5px] text-text-faint whitespace-nowrap pt-0.5">
            Zuletzt aktualisiert: {formatRefreshedAt(data?.data_refreshed_at)}
            {total > 0 && ` · ${total} Ticker`}
          </span>
        </div>

        {error ? (
          <div className="rounded-card border border-danger/30 bg-danger/10 p-6">
            <span className="text-danger text-sm">
              Fehler beim Laden: {error}. Falls noch kein Worker-Lauf erfolgt ist, wartet der erste auf den nächsten
              Daily-Cron um 04:00 CET.
            </span>
          </div>
        ) : (
          <div className="grid grid-cols-[236px_1fr] gap-[18px] items-start">
            <EpsFilters
              filters={filters}
              setFilters={setFilters}
              availableSectors={availableSectors}
              thresholds={thresholds}
              onThresholdsSaved={refetch}
              onReset={handleReset}
            />
            <div className="min-w-0">
              {loading && rows.length === 0 ? (
                <div className="rounded-card border border-border bg-card p-12 text-center text-text-muted text-sm">
                  Lade EPS-Daten…
                </div>
              ) : (
                <>
                  <EpsTable rows={rows} sortBy={filters.sortBy} sortAsc={filters.sortAsc} onSort={onSort} onSelect={setSelected} />
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
      </div>

      {selected && <EpsDetailModal row={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}
