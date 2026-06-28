import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  ArrowLeft, Star, Check, Loader2, ShoppingCart,
  Briefcase, TrendingUp, RotateCcw, Activity, Link2, LineChart, Ruler, ListChecks,
} from 'lucide-react'
import { useApi, apiPost, authFetch } from '../hooks/useApi'
import { usePortfolioData } from '../contexts/DataContext'
import { formatCHF, formatPct, formatNumber, formatDate, pnlColor } from '../lib/format'
import G from '../components/GlossarTooltip'
import { useToast } from '../components/Toast'
import TradingViewChart from '../components/TradingViewChart'
import StockScoreCard from '../components/StockScoreCard'
import FundamentalCharts from '../components/FundamentalCharts'
import EtfSectorPanel from '../components/EtfSectorPanel'
import DisclaimerBanner from '../components/DisclaimerBanner'
import SmartMoneyPanel from '../components/SmartMoneyPanel'
import EpsScannerPanel from '../components/EpsScannerPanel'
import TickerLogo from '../components/TickerLogo'
import ConcentrationBanner from '../components/ConcentrationBanner'
import TickerChip from '../components/ui/TickerChip'
import Button from '../components/ui/Button'
import { TypeBadge } from '../components/ui/Badge'

const TXN_LABELS = {
  buy: 'Kauf', sell: 'Verkauf', dividend: 'Dividende', fee: 'Gebühr',
  fee_correction: 'Gebühr', deposit: 'Einzahlung', withdrawal: 'Auszahlung',
  capital_gain: 'Kapitalgewinn', interest: 'Zinsertrag', tax: 'Steuer',
  tax_refund: 'Steuererstattung', fx_credit: 'FX Gutschrift', fx_debit: 'FX Belastung',
}

// --- Shared section card chrome (Redesign-Look) ---
function SectionCard({ title, subtitle, icon: Icon, iconColor = 'text-primary', right, bodyClass = 'p-[18px]', children }) {
  return (
    <div className="bg-card border border-border rounded-card overflow-hidden">
      <div className="px-[18px] py-4 border-b border-border-2 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5 min-w-0">
          {Icon && <Icon size={16} className={`${iconColor} shrink-0`} />}
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-text-primary truncate">{title}</h3>
            {subtitle && <p className="text-[11px] text-text-muted truncate mt-0.5">{subtitle}</p>}
          </div>
        </div>
        {right}
      </div>
      <div className={bodyClass}>{children}</div>
    </div>
  )
}

// Geteilte Zellen-Definition fuer Desktop- und Mobile-Positionskarte (gleiche
// echten Werte + Formatter — keine doppelte Berechnung).
function positionCells(position) {
  return [
    { label: 'Stück', value: formatNumber(position.shares, position.shares % 1 ? 4 : 0) },
    { label: 'Wert', value: formatCHF(position.market_value_chf) },
    { label: 'Einstand', value: formatCHF(position.cost_basis_chf) },
    { label: 'Allokation', value: `${(position.weight_pct ?? 0).toFixed(1)}%` },
    { label: 'PnL CHF', value: `${position.pnl_chf >= 0 ? '+' : ''}${formatCHF(position.pnl_chf)}`, tone: pnlColor(position.pnl_chf) },
    { label: 'PnL %', value: formatPct(position.pnl_pct), tone: pnlColor(position.pnl_pct) },
  ]
}

function MyPositionPanel({ ticker }) {
  const { data: summary } = usePortfolioData()
  const position = summary?.positions?.find((p) => p.ticker === ticker)

  if (!position) return null

  const cells = positionCells(position)

  return (
    <SectionCard title="Meine Position" icon={Briefcase}>
      <div className="grid grid-cols-2 gap-2.5">
        {cells.map((c) => (
          <div key={c.label} className="rounded-lg border border-border-2 bg-card-2 p-[13px]">
            <div className="font-mono text-[10.5px] tracking-[0.06em] uppercase text-text-label mb-1.5">{c.label}</div>
            <div className={`text-[15px] font-mono font-semibold tabular-nums leading-none ${c.tone || 'text-text-primary'}`}>{c.value}</div>
          </div>
        ))}
      </div>
    </SectionCard>
  )
}

// ---------------------------------------------------------------------------
// Mobile-Varianten (<md) — kompaktere Darstellung derselben echten Daten.
// ---------------------------------------------------------------------------

// Reihenfolge/Signal-Tonalitaet gespiegelt aus StockScoreCard (reine Anzeige).
const SCORE_GROUP_ORDER = ['Moving Averages', 'Trendbestätigung', 'Modifier', 'Breakout', 'Relative Stärke', 'Industry-Stärke', 'Volumen & Liquidität', 'Trendwende', 'Risiken']
const SIGNAL_TONE = {
  ETF_KAUFSIGNAL: 'text-etf bg-etf/15 border-etf/30',
  KAUFSIGNAL: 'text-success bg-success/15 border-success/30',
  WATCHLIST: 'text-warning bg-warning/15 border-warning/30',
  BEOBACHTEN: 'text-text-secondary bg-card-2 border-border-2',
  'KEIN SETUP': 'text-danger bg-danger/15 border-danger/30',
}

function MobilePriceChartCard({ ticker, scoreData }) {
  const { data: summary } = usePortfolioData()
  const position = summary?.positions?.find((p) => p.ticker === ticker)
  const price = scoreData?.price
  const currency = scoreData?.currency
  const pctFromHigh = scoreData?.range_52w?.pct_from_high
  // Tag-% liefert nur die gehaltene Position (change_pct_24h); sonst weglassen.
  const dayChange = position?.change_pct_24h

  return (
    <div className="bg-card border border-border rounded-card overflow-hidden">
      <div className="p-4 border-b border-border-2 flex items-end justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-baseline gap-2">
            <span className="font-mono text-[30px] font-semibold text-text-primary tabular-nums leading-none">
              {price != null ? price.toFixed(2) : '–'}
            </span>
            {currency && <span className="font-mono text-[12px] text-text-muted">{currency}</span>}
          </div>
          {dayChange != null && (
            <div className={`font-mono text-[13px] mt-2 ${pnlColor(dayChange)}`}>
              {formatPct(dayChange)} <span className="text-text-muted">heute</span>
            </div>
          )}
        </div>
        {pctFromHigh != null && (
          <div className="text-right shrink-0">
            <div className="font-mono text-[10px] tracking-[0.05em] uppercase text-text-label mb-1">z. 52W-Hoch</div>
            <div className={`font-mono text-[14px] tabular-nums ${pctFromHigh >= -1 ? 'text-success' : 'text-text-muted'}`}>
              {pctFromHigh.toFixed(1)}%
            </div>
          </div>
        )}
      </div>
      <div className="p-3">
        <TradingViewChart ticker={ticker} height={300} compact />
      </div>
    </div>
  )
}

function MobilePositionCard({ ticker }) {
  const { data: summary } = usePortfolioData()
  const position = summary?.positions?.find((p) => p.ticker === ticker)

  if (!position) return null

  const cells = positionCells(position)

  return (
    <SectionCard title="Meine Position" icon={Briefcase} bodyClass="p-[14px]">
      <div className="grid grid-cols-3 gap-2">
        {cells.map((c) => (
          <div key={c.label} className="rounded-lg border border-border-2 bg-card-2 p-2.5">
            <div className="font-mono text-[9.5px] tracking-[0.05em] uppercase text-text-label mb-1 truncate">{c.label}</div>
            <div className={`text-[13px] font-mono font-semibold tabular-nums leading-none ${c.tone || 'text-text-primary'}`}>{c.value}</div>
          </div>
        ))}
      </div>
    </SectionCard>
  )
}

function MobileScoreCard({ scoreData }) {
  if (!scoreData || !scoreData.criteria) return null

  const { criteria, score, max_score, signal, signal_label, setup_quality, rating } = scoreData

  const grouped = {}
  for (const c of criteria) {
    const g = c.group || 'Sonstige'
    if (!grouped[g]) grouped[g] = []
    grouped[g].push(c)
  }

  const tone = SIGNAL_TONE[signal] || SIGNAL_TONE['KEIN SETUP']
  const quality = setup_quality || rating

  return (
    <SectionCard
      title={<G term="Setup-Score">Kauf-Checkliste</G>}
      icon={ListChecks}
      bodyClass="p-[14px]"
      right={(
        <span className="font-mono text-[15px] font-semibold text-text-primary tabular-nums shrink-0">
          {score}<span className="text-text-muted text-[12px]">/{max_score}</span>
        </span>
      )}
    >
      <div className="flex flex-col gap-2.5">
        {/* Signal kompakt */}
        <div className={`rounded-lg border px-3 py-2.5 ${tone}`}>
          <div className="flex items-center justify-between gap-2">
            <span className="text-[12.5px] font-semibold"><G term={signal}>{signal}</G></span>
            {quality && <span className="font-mono text-[9.5px] tracking-[0.05em] uppercase opacity-80">{quality}</span>}
          </div>
          {signal_label && <p className="text-[11px] text-text-muted mt-0.5 leading-tight">{signal_label}</p>}
        </div>

        {/* Kategorien: Name + Dots + erfuellt/total */}
        <div className="flex flex-col">
          {SCORE_GROUP_ORDER.map((g) => {
            const items = grouped[g]
            if (!items) return null
            const passedItems = items.filter((c) => c.passed === true || c.passed === false)
            if (passedItems.length === 0) return null
            const passed = passedItems.filter((c) => c.passed === true).length
            return (
              <div key={g} className="flex items-center justify-between gap-3 py-2 border-b border-border-row last:border-b-0">
                <span className="text-[12.5px] text-text-secondary truncate">{g}</span>
                <div className="flex items-center gap-2.5 shrink-0">
                  <div className="flex items-center gap-1">
                    {passedItems.map((c, i) => (
                      <span key={i} className={`w-[7px] h-[7px] rounded-full ${c.passed ? 'bg-success' : 'bg-danger/40'}`} />
                    ))}
                  </div>
                  <span className="font-mono text-[11px] tabular-nums text-text-muted w-9 text-right">{passed}/{passedItems.length}</span>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </SectionCard>
  )
}

function EtfSectorPanelWrapper({ ticker }) {
  const { data: summary } = usePortfolioData()
  const position = summary?.positions?.find((p) => p.ticker === ticker)

  if (!position || !position.is_multi_sector) return null

  return <EtfSectorPanel ticker={ticker} marketValueChf={position.market_value_chf || 0} />
}

function MrsPanel({ mrs }) {
  if (mrs === null || mrs === undefined) return null

  const isPositive = mrs >= 0
  const color = isPositive ? 'text-success' : 'text-danger'
  // Balken um die Mittellinie (0). Skala illustrativ: |MRS| = 3 fuellt eine Haelfte.
  const fillPct = Math.min(Math.abs(mrs) / 3, 1) * 50

  return (
    <SectionCard title={<G term="MRS">Mansfield RS (MRS)</G>} icon={Activity}>
      <div className={`text-[26px] font-mono font-semibold leading-none mb-4 ${color}`}>
        {isPositive ? '+' : ''}{mrs.toFixed(2)}
      </div>
      <div className="relative h-3 rounded-md bg-card-2 border border-border-2">
        <div className="absolute top-0 bottom-0 left-1/2 w-px bg-border-chip z-10" />
        <div
          className={`absolute top-0.5 bottom-0.5 rounded-sm ${isPositive ? 'bg-success' : 'bg-danger'}`}
          style={isPositive
            ? { left: '50%', width: `${fillPct}%` }
            : { left: `calc(50% - ${fillPct}%)`, width: `${fillPct}%` }}
        />
      </div>
      <div className="flex justify-between font-mono text-[10px] text-text-faint mt-1.5">
        <span>schwächer</span>
        <span>0</span>
        <span>stärker</span>
      </div>
      <p className="text-xs text-text-secondary mt-3">
        {isPositive
          ? 'Relative Stärke positiv — der Titel schlägt den Benchmark (^GSPC).'
          : 'Relative Stärke negativ — der Titel ist schwächer als der Benchmark (^GSPC).'}
      </p>
    </SectionCard>
  )
}

function BreakoutEvents({ ticker }) {
  const [breakouts, setBreakouts] = useState(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    let cancelled = false
    setError(false)
    ;(async () => {
      try {
        const res = await authFetch(`/api/analysis/breakouts/${ticker}?period=1y`)
        if (cancelled) return
        if (res.ok) {
          const json = await res.json()
          if (!cancelled) setBreakouts(json.breakouts || [])
        } else {
          setError(true)
        }
      } catch { if (!cancelled) setError(true) }
    })()
    return () => { cancelled = true }
  }, [ticker])

  if (error) {
    return (
      <SectionCard title="Breakout-Ereignisse" icon={TrendingUp}>
        <p className="text-xs text-text-muted">Breakout-Daten konnten nicht geladen werden.</p>
      </SectionCard>
    )
  }
  if (!breakouts || breakouts.length === 0) return null

  return (
    <SectionCard title="Breakout-Ereignisse" subtitle="1J · am Folgetag bestätigt" icon={TrendingUp}>
      <div className="space-y-2">
        {breakouts.map((b, i) => {
          const isPending = b.status === 'pending'
          const tooltip = isPending
            ? `Ausbruch heute bei ${b.resistance} — Tag-2-Bestätigung steht noch aus`
            : `Ausbruch am ${formatDate(b.date)} bei ${b.resistance}, am Folgetag (${b.day2_date ? formatDate(b.day2_date) : '?'}) mit Close ${b.day2_close} bestätigt`
          return (
            <div key={i} className="flex items-center gap-2.5 rounded-lg border border-border-2 bg-card-2 px-3 py-2.5 text-xs" title={tooltip}>
              <span className="font-mono text-text-secondary w-16 shrink-0">{formatDate(b.date)}</span>
              <span className="font-mono text-text-primary">{b.price}</span>
              <span className="text-text-muted">über {b.resistance}</span>
              <span className="font-mono text-text-muted ml-auto">Vol {b.volume_ratio}×</span>
              <span className={`px-1.5 py-0.5 rounded-md text-[10px] font-medium shrink-0 ${isPending ? 'bg-warning/15 text-warning' : 'bg-success/15 text-success'}`}>
                {isPending ? 'in Prüfung' : 'bestätigt'}
              </span>
            </div>
          )
        })}
      </div>
    </SectionCard>
  )
}

function LevelRow({ price, label, kind, isCurrent }) {
  const dot = kind === 'resistance' ? '#e8625a' : kind === 'support' ? '#45c08a' : '#5b8def'
  return (
    <div className={`flex items-center gap-3 px-3 py-2 rounded-lg ${isCurrent ? 'bg-active-tint border border-border-active' : 'border border-transparent'}`}>
      <span className="w-2 h-2 rounded-full shrink-0" style={{ background: dot }} />
      <span className={`text-xs ${isCurrent ? 'text-text-bright font-medium' : 'text-text-secondary'}`}>{label}</span>
      <span className={`ml-auto font-mono tabular-nums ${isCurrent ? 'text-text-bright font-semibold text-sm' : 'text-text-primary text-[12.5px]'}`}>{price}</span>
    </div>
  )
}

function LevelsPanel({ ticker }) {
  const [levels, setLevels] = useState(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    let cancelled = false
    setError(false)
    ;(async () => {
      try {
        const res = await authFetch(`/api/analysis/levels/${ticker}`)
        if (cancelled) return
        if (res.ok) {
          const json = await res.json()
          if (!cancelled) setLevels(json)
        } else {
          setError(true)
        }
      } catch { if (!cancelled) setError(true) }
    })()
    return () => { cancelled = true }
  }, [ticker])

  if (error) {
    return (
      <SectionCard title="Marken" icon={Ruler}>
        <p className="text-xs text-text-muted">Support/Resistance-Daten konnten nicht geladen werden.</p>
      </SectionCard>
    )
  }
  if (!levels || (!levels.resistance && !levels.support)) return null

  const entries = []
  if (levels.resistance != null) entries.push({ price: levels.resistance, label: 'Widerstand (52W-Hoch)', kind: 'resistance' })
  ;(levels.resistance_historical || []).forEach((p) => entries.push({ price: p, label: 'Widerstand', kind: 'resistance' }))
  if (levels.current_price != null) entries.push({ price: levels.current_price, label: 'Aktueller Kurs', kind: 'current', isCurrent: true })
  ;(levels.support_historical || []).forEach((p) => entries.push({ price: p, label: 'Unterstützung', kind: 'support' }))
  if (levels.support != null) entries.push({ price: levels.support, label: 'Unterstützung (52W-Tief)', kind: 'support' })

  const sorted = entries.filter((e) => e.price != null).sort((a, b) => b.price - a.price)

  return (
    <SectionCard title={<G term="S/R">Marken (Support &amp; Resistance)</G>} icon={Ruler}>
      <div className="space-y-0.5">
        {sorted.map((e, i) => (
          <LevelRow key={i} price={e.price} label={e.label} kind={e.kind} isCurrent={e.isCurrent} />
        ))}
      </div>
    </SectionCard>
  )
}

function HeartbeatPanel({ ticker }) {
  const [heartbeat, setHeartbeat] = useState(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    let cancelled = false
    setError(false)
    ;(async () => {
      try {
        const res = await authFetch(`/api/analysis/heartbeat/${ticker}`)
        if (cancelled) return
        if (res.ok) {
          const json = await res.json()
          if (!cancelled) setHeartbeat(json)
        } else {
          setError(true)
        }
      } catch { if (!cancelled) setError(true) }
    })()
    return () => { cancelled = true }
  }, [ticker])

  if (error) return null
  if (!heartbeat || !heartbeat.detected) return null

  const { resistance_level, support_level, range_pct, touches, duration_days, current_price, position_in_range, atr_compression_ratio, wyckoff } = heartbeat
  const highTouches = touches.filter(t => t.type === 'high').length
  const lowTouches = touches.filter(t => t.type === 'low').length

  const positionPct = resistance_level > support_level
    ? Math.max(0, Math.min(100, ((current_price - support_level) / (resistance_level - support_level)) * 100))
    : 50

  const positionLabel = position_in_range === 'near_resistance' ? 'nahe Resistance'
    : position_in_range === 'near_support' ? 'nahe Support'
    : 'Mitte'

  const wyckoffScore = wyckoff?.score
  const wyckoffLabel = wyckoff?.label
  const springDetected = wyckoff?.spring_detected === true
  const springDate = wyckoff?.spring_date
  const springRatio = wyckoff?.spring_volume_ratio

  const isDistribution = wyckoffScore === -1
  const panelClasses = isDistribution
    ? 'bg-card rounded-card border border-danger/60 p-4'
    : 'bg-card rounded-card border border-primary/30 p-4'
  const headerClasses = isDistribution
    ? 'flex items-center gap-2 mb-3 -mx-4 -mt-4 px-4 pt-4 pb-2 bg-danger/10 rounded-t-[11px]'
    : 'flex items-center gap-2 mb-3'

  let wyckoffBadgeClasses = 'text-[10px] px-2 py-0.5 rounded-full ml-auto font-medium'
  if (wyckoffScore === 1) wyckoffBadgeClasses += ' bg-success/15 text-success border border-success/30'
  else if (wyckoffScore === -1) wyckoffBadgeClasses += ' bg-danger/15 text-danger border border-danger/30'
  else if (wyckoffScore === 0) wyckoffBadgeClasses += ' bg-card-2 text-text-secondary border border-border-2'
  else wyckoffBadgeClasses += ' bg-card-2/40 text-text-muted border border-border-2/50'

  return (
    <div className={panelClasses}>
      <div className={headerClasses}>
        <RotateCcw size={16} className="text-primary" />
        <h4 className="text-sm font-medium text-text-secondary">
          <G term="Heartbeat-Pattern">Heartbeat-Pattern aktiv</G>
        </h4>
        {wyckoffScore != null ? (
          <span className={wyckoffBadgeClasses}>
            <G term="Wyckoff-Volumen-Profil">Wyckoff: {wyckoffLabel}</G>
          </span>
        ) : (
          <span className="text-[10px] text-text-muted ml-auto">Wyckoff: keine Volumendaten</span>
        )}
      </div>

      <div className="relative bg-card-2 rounded-lg border border-border-2 p-3 mb-3" style={{ minHeight: '64px' }}>
        <div className="flex justify-between text-[11px] text-danger font-mono">
          <span>Resistance</span>
          <span>{resistance_level?.toFixed(2)}</span>
        </div>
        <div className="absolute left-3 right-3 border-t border-danger/40" style={{ top: '24px' }} />
        <div className="absolute left-3 right-3 border-t border-success/40" style={{ bottom: '24px' }} />
        <div className="absolute h-2 w-2 rounded-full bg-primary border border-card" style={{ left: `calc(${positionPct}% - 4px)`, top: '50%' }} title={`Aktuell: ${current_price?.toFixed(2)} (${positionLabel})`} />
        <div className="flex justify-between text-[11px] text-success font-mono mt-7">
          <span>Support</span>
          <span>{support_level?.toFixed(2)}</span>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-3 text-xs">
        <div>
          <div className="text-text-muted">Touches</div>
          <div className="font-mono text-text-primary">{highTouches} H / {lowTouches} L</div>
        </div>
        <div>
          <div className="text-text-muted">Range</div>
          <div className="font-mono text-text-primary">{range_pct?.toFixed(1)}%</div>
        </div>
        <div>
          <div className="text-text-muted">Dauer</div>
          <div className="font-mono text-text-primary">{duration_days} T</div>
        </div>
        <div>
          <div className="text-text-muted">Position</div>
          <div className="font-mono text-text-primary">{positionLabel}</div>
        </div>
      </div>

      {atr_compression_ratio !== null && atr_compression_ratio !== undefined && (
        <div className="mt-2 text-[11px] text-text-muted">
          ATR-Kompression: aktuell {(atr_compression_ratio * 100).toFixed(0)}% des 30%-Quantils der letzten 90 Tage
        </div>
      )}

      {springDetected && springDate && (
        <div className="mt-2 text-[11px]">
          <span
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-success/10 text-success border border-success/30"
            title={springRatio != null ? `Volumen am Spring-Tag: ${springRatio}x Range-Median` : undefined}
          >
            Spring am {springDate}
            {springRatio != null && (
              <span className="text-text-muted font-mono">({springRatio}x Vol.)</span>
            )}
          </span>
        </div>
      )}

      <p className="text-xs text-text-secondary mt-3">
        Heartbeat-Patterns sind Konsolidierungen — der Ausbruch in eine Richtung ist das eigentliche Setup. Das Wyckoff-Volumen-Profil bewertet die Range-Qualität: schrumpfendes Volumen deutet auf Akkumulation, steigendes auf Distribution.
      </p>
    </div>
  )
}

function ReversalPanel({ ticker }) {
  const [reversal, setReversal] = useState(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    let cancelled = false
    setError(false)
    ;(async () => {
      try {
        const res = await authFetch(`/api/analysis/reversal/${ticker}`)
        if (cancelled) return
        if (res.ok) {
          const json = await res.json()
          if (!cancelled) setReversal(json)
        } else {
          setError(true)
        }
      } catch { if (!cancelled) setError(true) }
    })()
    return () => { cancelled = true }
  }, [ticker])

  if (error) return null
  if (!reversal || !reversal.detected) return null

  return (
    <div className="bg-card rounded-card border border-warning/30 p-4">
      <div className="flex items-center gap-2 mb-3">
        <RotateCcw size={16} className="text-warning" />
        <h4 className="text-sm font-medium text-text-secondary">
          <G term="3-Punkt-Umkehr">3-Punkt-Umkehr erkannt</G>
        </h4>
      </div>
      <div className="grid grid-cols-4 gap-3 text-xs">
        <div>
          <div className="text-text-muted">LL1</div>
          <div className="font-mono text-text-primary">{reversal.ll1}</div>
          <div className="text-text-muted">{formatDate(reversal.ll1_date)}</div>
        </div>
        <div>
          <div className="text-text-muted">LL2</div>
          <div className="font-mono text-text-primary">{reversal.ll2}</div>
          <div className="text-text-muted">{formatDate(reversal.ll2_date)}</div>
        </div>
        <div>
          <div className="text-text-muted">LL3</div>
          <div className="font-mono text-text-primary">{reversal.ll3}</div>
          <div className="text-text-muted">{formatDate(reversal.ll3_date)}</div>
        </div>
        <div>
          <div className="text-warning font-medium">Higher Low</div>
          <div className="font-mono text-warning">{reversal.hl}</div>
          <div className="text-text-muted">{formatDate(reversal.hl_date)}</div>
        </div>
      </div>
      <p className="text-xs text-text-secondary mt-3">Drei tiefere Tiefs gefolgt von einem höheren Tief — mögliche Trendwende.</p>
    </div>
  )
}

function txnDetail(t) {
  if (t.shares && t.price_per_share) {
    return `${formatNumber(t.shares, t.shares % 1 ? 4 : 0)} × ${formatNumber(t.price_per_share, 2)}${t.currency ? ' ' + t.currency : ''}`
  }
  if (t.notes) return t.notes
  return t.position_name || '—'
}

function LinkedTransactions({ ticker }) {
  const { data } = useApi(`/transactions?ticker=${encodeURIComponent(ticker)}&per_page=12`)
  const items = data?.items || []

  // Nur anzeigen, wenn es verknuepfte Buchungen gibt (Research-Ticker ohne
  // Buchungen blenden die Karte aus).
  if (!data || items.length === 0) return null

  return (
    <SectionCard title="Verknüpfte Transaktionen" icon={Link2} bodyClass="p-0">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-table-head border-b border-border-2 font-mono text-[10px] uppercase tracking-[0.05em] text-text-faint">
              <th className="text-left px-[18px] py-[11px] font-medium">Datum</th>
              <th className="text-left px-3 py-[11px] font-medium">Typ</th>
              <th className="text-left px-3 py-[11px] font-medium">Detail</th>
              <th className="text-right pr-[18px] pl-3 py-[11px] font-medium">Betrag CHF</th>
            </tr>
          </thead>
          <tbody>
            {items.map((t) => (
              <tr key={t.id} className="border-b border-border-row hover:bg-hover transition-colors">
                <td className="px-[18px] py-3 font-mono text-[11.5px] text-text-secondary whitespace-nowrap">{formatDate(t.date)}</td>
                <td className="px-3 py-3"><TypeBadge label={TXN_LABELS[t.type] || t.type} kind="txn" /></td>
                <td className="px-3 py-3 text-text-muted text-xs">{txnDetail(t)}</td>
                <td className={`pr-[18px] pl-3 py-3 text-right font-mono font-medium tabular-nums ${t.total_chf < 0 ? 'text-danger' : 'text-text-primary'}`}>
                  {formatCHF(t.total_chf, { decimals: 2 })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </SectionCard>
  )
}

export default function StockDetail() {
  const { ticker } = useParams()
  const navigate = useNavigate()
  const { data: scoreData } = useApi(`/analysis/score/${ticker}`)
  const { data: watchlist } = useApi('/analysis/watchlist')
  const [inWatchlist, setInWatchlist] = useState(false)
  const [addingToWl, setAddingToWl] = useState(false)
  const toast = useToast()

  useEffect(() => {
    if (watchlist && ticker) {
      const items = watchlist?.items || watchlist || []
      setInWatchlist(items.some((w) => w.ticker === ticker.toUpperCase() || w.ticker === ticker))
    }
  }, [watchlist, ticker])

  const handleAddToWatchlist = async () => {
    setAddingToWl(true)
    try {
      await apiPost('/analysis/watchlist', { ticker: ticker.toUpperCase(), name: ticker.toUpperCase(), sector: null })
      setInWatchlist(true)
      toast('Zur Watchlist hinzugefügt', 'success')
    } catch (e) {
      toast('Fehler: ' + e.message, 'error')
    } finally {
      setAddingToWl(false)
    }
  }

  const name = scoreData?.name
  const sector = scoreData?.sector
  const industry = scoreData?.industry
  const price = scoreData?.price
  const currency = scoreData?.currency
  const pctFromHigh = scoreData?.range_52w?.pct_from_high

  return (
    <div className="pb-10">
      {/* Sticky Detail-Header */}
      <header className="sticky top-0 z-30 -mx-4 md:-mx-6 -mt-4 md:-mt-6 mb-4 md:mb-[18px] flex items-center gap-3 md:gap-4 px-4 md:px-6 py-[14px] border-b border-border-soft bg-body/[0.86] backdrop-blur-md">
        <button
          onClick={() => navigate(-1)}
          aria-label="Zurück"
          className="w-9 h-9 rounded-lg bg-surface border border-border text-text-muted hover:border-border-hover transition-colors flex items-center justify-center shrink-0"
        >
          <ArrowLeft size={16} />
        </button>

        <div className="flex items-center gap-3 min-w-0">
          <span className="hidden md:block"><TickerLogo ticker={ticker} size={34} /></span>
          <div className="min-w-0">
            <div className="flex items-center gap-2 min-w-0">
              <TickerChip>{ticker}</TickerChip>
              {name && <span className="text-[15px] font-semibold text-text-primary truncate">{name}</span>}
            </div>
            {(sector || industry) && (
              <div className="hidden md:block font-mono text-[11px] text-text-faint truncate mt-0.5">
                {[sector, industry].filter(Boolean).join(' · ')}
              </div>
            )}
          </div>
        </div>

        {price != null && (
          <div className="hidden md:flex items-baseline gap-2.5 ml-1 shrink-0">
            <span className="font-mono text-[22px] font-semibold text-text-primary tabular-nums leading-none">{price.toFixed(2)}</span>
            {currency && <span className="font-mono text-[11px] text-text-muted">{currency}</span>}
            {pctFromHigh != null && (
              <span
                className={`font-mono text-[12px] ${pctFromHigh >= -1 ? 'text-success' : 'text-text-muted'}`}
                title="Abstand zum 52-Wochen-Hoch"
              >
                {pctFromHigh.toFixed(1)}% z. 52W-Hoch
              </span>
            )}
          </div>
        )}

        <div className="flex-1" />

        {/* Watchlist-Toggle — Desktop: Pill/Button, Mobile: Icon */}
        {inWatchlist ? (
          <span className="hidden md:inline-flex items-center gap-[7px] rounded-lg text-[12.5px] font-medium bg-success/15 text-success border border-success/30 px-[13px] py-2">
            <Check size={15} />
            In Watchlist
          </span>
        ) : (
          <button
            onClick={handleAddToWatchlist}
            disabled={addingToWl}
            className="hidden md:inline-flex items-center gap-[7px] rounded-lg text-[12.5px] font-medium bg-surface border border-border text-text-secondary px-[13px] py-2 hover:border-border-hover transition-colors disabled:opacity-50"
          >
            {addingToWl ? <Loader2 size={15} className="animate-spin" /> : <Star size={15} />}
            Watchlist
          </button>
        )}
        <button
          onClick={inWatchlist ? undefined : handleAddToWatchlist}
          disabled={addingToWl || inWatchlist}
          aria-label={inWatchlist ? 'In Watchlist' : 'Zur Watchlist hinzufügen'}
          className={`md:hidden w-9 h-9 rounded-lg flex items-center justify-center shrink-0 border transition-colors disabled:opacity-50 ${
            inWatchlist ? 'bg-success/15 border-success/30 text-success' : 'bg-surface border-border text-text-muted hover:border-border-hover'
          }`}
        >
          {addingToWl ? <Loader2 size={16} className="animate-spin" /> : <Star size={16} />}
        </button>

        <Button variant="primary" icon={ShoppingCart} className="hidden md:inline-flex" onClick={() => navigate('/transactions?action=add')}>
          Order
        </Button>
      </header>

      {/* ===== Desktop-Ansicht (>=md) — unverändert ===== */}
      <div className="hidden md:grid grid-cols-1 xl:grid-cols-[1.7fr_1fr] gap-[18px]">
        {/* LINKS */}
        <div className="flex flex-col gap-[18px]">
          <SectionCard title="Kursverlauf" icon={LineChart}>
            <TradingViewChart ticker={ticker} height={600} showControls />
          </SectionCard>

          <FundamentalCharts ticker={ticker} />

          <EtfSectorPanelWrapper ticker={ticker} />

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-[18px]">
            <EpsScannerPanel ticker={ticker} />
            <SmartMoneyPanel ticker={ticker} />
          </div>

          <LinkedTransactions ticker={ticker} />
        </div>

        {/* RECHTS */}
        <div className="flex flex-col gap-[18px]">
          <MyPositionPanel ticker={ticker} />

          {/* Konzentrations-Warnbox (self-hiding, falls Schwellen nicht erreicht) */}
          <ConcentrationBanner
            concentration={scoreData?.concentration}
            ticker={ticker}
            liquidPortfolioChf={scoreData?.liquid_portfolio_chf}
          />

          <StockScoreCard ticker={ticker} scoreData={scoreData} />

          <MrsPanel mrs={scoreData?.mansfield_rs} />

          <BreakoutEvents ticker={ticker} />
          <HeartbeatPanel ticker={ticker} />
          <ReversalPanel ticker={ticker} />

          <LevelsPanel ticker={ticker} />
        </div>
      </div>

      {/* ===== Mobile-Ansicht (<md) — kuratierter Subset ===== */}
      <div className="md:hidden flex flex-col gap-[14px]">
        <MobilePriceChartCard ticker={ticker} scoreData={scoreData} />

        <MobilePositionCard ticker={ticker} />

        {/* Konzentrations-Warnbox (self-hiding) */}
        <ConcentrationBanner
          concentration={scoreData?.concentration}
          ticker={ticker}
          liquidPortfolioChf={scoreData?.liquid_portfolio_chf}
        />

        <MobileScoreCard scoreData={scoreData} />

        <FundamentalCharts ticker={ticker} />

        <Button
          variant="primary"
          icon={ShoppingCart}
          className="w-full justify-center py-3"
          onClick={() => navigate('/transactions?action=add')}
        >
          Order anlegen
        </Button>
      </div>

      {/* Disclaimer */}
      <div className="rounded-card border border-border-2 bg-card-2 px-4 py-3 mt-[18px]">
        <DisclaimerBanner className="!mt-0" />
      </div>
    </div>
  )
}
