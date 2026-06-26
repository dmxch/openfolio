import { useState, useCallback, useEffect } from 'react'
import useFocusTrap from '../hooks/useFocusTrap'
import useScrollLock from '../hooks/useScrollLock'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { usePortfolioData } from '../contexts/DataContext'
import { useApi, apiPost, apiDelete, authFetch } from '../hooks/useApi'
import { useToast } from '../components/Toast'
import PortfolioTable from '../components/PortfolioTable'
import ImmobilienWidget from '../components/ImmobilienWidget'
import PreciousMetalsWidget from '../components/PreciousMetalsWidget'
import CryptoWidget from '../components/CryptoWidget'
import PrivateEquityWidget from '../components/PrivateEquityWidget'
import AlertsBanner, { notifyAlertsChanged } from '../components/AlertsBanner'
import OnboardingChecklist from '../components/OnboardingChecklist'
import EditPositionModal from '../components/EditPositionModal'
import AddPositionModal from '../components/AddPositionModal'
import TransactionModal from '../components/TransactionModal'
import StopLossModal from '../components/StopLossModal'
import ContextMenu from '../components/ContextMenu'
import { formatCHF, formatCHFExact, formatNumber } from '../lib/format'
import DeleteConfirm from '../components/DeleteConfirm'
import Skeleton from '../components/Skeleton'
import { Briefcase, RefreshCw, Plus, Pencil, Trash2, Wallet, Landmark, MoreVertical } from 'lucide-react'

export default function Portfolio() {
  const { refetch: refetchPortfolio } = usePortfolioData()
  const { data: summary, loading, error, refetch: refetchLocal } = useApi('/portfolio/summary')
  const { data: reData, refetch: refetchRE } = useApi('/properties')
  // Bucket-Liste fuer das Bucket-Badge in der Aktien-Tabelle. Die komplette
  // Performance-Auswertung (Renditen, Heatmap, Top-Mover, Allokation, ...) lebt
  // jetzt auf der eigenen /performance-Seite; die Portfolio-Seite ist reine
  // Positionsverwaltung (kein Bucket-View-Switch mehr).
  const { data: bucketList } = useApi('/portfolio/buckets', { skip: !summary })

  const refetch = useCallback(() => {
    refetchLocal()
    refetchPortfolio()
    // Alerts hängen an den Positionsdaten (Stop-Loss, Branche, Limits) —
    // jeder Positions-Refresh muss auch den Alert-Fetch invalidieren.
    notifyAlertsChanged()
  }, [refetchLocal, refetchPortfolio])

  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()

  // Handle deep-link actions from onboarding checklist
  useEffect(() => {
    const action = searchParams.get('action')
    if (action && !loading) {
      setSearchParams({}, { replace: true })
      if (action === 'add-cash') {
        window.dispatchEvent(new CustomEvent('openAddCash'))
      }
    }
  }, [searchParams, loading, setSearchParams])

  if (loading) {
    return (
      <div className="space-y-6">
        <Header />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
        <Skeleton className="h-96" />
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-72" />
          ))}
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="space-y-6">
        <Header />
        <div className="rounded-lg border border-danger/30 bg-danger/10 p-6 flex items-center justify-between">
          <span className="text-danger text-sm">Fehler beim Laden: {error}</span>
          <button
            onClick={refetch}
            className="flex items-center gap-2 px-4 py-2 bg-primary text-white text-sm rounded-lg hover:bg-primary/90 transition-colors"
          >
            <RefreshCw size={14} />
            Erneut laden
          </button>
        </div>
      </div>
    )
  }

  const positions = summary?.positions || []

  // count_as_cash-ETFs (Geldmarkt-/T-Bill-ETF) gehören ins Liquiditäts-Widget —
  // konsistent zur Cash-Quote. Sie werden live bepreist (Ticker/Shares/Kurs),
  // tragen aber keinen Bank/IBAN/Saldo.
  const cashPositions = positions.filter((p) => p.type === 'cash' || p.count_as_cash)
  const pensionPositions = positions.filter((p) => p.type === 'pension')
  const commodityPositions = positions.filter((p) => p.type === 'commodity')
  const cryptoPositions = positions.filter((p) => p.type === 'crypto')
  const stockPositions = positions.filter((p) => p.type !== 'cash' && p.type !== 'pension' && p.type !== 'commodity' && p.type !== 'crypto' && p.type !== 'private_equity' && !p.count_as_cash)

  // Bucket-Map (id -> {name,color}) fuer das Bucket-Badge in der Aktien-Tabelle.
  const bucketMap = {}
  const _buckets = bucketList?.buckets || (Array.isArray(bucketList) ? bucketList : [])
  _buckets.forEach((b) => { if (b?.id) bucketMap[b.id] = { name: b.name, color: b.color } })

  return (
    <div className="space-y-6">
      <Header onRecalculate={refetch} />

      <OnboardingChecklist />

      <AlertsBanner
        onEditPosition={async (ticker) => {
          // Find position by ticker and open edit modal
          const pos = summary?.positions?.find(p => p.ticker === ticker)
          if (pos) {
            try {
              const res = await authFetch(`/api/portfolio/positions/${pos.id}`)
              const full = await res.json()
              // Dispatch custom event that PortfolioTable listens for
              window.dispatchEvent(new CustomEvent('openEditPosition', { detail: full }))
            } catch {
              window.dispatchEvent(new CustomEvent('openEditPosition', { detail: pos }))
            }
          }
        }}
        onEditStopLoss={(ticker) => {
          // Scroll to position in table
          const el = document.querySelector(`[data-ticker="${ticker}"]`)
          if (el) { el.scrollIntoView({ behavior: 'smooth', block: 'center' }); el.classList.add('ring-2', 'ring-primary'); setTimeout(() => el.classList.remove('ring-2', 'ring-primary'), 3000) }
        }}
        onScrollTo={(ticker, section) => {
          if (section === 'allocation') {
            // Allokations-Charts liegen jetzt auf der Performance-Seite.
            navigate('/performance#allocation-charts')
          } else if (ticker) {
            const el = document.querySelector(`[data-ticker="${ticker}"]`)
            if (el) { el.scrollIntoView({ behavior: 'smooth', block: 'center' }); el.classList.add('ring-2', 'ring-primary'); setTimeout(() => el.classList.remove('ring-2', 'ring-primary'), 3000) }
          }
        }}
      />

      {/* Aktien & ETFs — die Performance-Auswertung (Renditen, Heatmap, Top-Mover,
          Allokation, Risiko/Faktoren) lebt jetzt auf der /performance-Seite. */}
      <PortfolioTable positions={stockPositions} onRefresh={refetch} totalFees={summary?.total_fees_chf} bucketMap={bucketMap} />

      {/* Immobilien */}
      <ImmobilienWidget onRefresh={() => { refetchRE(); refetch() }} />

      {/* 7. Direktbeteiligungen */}
      <PrivateEquityWidget onRefresh={refetch} />

      {/* 8. Edelmetalle */}
      <PreciousMetalsWidget positions={commodityPositions} onRefresh={refetch} />

      {/* 8. Crypto */}
      <CryptoWidget positions={cryptoPositions} onRefresh={refetch} />

      {/* 7. Liquidität */}
      <CashTable
        positions={cashPositions}
        totalMarketValue={summary?.total_market_value_chf}
        onRefresh={refetch}
      />

      {/* 8. Vorsorge */}
      <PensionTable
        positions={pensionPositions}
        totalMarketValue={summary?.total_market_value_chf}
        onRefresh={refetch}
      />
    </div>
  )
}

function CashTable({ positions, totalMarketValue, onRefresh }) {
  const [ctxMenu, setCtxMenu] = useState(null)
  const [editPosition, setEditPosition] = useState(null)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [txnModal, setTxnModal] = useState(null)
  const [stopLossTarget, setStopLossTarget] = useState(null)
  const [showAdd, setShowAdd] = useState(false)
  const toast = useToast()

  // Listen for openAddCash event from onboarding checklist
  useEffect(() => {
    const handler = () => setShowAdd(true)
    window.addEventListener('openAddCash', handler)
    return () => window.removeEventListener('openAddCash', handler)
  }, [])

  const totalCash = positions.reduce((s, p) => s + p.market_value_chf, 0)

  const openCtxFor = useCallback((e, position) => {
    e.stopPropagation()
    const rect = e.currentTarget.getBoundingClientRect()
    setCtxMenu({ x: rect.left, y: rect.bottom + 4, position })
  }, [])

  const handleAction = useCallback(async (action) => {
    const pos = ctxMenu?.position
    if (!pos) return
    setCtxMenu(null)

    if (action === 'edit') {
      try {
        const res = await authFetch(`/api/portfolio/positions/${pos.id}`)
        const full = await res.json()
        setEditPosition(full)
      } catch {
        setEditPosition(pos)
      }
    } else if (action === 'delete') {
      setDeleteTarget(pos)
    } else if (['deposit', 'withdrawal', 'buy', 'sell', 'dividend'].includes(action)) {
      // deposit/withdrawal für echte Cash-Konten; buy/sell/dividend für
      // count_as_cash-ETFs, die im Liquiditäts-Widget mitgelistet werden.
      setTxnModal({ position: pos, type: action })
    } else if (action === 'stop_loss') {
      setStopLossTarget(pos)
    }
  }, [ctxMenu])

  const confirmDelete = useCallback(async () => {
    if (!deleteTarget) return
    try {
      await apiDelete(`/portfolio/positions/${deleteTarget.id}`)
      onRefresh?.()
    } catch (e) {
      toast('Fehler: ' + e.message, 'error')
    }
    setDeleteTarget(null)
  }, [deleteTarget, onRefresh, toast])

  return (
    <div className="rounded-lg border border-white/[0.06] border-t-2 border-t-blue-500/60 bg-card overflow-hidden shadow-[0_1px_3px_rgba(0,0,0,0.3)]">
      <div className="p-4 border-b border-white/[0.08] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Wallet size={20} className="text-blue-500" />
          <h3 className="text-lg font-semibold text-text-primary">Bargeldbestände</h3>
        </div>
        <button
          onClick={() => setShowAdd(true)}
          className="flex items-center gap-1 px-3 py-1.5 text-xs bg-primary text-white rounded-lg hover:bg-primary/90"
        >
          <Plus size={14} />
          Konto
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-white/[0.08] text-text-secondary text-[11px] uppercase tracking-wider">
              <th className="text-left p-3 font-medium">Bank</th>
              <th className="text-left p-3 font-medium">IBAN</th>
              <th className="text-left p-3 font-medium">Währung</th>
              <th className="text-right p-3 font-medium">Saldo</th>
              <th className="text-right p-3 font-medium">Wert CHF</th>
              <th className="text-right p-3 font-medium">Anteil</th>
              <th className="p-3 w-10" />
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => {
              // count_as_cash-ETF: live bepreist, kein Bank/IBAN/Fremdwährungs-
              // Saldo. cost_basis_chf ist hier der CHF-Einstand (nicht der Saldo),
              // darf also NICHT mit Währungs-Label als "Saldo" gezeigt werden.
              const isSecurity = !!p.count_as_cash
              return (
              <tr
                key={p.id}
                className="border-b border-border/50 hover:bg-card-alt/50 transition-colors"
              >
                <td className="p-3 text-text-primary">
                  {p.bank_name || p.name}
                  {isSecurity && (
                    <span className="ml-2 align-middle text-[10px] px-1.5 py-0.5 rounded border bg-blue-500/10 text-blue-400 border-blue-500/20">ETF · live</span>
                  )}
                </td>
                <td className="p-3 text-text-secondary text-xs font-mono">
                  {isSecurity ? p.ticker : (p.iban ? p.iban.replace(/(.{4})/g, '$1 ').trim() : '–')}
                </td>
                <td className="p-3">
                  <span className="text-xs px-2 py-0.5 rounded border bg-primary/10 text-primary border-primary/20">{p.currency}</span>
                </td>
                <td className="p-3 text-right text-text-secondary tabular-nums whitespace-nowrap">
                  {isSecurity
                    ? (p.shares ? `${formatNumber(p.shares, p.shares % 1 !== 0 ? 2 : 0)} × ${p.price_currency || p.currency} ${p.current_price != null ? formatNumber(p.current_price, 2) : '–'}` : '–')
                    : (p.currency !== 'CHF' ? `${p.currency} ${formatNumber(p.cost_basis_chf)}` : formatCHF(p.cost_basis_chf))}
                </td>
                <td className="p-3 text-right text-text-primary font-medium tabular-nums">{formatCHF(p.market_value_chf)}</td>
                <td className="p-3 text-right text-text-secondary tabular-nums">{p.weight_pct.toFixed(1)}%</td>
                <td className="p-3 text-center">
                  <button
                    onClick={(e) => openCtxFor(e, p)}
                    className="p-1.5 rounded text-text-secondary hover:text-text-primary hover:bg-white/10 transition-colors"
                    title="Aktionen" aria-label="Aktionen öffnen"
                    aria-expanded={ctxMenu?.position?.id === p.id}
                  >
                    <MoreVertical size={16} />
                  </button>
                </td>
              </tr>
              )
            })}
            {positions.length > 0 && (
              <tr className="bg-card-alt/30">
                <td className="p-3 text-text-primary font-medium" colSpan={4}>Total</td>
                <td className="p-3 text-right text-text-primary font-bold tabular-nums">{formatCHF(totalCash)}</td>
                <td className="p-3 text-right text-text-secondary font-medium tabular-nums">
                  {totalMarketValue ? (totalCash / totalMarketValue * 100).toFixed(1) : 0}%
                </td>
                <td />
              </tr>
            )}
            {positions.length === 0 && (
              <tr>
                <td colSpan={7} className="p-6 text-center text-text-muted text-sm">Keine Cash-Konten vorhanden.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {ctxMenu && (
        <ContextMenu
          x={ctxMenu.x}
          y={ctxMenu.y}
          onAction={handleAction}
          onClose={() => setCtxMenu(null)}
          positionType={ctxMenu.position?.type}
        />
      )}

      {editPosition && (
        <EditPositionModal
          position={editPosition}
          onClose={() => setEditPosition(null)}
          onSaved={() => onRefresh?.()}
        />
      )}

      {txnModal && (
        <TransactionModal
          position={txnModal.position}
          type={txnModal.type}
          onClose={() => setTxnModal(null)}
          onSaved={() => onRefresh?.()}
        />
      )}

      {stopLossTarget && (
        <StopLossModal
          position={stopLossTarget}
          onClose={() => setStopLossTarget(null)}
          onSaved={() => onRefresh?.()}
        />
      )}

      {deleteTarget && (
        <DeleteConfirm
          name={deleteTarget.name}
          onConfirm={confirmDelete}
          onCancel={() => setDeleteTarget(null)}
        />
      )}

      {showAdd && (
        <AddPositionModal
          onClose={() => setShowAdd(false)}
          onSaved={() => onRefresh?.()}
          allowedTypes={["cash"]}
        />
      )}
    </div>
  )
}

function PensionTable({ positions, totalMarketValue, onRefresh }) {
  const [ctxMenu, setCtxMenu] = useState(null)
  const [editPosition, setEditPosition] = useState(null)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [txnModal, setTxnModal] = useState(null)
  const [showAdd, setShowAdd] = useState(false)
  const toast = useToast()

  const totalPension = positions.reduce((s, p) => s + p.market_value_chf, 0)

  const openCtxFor = useCallback((e, position) => {
    e.stopPropagation()
    const rect = e.currentTarget.getBoundingClientRect()
    setCtxMenu({ x: rect.left, y: rect.bottom + 4, position })
  }, [])

  const handleAction = useCallback(async (action) => {
    const pos = ctxMenu?.position
    if (!pos) return
    setCtxMenu(null)

    if (action === 'edit') {
      try {
        const res = await authFetch(`/api/portfolio/positions/${pos.id}`)
        const full = await res.json()
        setEditPosition(full)
      } catch {
        setEditPosition(pos)
      }
    } else if (action === 'delete') {
      setDeleteTarget(pos)
    } else if (action === 'deposit') {
      setTxnModal({ position: pos, type: 'deposit' })
    }
  }, [ctxMenu])

  const confirmDelete = useCallback(async () => {
    if (!deleteTarget) return
    try {
      await apiDelete(`/portfolio/positions/${deleteTarget.id}`)
      onRefresh?.()
    } catch (e) {
      toast('Fehler: ' + e.message, 'error')
    }
    setDeleteTarget(null)
  }, [deleteTarget, onRefresh, toast])

  return (
    <div className="rounded-lg border border-white/[0.06] border-t-2 border-t-purple-500/60 bg-card overflow-hidden shadow-[0_1px_3px_rgba(0,0,0,0.3)]">
      <div className="p-4 border-b border-white/[0.08] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Landmark size={20} className="text-purple-500" />
          <h3 className="text-lg font-semibold text-text-primary">Vorsorge</h3>
        </div>
        <button
          onClick={() => setShowAdd(true)}
          className="flex items-center gap-1 px-3 py-1.5 text-xs bg-primary text-white rounded-lg hover:bg-primary/90"
        >
          <Plus size={14} />
          Vorsorge
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-white/[0.08] text-text-secondary text-[11px] uppercase tracking-wider">
              <th className="text-left p-3 font-medium">Konto</th>
              <th className="text-left p-3 font-medium">Anbieter</th>
              <th className="text-right p-3 font-medium">Betrag CHF</th>
              <th className="text-right p-3 font-medium">Anteil</th>
              <th className="p-3 w-10" />
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => (
              <tr
                key={p.id}
                className="border-b border-border/50 hover:bg-card-alt/50 transition-colors"
              >
                <td className="p-3 text-text-primary">{p.name}</td>
                <td className="p-3 text-text-secondary">{p.bank_name || '–'}</td>
                <td className="p-3 text-right text-text-primary font-medium tabular-nums">{formatCHF(p.market_value_chf)}</td>
                <td className="p-3 text-right text-text-secondary tabular-nums">{p.weight_pct.toFixed(1)}%</td>
                <td className="p-3 text-center">
                  <button
                    onClick={(e) => openCtxFor(e, p)}
                    className="p-1.5 rounded text-text-secondary hover:text-text-primary hover:bg-white/10 transition-colors"
                    title="Aktionen" aria-label="Aktionen öffnen"
                    aria-expanded={ctxMenu?.position?.id === p.id}
                  >
                    <MoreVertical size={16} />
                  </button>
                </td>
              </tr>
            ))}
            {positions.length > 0 && (
              <tr className="bg-card-alt/30">
                <td className="p-3 text-text-primary font-medium" colSpan={2}>Total</td>
                <td className="p-3 text-right text-text-primary font-bold tabular-nums">{formatCHF(totalPension)}</td>
                <td className="p-3 text-right text-text-secondary font-medium tabular-nums">
                  {totalMarketValue ? (totalPension / totalMarketValue * 100).toFixed(1) : 0}%
                </td>
                <td />
              </tr>
            )}
            {positions.length === 0 && (
              <tr>
                <td colSpan={5} className="p-6 text-center text-text-muted text-sm">
                  Keine Vorsorge-Positionen vorhanden.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="px-4 py-2 border-t border-border">
        <p className="text-xs text-text-secondary">Gebundene Vorsorge (Säule 3a). Nicht liquide.</p>
      </div>

      {ctxMenu && (
        <ContextMenu
          x={ctxMenu.x}
          y={ctxMenu.y}
          onAction={handleAction}
          onClose={() => setCtxMenu(null)}
          positionType="pension"
        />
      )}

      {editPosition && (
        <EditPositionModal
          position={editPosition}
          onClose={() => setEditPosition(null)}
          onSaved={() => onRefresh?.()}
        />
      )}

      {txnModal && (
        <TransactionModal
          position={txnModal.position}
          type={txnModal.type}
          onClose={() => setTxnModal(null)}
          onSaved={() => onRefresh?.()}
        />
      )}

      {deleteTarget && (
        <DeleteConfirm
          name={deleteTarget.name}
          onConfirm={confirmDelete}
          onCancel={() => setDeleteTarget(null)}
        />
      )}

      {showAdd && (
        <AddPositionModal
          onClose={() => setShowAdd(false)}
          onSaved={() => onRefresh?.()}
          allowedTypes={["pension"]}
        />
      )}
    </div>
  )
}

function Header({ onRecalculate }) {
  const [recalculating, setRecalculating] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const confirmTrapRef = useFocusTrap(showConfirm)
  useScrollLock(showConfirm)
  const toast = useToast()

  const handleRecalculate = async () => {
    setRecalculating(true)
    setShowConfirm(false)
    try {
      const res = await apiPost('/portfolio/recalculate', {})
      await onRecalculate()
      const count = res.recalculated || 0
      const positions = res.positions || []
      const maxDelta = positions.reduce((max, p) => Math.abs(p.delta_chf) > Math.abs(max.delta_chf) ? p : max, { delta_chf: 0 })
      let msg = `${count} Positionen neu berechnet`
      if (maxDelta.ticker && Math.abs(maxDelta.delta_chf) >= 0.01) {
        msg += ` · Grösste Änderung: ${maxDelta.ticker} ${formatCHFExact(maxDelta.delta_chf)}`
      }
      toast(msg, 'success')
    } catch (err) {
      toast('Neuberechnung fehlgeschlagen', 'error')
    } finally {
      setRecalculating(false)
    }
  }

  return (
    <>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Briefcase size={22} className="text-primary" />
          <h2 className="text-xl font-bold text-text-primary">Portfolio</h2>
        </div>
        <button
          onClick={() => setShowConfirm(true)}
          disabled={recalculating}
          className="flex items-center gap-2 px-3 py-1.5 text-sm rounded-lg border border-border text-text-secondary hover:border-primary hover:text-primary transition-colors disabled:opacity-50"
        >
          <RefreshCw size={14} className={recalculating ? 'animate-spin' : ''} />
          {recalculating ? 'Berechne...' : 'Neu berechnen'}
        </button>
      </div>

      {showConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setShowConfirm(false)}>
          <div
            ref={confirmTrapRef}
            className="bg-card border border-border rounded-xl p-6 max-w-md mx-4 shadow-xl"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-label="Neuberechnung bestätigen"
          >
            <div className="flex items-center gap-3 mb-4">
              <div className="p-2 rounded-lg bg-primary/10">
                <RefreshCw size={18} className="text-primary" />
              </div>
              <h3 className="text-lg font-semibold text-text-primary">Positionen neu berechnen?</h3>
            </div>
            <p className="text-sm text-text-secondary mb-6">
              Alle Positionen neu berechnen? Dies aktualisiert Cost Basis, Performance und Gebühren basierend auf den aktuellen Transaktionsdaten.
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setShowConfirm(false)}
                className="px-4 py-2 text-sm rounded-lg border border-border text-text-secondary hover:bg-card-alt transition-colors"
              >
                Abbrechen
              </button>
              <button
                onClick={handleRecalculate}
                className="px-4 py-2 text-sm rounded-lg bg-primary text-white hover:bg-primary/90 transition-colors"
              >
                Neu berechnen
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
