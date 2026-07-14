import { useState, useEffect } from 'react'
import { formatCHF } from '../lib/format'
import { authFetch } from '../hooks/useApi'
import { CHART_COLORS } from '../lib/chartColors'

const PALETTE_TYPE = {
  stock: CHART_COLORS.primary, etf: '#8b5cf6', bond: '#d9739e', crypto: CHART_COLORS.warning, commodity: CHART_COLORS.success,
  cash: CHART_COLORS.textMuted, pension: '#06b6d4', real_estate: '#805AD5', private_equity: '#059669',
}
const PALETTE_SECTOR = [
  CHART_COLORS.primary, CHART_COLORS.success, CHART_COLORS.warning, CHART_COLORS.danger, '#8b5cf6',
  '#06b6d4', '#ec4899', '#84cc16', '#f97316', '#14b8a6', '#6366f1',
  '#a855f7', CHART_COLORS.textMuted,
]
const PALETTE_CCY = { CHF: CHART_COLORS.danger, USD: CHART_COLORS.primary, EUR: CHART_COLORS.success, CAD: CHART_COLORS.warning, GBP: '#8b5cf6' }

const TYPE_LABELS = {
  stock: 'Aktien', etf: 'ETFs', bond: 'Anleihen', crypto: 'Crypto', commodity: 'Rohstoffe',
  cash: 'Cash', pension: 'Pension', real_estate: 'Immobilien', private_equity: 'Private Equity',
}

const EXCLUDED_SECTORS = new Set(['Cash', 'Pension'])

// Invested asset types that get their own sector category
const TYPE_TO_SECTOR = {
  crypto: 'Crypto',
  commodity: 'Commodities',
  private_equity: 'Private Equity',
}
// Types excluded from sector chart entirely (shown in Anlageklasse widget).
// Anleihen sind strukturell sektorlos: sie fehlen im Zähler, müssen also auch
// aus dem Nenner — sonst verwässert jede Aufstockung still die Sektor-Prozente.
const SECTOR_EXCLUDED_TYPES = new Set(['cash', 'pension', 'bond'])

const SECTOR_COLORS = {
  'Commodities': '#D4A017',
  'Crypto': '#F7931A',
  'Cash': '#6B7280',
  'Pension': '#8B5CF6',
  'Vorsorge': '#8B5CF6',
  'Private Equity': '#059669',
  'Multi-Sector (unverteilt)': '#374151',
}

function getColor(chartType, name, index, dataPoint) {
  if (chartType === 'bucket') {
    // User-defined Bucket-Farbe nutzen, sonst Fallback
    if (dataPoint?.color) return dataPoint.color
    return PALETTE_SECTOR[index % PALETTE_SECTOR.length]
  }
  if (chartType === 'type') return PALETTE_TYPE[name] || PALETTE_SECTOR[index % PALETTE_SECTOR.length]
  if (chartType === 'currency') return PALETTE_CCY[name] || PALETTE_SECTOR[index % PALETTE_SECTOR.length]
  if (SECTOR_COLORS[name]) return SECTOR_COLORS[name]
  return PALETTE_SECTOR[index % PALETTE_SECTOR.length]
}

const TYPE_SUFFIXES = { pension: 'Vorsorge', cash: 'Cash' }

function buildTooltipMap(positions, realEstateEquity, etfSectorMap) {
  if (!positions?.length) return {}

  const map = { type: {}, sector: {}, currency: {} }

  const addTo = (category, key, item) => {
    if (!map[category][key]) map[category][key] = []
    map[category][key].push(item)
  }

  for (const p of positions) {
    if (p.shares <= 0) continue
    // count_as_cash-ETFs (Geldmarkt/T-Bill) zaehlen ueberall als Cash.
    const isCashLike = !!p.count_as_cash
    const suffix = isCashLike ? 'Cash' : TYPE_SUFFIXES[p.type]
    const item = suffix
      ? { ...p, _displayName: `${p.name} (${suffix})` }
      : p

    // By type
    const typeKey = isCashLike ? 'cash' : (p.type || 'stock')
    addTo('type', typeKey, item)

    // By sector: cash-klassifizierte und sektorlose Positionen (Cash/Vorsorge/
    // Anleihen) werden aus dem Sektor-Chart ausgeschlossen — dieselbe Regel wie
    // in filterSectors, damit Tooltip und Balken dieselbe Basis zeigen.
    // Währung läuft weiter (echte FX-Exposure).
    if (!isCashLike && !SECTOR_EXCLUDED_TYPES.has(p.type)) {
      const isMultiSector = p.is_multi_sector
      const etfWeights = isMultiSector ? etfSectorMap?.[p.ticker] : null
      if (isMultiSector && etfWeights?.length) {
        for (const sw of etfWeights) {
          const sectorValue = p.market_value_chf * sw.weight_pct / 100
          addTo('sector', sw.sector, { ...item, market_value_chf: sectorValue, _displayName: `${p.ticker} (${sw.weight_pct}%)` })
        }
      } else if (isMultiSector) {
        addTo('sector', 'Multi-Sector (unverteilt)', item)
      } else if (p.sector && !EXCLUDED_SECTORS.has(p.sector)) {
        addTo('sector', p.sector, item)
      } else if (TYPE_TO_SECTOR[p.type]) {
        // Crypto/Commodity get their own sector category
        addTo('sector', TYPE_TO_SECTOR[p.type], item)
      }
      // Cash and Pension are excluded from sector chart (shown in Anlageklasse)
    }

    // By currency
    if (p.currency) {
      addTo('currency', p.currency, item)
    }
  }

  // Inject synthetic real estate entry
  if (realEstateEquity > 0) {
    const reItem = {
      id: '_real_estate',
      ticker: '',
      name: 'Immobilien-Eigenkapital',
      _displayName: 'Immobilien-Eigenkapital',
      market_value_chf: realEstateEquity,
    }
    addTo('type', 'real_estate', reItem)
    addTo('sector', 'Immobilien', reItem)
    addTo('currency', 'CHF', reItem)
  }

  // Sort each group by value descending
  for (const cat of Object.values(map)) {
    for (const key of Object.keys(cat)) {
      cat[key].sort((a, b) => b.market_value_chf - a.market_value_chf)
    }
  }

  return map
}

function AllocationBar({ title, data, chartType, tooltipMap }) {
  const [tooltip, setTooltip] = useState(null)

  if (!data?.length) return null

  const maxPct = Math.max(...data.map((d) => d.pct))

  const handleMouseMove = (e, name) => {
    const items = tooltipMap?.[name] || []
    if (items.length === 0) { setTooltip(null); return }
    setTooltip({ x: e.clientX + 16, y: e.clientY - 8, name, items })
  }

  return (
    <div className="rounded-card border border-border bg-card overflow-hidden">
      <div className="px-[18px] py-3.5 border-b border-border-2">
        <h4 className="text-sm font-semibold text-text-primary">{title}</h4>
      </div>
      <div className="p-[18px] space-y-2.5">
        {data.map((d, i) => {
          const color = getColor(chartType, d.name, i, d)
          const label = chartType === 'type' ? (TYPE_LABELS[d.name] || d.name) : d.name
          return (
            <div
              key={d.name}
              className="group"
              onMouseMove={(e) => handleMouseMove(e, d.name)}
              onMouseLeave={() => setTooltip(null)}
            >
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-2 w-24 shrink-0">
                  <div className="w-2 h-2 rounded-full shrink-0" style={{ background: color }} />
                  <span className="text-xs text-text-secondary truncate" title={label}>{label}</span>
                </div>
                <div className="flex-1 h-2 rounded-full bg-card-2 overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all"
                    style={{ width: `${maxPct > 0 ? (d.pct / maxPct) * 100 : 0}%`, background: color }}
                  />
                </div>
                <span className="text-xs font-mono font-semibold text-text-primary tabular-nums w-12 text-right">{d.pct.toFixed(1)}%</span>
              </div>
            </div>
          )
        })}
      </div>
      {tooltip && (
        <div
          style={{ position: 'fixed', left: tooltip.x, top: tooltip.y, zIndex: 9999, pointerEvents: 'none' }}
          className="bg-modal border border-border-hover rounded-lg shadow-xl p-3 max-w-xs"
        >
          <p className="text-xs font-semibold text-text-primary mb-2">
            {chartType === 'type' ? (TYPE_LABELS[tooltip.name] || tooltip.name) : tooltip.name}
          </p>
          {tooltip.items.slice(0, 10).map((p) => (
            <div key={p.id} className="flex justify-between gap-4 text-xs py-0.5">
              <span className="text-text-secondary truncate">{p.ticker ? `${p.ticker} ` : ''}{p._displayName || p.name}</span>
              <span className="text-text-primary font-mono font-medium tabular-nums whitespace-nowrap">{formatCHF(p.market_value_chf)}</span>
            </div>
          ))}
          {tooltip.items.length > 10 && (
            <div className="text-xs text-text-secondary pt-1">+{tooltip.items.length - 10} weitere</div>
          )}
        </div>
      )}
    </div>
  )
}

const PI2 = 2 * Math.PI

// Mitte des Donuts: Anzahl Kategorien + Label — konsistent zum Uebersicht-Widget
// AllocationDonutCard (zeigt ebenfalls den Count) und nicht-redundant (der
// Gesamtwert waere in allen drei Tab-Donuts derselbe).
const DONUT_CENTER_LABEL = { bucket: 'BUCKETS', type: 'KLASSEN', currency: 'WÄHRUNGEN' }

// Donut-Variante von AllocationBar: identische Daten ({name,value_chf,pct,color?}),
// dieselben Farben (getColor) und derselbe Positions-Tooltip beim Hover ueber eine
// Legende-Zeile. Donut oben, Legende darunter (konsistent zum Uebersicht-Widget).
// Die Segment-Anteile kommen aus value_chf (schliesst den Ring garantiert), die
// Legende zeigt pct wie die Balken.
function AllocationDonut({ title, data, chartType, tooltipMap }) {
  const [tooltip, setTooltip] = useState(null)
  const items = (data || []).filter((d) => (d.value_chf ?? 0) > 0)
  if (!items.length) return null

  const total = items.reduce((s, d) => s + (d.value_chf ?? 0), 0)
  const R = 54
  const CIRC = PI2 * R
  let cursor = 0
  const segments = items.map((d, i) => {
    const frac = total > 0 && d.value_chf != null ? d.value_chf / total : (d.pct ?? 0) / 100
    const len = frac * CIRC
    const seg = {
      name: d.name,
      color: getColor(chartType, d.name, i, d),
      label: chartType === 'type' ? (TYPE_LABELS[d.name] || d.name) : d.name,
      pct: frac * 100,
      dash: `${len.toFixed(3)} ${(CIRC - len).toFixed(3)}`,
      offset: (-cursor * CIRC).toFixed(3),
    }
    cursor += frac
    return seg
  })

  const handleHover = (e, name) => {
    const list = tooltipMap?.[name] || []
    if (!list.length) { setTooltip(null); return }
    setTooltip({ x: e.clientX + 16, y: e.clientY - 8, name, items: list })
  }

  return (
    <div className="rounded-card border border-border bg-card overflow-hidden">
      <div className="px-[18px] py-3.5 border-b border-border-2">
        <h4 className="text-sm font-semibold text-text-primary">{title}</h4>
      </div>
      <div className="p-[18px] flex flex-col items-center gap-4">
        <svg viewBox="0 0 140 140" className="w-full max-w-[180px] aspect-square">
          <g transform="rotate(-90 70 70)">
            {segments.map((s) => (
              <circle
                key={s.name}
                cx="70"
                cy="70"
                r={R}
                fill="none"
                stroke={s.color}
                strokeWidth="18"
                strokeDasharray={s.dash}
                strokeDashoffset={s.offset}
              />
            ))}
          </g>
          <text x="70" y="66" textAnchor="middle" className="fill-text-primary font-sans tabular-nums" fontSize="17" fontWeight="600">{items.length}</text>
          <text x="70" y="82" textAnchor="middle" className="fill-text-muted font-mono" fontSize="9" letterSpacing="0.06em">{DONUT_CENTER_LABEL[chartType] || ''}</text>
        </svg>
        <div className="w-full flex flex-col gap-1.5">
          {segments.map((s) => (
            <div
              key={s.name}
              onMouseMove={(e) => handleHover(e, s.name)}
              onMouseLeave={() => setTooltip(null)}
              className="flex items-center gap-2 text-xs"
            >
              <span className="w-[9px] h-[9px] rounded-[2px] shrink-0" style={{ background: s.color }} />
              <span className="flex-1 text-text-secondary truncate" title={s.label}>{s.label}</span>
              <span className="font-mono font-medium tabular-nums text-text-bright shrink-0">{s.pct.toFixed(1)}%</span>
            </div>
          ))}
        </div>
      </div>
      {tooltip && (
        <div
          style={{ position: 'fixed', left: tooltip.x, top: tooltip.y, zIndex: 9999, pointerEvents: 'none' }}
          className="bg-modal border border-border-hover rounded-lg shadow-xl p-3 max-w-xs"
        >
          <p className="text-xs font-semibold text-text-primary mb-2">
            {chartType === 'type' ? (TYPE_LABELS[tooltip.name] || tooltip.name) : tooltip.name}
          </p>
          {tooltip.items.slice(0, 10).map((p) => (
            <div key={p.id} className="flex justify-between gap-4 text-xs py-0.5">
              <span className="text-text-secondary truncate">{p.ticker ? `${p.ticker} ` : ''}{p._displayName || p.name}</span>
              <span className="text-text-primary font-mono font-medium tabular-nums whitespace-nowrap">{formatCHF(p.market_value_chf)}</span>
            </div>
          ))}
          {tooltip.items.length > 10 && (
            <div className="text-xs text-text-secondary pt-1">+{tooltip.items.length - 10} weitere</div>
          )}
        </div>
      )}
    </div>
  )
}

function injectRealEstate(data, equity, name) {
  if (!data || equity <= 0) return data
  // Check if a bucket with the same name already exists — merge if so
  const existing = data.find((d) => d.name === name)
  let items
  if (existing) {
    items = data.map((d) =>
      d.name === name ? { ...d, value_chf: d.value_chf + equity } : d
    )
  } else {
    items = [...data, { name, value_chf: equity, pct: 0 }]
  }
  const total = items.reduce((s, d) => s + d.value_chf, 0)
  return items
    .map((d) => ({ ...d, pct: total > 0 ? (d.value_chf / total) * 100 : 0 }))
    .sort((a, b) => b.pct - a.pct)
}

function filterSectors(data, positions, etfSectorMap) {
  if (!data || !positions?.length) return data?.filter((d) => !EXCLUDED_SECTORS.has(d.name) && d.name !== 'Nicht zugewiesen') || []

  // Build sector allocation from positions, distributing multi-sector ETFs by weight
  const buckets = {}
  for (const p of positions) {
    if (p.shares <= 0) continue
    if (SECTOR_EXCLUDED_TYPES.has(p.type) || p.count_as_cash) continue

    const val = p.market_value_chf || 0
    const cat = TYPE_TO_SECTOR[p.type]
    if (cat) {
      buckets[cat] = (buckets[cat] || 0) + val
    } else if (p.is_multi_sector) {
      const etfWeights = etfSectorMap?.[p.ticker]
      if (etfWeights?.length) {
        for (const sw of etfWeights) {
          buckets[sw.sector] = (buckets[sw.sector] || 0) + val * sw.weight_pct / 100
        }
      } else {
        buckets['Multi-Sector (unverteilt)'] = (buckets['Multi-Sector (unverteilt)'] || 0) + val
      }
    } else if (p.sector && !EXCLUDED_SECTORS.has(p.sector)) {
      buckets[p.sector] = (buckets[p.sector] || 0) + val
    }
  }

  const result = Object.entries(buckets).map(([name, value_chf]) => ({ name, value_chf, pct: 0 }))
  const total = result.reduce((s, d) => s + d.value_chf, 0)
  return result.map((d) => ({ ...d, pct: total > 0 ? (d.value_chf / total) * 100 : 0 })).sort((a, b) => b.pct - a.pct)
}

function filterOut(data, names) {
  if (!data) return data
  const filtered = data.filter((d) => !names.has(d.name))
  const total = filtered.reduce((s, d) => s + d.value_chf, 0)
  return filtered.map((d) => ({ ...d, pct: total > 0 ? (d.value_chf / total) * 100 : 0 }))
}

const ILLIQUID_TYPES = new Set(['pension', 'private_equity'])
const ILLIQUID_SECTORS = new Set(['Pension', 'Private Equity'])

export default function AllocationCharts({ allocations, realEstateEquity = 0, positions }) {
  const [viewMode, setViewMode] = useState('total')
  const [etfSectorMap, setEtfSectorMap] = useState({})

  // Fetch ETF sector weights for all ETF positions
  useEffect(() => {
    if (!positions?.length) return
    const etfTickers = [...new Set(positions.filter((p) => p.is_multi_sector).map((p) => p.ticker))]
    if (etfTickers.length === 0) return

    Promise.all(
      etfTickers.map((t) =>
        authFetch(`/api/etf-sectors/${t}`).then((r) => r.ok ? r.json() : null).catch(() => null)
      )
    ).then((results) => {
      const map = {}
      results.forEach((r) => {
        if (r?.sectors?.length && r.is_complete) map[r.ticker] = r.sectors
      })
      setEtfSectorMap(map)
    })
  }, [positions])

  const hasIlliquid = realEstateEquity > 0 || positions?.some((p) => p.type === 'private_equity')
  const showToggle = hasIlliquid
  const isTotal = showToggle && viewMode === 'total'
  const isLiquid = !isTotal

  // Bucket-Allokation aus eigenem Endpoint laden (additiv, beruehrt portfolio_service nicht)
  const [bucketItems, setBucketItems] = useState(null)
  useEffect(() => {
    let cancelled = false
    async function loadBuckets() {
      try {
        const res = await authFetch('/api/portfolio/buckets/allocations')
        if (!res.ok) return
        const data = await res.json()
        if (cancelled) return
        const items = (data.items || []).filter((d) => d.value_chf > 0)
        setBucketItems(items)
      } catch {
        // ignore
      }
    }
    loadBuckets()
    return () => {
      cancelled = true
    }
  }, [])

  // Anzeige-Logik: wenn User mind. 1 user-bucket hat, zeige Bucket-Chart
  // statt Core/Satellite. System-only-User behaltn die alte Ansicht.
  const hasUserBuckets = bucketItems && bucketItems.some((b) => b.kind === 'user')

  if (!allocations) return null

  // In liquid view: exclude pension from all allocations
  // In total view: include everything + real estate
  let byType = allocations.by_type
  let bySector = filterSectors(allocations.by_sector, positions, etfSectorMap)
  let byCurrency = allocations.by_currency

  if (isLiquid) {
    byType = filterOut(byType, ILLIQUID_TYPES)
    const illiquidValue = allocations.by_type?.filter((d) => ILLIQUID_TYPES.has(d.name)).reduce((s, d) => s + d.value_chf, 0) || 0
    bySector = filterOut(bySector, ILLIQUID_SECTORS)
    if (illiquidValue > 0) {
      byCurrency = byCurrency.map((d) =>
        d.name === 'CHF' ? { ...d, value_chf: d.value_chf - illiquidValue } : d
      ).filter((d) => d.value_chf > 0)
      const ccyTotal = byCurrency.reduce((s, d) => s + d.value_chf, 0)
      byCurrency = byCurrency.map((d) => ({ ...d, pct: ccyTotal > 0 ? (d.value_chf / ccyTotal) * 100 : 0 }))
    }
  } else {
    byType = injectRealEstate(byType, realEstateEquity, 'real_estate')
    bySector = injectRealEstate(bySector, realEstateEquity, 'Immobilien')
    byCurrency = injectRealEstate(byCurrency, realEstateEquity, 'CHF')
  }

  const liquidPositions = isLiquid
    ? positions?.filter((p) => !ILLIQUID_TYPES.has(p.type))
    : positions
  const tooltipMap = buildTooltipMap(liquidPositions, isTotal ? realEstateEquity : 0, etfSectorMap)

  return (
    <div>
      {showToggle && (
        <div className="flex gap-1 mb-[18px] p-1 bg-surface rounded-lg w-fit border border-border-2">
          <button
            onClick={() => setViewMode('liquid')}
            className={`px-3 py-1.5 text-xs rounded-md transition-colors ${viewMode === 'liquid' ? 'bg-active-tint text-text-bright' : 'text-text-muted hover:text-text-primary'}`}
          >
            Liquides Vermögen
          </button>
          <button
            onClick={() => setViewMode('total')}
            className={`px-3 py-1.5 text-xs rounded-md transition-colors ${viewMode === 'total' ? 'bg-active-tint text-text-bright' : 'text-text-muted hover:text-text-primary'}`}
          >
            Gesamtvermögen
          </button>
        </div>
      )}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-[18px]">
        {hasUserBuckets ? (
          <AllocationDonut title="Buckets" data={bucketItems} chartType="bucket" />
        ) : (
          <div>
            <AllocationDonut title="Buckets" data={bucketItems || []} chartType="bucket" />
            <p className="text-[11px] text-text-muted mt-1.5">
              Erstelle eigene Buckets in den Einstellungen, um dein Portfolio nach Strategie zu segmentieren.
            </p>
          </div>
        )}
        <AllocationDonut title="Anlageklasse" data={byType} chartType="type" tooltipMap={tooltipMap.type} />
        <AllocationBar title="Sektor" data={bySector} chartType="sector" tooltipMap={tooltipMap.sector} />
        <AllocationDonut title="Währung" data={byCurrency} chartType="currency" tooltipMap={tooltipMap.currency} />
      </div>
    </div>
  )
}
