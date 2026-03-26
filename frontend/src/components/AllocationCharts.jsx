import { useState, useEffect, useMemo } from 'react'
import { formatCHF } from '../lib/format'
import { authFetch } from '../hooks/useApi'
import { CHART_COLORS } from '../lib/chartColors'
import G from './GlossarTooltip'

const PALETTE_RK = { RK1: CHART_COLORS.primary, RK2: CHART_COLORS.success, RK3: CHART_COLORS.warning, RK4: CHART_COLORS.danger }
const PALETTE_CS = {
  Core: CHART_COLORS.primary,
  Satellite: CHART_COLORS.warning,
  'Nicht zugewiesen': CHART_COLORS.benchmark,
}
const CS_LABELS = {
  core: 'Core',
  satellite: 'Satellite',
  'Nicht zugewiesen': 'Nicht zugewiesen',
}
const PALETTE_TYPE = {
  stock: CHART_COLORS.primary, etf: '#8b5cf6', crypto: CHART_COLORS.warning, commodity: CHART_COLORS.success,
  cash: CHART_COLORS.textMuted, pension: '#06b6d4', real_estate: '#805AD5', private_equity: '#059669',
}
const PALETTE_SECTOR = [
  CHART_COLORS.primary, CHART_COLORS.success, CHART_COLORS.warning, CHART_COLORS.danger, '#8b5cf6',
  '#06b6d4', '#ec4899', '#84cc16', '#f97316', '#14b8a6', '#6366f1',
  '#a855f7', CHART_COLORS.textMuted,
]
const PALETTE_CCY = { CHF: CHART_COLORS.danger, USD: CHART_COLORS.primary, EUR: CHART_COLORS.success, CAD: CHART_COLORS.warning, GBP: '#8b5cf6' }

const TYPE_LABELS = {
  stock: 'Aktien', etf: 'ETFs', crypto: 'Crypto', commodity: 'Rohstoffe',
  cash: 'Cash', pension: 'Pension', real_estate: 'Immobilien', private_equity: 'Private Equity',
}

const RK_MAP = { 1: 'RK1', 2: 'RK2', 3: 'RK3', 4: 'RK4' }

const EXCLUDED_SECTORS = new Set(['Cash', 'Pension'])

// Invested asset types that get their own sector category
const TYPE_TO_SECTOR = {
  crypto: 'Crypto',
  commodity: 'Commodities',
  private_equity: 'Private Equity',
}
// Types excluded from sector chart entirely (shown in Anlageklasse widget)
const SECTOR_EXCLUDED_TYPES = new Set(['cash', 'pension'])

const SECTOR_COLORS = {
  'Commodities': '#D4A017',
  'Crypto': '#F7931A',
  'Cash': '#6B7280',
  'Pension': '#8B5CF6',
  'Vorsorge': '#8B5CF6',
  'Private Equity': '#059669',
  'Multi-Sector (unverteilt)': '#374151',
}

function getColor(chartType, name, index) {
  if (chartType === 'rk') return PALETTE_RK[name] || PALETTE_SECTOR[index % PALETTE_SECTOR.length]
  if (chartType === 'core_satellite') return PALETTE_CS[name] || PALETTE_SECTOR[index % PALETTE_SECTOR.length]
  if (chartType === 'type') return PALETTE_TYPE[name] || PALETTE_SECTOR[index % PALETTE_SECTOR.length]
  if (chartType === 'currency') return PALETTE_CCY[name] || PALETTE_SECTOR[index % PALETTE_SECTOR.length]
  if (SECTOR_COLORS[name]) return SECTOR_COLORS[name]
  return PALETTE_SECTOR[index % PALETTE_SECTOR.length]
}

const TYPE_SUFFIXES = { pension: 'Vorsorge', cash: 'Cash' }

function buildTooltipMap(positions, realEstateEquity, etfSectorMap) {
  if (!positions?.length) return {}

  const map = { rk: {}, core_satellite: {}, type: {}, sector: {}, currency: {} }

  const addTo = (category, key, item) => {
    if (!map[category][key]) map[category][key] = []
    map[category][key].push(item)
  }

  for (const p of positions) {
    if (p.shares <= 0) continue
    const suffix = TYPE_SUFFIXES[p.type]
    const item = suffix
      ? { ...p, _displayName: `${p.name} (${suffix})` }
      : p

    // By risk class
    const rkKey = RK_MAP[p.risk_class] || `RK${p.risk_class}`
    addTo('rk', rkKey, item)

    // By core/satellite (null → 'Nicht zugewiesen'), use display names as keys
    const csKey = p.position_type === 'core' ? 'Core' : p.position_type === 'satellite' ? 'Satellite' : 'Nicht zugewiesen'
    addTo('core_satellite', csKey, item)

    // By type
    const typeKey = p.type || 'stock'
    addTo('type', typeKey, item)

    // By sector: Multi-Sector positions with weights get distributed
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
    addTo('rk', 'RK2', reItem)
    addTo('core_satellite', 'Nicht zugewiesen', reItem)  // display name as key
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
    <div className="rounded-lg border border-white/[0.06] bg-card p-4 shadow-[0_1px_3px_rgba(0,0,0,0.3)]">
      <h4 className="text-sm font-medium text-text-secondary mb-3">{title}</h4>
      <div className="space-y-2.5">
        {data.map((d, i) => {
          const color = getColor(chartType, d.name, i)
          const label = chartType === 'type' ? (TYPE_LABELS[d.name] || d.name)
            : chartType === 'core_satellite' ? (CS_LABELS[d.name] || d.name) : d.name
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
                <div className="flex-1 h-2 rounded-full bg-border overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all"
                    style={{ width: `${maxPct > 0 ? (d.pct / maxPct) * 100 : 0}%`, background: color }}
                  />
                </div>
                <span className="text-xs font-bold text-text-primary tabular-nums w-12 text-right">{d.pct.toFixed(1)}%</span>
              </div>
            </div>
          )
        })}
      </div>
      {tooltip && (
        <div
          style={{ position: 'fixed', left: tooltip.x, top: tooltip.y, zIndex: 9999, pointerEvents: 'none' }}
          className="bg-card-alt border border-border rounded-lg shadow-xl p-3 max-w-xs"
        >
          <p className="text-xs font-bold text-text-primary mb-2">
            {chartType === 'type' ? (TYPE_LABELS[tooltip.name] || tooltip.name)
              : chartType === 'core_satellite' ? (CS_LABELS[tooltip.name] || tooltip.name) : tooltip.name}
          </p>
          {tooltip.items.slice(0, 10).map((p) => (
            <div key={p.id} className="flex justify-between gap-4 text-xs py-0.5">
              <span className="text-text-secondary truncate">{p.ticker ? `${p.ticker} ` : ''}{p._displayName || p.name}</span>
              <span className="text-text-primary font-medium tabular-nums whitespace-nowrap">{formatCHF(p.market_value_chf)}</span>
            </div>
          ))}
          {tooltip.items.length > 10 && (
            <div className="text-xs text-text-muted pt-1">+{tooltip.items.length - 10} weitere</div>
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
    if (SECTOR_EXCLUDED_TYPES.has(p.type)) continue

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

  // Build core/satellite data from allocations (same endpoint, no extra fetch)
  const CS_NAME_MAP = { core: 'Core', satellite: 'Satellite', unassigned: 'Nicht zugewiesen' }
  const csItems = useMemo(() => {
    if (!allocations?.by_core_satellite) return null
    return allocations.by_core_satellite
      .filter((d) => d.value_chf > 0)
      .map((d) => ({ ...d, name: CS_NAME_MAP[d.name] || d.name }))
  }, [allocations?.by_core_satellite])

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
        <div className="flex gap-1 mb-3 p-1 bg-card-alt/50 rounded-lg w-fit border border-border">
          <button
            onClick={() => setViewMode('liquid')}
            className={`px-3 py-1.5 text-xs rounded-md transition-colors ${viewMode === 'liquid' ? 'bg-primary text-white' : 'text-text-muted hover:text-text-primary'}`}
          >
            Liquides Vermögen
          </button>
          <button
            onClick={() => setViewMode('total')}
            className={`px-3 py-1.5 text-xs rounded-md transition-colors ${viewMode === 'total' ? 'bg-primary text-white' : 'text-text-muted hover:text-text-primary'}`}
          >
            Gesamtvermögen
          </button>
        </div>
      )}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <div>
          <AllocationBar title={<><G term="Core">Core</G> / <G term="Satellite">Satellite</G></>} data={csItems} chartType="core_satellite" tooltipMap={tooltipMap.core_satellite} />
          <p className="text-[11px] text-text-muted mt-1.5">Ziel: Core 70% / Satellite 30%</p>
        </div>
        <AllocationBar title="Anlageklasse" data={byType} chartType="type" tooltipMap={tooltipMap.type} />
        <AllocationBar title="Sektor" data={bySector} chartType="sector" tooltipMap={tooltipMap.sector} />
        <AllocationBar title="Währung" data={byCurrency} chartType="currency" tooltipMap={tooltipMap.currency} />
      </div>
    </div>
  )
}
