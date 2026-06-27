import { useApi } from '../hooks/useApi'
import { formatCHF } from '../lib/format'
import { Wallet, Loader2 } from 'lucide-react'

const CARD = "rounded-lg border border-white/[0.06] bg-card p-4 shadow-[0_1px_3px_rgba(0,0,0,0.3)]"

export default function NetWorthCard() {
  const { data, loading } = useApi('/analysis/net-worth')

  if (loading) {
    return (
      <div className={CARD}>
        <div className="text-center py-6"><Loader2 size={18} className="animate-spin text-text-muted mx-auto" /></div>
      </div>
    )
  }
  if (!data || data.net_worth_chf == null) return null

  const comps = data.components || []

  return (
    <div className={CARD}>
      <div className="flex items-center gap-2 mb-1">
        <Wallet size={16} className="text-primary" />
        <h3 className="text-sm font-semibold text-text-primary">Netto-Vermögen</h3>
      </div>
      <div className="mb-3">
        <div className="text-2xl font-bold text-text-primary tabular-nums">{formatCHF(data.net_worth_chf)}</div>
        <div className="text-[11px] text-text-muted">
          Vermögen {formatCHF(data.total_assets_chf)} − Verbindlichkeiten {formatCHF(data.total_liabilities_chf)}
        </div>
      </div>

      <div className="space-y-1">
        {comps.map((c) => (
          <div key={c.key} className="flex items-center justify-between text-xs">
            <span className="text-text-secondary">{c.label}</span>
            <span className={`tabular-nums ${c.kind === 'liability' ? 'text-danger' : 'text-text-primary'}`}>
              {formatCHF(c.value_chf)}
            </span>
          </div>
        ))}
        <div className="flex items-center justify-between text-xs pt-1.5 mt-1 border-t border-border/50">
          <span className="text-text-primary font-medium">Netto-Vermögen</span>
          <span className="text-text-primary font-semibold tabular-nums">{formatCHF(data.net_worth_chf)}</span>
        </div>
      </div>

      {data.has_real_estate && (
        <p className="text-[11px] text-text-muted mt-2">
          Immobilienwert = geschätzter Brutto-Marktwert (nicht Vermögenssteuerwert); Hypothek nach Amortisation.
        </p>
      )}
    </div>
  )
}
