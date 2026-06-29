import { useApi } from '../hooks/useApi'
import { BookCheck, Loader2 } from 'lucide-react'

const MAX_ROWS = 12

const SIDE = {
  buy: { label: 'Kauf', color: 'text-success' },
  sell: { label: 'Verkauf', color: 'text-danger' },
}

/**
 * Trade-Journal — Plan (Vault-Report von claude-finance) gegen Ist (ausgefuehrte
 * Transaktion). Mockup-Layout: Datum links, Ticker + Aktion, Plan-Titel als
 * Textvorschau, Status-Chip rechts. Read-only, neutrale Sprache.
 * Quelle: GET /api/analysis/trade-journal.
 */
export default function TradeJournalCard() {
  const { data, loading } = useApi('/analysis/trade-journal')

  if (loading) {
    return (
      <div className="bg-card border border-border rounded-card">
        <div className="text-center py-10"><Loader2 size={18} className="animate-spin text-text-muted mx-auto" /></div>
      </div>
    )
  }
  if (!data) return null

  const entries = data.entries || []
  const s = data.summary || { total: 0, executed: 0, open: 0 }
  const shown = entries.slice(0, MAX_ROWS)

  return (
    <div className="bg-card border border-border rounded-card overflow-hidden">
      <div className="px-[18px] py-4 border-b border-border-2 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <BookCheck size={16} className="text-primary" />
          <h3 className="text-sm font-semibold text-text-primary">Trade-Journal</h3>
        </div>
        {s.total > 0 && (
          <span className="text-[11px] text-text-muted font-mono tabular-nums shrink-0">
            {s.total} Pläne · <span className="text-success">{s.executed} umgesetzt</span> · {s.open} offen
          </span>
        )}
      </div>

      <div className="px-[18px]">
        {s.total === 0 ? (
          <p className="text-xs text-text-muted py-4">
            Noch keine Trade-Pläne verknüpft. Sobald die Trade-Reports mit Ticker/Seite getaggt sind
            (und nach dem Buchen mit der Transaktion verlinkt werden), erscheinen die Pläne hier.
          </p>
        ) : (
          <>
            {shown.map((e) => {
              const side = SIDE[e.side] || { label: '—', color: 'text-text-muted' }
              const executed = e.status === 'executed'
              return (
                <div key={e.report_id} className="flex gap-3.5 py-3 border-b border-border-row2 last:border-0">
                  <span className="font-mono text-[11.5px] text-text-muted w-[78px] shrink-0 pt-0.5 tabular-nums">
                    {e.report_date}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-mono text-[12.5px] font-semibold text-text-bright">{e.ticker || '—'}</span>
                      <span className={`text-[11px] font-semibold ${side.color}`}>{side.label}</span>
                    </div>
                    <div className="text-[12.5px] text-text-secondary leading-snug line-clamp-2" title={e.rationale || e.title}>
                      {e.rationale || e.title}
                    </div>
                    {executed && e.ist && (
                      <div className="text-[11px] text-text-muted font-mono tabular-nums mt-0.5">
                        Ist: {e.ist.shares} @ {e.ist.price_per_share} {e.ist.currency} · {e.ist.date}
                      </div>
                    )}
                  </div>
                  <span
                    className={`shrink-0 self-start font-mono text-[10.5px] rounded-[5px] px-2 py-0.5 border ${
                      executed
                        ? 'bg-success/10 text-success border-success/25'
                        : 'bg-surface text-text-muted border-border-2'
                    }`}
                  >
                    {executed ? 'umgesetzt' : 'offen'}
                  </span>
                </div>
              )
            })}
            {entries.length > MAX_ROWS && (
              <p className="text-[11px] text-text-muted py-2.5">+{entries.length - MAX_ROWS} weitere</p>
            )}
          </>
        )}
      </div>
    </div>
  )
}
