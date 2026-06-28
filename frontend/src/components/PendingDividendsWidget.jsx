import { useState } from 'react'
import { Coins, Check, X as XIcon } from 'lucide-react'
import { useApi, apiPost } from '../hooks/useApi'
import { useDividendCount } from '../contexts/DividendCountContext'
import { formatDate, formatCHF } from '../lib/format'
import ConfirmDividendModal from './ConfirmDividendModal'
import Card from './ui/Card'
import TickerChip from './ui/TickerChip'

const MAX_VISIBLE = 6

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
      <Card className="hidden md:block overflow-hidden" aria-labelledby="pending-divs-heading">
        <div className="px-[18px] py-4 border-b border-border-2 flex items-center gap-2.5">
          <Coins size={15} className="text-warning" />
          <h3 id="pending-divs-heading" className="text-sm font-semibold text-text-primary">Kommende Dividenden</h3>
          <span className="bg-warning/15 text-warning text-[11px] font-semibold px-1.5 py-0.5 rounded-full">
            {items.length}
          </span>
        </div>

        <div className="p-[18px]">
          {actionError && (
            <div role="alert" className="text-sm text-danger bg-danger/10 border border-danger/30 rounded-card px-3 py-2 mb-3">
              {actionError}
            </div>
          )}

          <ul role="list" className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
            {visible.map((item) => {
              const expectedChf = item.expected_gross_chf_recomputed != null
                ? item.expected_gross_chf_recomputed
                : item.expected_gross_chf
              const whPct = resolveWithholdingForItem(item)
              return (
                <li
                  key={item.id}
                  role="listitem"
                  className="flex flex-col gap-2 bg-card-2 border border-border-2 rounded-lg p-3"
                >
                  <div className="flex items-center justify-between gap-2">
                    <TickerChip>{item.ticker}</TickerChip>
                    <span className="inline-flex items-center font-mono text-[10.5px] text-success bg-success/10 rounded px-1.5 py-0.5 whitespace-nowrap">
                      Ex {formatDate(item.ex_date)}
                    </span>
                  </div>
                  <div className="text-[11.5px] text-text-muted truncate" title={item.position_name}>{item.position_name}</div>
                  <div className="text-[20px] font-mono font-semibold text-success leading-none">
                    {formatCHF(expectedChf, { decimals: 2 })}
                  </div>
                  {whPct != null && (
                    <div className="font-mono text-[10.5px] text-text-faint">
                      Quellensteuer {(whPct * 100).toFixed(0)}%
                    </div>
                  )}
                  <div className="flex items-center gap-2 mt-0.5">
                    <button
                      type="button"
                      onClick={() => setConfirmTarget(item)}
                      aria-label={`Dividende ${item.ticker} erfassen`}
                      className="flex-1 flex items-center justify-center gap-1 px-3 py-1.5 text-xs font-medium bg-primary-btn border border-primary-btn-border text-white rounded-lg hover:bg-primary-btn-border transition-colors"
                    >
                      <Check size={12} />
                      Erfassen
                    </button>
                    <button
                      type="button"
                      onClick={() => setDismissTarget(item)}
                      aria-label={`Dividende ${item.ticker} ignorieren`}
                      className="flex items-center justify-center gap-1 px-3 py-1.5 text-xs text-text-muted hover:text-text-primary bg-surface border border-border rounded-lg hover:border-border-hover transition-colors"
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
            <p className="text-xs text-text-muted mt-3">… und {overflow} weitere</p>
          )}
        </div>
      </Card>

      {/* MOBILE — kompakte Liste */}
      <Card className="md:hidden overflow-hidden" aria-labelledby="pending-divs-heading-m">
        <div className="px-4 py-3.5 border-b border-border-2 flex items-center gap-2.5">
          <Coins size={15} className="text-warning" />
          <h3 id="pending-divs-heading-m" className="text-sm font-semibold text-text-primary">Kommende Dividenden</h3>
          <span className="bg-warning/15 text-warning text-[11px] font-semibold px-1.5 py-0.5 rounded-full">
            {items.length}
          </span>
        </div>

        <div className="p-3">
          {actionError && (
            <div role="alert" className="text-sm text-danger bg-danger/10 border border-danger/30 rounded-card px-3 py-2 mb-3">
              {actionError}
            </div>
          )}

          <ul role="list" className="flex flex-col gap-2">
            {visible.map((item) => {
              const expectedChf = item.expected_gross_chf_recomputed != null
                ? item.expected_gross_chf_recomputed
                : item.expected_gross_chf
              return (
                <li
                  key={item.id}
                  role="listitem"
                  className="flex flex-col gap-2 bg-card-2 border border-border-2 rounded-lg p-3"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <TickerChip>{item.ticker}</TickerChip>
                      <span className="inline-flex items-center font-mono text-[10px] text-success bg-success/10 rounded px-1.5 py-0.5 whitespace-nowrap">
                        Ex {formatDate(item.ex_date)}
                      </span>
                    </div>
                    <span className="text-[17px] font-mono font-semibold text-success leading-none whitespace-nowrap">
                      {formatCHF(expectedChf, { decimals: 2 })}
                    </span>
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11px] text-text-muted truncate min-w-0" title={item.position_name}>
                      {item.position_name}
                    </span>
                    <div className="flex items-center gap-1.5 flex-none">
                      <button
                        type="button"
                        onClick={() => setConfirmTarget(item)}
                        aria-label={`Dividende ${item.ticker} erfassen`}
                        className="flex items-center justify-center w-8 h-8 bg-primary-btn border border-primary-btn-border text-white rounded-lg hover:bg-primary-btn-border transition-colors"
                      >
                        <Check size={14} />
                      </button>
                      <button
                        type="button"
                        onClick={() => setDismissTarget(item)}
                        aria-label={`Dividende ${item.ticker} ignorieren`}
                        className="flex items-center justify-center w-8 h-8 text-text-muted hover:text-text-primary bg-surface border border-border rounded-lg hover:border-border-hover transition-colors"
                      >
                        <XIcon size={14} />
                      </button>
                    </div>
                  </div>
                </li>
              )
            })}
          </ul>

          {overflow > 0 && (
            <p className="text-xs text-text-muted mt-3">… und {overflow} weitere</p>
          )}
        </div>
      </Card>

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
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-[#04070c]/[0.72] backdrop-blur-sm" onClick={onCancel}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Dividende ignorieren"
        className="bg-modal border border-border-hover rounded-[14px] shadow-2xl p-6 max-w-sm w-full mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-base font-semibold text-text-primary mb-2">Offene Dividende ignorieren?</h3>
        <p className="text-sm text-text-secondary">
          Offene Dividende für <span className="font-mono font-medium text-text-primary">{item.ticker}</span> vom {formatDate(item.ex_date)} wird nicht mehr angezeigt.
          Die Dividende kann weiterhin manuell als Transaktion erfasst werden.
        </p>
        <div className="flex gap-2 justify-end mt-5">
          <button
            onClick={onCancel}
            disabled={dismissing}
            className="px-4 py-2 text-sm rounded-lg border border-border text-text-secondary hover:text-text-primary hover:border-border-hover transition-colors disabled:opacity-40"
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
