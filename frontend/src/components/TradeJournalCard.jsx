import { useApi } from '../hooks/useApi'
import { formatCHF } from '../lib/format'
import { BookCheck, Loader2 } from 'lucide-react'

const CARD = "rounded-lg border border-white/[0.06] bg-card p-4 shadow-[0_1px_3px_rgba(0,0,0,0.3)]"
const MAX_ROWS = 15

/**
 * Trade-Journal — Plan (Vault-Report von claude-finance) gegen Ist (ausgefuehrte
 * Transaktion). Zeigt pro Plan, ob er umgesetzt wurde. Read-only, neutrale Sprache.
 * Quelle: GET /api/analysis/trade-journal.
 */
export default function TradeJournalCard() {
  const { data, loading } = useApi('/analysis/trade-journal')

  if (loading) {
    return (
      <div className={CARD}>
        <div className="text-center py-6"><Loader2 size={18} className="animate-spin text-text-muted mx-auto" /></div>
      </div>
    )
  }
  if (!data) return null

  const entries = data.entries || []
  const s = data.summary || { total: 0, executed: 0, open: 0 }
  const shown = entries.slice(0, MAX_ROWS)

  return (
    <div className={CARD}>
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <BookCheck size={16} className="text-primary" />
          <h3 className="text-sm font-semibold text-text-primary">Trade-Journal</h3>
        </div>
        {s.total > 0 && (
          <span className="text-[11px] text-text-muted tabular-nums">
            {s.total} Pläne · <span className="text-success">{s.executed} umgesetzt</span> · {s.open} offen
          </span>
        )}
      </div>
      <p className="text-[11px] text-text-muted mb-3">Plan (aus dem Report-Vault) gegen tatsächliche Ausführung.</p>

      {s.total === 0 ? (
        <p className="text-xs text-text-muted py-3">
          Noch keine Trade-Pläne verknüpft. Sobald die Trade-Reports mit Ticker/Seite getaggt sind
          (und nach dem Buchen mit der Transaktion verlinkt werden), erscheinen die Pläne hier.
        </p>
      ) : (
        <div className="space-y-1">
          {shown.map((e) => {
            const isBuy = e.side === 'buy'
            const sideLabel = isBuy ? 'Kauf' : e.side === 'sell' ? 'Verkauf' : '—'
            const executed = e.status === 'executed'
            return (
              <div key={e.report_id} className="flex items-center justify-between gap-3 text-xs py-1 border-b border-border/30 last:border-0">
                <div className="flex items-center gap-2 min-w-0">
                  <span className={`shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium ${isBuy ? 'bg-success/10 text-success' : 'bg-danger/10 text-danger'}`}>
                    {sideLabel}
                  </span>
                  <span className="shrink-0 font-medium text-text-primary tabular-nums">{e.ticker || '—'}</span>
                  <span className="truncate text-text-secondary">{e.title}</span>
                </div>
                <div className="flex items-center gap-3 shrink-0">
                  {executed && e.ist ? (
                    <span className="text-text-muted tabular-nums hidden sm:inline">
                      {e.ist.shares} @ {e.ist.price_per_share} {e.ist.currency} · {e.ist.date}
                    </span>
                  ) : (
                    <span className="text-text-muted tabular-nums hidden sm:inline">{e.report_date}</span>
                  )}
                  <span className={`shrink-0 ${executed ? 'text-success' : 'text-text-muted'}`}>
                    {executed ? 'umgesetzt' : 'offen'}
                  </span>
                </div>
              </div>
            )
          })}
          {entries.length > MAX_ROWS && (
            <p className="text-[11px] text-text-muted pt-1">+{entries.length - MAX_ROWS} weitere</p>
          )}
        </div>
      )}
    </div>
  )
}
