import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import { formatCHF } from '../lib/format'
import { Receipt, ChevronDown } from 'lucide-react'

const MONTH_NAMES = ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun', 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez']
const THEAD = 'bg-table-head border-b border-border-2 font-mono text-[10px] uppercase tracking-[0.05em] text-text-faint'

export default function FeeSummary({ bucketId = null }) {
  const { data, loading } = useApi(bucketId ? `/portfolio/buckets/${bucketId}/fee-summary` : '/portfolio/fee-summary')
  const [open, setOpen] = useState(false)

  if (loading || !data) return null
  if (!data.by_month || data.by_month.length === 0) return null

  const totalAll = data.total_trading_fees_chf + data.total_other_fees_chf + data.total_taxes_chf

  return (
    <div className="rounded-card border border-border bg-card overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full px-[18px] py-4 flex items-center justify-between hover:bg-hover transition-colors"
      >
        <div className="flex items-center gap-2.5">
          <Receipt size={16} className="text-primary" />
          <h3 className="text-sm font-semibold text-text-primary">Gebühren & Steuern</h3>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm font-mono font-semibold text-text-primary tabular-nums">{formatCHF(totalAll)}</span>
          <ChevronDown size={16} className={`text-text-muted transition-transform ${open ? 'rotate-180' : ''}`} />
        </div>
      </button>
      {open && (
        <div className="border-t border-border-2">
          {/* Summary cards */}
          <div className="grid grid-cols-3 gap-px bg-border-2">
            <SummaryCell label="Handelsgebühren" value={data.total_trading_fees_chf} />
            <SummaryCell label="Depotgebühren" value={data.total_other_fees_chf} />
            <SummaryCell label="Steuern" value={data.total_taxes_chf} />
          </div>

          {/* Monthly breakdown */}
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className={THEAD}>
                  <th className="text-left pl-[18px] pr-3 py-2.5 font-medium">Monat</th>
                  <th className="text-right px-3 py-2.5 font-medium">Handelsgebühren</th>
                  <th className="text-right px-3 py-2.5 font-medium">Depotgebühren</th>
                  <th className="text-right px-3 py-2.5 font-medium">Steuern</th>
                  <th className="text-right px-3 py-2.5 font-medium pr-[18px]">Total</th>
                </tr>
              </thead>
              <tbody>
                {data.by_month.map((m) => {
                  const monthTotal = m.trading_fees_chf + m.other_fees_chf + m.taxes_chf
                  return (
                    <tr key={`${m.year}-${m.month}`} className="border-b border-border-row hover:bg-hover transition-colors">
                      <td className="pl-[18px] pr-3 py-2.5 font-mono text-text-primary tabular-nums">{MONTH_NAMES[m.month - 1]} {m.year}</td>
                      <td className="px-3 py-2.5 text-right font-mono text-text-secondary tabular-nums">{m.trading_fees_chf > 0 ? formatCHF(m.trading_fees_chf) : '–'}</td>
                      <td className="px-3 py-2.5 text-right font-mono text-text-secondary tabular-nums">{m.other_fees_chf > 0 ? formatCHF(m.other_fees_chf) : '–'}</td>
                      <td className="px-3 py-2.5 text-right font-mono text-text-secondary tabular-nums">{m.taxes_chf > 0 ? formatCHF(m.taxes_chf) : '–'}</td>
                      <td className="px-3 py-2.5 text-right font-mono text-text-primary font-medium tabular-nums pr-[18px]">{formatCHF(monthTotal)}</td>
                    </tr>
                  )
                })}
                <tr className="bg-table-head border-t border-border-2">
                  <td className="pl-[18px] pr-3 py-2.5 text-text-primary font-medium">Total</td>
                  <td className="px-3 py-2.5 text-right font-mono text-text-primary font-semibold tabular-nums">{formatCHF(data.total_trading_fees_chf)}</td>
                  <td className="px-3 py-2.5 text-right font-mono text-text-primary font-semibold tabular-nums">{formatCHF(data.total_other_fees_chf)}</td>
                  <td className="px-3 py-2.5 text-right font-mono text-text-primary font-semibold tabular-nums">{formatCHF(data.total_taxes_chf)}</td>
                  <td className="px-3 py-2.5 text-right font-mono text-text-primary font-semibold tabular-nums pr-[18px]">{formatCHF(totalAll)}</td>
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
    <div className="bg-card-2 p-4 text-center">
      <p className="font-mono text-[10.5px] tracking-[0.06em] uppercase text-text-label mb-1">{label}</p>
      <p className="text-lg font-mono font-semibold text-text-primary tabular-nums">{formatCHF(value)}</p>
    </div>
  )
}
