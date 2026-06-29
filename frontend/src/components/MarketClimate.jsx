import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { formatDate, formatDateTime, formatNumber } from '../lib/format'
import { Shield, Info, ChevronDown, ChevronUp, Settings, TrendingUp, TrendingDown, AlertTriangle } from 'lucide-react'
import G from './GlossarTooltip'
import Card, { CardLabel } from './ui/Card'
import StatTile from './ui/StatTile'

// combined_status (green/yellow/red) -> Tokens
const COMBINED_TONE = { green: 'success', yellow: 'warning', red: 'danger' }
const COMBINED_TEXT = { green: 'text-success', yellow: 'text-warning', red: 'text-danger' }

// Indikator-Status (green/yellow/orange/red/unavailable) -> Tokens
const IND_TONE = { green: 'success', yellow: 'warning', orange: 'warning', red: 'danger' }
const IND_TEXT = {
  green: 'text-success', yellow: 'text-warning', orange: 'text-warning',
  red: 'text-danger', unavailable: 'text-text-muted', unknown: 'text-text-muted',
}
const IND_DOT = {
  green: '#45c08a', yellow: '#e0a64b', orange: '#e0a64b',
  red: '#e8625a', unavailable: '#7a8698', unknown: '#7a8698',
}

// Die 6 Klima-Kriterien (S&P-500-Trendstruktur) aus dem climate.checks-Objekt.
const CRITERIA = [
  ['price_above_ma200', 'S&P 500 > 200-DMA'],
  ['price_above_ma150', 'S&P 500 > 150-DMA'],
  ['price_above_ma50', 'S&P 500 > 50-DMA'],
  ['ma50_above_ma150', '50-DMA > 150-DMA'],
  ['ma50_above_ma200', '50-DMA > 200-DMA'],
  ['ma150_above_ma200', '150-DMA > 200-DMA'],
]

function CriterionRow({ label, value }) {
  const dot = value === true ? '#45c08a' : value === false ? '#e8625a' : '#7a8698'
  const status = value === true ? 'Bullish' : value === false ? 'Bearish' : '–'
  const cls = value === true ? 'text-success' : value === false ? 'text-danger' : 'text-text-muted'
  return (
    <div className="flex items-center gap-2">
      <span className="w-[9px] h-[9px] rounded-[3px] flex-shrink-0" style={{ background: dot }} />
      <span className="text-[12.5px] text-text-secondary flex-1 min-w-0 truncate"><G term={label}>{label}</G></span>
      <span className={`font-mono text-[10.5px] ${cls}`}>{status}</span>
    </div>
  )
}

function IndicatorRow({ indicator }) {
  const txt = IND_TEXT[indicator.status] || 'text-text-muted'
  const dot = IND_DOT[indicator.status] || '#7a8698'
  const hasAvg = indicator.historical_avg != null && indicator.value != null
  return (
    <div
      className="flex items-center gap-2.5 py-[9px] border-b border-border-row2 last:border-0"
      title={`Schwellenwerte: ${indicator.thresholds?.green || ''} / ${indicator.thresholds?.yellow || ''} / ${indicator.thresholds?.red || ''}\nQuelle: ${indicator.source}\nLetzte Aktualisierung: ${formatDateTime(indicator.updated_at)}`}
    >
      <span className="w-[9px] h-[9px] rounded-[3px] flex-shrink-0" style={{ background: dot }} />
      <span className="text-[12.5px] text-text-secondary flex-1 min-w-0 truncate"><G term={indicator.label}>{indicator.label}</G></span>
      <span className={`font-mono text-[12.5px] font-medium ${txt}`}>
        {indicator.value != null
          ? <>{typeof indicator.value === 'number' ? formatNumber(indicator.value, 2, { minDecimals: 0 }) : indicator.value}{indicator.unit || ''}</>
          : '–'}
      </span>
      <span className="text-[11px] text-text-muted w-24 text-right truncate">
        {indicator.status_label}
        {hasAvg && <span className="text-text-faint ml-1">({'⌀'} {indicator.historical_avg}{indicator.unit})</span>}
      </span>
    </div>
  )
}

// Bewertungs-Badge (CAPE/Buffett) — bewusst in Warn-Ton (amber), NICHT Risk-Rot:
// strukturelle Überbewertung ist Kontext, kein akutes Risk-Off. Wird nur gezeigt,
// wenn die Bewertung erhöht/überbewertet ist (grün/keine Daten -> nichts).
function ValuationBadge({ status, label, shiller, buffett }) {
  if (!status || status === 'unavailable' || status === 'green') return null
  const parts = []
  if (shiller?.value != null) parts.push(`CAPE ${formatNumber(shiller.value, 1, { minDecimals: 0 })}`)
  if (buffett?.value != null) parts.push(`Buffett ${formatNumber(buffett.value, 0)}%`)
  return (
    <div className="mt-2.5 inline-flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/10 px-2.5 py-1.5">
      <AlertTriangle size={13} className="text-warning shrink-0 mt-0.5" />
      <span className="text-[11.5px] text-warning leading-snug">
        <G term="Bewertung">Bewertung</G>: {label}
        {parts.length > 0 && <span className="text-text-muted font-mono tabular-nums"> · {parts.join(' · ')}</span>}
      </span>
    </div>
  )
}

function ExtraIndicatorCard({ indicator }) {
  const hasChange = indicator.change_pct != null
  const isPositive = hasChange && indicator.change_pct >= 0
  const changeColor = hasChange ? (isPositive ? 'text-success' : 'text-danger') : 'text-text-muted'
  const ChangeIcon = isPositive ? TrendingUp : TrendingDown
  const spreadStatusColor = indicator.status === 'red' ? 'text-danger' : indicator.status === 'yellow' ? 'text-warning' : indicator.status === 'green' ? 'text-success' : ''

  return (
    <div className="bg-card-2 border border-border-2 rounded-lg px-3 py-2.5" title={`Quelle: ${indicator.source}`}>
      <div className="text-[11px] text-text-muted mb-1 truncate"><G term={indicator.label}>{indicator.label}</G></div>
      <div className="flex items-baseline gap-1.5 flex-wrap">
        <span className={`text-[13px] font-mono font-medium ${spreadStatusColor || 'text-text-primary'}`}>
          {indicator.value != null
            ? (typeof indicator.value === 'number'
              ? formatNumber(indicator.value, indicator.value < 10 ? 4 : 2, { minDecimals: 0 })
              : indicator.value)
            : '–'}
          {indicator.unit || ''}
        </span>
        {hasChange && (
          <span className={`flex items-center gap-0.5 text-[11px] font-mono ${changeColor}`}>
            <ChangeIcon size={11} />
            {isPositive ? '+' : ''}{indicator.change_pct.toFixed(2)}%
          </span>
        )}
        {indicator.spread_pct != null && (
          <span className={`text-[11px] font-mono ${spreadStatusColor}`}>
            ({indicator.spread_pct > 0 ? '+' : ''}{indicator.spread_pct.toFixed(1)}%)
          </span>
        )}
        {indicator.last_change_date && (
          <span className="text-[10.5px] text-text-muted">seit {formatDate(`${indicator.last_change_date}T00:00:00`)}</span>
        )}
      </div>
    </div>
  )
}

function GateSection({ gate }) {
  const [expanded, setExpanded] = useState(false)
  if (!gate) return null

  const unavailCount = gate.unavailable_count || 0
  const maxScoreTitle = unavailCount > 0
    ? `Reduziert von 9 auf ${gate.max_score} weil ${unavailCount} Indikator${unavailCount > 1 ? 'en' : ''} nicht verfügbar`
    : ''

  return (
    <div className="border-t border-border-2 pt-3.5 mt-1">
      <button onClick={() => setExpanded(!expanded)} className="flex items-center gap-2 w-full text-left">
        <Shield size={14} className={gate.passed ? 'text-success' : 'text-danger'} />
        <span className="text-[12.5px] font-medium text-text-secondary">
          <G term="Makro-Gate">Makro-Gate</G>:{' '}
          <span className={`font-mono ${gate.passed ? 'text-success' : 'text-danger'}`} title={maxScoreTitle}>
            {gate.score}/{gate.max_score}
          </span>
          {' '}<span className={gate.passed ? 'text-success' : 'text-danger'}>({gate.label})</span>
        </span>
        {expanded ? <ChevronUp size={13} className="text-text-muted ml-auto" /> : <ChevronDown size={13} className="text-text-muted ml-auto" />}
      </button>
      {expanded && (
        <div className="mt-2.5 space-y-1.5 pl-5">
          {gate.checks?.map((c) => (
            <div key={c.id} className="flex items-center gap-2 text-[11.5px]">
              <span>{c.unavailable ? '⚪' : c.passed ? '✅' : '❌'}</span>
              <span className={`flex-1 ${c.unavailable ? 'text-text-muted' : 'text-text-secondary'}`}>{c.label}</span>
              <span className="text-text-muted font-mono">
                {c.unavailable ? '–' : <><G term="Gew.">Gew.</G> {c.weight}</>}
              </span>
            </div>
          ))}
          <div className="text-[11px] text-text-muted mt-1">
            <G term="Schwelle">Schwelle</G>: {gate.threshold}/{gate.max_score} Punkte (2/3)
            {unavailCount > 0 && ` — ${unavailCount} Check${unavailCount > 1 ? 's' : ''} ohne Daten`}
          </div>
        </div>
      )}
    </div>
  )
}

export default function MarketClimate({ data: externalData }) {
  const { data: fetchedData, loading, error } = useApi('/market/climate', { skip: !!externalData })
  const data = externalData || fetchedData

  if (!data && loading) return <ClimateShell />
  if (!data && error) return <ClimateError error={error} />
  if (!data) return <ClimateShell />

  const { sp500_price, checks, macro, extra_indicators, gate, combined_status, combined_label, combined_hint, vix, valuation_status, valuation_label } = data
  const toneText = COMBINED_TEXT[combined_status] || 'text-warning'

  const checkObj = checks || {}
  const usable = CRITERIA.filter(([k]) => checkObj[k] != null)
  const trueCount = usable.filter(([k]) => checkObj[k] === true).length
  const total = usable.length || 6
  const scorePct = Math.max(0, Math.min(100, total > 0 ? Math.round((trueCount / total) * 100) : 50))

  const macroData = macro || {}
  const indicators = macroData.indicators || []
  const unavailableCount = macroData.unavailable_count || 0

  // Indikatoren in Risk-Treiber vs. Bewertung trennen (robust auch ohne group-Feld).
  const isValuation = (i) => i.group === 'valuation' || i.name === 'shiller_pe' || i.name === 'buffett_indicator'
  const riskInds = indicators.filter((i) => !isValuation(i))
  const valInds = indicators.filter(isValuation)
  const shiller = indicators.find((i) => i.name === 'shiller_pe')
  const buffett = indicators.find((i) => i.name === 'buffett_indicator')

  // 2x2 Kennzahlen-Tiles aus echten Klima-Feldern
  const vixInd = indicators.find((i) => i.name === 'vix')
  const vixValue = vixInd?.value != null ? vixInd.value : vix?.value
  const tiles = [
    {
      label: 'VIX',
      value: vixValue != null ? formatNumber(vixValue, 1, { minDecimals: 0 }) : '–',
      tone: IND_TONE[vixInd?.status] || 'default',
      sub: vixInd?.status_label,
    },
    {
      label: 'S&P 500',
      value: sp500_price != null ? formatNumber(sp500_price, 0) : '–',
      tone: 'default',
      sub: `${trueCount}/${total} Kriterien`,
    },
    {
      label: 'Makro-Gate',
      value: gate ? `${gate.score}/${gate.max_score}` : '–',
      tone: gate ? (gate.passed ? 'success' : 'danger') : 'default',
      sub: gate?.label,
    },
    {
      label: 'Risk-Ampel',
      value: macroData.overall_label || '–',
      tone: IND_TONE[macroData.overall_status] || 'default',
      sub: `${macroData.green_count || 0} grün · ${macroData.red_count || 0} rot`,
    },
  ]

  return (
    <>
    {/* DESKTOP */}
    <div className="hidden md:grid grid-cols-1 xl:grid-cols-[1.7fr_1fr] gap-[18px]">
      {/* LINKS: Klima-Hero */}
      <Card className="p-[18px]">
        <CardLabel>Markt-Klima</CardLabel>
        <div className={`text-[30px] font-semibold tracking-[-0.01em] leading-none mt-2.5 ${toneText}`}>
          <G term={combined_label}>{combined_label}</G>
        </div>
        <div className="text-[13px] text-text-secondary mt-2">
          <span className="font-mono font-medium text-text-primary">{trueCount}</span> von {total} Kriterien bullish
        </div>
        {combined_hint && <p className={`text-xs mt-1 ${toneText}`}>{combined_hint}</p>}
        <ValuationBadge status={valuation_status} label={valuation_label} shiller={shiller} buffett={buffett} />

        {/* Gradient-Balken */}
        <div className="mt-4">
          <div
            className="relative h-2.5 rounded-full"
            style={{ background: 'linear-gradient(90deg, #e8625a 0%, #e0a64b 50%, #45c08a 100%)' }}
          >
            <div
              className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-3.5 h-3.5 rounded-full bg-white border-2 border-body shadow-md"
              style={{ left: `${scorePct}%` }}
            />
          </div>
          <div className="flex justify-between mt-1.5 font-mono text-[10px] uppercase tracking-[0.05em] text-text-faint">
            <span>Bearish</span><span>Neutral</span><span>Bullish</span>
          </div>
        </div>

        {/* 6 Kriterien */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-5 gap-y-2.5 mt-4">
          {CRITERIA.map(([key, label]) => (
            <CriterionRow key={key} label={label} value={checkObj[key]} />
          ))}
        </div>

        {/* Makro-Indikatoren (Detail) */}
        {indicators.length > 0 && (
          <div className="border-t border-border-2 pt-3.5 mt-4">
            <CardLabel className="mb-1.5">Makro-Indikatoren</CardLabel>
            {riskInds.length > 0 && (
              <div>
                <div className="text-[10px] font-mono uppercase tracking-[0.06em] text-text-faint mb-0.5">Risk-Treiber</div>
                {riskInds.map((ind) => <IndicatorRow key={ind.name} indicator={ind} />)}
              </div>
            )}
            {valInds.length > 0 && (
              <div className="mt-3">
                <div className="text-[10px] font-mono uppercase tracking-[0.06em] text-text-faint mb-0.5">Bewertung (Kontext — kein Risk-Treiber)</div>
                {valInds.map((ind) => <IndicatorRow key={ind.name} indicator={ind} />)}
              </div>
            )}
          </div>
        )}

        <GateSection gate={gate} />

        {unavailableCount > 0 && (
          <div className="mt-3 flex items-center gap-2 text-[11px] text-text-muted">
            <Settings size={11} className="flex-shrink-0" />
            <span>
              Für vollständige Daten:{' '}
              <Link to="/settings" className="text-link hover:underline">FRED API Key in den Einstellungen hinterlegen</Link>
            </span>
          </div>
        )}

        <div className="mt-3 flex items-start gap-2 text-[11px] text-text-muted">
          <Info size={12} className="flex-shrink-0 mt-0.5" />
          <span>Kein einzelner Indikator ist perfekt. Nutze sie als Gesamtbild. Dein bester Schutz bleibt der Trailing Stop-Loss.</span>
        </div>
      </Card>

      {/* RECHTS: Kennzahlen-Tiles + weitere Indikatoren */}
      <div className="flex flex-col gap-[14px]">
        <div className="grid grid-cols-2 gap-[14px]">
          {tiles.map((t, i) => <StatTile key={i} {...t} />)}
        </div>

        {extra_indicators && extra_indicators.length > 0 && (
          <Card className="p-[18px]">
            <CardLabel className="mb-2.5">Weitere Indikatoren</CardLabel>
            <div className="grid grid-cols-2 gap-2.5">
              {extra_indicators.map((ind) => <ExtraIndicatorCard key={ind.name} indicator={ind} />)}
            </div>
          </Card>
        )}
      </div>
    </div>

    {/* MOBILE — kompakte Klima-Sicht */}
    <div className="md:hidden flex flex-col gap-[14px]">
      {/* 1) Klima-Karte mit Score-Gauge */}
      <Card className="p-4">
        <CardLabel>Markt-Klima</CardLabel>
        <div className={`text-[26px] font-semibold tracking-[-0.01em] leading-none mt-2 ${toneText}`}>
          {combined_label}
        </div>
        <div className="text-[12.5px] text-text-secondary mt-1.5">
          <span className="font-mono font-medium text-text-primary">{trueCount}</span> von {total} Kriterien bullish
        </div>
        {combined_hint && <p className={`text-[11.5px] mt-1 ${toneText}`}>{combined_hint}</p>}
        <ValuationBadge status={valuation_status} label={valuation_label} shiller={shiller} buffett={buffett} />

        <div className="mt-3.5">
          <div
            className="relative h-2.5 rounded-full"
            style={{ background: 'linear-gradient(90deg, #e8625a 0%, #e0a64b 50%, #45c08a 100%)' }}
          >
            <div
              className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-3.5 h-3.5 rounded-full bg-white border-2 border-body shadow-md"
              style={{ left: `${scorePct}%` }}
            />
          </div>
          <div className="flex justify-between mt-1.5 font-mono text-[10px] uppercase tracking-[0.05em] text-text-faint">
            <span>Bearish</span><span>Bullish</span>
          </div>
        </div>
      </Card>

      {/* 2) 2x2 Kennzahlen-Tiles */}
      <div className="grid grid-cols-2 gap-[14px]">
        {tiles.map((t, i) => <StatTile key={i} {...t} />)}
      </div>

      {/* 3) Kriterien-Liste */}
      <Card className="p-4">
        <CardLabel className="mb-2.5">Kriterien</CardLabel>
        <div className="flex flex-col gap-2.5">
          {CRITERIA.map(([key, label]) => (
            <CriterionRow key={key} label={label} value={checkObj[key]} />
          ))}
        </div>
      </Card>
    </div>
    </>
  )
}

function ClimateShell() {
  return (
    <div className="grid grid-cols-1 xl:grid-cols-[1.7fr_1fr] gap-[18px]">
      <div className="bg-card border border-border rounded-card p-[18px] animate-pulse">
        <div className="h-3 bg-card-2 rounded w-24 mb-3" />
        <div className="h-8 bg-card-2 rounded w-40 mb-3" />
        <div className="h-2.5 bg-card-2 rounded w-full mb-4" />
        <div className="grid grid-cols-2 gap-3">
          {[...Array(6)].map((_, i) => <div key={i} className="h-4 bg-card-2 rounded" />)}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-[14px]">
        {[...Array(4)].map((_, i) => <div key={i} className="h-[88px] bg-card border border-border rounded-card animate-pulse" />)}
      </div>
    </div>
  )
}

function ClimateError({ error }) {
  return (
    <div className="rounded-card border border-danger/30 bg-danger/10 p-5">
      <h3 className="text-sm font-medium text-text-secondary mb-2">Marktklima</h3>
      <p className="text-sm text-danger">Fehler: {error}</p>
    </div>
  )
}
