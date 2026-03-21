import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { formatNumber } from '../lib/format'
import { Shield, Info, ChevronDown, ChevronUp, Settings, CheckCircle, XCircle, TrendingUp, TrendingDown } from 'lucide-react'
import G from './GlossarTooltip'

const STATUS_CONFIG = {
  green: { dot: 'bg-success', text: 'text-success' },
  yellow: { dot: 'bg-warning', text: 'text-warning' },
  red: { dot: 'bg-danger', text: 'text-danger' },
  unavailable: { dot: 'bg-text-muted/40', text: 'text-text-muted' },
  unknown: { dot: 'bg-text-muted/40', text: 'text-text-muted' },
}

const COMBINED_CONFIG = {
  green: { bg: 'bg-success/10', border: 'border-success/30', text: 'text-success' },
  yellow: { bg: 'bg-warning/10', border: 'border-warning/30', text: 'text-warning' },
  red: { bg: 'bg-danger/10', border: 'border-danger/30', text: 'text-danger' },
}

function StatusDot({ status }) {
  const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.unknown
  return <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${cfg.dot}`} />
}

function TechCheck({ check }) {
  const isUnavailable = check.passed === null || check.passed === undefined
  return (
    <div className="flex items-center gap-2 text-sm">
      {isUnavailable
        ? <span className="w-3.5 h-3.5 flex items-center justify-center text-text-muted flex-shrink-0">–</span>
        : check.passed
          ? <CheckCircle size={14} className="text-success flex-shrink-0" />
          : <XCircle size={14} className="text-danger flex-shrink-0" />
      }
      <span className={isUnavailable ? 'text-text-muted' : check.passed ? 'text-text-secondary' : 'text-text-muted'}><G term={check.label}>{check.label}</G></span>
    </div>
  )
}

function IndicatorRow({ indicator }) {
  const cfg = STATUS_CONFIG[indicator.status] || STATUS_CONFIG.unknown
  const hasAvg = indicator.historical_avg != null && indicator.value != null

  return (
    <div className="flex items-center gap-3 py-2" title={
      `Schwellenwerte: ${indicator.thresholds?.green || ''} / ${indicator.thresholds?.yellow || ''} / ${indicator.thresholds?.red || ''}\nQuelle: ${indicator.source}\nLetzte Aktualisierung: ${indicator.updated_at ? new Date(indicator.updated_at).toLocaleString('de-CH') : '\u2013'}`
    }>
      <StatusDot status={indicator.status} />
      <div className="flex-1 min-w-0">
        <span className="text-sm text-text-primary"><G term={indicator.label}>{indicator.label}</G></span>
      </div>
      <div className="text-right flex items-center gap-2">
        <span className={`text-sm font-mono font-medium ${cfg.text}`}>
          {indicator.value != null ? (
            <>
              {typeof indicator.value === 'number' ? indicator.value.toLocaleString('de-CH', { maximumFractionDigits: 2 }) : indicator.value}
              {indicator.unit && indicator.unit}
            </>
          ) : '\u2013'}
        </span>
        <span className="text-xs text-text-muted w-28 text-right truncate">
          {indicator.status_label}
          {hasAvg && (
            <span className="text-text-muted opacity-60 ml-1">
              ({'\u2300'} {indicator.historical_avg}{indicator.unit})
            </span>
          )}
        </span>
      </div>
    </div>
  )
}

function ExtraIndicatorCard({ indicator }) {
  const hasChange = indicator.change_pct != null
  const isPositive = hasChange && indicator.change_pct >= 0
  const changeColor = hasChange ? (isPositive ? 'text-success' : 'text-danger') : 'text-text-muted'
  const ChangeIcon = isPositive ? TrendingUp : TrendingDown

  return (
    <div className="bg-card-alt/50 rounded-lg px-4 py-3" title={`Quelle: ${indicator.source}`}>
      <div className="text-xs text-text-muted mb-1"><G term={indicator.label}>{indicator.label}</G></div>
      <div className="flex items-baseline gap-2">
        <span className="text-sm font-mono font-medium text-text-primary">
          {indicator.value != null
            ? (typeof indicator.value === 'number'
              ? indicator.value.toLocaleString('de-CH', { maximumFractionDigits: indicator.value < 10 ? 4 : 2 })
              : indicator.value)
            : '\u2013'}
          {indicator.unit || ''}
        </span>
        {hasChange && (
          <span className={`flex items-center gap-0.5 text-xs font-mono ${changeColor}`}>
            <ChangeIcon size={11} />
            {isPositive ? '+' : ''}{indicator.change_pct.toFixed(2)}%
          </span>
        )}
        {indicator.last_change_date && (
          <span className="text-[11px] text-text-muted">
            seit {new Date(indicator.last_change_date + 'T00:00:00').toLocaleDateString('de-CH')}
          </span>
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
    <div className="border-t border-border/50 pt-3 mt-1">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 w-full text-left"
      >
        <Shield size={14} className={gate.passed ? 'text-success' : 'text-danger'} />
        <span className="text-xs font-medium text-text-secondary">
          <G term="Makro-Gate">Makro-Gate</G>:{' '}
          <span className={`font-mono ${gate.passed ? 'text-success' : 'text-danger'}`} title={maxScoreTitle}>
            {gate.score}/{gate.max_score}
          </span>
          {' '}<span className={gate.passed ? 'text-success' : 'text-danger'}>({gate.label})</span>
        </span>
        {expanded ? <ChevronUp size={12} className="text-text-muted ml-auto" /> : <ChevronDown size={12} className="text-text-muted ml-auto" />}
      </button>
      {expanded && (
        <div className="mt-2 space-y-1 pl-5">
          {gate.checks?.map((c) => (
            <div key={c.id} className="flex items-center gap-2 text-xs">
              <span>{c.unavailable ? '\u26AA' : c.passed ? '\u2705' : '\u274C'}</span>
              <span className={`flex-1 ${c.unavailable ? 'text-text-muted' : 'text-text-secondary'}`}>{c.label}</span>
              <span className="text-text-muted font-mono">
                {c.unavailable ? '\u2013' : <><G term="Gew.">Gew.</G> {c.weight}</>}
              </span>
            </div>
          ))}
          <div className="text-[11px] text-text-muted mt-1">
            <G term="Schwelle">Schwelle</G>: {gate.threshold}/{gate.max_score} Punkte (2/3)
            {unavailCount > 0 && ` \u2014 ${unavailCount} Check${unavailCount > 1 ? 's' : ''} ohne Daten`}
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

  const { sp500_price, tech_checks, macro, extra_indicators, gate, combined_status, combined_label, combined_hint } = data
  const style = COMBINED_CONFIG[combined_status] || COMBINED_CONFIG.yellow

  const macroData = macro || {}
  const indicators = macroData.indicators || []
  const unavailableCount = macroData.unavailable_count || 0

  return (
    <div className={`rounded-lg border p-5 ${style.bg} ${style.border}`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-medium text-text-secondary"><G term="Marktklima">Marktklima</G></h3>
        <span
          className={`text-xs font-bold px-2.5 py-1 rounded ${style.text} ${style.bg} border ${style.border}`}
          title={combined_hint}
        >
          <G term={combined_label}>{combined_label}</G>
        </span>
      </div>

      {/* S&P 500 Price + Hint */}
      <div className="mb-4">
        <div className="text-sm text-text-secondary">
          S&P 500: <span className="text-text-primary font-mono font-medium">{formatNumber(sp500_price, 2)}</span>
        </div>
        <p className={`text-xs mt-1 ${style.text}`}>{combined_hint}</p>
      </div>

      {/* Technical Indicators */}
      {tech_checks && tech_checks.length > 0 && (
        <div className="mb-4">
          <div className="text-xs font-medium text-text-muted uppercase tracking-wide mb-2">Technische Indikatoren</div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1">
            {tech_checks.map((c) => <TechCheck key={c.id} check={c} />)}
          </div>
        </div>
      )}

      {/* Macro Indicators */}
      {indicators.length > 0 && (
        <div>
          <div className="text-xs font-medium text-text-muted uppercase tracking-wide mb-1">Makro-Indikatoren</div>
          <div className="divide-y divide-border/30">
            {indicators.map((ind) => (
              <IndicatorRow key={ind.name} indicator={ind} />
            ))}
          </div>
        </div>
      )}

      {/* Extra Indicators (Oil, Fed Rate, USD/CHF) */}
      {extra_indicators && extra_indicators.length > 0 && (
        <div className="mt-4">
          <div className="text-xs font-medium text-text-muted uppercase tracking-wide mb-2">Weitere Indikatoren</div>
          <div className="grid grid-cols-3 gap-2">
            {extra_indicators.map((ind) => (
              <ExtraIndicatorCard key={ind.name} indicator={ind} />
            ))}
          </div>
        </div>
      )}

      {/* Ampel counts + timestamp */}
      <div className="flex items-center gap-4 mt-3 text-xs text-text-muted">
        <span>{macroData.green_count || 0} <span className="text-success">{'\u{1F7E2}'}</span></span>
        <span>{macroData.yellow_count || 0} <span className="text-warning">{'\u{1F7E1}'}</span></span>
        <span>{macroData.red_count || 0} <span className="text-danger">{'\u{1F534}'}</span></span>
        {unavailableCount > 0 && (
          <span>{unavailableCount} <span className="text-text-muted">{'\u26AA'}</span></span>
        )}
        <span className="ml-auto">
          {macroData.updated_at ? new Date(macroData.updated_at).toLocaleString('de-CH', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : ''}
        </span>
      </div>

      {/* Gate */}
      <GateSection gate={gate} />

      {/* FRED API hint */}
      {unavailableCount > 0 && (
        <div className="mt-2 flex items-center gap-2 text-[11px] text-text-muted">
          <Settings size={11} className="flex-shrink-0" />
          <span>
            Für vollständige Daten:{' '}
            <Link to="/settings" className="text-primary hover:underline">FRED API Key in den Einstellungen hinterlegen</Link>
          </span>
        </div>
      )}

      {/* Disclaimer */}
      <div className="mt-2 flex items-start gap-2 text-[11px] text-text-muted">
        <Info size={12} className="flex-shrink-0 mt-0.5" />
        <span>Kein einzelner Indikator ist perfekt. Nutze sie als Gesamtbild. Dein bester Schutz bleibt der Trailing Stop-Loss.</span>
      </div>
    </div>
  )
}

function ClimateShell() {
  return (
    <div className="rounded-lg border border-border bg-card p-5 animate-pulse">
      <div className="h-4 bg-card-alt rounded w-24 mb-3" />
      <div className="h-8 bg-card-alt rounded w-32 mb-2" />
      <div className="h-4 bg-card-alt rounded w-48" />
    </div>
  )
}

function ClimateError({ error }) {
  return (
    <div className="rounded-lg border border-danger/30 bg-danger/10 p-5">
      <h3 className="text-sm font-medium text-text-secondary mb-2">Marktklima</h3>
      <p className="text-sm text-danger">Fehler: {error}</p>
    </div>
  )
}
