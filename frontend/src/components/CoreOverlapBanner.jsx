import { AlertTriangle, Info } from 'lucide-react'

/**
 * Core-Overlap-Banner: zeigt indirekte Aktien-Exposure via User-ETFs.
 *
 * Phase 1 deckt nur US-ETFs ab (FMP-Coverage). Für Non-US-ETFs (.SW, .L, .TO)
 * existiert kein Holdings-Mapping, daher zeigt der Banner für diese Ticker
 * nichts.
 *
 * Tooltip-Logik gegen Falsch-Sicherheit:
 *   - as_of vorhanden → "Holdings-Stand laut FMP: <date>"
 *   - as_of None → "Stichtag unbekannt, typisch 30-60 Tage Lag"
 *   - Niemals updated_at als Holdings-Stand zeigen (das wäre nur Pull-Zeit)
 */
export default function CoreOverlapBanner({ overlaps, ticker, liquidPortfolioChf }) {
  if (!overlaps || overlaps.length === 0) return null

  const totalIndirectChf = overlaps.reduce((sum, o) => sum + (o.indirect_exposure_chf || 0), 0)
  const indirectPct = liquidPortfolioChf && liquidPortfolioChf > 0
    ? (totalIndirectChf / liquidPortfolioChf) * 100
    : null

  // Hypothetischer 5%-Direktkauf vom Liquid-Portfolio
  const hypotheticalDirectChf = liquidPortfolioChf ? liquidPortfolioChf * 0.05 : null
  const hypotheticalTotalPct = (indirectPct !== null && hypotheticalDirectChf !== null)
    ? indirectPct + 5.0
    : null

  const fmtChf = (v) => Math.round(v).toLocaleString('de-CH')
  const fmtAsOf = (iso) => iso ? new Date(iso).toLocaleDateString('de-CH') : null

  return (
    <div className="bg-warning/10 border border-warning/30 rounded-lg p-4 mb-3">
      <div className="flex items-start gap-3">
        <AlertTriangle size={18} className="text-warning mt-0.5 flex-shrink-0" />
        <div className="flex-1 text-sm">
          <p className="font-medium text-text-primary mb-2">
            Du hältst {ticker} bereits indirekt über deine ETFs:
          </p>
          <ul className="space-y-1 mb-2">
            {overlaps.map((o) => (
              <li key={o.etf_ticker} className="text-text-secondary flex items-baseline gap-1.5 flex-wrap">
                <span className="font-mono text-text-primary">{o.etf_ticker}</span>
                <span className="text-text-muted">
                  ({o.etf_name}):
                </span>
                <span className="font-medium">{o.weight_pct.toFixed(1)}%</span>
                <span className="text-text-muted">Gewicht</span>
                <span className="text-text-muted">·</span>
                <span className="text-text-muted">
                  Position {fmtChf(o.etf_position_chf)} CHF =
                </span>
                <span className="font-medium text-text-primary">
                  ~{fmtChf(o.indirect_exposure_chf)} CHF {ticker}
                </span>
                <HoldingsStandTooltip asOf={o.holdings_as_of} />
              </li>
            ))}
          </ul>
          <p className="text-text-secondary">
            <span className="font-medium">Total indirekt:</span>
            {' '}~{fmtChf(totalIndirectChf)} CHF {ticker}-Exposure
            {indirectPct !== null && (
              <span> (~{indirectPct.toFixed(1)}% deines Liquid-Portfolios)</span>
            )}
          </p>
          {hypotheticalTotalPct !== null && (
            <p className="text-text-secondary mt-1">
              Direktkauf von 5% Position-Size (~{fmtChf(hypotheticalDirectChf)} CHF) würde
              Total-{ticker} auf <span className="font-bold text-warning">~{hypotheticalTotalPct.toFixed(1)}%</span> heben
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
      </div>
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
