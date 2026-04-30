import { AlertTriangle, Info } from 'lucide-react'

/**
 * ConcentrationBanner: vollständige Sicht auf Single-Name + Sektor-Konzentration.
 *
 * Phase 1.1 (v0.29.0) ersetzt den alten CoreOverlapBanner. Scope-Erweiterung:
 *  - Single-Name-Zeile: Direkt-Position-Baseline + Indirekt via ETFs
 *  - Sektor-Zeile: aggregiert über alle Direkt-Holdings + ETF-anteilig
 *
 * Conditional Rendering:
 *  - Single-Name-Zeile: wenn Indirekt-Overlap ≥2% ODER Direkt-Position ≥6%
 *  - Sektor-Zeile: wenn sector_aggregation.status === "ok"
 *  - Beide fehlen → kein Banner
 *
 * Tooltip-Logik gegen Falsch-Sicherheit (Phase B carry-over):
 *   - as_of vorhanden → "Holdings-Stand laut FMP: <date>"
 *   - as_of None → "Stichtag unbekannt, typisch 30-60 Tage Lag"
 *   - Niemals updated_at als Holdings-Stand zeigen
 */
export default function ConcentrationBanner({ concentration, ticker, liquidPortfolioChf }) {
  if (!concentration) return null

  const singleName = concentration.single_name || {}
  const sector = concentration.sector || { status: 'no_sector' }

  const overlaps = singleName.overlaps || []
  const directChf = singleName.direct_position_chf
  const directPct = liquidPortfolioChf && liquidPortfolioChf > 0 && directChf
    ? (directChf / liquidPortfolioChf) * 100
    : null

  const showSingleNameRow = overlaps.length > 0 || (directPct !== null && directPct >= 6)
  const showSectorRow = sector.status === 'ok'
  const showCoverageWarning = sector.status === 'low_coverage'

  if (!showSingleNameRow && !showSectorRow && !showCoverageWarning) return null

  const isHardWarn = sector.hard_warn === true
  const bannerColor = isHardWarn
    ? 'bg-danger/10 border-danger/30'
    : 'bg-warning/10 border-warning/30'
  const iconColor = isHardWarn ? 'text-danger' : 'text-warning'

  return (
    <div className={`${bannerColor} border rounded-lg p-4 mb-3`}>
      <div className="flex items-start gap-3">
        <AlertTriangle size={18} className={`${iconColor} mt-0.5 flex-shrink-0`} />
        <div className="flex-1 text-sm space-y-3">
          <p className="font-medium text-text-primary">
            Konzentrations-Check {ticker}
          </p>

          {showSingleNameRow && (
            <SingleNameRow
              ticker={ticker}
              overlaps={overlaps}
              singleName={singleName}
              directPct={directPct}
              liquidPortfolioChf={liquidPortfolioChf}
            />
          )}

          {showSectorRow && (
            <SectorRow ticker={ticker} sector={sector} />
          )}

          {showCoverageWarning && (
            <CoverageWarningRow sector={sector} />
          )}
        </div>
      </div>
    </div>
  )
}


function SingleNameRow({ ticker, overlaps, singleName, directPct, liquidPortfolioChf }) {
  const fmtChf = (v) => Math.round(v).toLocaleString('de-CH')

  const totalChf = singleName.total_chf || 0
  const totalIndirectChf = singleName.total_indirect_chf || 0
  const directChf = singleName.direct_position_chf
  const totalPct = singleName.total_pct
  const indirectPct = liquidPortfolioChf && liquidPortfolioChf > 0
    ? (totalIndirectChf / liquidPortfolioChf) * 100
    : null

  const hypotheticalDirectChf = liquidPortfolioChf ? liquidPortfolioChf * 0.05 : null
  const hypotheticalTotalPct = (totalPct !== null && hypotheticalDirectChf !== null)
    ? totalPct + 5.0
    : null

  return (
    <div className="space-y-1.5">
      <p className="text-text-secondary font-medium">Single-Name:</p>
      {directChf !== null && directChf > 0 && (
        <p className="text-text-secondary text-xs ml-2">
          • <span className="font-mono">Direkt</span>: {fmtChf(directChf)} CHF
          {directPct !== null && <span> ({directPct.toFixed(1)}%)</span>}
        </p>
      )}
      {overlaps.map((o) => (
        <p key={o.etf_ticker} className="text-text-secondary text-xs ml-2 flex items-baseline gap-1 flex-wrap">
          • <span className="font-mono text-text-primary">{o.etf_ticker}</span>
          <span className="text-text-muted">({o.etf_name}):</span>
          <span>{o.weight_pct.toFixed(1)}% Gewicht</span>
          <span className="text-text-muted">·</span>
          <span>~{fmtChf(o.indirect_exposure_chf)} CHF {ticker}</span>
          <HoldingsStandTooltip asOf={o.holdings_as_of} />
        </p>
      ))}
      <p className="text-text-secondary mt-1">
        <span className="font-medium">Total:</span>
        {' '}~{fmtChf(totalChf)} CHF
        {totalPct !== null && <span> (~{totalPct.toFixed(1)}% Liquid-Portfolio)</span>}
      </p>
      {hypotheticalTotalPct !== null && (
        <p className="text-text-secondary">
          Direktkauf von 5% Position-Size (~{fmtChf(hypotheticalDirectChf)} CHF) würde
          {ticker}-Total auf <span className="font-bold">~{hypotheticalTotalPct.toFixed(1)}%</span> heben
          {hypotheticalTotalPct > 8 && (
            <span> — überschreitet Single-Name-Cap (~6–8%) deutlich.</span>
          )}
          {hypotheticalTotalPct >= 6 && hypotheticalTotalPct <= 8 && (
            <span> — am oberen Rand des Single-Name-Caps (~6–8%).</span>
          )}
          {hypotheticalTotalPct < 6 && (
            <span> — innerhalb Single-Name-Cap (~6–8%).</span>
          )}
        </p>
      )}
    </div>
  )
}


function SectorRow({ ticker, sector }) {
  const currentPct = sector.current_pct
  const postBuyPct = sector.post_buy_pct
  const sectorName = sector.sector
  const isHard = sector.hard_warn === true
  const isSoft = sector.soft_warn === true && !isHard

  const colorClass = isHard ? 'text-danger' : 'text-warning'
  const labelText = isHard
    ? 'Hard-Warn'
    : 'Soft-Warn'

  return (
    <div className="space-y-1 pt-2 border-t border-border/50">
      <p className="text-text-secondary font-medium">
        Sektor-Aggregation: {sectorName}
      </p>
      <p className="text-text-secondary">
        <span className="font-medium">Total-{sectorName}:</span>
        {' '}<span className={`font-bold ${colorClass}`}>{currentPct?.toFixed(1)}%</span>
        {' '}<span className="text-text-muted">(Strategie-Range 15–25%, {labelText})</span>
      </p>
      {postBuyPct !== null && postBuyPct !== undefined && (
        <p className="text-text-secondary">
          Direktkauf {ticker} hebt {sectorName} auf <span className={`font-bold ${colorClass}`}>{postBuyPct.toFixed(1)}%</span>
          {postBuyPct >= 35 && (
            <span> — über Hard-Limit (35%), klares Konzentrationsrisiko.</span>
          )}
          {postBuyPct >= 25 && postBuyPct < 35 && (
            <span> — am oberen Rand der Strategie-Range (Soft-Warn).</span>
          )}
        </p>
      )}
    </div>
  )
}


function CoverageWarningRow({ sector }) {
  const affected = sector.affected_etfs || []
  return (
    <div className="space-y-1 pt-2 border-t border-border/50">
      <p className="text-text-muted text-xs italic">
        Sektor-Aggregation aktuell nicht verfügbar — Coverage-Lücke bei{' '}
        {affected.map((e, i) => (
          <span key={e.etf_ticker}>
            {i > 0 ? ', ' : ''}
            <span className="font-mono">{e.etf_ticker}</span> ({e.classified_pct?.toFixed(0)}%)
          </span>
        ))}
        . Operator wurde via Worker-Log informiert.
      </p>
    </div>
  )
}


function HoldingsStandTooltip({ asOf }) {
  const tooltip = asOf
    ? `Holdings-Stand laut FMP: ${new Date(asOf).toLocaleDateString('de-CH')} (typisch 30–60 Tage Lag)`
    : 'Holdings-Quelle FMP, Stichtag unbekannt, typisch 30–60 Tage Lag'
  return (
    <span className="inline-flex items-center" title={tooltip}>
      <Info size={11} className="text-text-muted cursor-help" />
    </span>
  )
}
