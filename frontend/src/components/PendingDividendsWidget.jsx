import { useState } from 'react'
import { Coins, Check, X as XIcon } from 'lucide-react'
import { useApi, apiPost } from '../hooks/useApi'
import { useDividendCount } from '../contexts/DividendCountContext'
import { formatDate, formatCHF } from '../lib/format'
import ConfirmDividendModal from './ConfirmDividendModal'

const MAX_VISIBLE = 5

/**
 * Dashboard-Widget "Offene Dividenden".
 * Null-Render wenn loading || error || keine Items.
 */
export default function PendingDividendsWidget() {
  const { data, loading, error, refetch } = useApi('/dividends/pending?status=pending&limit=10')
  const { refetch: refetchCount } = useDividendCount()
  const [confirmTarget, setConfirmTarget] = useState(null)
  const [dismissTarget, setDismissTarget] = useState(null)
  const [dismissing, setDismissing] = useState(false)
  const [actionError, setActionError] = useState(null)

  if (loading || error || !data?.items?.length) return null

  const items = data.items
  const visible = items.slice(0, MAX_VISIBLE)
  const overflow = items.length - visible.length

  // Backend liefert Default als Dezimal (0.35), nicht in Prozent — defensiv beide Schreibweisen unterstützen.
  const withholdingDefaultRaw = data.withholding_default_pct ?? 0.35
  const withholdingDefaultDecimal = withholdingDefaultRaw > 1 ? withholdingDefaultRaw / 100 : withholdingDefaultRaw

  const refreshAll = () => {
    refetch()
    refetchCount()
  }

  const handleDismiss = async () => {
    if (!dismissTarget) return
    setDismissing(true)
    setActionError(null)
    try {
      await apiPost(`/dividends/${dismissTarget.id}/dismiss`, {})
      setDismissTarget(null)
      refreshAll()
    } catch (err) {
      setActionError(err?.message || 'Ignorieren fehlgeschlagen.')
    } finally {
      setDismissing(false)
    }
  }

  // Withholding-Resolution: Backend liefert pro Item `withholding_pct` (0.0–1.0)
  // bereits aufgelöst (Position-Override > ISIN-Country-Map > User-Default).
  // Fallback auf den globalen Default falls das Feld in der Response fehlt.
  const resolveWithholdingForItem = (item) => {
    if (item.withholding_pct != null) return Number(item.withholding_pct)
    return withholdingDefaultDecimal
  }

  return (
    <>
      <div className="rounded-lg border border-border p-5" aria-labelledby="pending-divs-heading">
        <div className="flex items-center gap-2 mb-3">
          <Coins size={16} className="text-warning" />
          <h3 id="pending-divs-heading" className="text-sm font-medium text-text-secondary">Offene Dividenden</h3>
          <span className="bg-warning text-white text-xs font-bold px-1.5 py-0.5 rounded-full">
            {items.length}
          </span>
        </div>

        {actionError && (
          <div role="alert" className="text-sm text-danger bg-danger/10 border border-danger/30 rounded-lg px-3 py-2 mb-3">
            {actionError}
          </div>
        )}

        <ul role="list" className="divide-y divide-border/50">
          {visible.map((item) => {
            const expectedChf = item.expected_gross_chf_recomputed != null
              ? item.expected_gross_chf_recomputed
              : item.expected_gross_chf
            return (
              <li
                key={item.id}
                role="listitem"
                className="flex items-center gap-3 py-2.5 first:pt-0 last:pb-0"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline gap-2 flex-wrap">
                    <span className="font-mono text-sm font-semibold text-text-primary">{item.ticker}</span>
                    <span className="text-sm text-text-secondary truncate">{item.position_name}</span>
                  </div>
                  <div className="text-xs text-text-muted mt-0.5">
                    Ex-Date {formatDate(item.ex_date)} · ~ {formatCHF(expectedChf, { decimals: 2 })}
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <button
                    type="button"
                    onClick={() => setConfirmTarget(item)}
                    aria-label={`Dividende ${item.ticker} erfassen`}
                    className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium bg-primary text-white rounded-lg hover:bg-primary/80 transition-colors"
                  >
                    <Check size={12} />
                    Erfassen
                  </button>
                  <button
                    type="button"
                    onClick={() => setDismissTarget(item)}
                    aria-label={`Dividende ${item.ticker} ignorieren`}
                    className="flex items-center gap-1 px-3 py-1.5 text-xs text-text-muted hover:text-text-primary border border-border rounded-lg hover:border-border/80 transition-colors"
                  >
                    <XIcon size={12} />
                    Ignorieren
                  </button>
                </div>
              </li>
            )
          })}
        </ul>

        {overflow > 0 && (
          <p className="text-xs text-text-muted mt-3">
            … und {overflow} weitere
          </p>
        )}
      </div>

      {confirmTarget && (
        <ConfirmDividendModal
          pendingDividend={confirmTarget}
          withholdingResolved={resolveWithholdingForItem(confirmTarget)}
          onClose={() => setConfirmTarget(null)}
          onSuccess={refreshAll}
        />
      )}

      {dismissTarget && (
        <DismissConfirm
          item={dismissTarget}
          dismissing={dismissing}
          onConfirm={handleDismiss}
          onCancel={() => { setDismissTarget(null); setActionError(null) }}
        />
      )}
    </>
  )
}

/**
 * Eigene Confirm-Komponente für Dismiss — semantisch "ausblenden", nicht "löschen",
 * deshalb nicht DeleteConfirm wiederverwendet (rote Lösch-Optik passt nicht).
 */
function DismissConfirm({ item, dismissing, onConfirm, onCancel }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onCancel}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Dividende ignorieren"
        className="bg-card border border-border rounded-xl shadow-2xl p-6 max-w-sm w-full mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-sm font-semibold text-text-primary mb-2">Offene Dividende ignorieren?</h3>
        <p className="text-sm text-text-secondary">
          Offene Dividende für <span className="font-mono font-medium text-text-primary">{item.ticker}</span> vom {formatDate(item.ex_date)} wird nicht mehr angezeigt.
          Die Dividende kann weiterhin manuell als Transaktion erfasst werden.
        </p>
        <div className="flex gap-2 justify-end mt-5">
          <button
            onClick={onCancel}
            disabled={dismissing}
            className="px-4 py-2 text-sm rounded-lg border border-border text-text-secondary hover:text-text-primary hover:border-border/80 transition-colors disabled:opacity-40"
          >
            Abbrechen
          </button>
          <button
            onClick={onConfirm}
            disabled={dismissing}
            className="px-4 py-2 text-sm rounded-lg bg-warning text-white hover:bg-warning/90 transition-colors font-medium disabled:opacity-40"
          >
            {dismissing ? 'Wird ausgeblendet…' : 'Ausblenden'}
          </button>
        </div>
      </div>
    </div>
  )
}
