import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import { formatCHF } from '../lib/format'
import { Receipt, ChevronDown } from 'lucide-react'

const MONTH_NAMES = ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun', 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez']

export default function FeeSummary() {
  const { data, loading } = useApi('/portfolio/fee-summary')
  const [open, setOpen] = useState(false)

  if (loading || !data) return null
  if (!data.by_month || data.by_month.length === 0) return null

  const totalAll = data.total_trading_fees_chf + data.total_other_fees_chf + data.total_taxes_chf

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full p-4 flex items-center justify-between hover:bg-card-alt/30 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Receipt size={16} className="text-primary" />
          <h3 className="text-sm font-medium text-text-secondary">Gebühren & Steuern</h3>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm font-bold text-text-primary">{formatCHF(totalAll)}</span>
          <ChevronDown size={16} className={`text-text-muted transition-transform ${open ? 'rotate-180' : ''}`} />
        </div>
      </button>
      {open && (
        <div className="border-t border-border">
          {/* Summary cards */}
          <div className="grid grid-cols-3 gap-px bg-border/30">
            <SummaryCell label="Handelsgebühren" value={data.total_trading_fees_chf} />
            <SummaryCell label="Depotgebühren" value={data.total_other_fees_chf} />
            <SummaryCell label="Steuern" value={data.total_taxes_chf} />
          </div>

          {/* Monthly breakdown */}
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/[0.08] text-slate-400 text-[11px] uppercase tracking-wider">
                  <th className="text-left p-3 font-medium">Monat</th>
                  <th className="text-right p-3 font-medium">Handelsgebühren</th>
                  <th className="text-right p-3 font-medium">Depotgebühren</th>
                  <th className="text-right p-3 font-medium">Steuern</th>
                  <th className="text-right p-3 font-medium">Total</th>
                </tr>
              </thead>
              <tbody>
                {data.by_month.map((m) => {
                  const monthTotal = m.trading_fees_chf + m.other_fees_chf + m.taxes_chf
                  return (
                    <tr key={`${m.year}-${m.month}`} className="border-b border-border/50 hover:bg-card-alt/50 transition-colors">
                      <td className="p-3 text-text-primary tabular-nums">{MONTH_NAMES[m.month - 1]} {m.year}</td>
                      <td className="p-3 text-right text-text-secondary tabular-nums">{m.trading_fees_chf > 0 ? formatCHF(m.trading_fees_chf) : '–'}</td>
                      <td className="p-3 text-right text-text-secondary tabular-nums">{m.other_fees_chf > 0 ? formatCHF(m.other_fees_chf) : '–'}</td>
                      <td className="p-3 text-right text-text-secondary tabular-nums">{m.taxes_chf > 0 ? formatCHF(m.taxes_chf) : '–'}</td>
                      <td className="p-3 text-right text-text-primary font-medium tabular-nums">{formatCHF(monthTotal)}</td>
                    </tr>
                  )
                })}
                <tr className="bg-card-alt/30">
                  <td className="p-3 text-text-primary font-medium">Total</td>
                  <td className="p-3 text-right text-text-primary font-bold tabular-nums">{formatCHF(data.total_trading_fees_chf)}</td>
                  <td className="p-3 text-right text-text-primary font-bold tabular-nums">{formatCHF(data.total_other_fees_chf)}</td>
                  <td className="p-3 text-right text-text-primary font-bold tabular-nums">{formatCHF(data.total_taxes_chf)}</td>
                  <td className="p-3 text-right text-text-primary font-bold tabular-nums">{formatCHF(totalAll)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

function SummaryCell({ label, value }) {
  return (
    <div className="bg-card p-4 text-center">
      <p className="text-xs text-text-muted mb-1">{label}</p>
      <p className="text-lg font-bold text-text-primary tabular-nums">{formatCHF(value)}</p>
    </div>
  )
}
