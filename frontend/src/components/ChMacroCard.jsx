import { useApi } from '../hooks/useApi'
import { formatNumber, formatDate } from '../lib/format'
import { ArrowUp, ArrowDown, Minus } from 'lucide-react'
import Skeleton from './Skeleton'

function TrendPill({ trend }) {
  if (trend === 'up' || trend === 'chf_stronger') return <ArrowUp size={14} className="text-success" />
  if (trend === 'down' || trend === 'chf_weaker') return <ArrowDown size={14} className="text-danger" />
  return <Minus size={14} className="text-text-muted" />
}

function Metric({ label, value, sub, trend }) {
  return (
    <div className="bg-body border border-border rounded-lg p-3">
      <div className="text-xs text-text-muted">{label}</div>
      <div className="flex items-baseline gap-2">
        <div className="text-lg font-semibold text-text-primary">{value}</div>
        {trend && <TrendPill trend={trend} />}
      </div>
      {sub && <div className="text-xs text-text-muted mt-0.5">{sub}</div>}
    </div>
  )
}

export default function ChMacroCard() {
  const { data, loading, error } = useApi('/market/macro/ch')

  if (loading) return <Skeleton className="h-64" />
  if (error || !data) return null

  return (
    <div className="bg-card border border-border rounded-2xl p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-text-secondary uppercase tracking-wide">Schweiz</h3>
        {data.warnings?.length > 0 && (
          <span className="text-xs text-text-muted">{data.warnings.length} warnings</span>
        )}
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        {data.snb && (
          <Metric
            label="SNB Leitzins"
            value={`${formatNumber(data.snb.policy_rate_pct, 2)}%`}
            sub={data.snb.next_meeting ? `Naechste Sitzung: ${formatDate(data.snb.next_meeting)}` : null}
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
            label="CH Inflation (HICP)"
            value={`${formatNumber(data.ch_inflation.cpi_yoy_pct, 2)}%`}
            sub={data.ch_inflation.core_cpi_yoy_pct != null
              ? `Core ${formatNumber(data.ch_inflation.core_cpi_yoy_pct, 2)}% (${data.ch_inflation.cpi_as_of})`
              : data.ch_inflation.cpi_as_of}
          />
        )}
        {data.smi_vs_sp500_30d && (
          <Metric
            label="SMI vs S&P 500 (30d)"
            value={`${data.smi_vs_sp500_30d.relative_pct > 0 ? '+' : ''}${formatNumber(data.smi_vs_sp500_30d.relative_pct, 2)}%`}
            sub={`SMI ${formatNumber(data.smi_vs_sp500_30d.smi_return_pct, 1)}% / SPX ${formatNumber(data.smi_vs_sp500_30d.sp500_return_pct, 1)}%`}
          />
        )}
      </div>
    </div>
  )
}
