import { useApi } from '../hooks/useApi'
import { formatNumber, formatDate } from '../lib/format'
import { ArrowUp, ArrowDown, Minus } from 'lucide-react'
import G from './GlossarTooltip'
import Card from './ui/Card'

function TrendIcon({ trend }) {
  if (trend === 'up' || trend === 'chf_stronger') return <ArrowUp size={12} className="text-success flex-shrink-0" />
  if (trend === 'down' || trend === 'chf_weaker') return <ArrowDown size={12} className="text-danger flex-shrink-0" />
  return <Minus size={12} className="text-text-muted flex-shrink-0" />
}

function Metric({ label, value, sub, trend }) {
  return (
    <div className="flex items-center gap-3 py-[11px] border-b border-border-row2 last:border-0">
      <div className="flex-1 min-w-0">
        <div className="text-[12.5px] text-text-secondary">{label}</div>
        {sub && <div className="text-[11px] text-text-muted truncate mt-0.5">{sub}</div>}
      </div>
      <div className="flex items-center gap-1.5 flex-shrink-0">
        <span className="text-text-primary font-mono font-medium text-[13px] tabular-nums">{value}</span>
        {trend && <TrendIcon trend={trend} />}
      </div>
    </div>
  )
}

export default function ChMacroCard() {
  const { data, loading, error } = useApi('/market/macro/ch')

  if (loading) {
    return (
      <Card className="p-[18px] animate-pulse">
        <div className="h-3 bg-card-2 rounded w-32 mb-4" />
        <div className="space-y-2">
          {[...Array(7)].map((_, i) => <div key={i} className="h-8 bg-card-2 rounded" />)}
        </div>
      </Card>
    )
  }
  if (error || !data) return null

  return (
    <Card className="overflow-hidden">
      <div className="px-[18px] py-4 border-b border-border-2 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <span className="w-[9px] h-[9px] rounded-[3px]" style={{ background: '#e8625a' }} />
          <h3 className="text-sm font-semibold text-text-primary">Schweiz — Makro &amp; FX</h3>
        </div>
        {data.warnings?.length > 0 && (
          <span className="text-[11px] text-text-muted" title={data.warnings.join(', ')}>
            {data.warnings.length} Hinweis{data.warnings.length === 1 ? '' : 'e'}
          </span>
        )}
      </div>

      <div className="px-[18px] py-1">
        {data.snb && (
          <Metric
            label={<><G term="SNB">SNB</G> Leitzins</>}
            value={`${formatNumber(data.snb.policy_rate_pct, 2)}%`}
            sub={data.snb.next_meeting ? `Nächste Sitzung: ${formatDate(data.snb.next_meeting)}` : null}
          />
        )}
        {data.saron && (
          <Metric
            label="SARON"
            value={`${formatNumber(data.saron.current_pct, 2)}%`}
            sub={`30d: ${data.saron.delta_30d_bps > 0 ? '+' : ''}${data.saron.delta_30d_bps} bps`}
            trend={data.saron.trend}
          />
        )}
        {data.fx?.chf_eur && (
          <Metric
            label="CHF/EUR"
            value={formatNumber(data.fx.chf_eur.rate, 4)}
            sub={`30d: ${data.fx.chf_eur.delta_30d_pct > 0 ? '+' : ''}${formatNumber(data.fx.chf_eur.delta_30d_pct, 2)}%`}
            trend={data.fx.chf_eur.trend}
          />
        )}
        {data.fx?.chf_usd && (
          <Metric
            label="CHF/USD"
            value={formatNumber(data.fx.chf_usd.rate, 4)}
            sub={`30d: ${data.fx.chf_usd.delta_30d_pct > 0 ? '+' : ''}${formatNumber(data.fx.chf_usd.delta_30d_pct, 2)}%`}
            trend={data.fx.chf_usd.trend}
          />
        )}
        {data.ch_rates && (
          <Metric
            label="Eidg. 10Y Rendite"
            value={`${formatNumber(data.ch_rates.eidg_10y_yield_pct, 2)}%`}
            sub={`30d: ${data.ch_rates.delta_30d_bps > 0 ? '+' : ''}${data.ch_rates.delta_30d_bps} bps`}
            trend={data.ch_rates.trend}
          />
        )}
        {data.ch_inflation && data.ch_inflation.cpi_yoy_pct != null && (
          <Metric
            label={<>CH Inflation (<G term="HICP">HICP</G>)</>}
            value={`${formatNumber(data.ch_inflation.cpi_yoy_pct, 2)}%`}
            sub={data.ch_inflation.core_cpi_yoy_pct != null
              ? `Core ${formatNumber(data.ch_inflation.core_cpi_yoy_pct, 2)}% · ${data.ch_inflation.cpi_as_of}`
              : data.ch_inflation.cpi_as_of}
          />
        )}
        {data.smi_vs_sp500_30d && (
          <Metric
            label="SMI vs S&P 500 (30d)"
            value={`${data.smi_vs_sp500_30d.relative_pct > 0 ? '+' : ''}${formatNumber(data.smi_vs_sp500_30d.relative_pct, 2)}%`}
            sub={`SMI ${formatNumber(data.smi_vs_sp500_30d.smi_return_pct, 1)}% · SPX ${formatNumber(data.smi_vs_sp500_30d.sp500_return_pct, 1)}%`}
          />
        )}
      </div>
    </Card>
  )
}
