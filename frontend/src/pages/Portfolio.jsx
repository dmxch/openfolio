import { useState, useCallback, useEffect } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { usePortfolioData } from '../contexts/DataContext'
import { useApi, apiDelete, authFetch } from '../hooks/useApi'
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
import RecalculateButton from '../components/RecalculateButton'
import { formatCHF, formatNumber, formatPct } from '../lib/format'
import DeleteConfirm from '../components/DeleteConfirm'
import Skeleton from '../components/Skeleton'
import PageHeader from '../components/ui/PageHeader'
import StatTile from '../components/ui/StatTile'
import Button from '../components/ui/Button'
import { RefreshCw, Plus, MoreVertical } from 'lucide-react'

export default function Portfolio() {
  const { refetch: refetchPortfolio } = usePortfolioData()
  const { data: summary, loading, error, refetch: refetchLocal } = useApi('/portfolio/summary')
  const { refetch: refetchRE } = useApi('/properties')
  const navigate = useNavigate()
  // Bucket-Liste fuer das Bucket-Badge in der Aktien-Tabelle. Die komplette
  // Performance-Auswertung lebt auf der /performance-Seite; Portfolio ist reine
  // Positionsverwaltung.
  const { data: bucketList } = useApi('/portfolio/buckets', { skip: !summary })

  const refetch = useCallback(() => {
    refetchLocal()
    refetchPortfolio()
    notifyAlertsChanged()
  }, [refetchLocal, refetchPortfolio])

  const [searchParams, setSearchParams] = useSearchParams()

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
      <div className="pb-10">
        <PageHeader title="Portfolio" subtitle="Positionsverwaltung" showBell={false} />
        <div className="flex flex-col gap-[18px]">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-[14px]">
            {[1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-[88px] rounded-card" />)}
          </div>
          <Skeleton className="h-96 rounded-card" />
          <Skeleton className="h-48 rounded-card" />
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="pb-10">
        <PageHeader title="Portfolio" subtitle="Positionsverwaltung" showBell={false} />
        <div className="rounded-card border border-danger/30 bg-danger/10 p-6 flex items-center justify-between">
          <span className="text-danger text-sm">Fehler beim Laden: {error}</span>
          <Button variant="primary" icon={RefreshCw} onClick={refetch}>Erneut laden</Button>
        </div>
      </div>
    )
  }

  const positions = summary?.positions || []

  const cashPositions = positions.filter((p) => p.type === 'cash' || p.count_as_cash)
  const pensionPositions = positions.filter((p) => p.type === 'pension')
  const commodityPositions = positions.filter((p) => p.type === 'commodity')
  const cryptoPositions = positions.filter((p) => p.type === 'crypto')
  const stockPositions = positions.filter((p) => p.type !== 'cash' && p.type !== 'pension' && p.type !== 'commodity' && p.type !== 'crypto' && p.type !== 'private_equity' && !p.count_as_cash)

  // Summary-Kacheln — ausschliesslich aus bekannten Positionsfeldern berechnet,
  // konsistent zur Tabellen-Summe (keine erfundenen Zahlen).
  const total = summary?.total_market_value_chf || 0
  const tradable = positions.filter((p) => p.type !== 'cash' && p.type !== 'pension' && !p.count_as_cash && p.shares > 0)
  const totalPnl = tradable.reduce((s, p) => s + (p.pnl_chf || 0), 0)
  const totalCost = tradable.reduce((s, p) => s + (p.cost_basis_chf || 0), 0)
  const unrealPct = totalCost > 0 ? (totalPnl / totalCost) * 100 : 0
  const cashValue = cashPositions.reduce((s, p) => s + (p.market_value_chf || 0), 0)
  const cashPct = total > 0 ? (cashValue / total) * 100 : 0
  const classCount = new Set(positions.map((p) => p.type)).size

  // Bucket-Map (id -> {name,color}) fuer das Bucket-Badge in der Aktien-Tabelle.
  const bucketMap = {}
  const _buckets = bucketList?.buckets || (Array.isArray(bucketList) ? bucketList : [])
  _buckets.forEach((b) => { if (b?.id) bucketMap[b.id] = { name: b.name, color: b.color } })

  return (
    <div className="pb-10">
      <PageHeader
        title="Portfolio"
        subtitle={`${classCount} Anlageklasse${classCount === 1 ? '' : 'n'} · CHF`}
        actions={
          <>
            <RecalculateButton onRecalculate={refetch} />
            <Button variant="primary" icon={Plus} onClick={() => navigate('/transactions?action=add')}>Position</Button>
          </>
        }
      />

      <div className="flex flex-col gap-[18px]">
        {/* Summary tiles */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-[14px]">
          <StatTile label="Gesamtwert" value={formatCHF(total)} mono={false} />
          <StatTile
            label="Unrealisiert"
            value={`${totalPnl >= 0 ? '+' : ''}${formatCHF(totalPnl)}`}
            sub={formatPct(unrealPct)}
            tone={totalPnl >= 0 ? 'success' : 'danger'}
          />
          <StatTile label="Cash-Quote" value={`${cashPct.toFixed(1)}%`} tone="bright" />
          <StatTile label="Positionen" value={tradable.length} tone="bright" />
        </div>

        <OnboardingChecklist />

        <AlertsBanner
          onEditPosition={async (ticker) => {
            const pos = summary?.positions?.find(p => p.ticker === ticker)
            if (pos) {
              try {
                const res = await authFetch(`/api/portfolio/positions/${pos.id}`)
                const full = await res.json()
                window.dispatchEvent(new CustomEvent('openEditPosition', { detail: full }))
              } catch {
                window.dispatchEvent(new CustomEvent('openEditPosition', { detail: pos }))
              }
            }
          }}
          onEditStopLoss={(ticker) => {
            const el = document.querySelector(`[data-ticker="${ticker}"]`)
            if (el) { el.scrollIntoView({ behavior: 'smooth', block: 'center' }); el.classList.add('ring-2', 'ring-primary'); setTimeout(() => el.classList.remove('ring-2', 'ring-primary'), 3000) }
          }}
          onScrollTo={(ticker, section) => {
            if (section === 'allocation') {
              navigate('/performance#allocation-charts')
            } else if (ticker) {
              const el = document.querySelector(`[data-ticker="${ticker}"]`)
              if (el) { el.scrollIntoView({ behavior: 'smooth', block: 'center' }); el.classList.add('ring-2', 'ring-primary'); setTimeout(() => el.classList.remove('ring-2', 'ring-primary'), 3000) }
            }
          }}
        />

        {/* Aktien & ETFs */}
        <PortfolioTable positions={stockPositions} onRefresh={refetch} totalFees={summary?.total_fees_chf} bucketMap={bucketMap} />

        {/* Immobilien */}
        <ImmobilienWidget onRefresh={() => { refetchRE(); refetch() }} />

        {/* Private Equity + Edelmetalle */}
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-[18px]">
          <PrivateEquityWidget onRefresh={refetch} />
          <PreciousMetalsWidget positions={commodityPositions} onRefresh={refetch} />
        </div>

        {/* Krypto */}
        <CryptoWidget positions={cryptoPositions} onRefresh={refetch} />

        {/* Liquidität + Vorsorge */}
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-[18px]">
          <CashTable positions={cashPositions} totalMarketValue={summary?.total_market_value_chf} onRefresh={refetch} />
          <PensionTable positions={pensionPositions} totalMarketValue={summary?.total_market_value_chf} onRefresh={refetch} />
        </div>
      </div>
    </div>
  )
}

function SectionCard({ dot, title, action, children }) {
  return (
    <div className="bg-card border border-border rounded-card overflow-hidden">
      <div className="px-[18px] py-4 border-b border-border-2 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <span className="w-[9px] h-[9px] rounded-[3px]" style={{ background: dot }} />
          <h3 className="text-sm font-semibold text-text-primary">{title}</h3>
        </div>
        {action}
      </div>
      {children}
    </div>
  )
}

function AddBtn({ onClick, children }) {
  return (
    <button
      onClick={onClick}
      className="bg-surface border border-border rounded-lg px-[11px] py-1.5 text-link text-[11.5px] hover:border-border-hover transition-colors"
    >
      {children}
    </button>
  )
}

const TH = 'px-3 py-2.5 font-medium'
const THEAD = 'bg-table-head border-b border-border-2 font-mono text-[10px] uppercase tracking-[0.05em] text-text-faint'

function CashTable({ positions, totalMarketValue, onRefresh }) {
  const [ctxMenu, setCtxMenu] = useState(null)
  const [editPosition, setEditPosition] = useState(null)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [txnModal, setTxnModal] = useState(null)
  const [stopLossTarget, setStopLossTarget] = useState(null)
  const [showAdd, setShowAdd] = useState(false)
  const toast = useToast()

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
      } catch { setEditPosition(pos) }
    } else if (action === 'delete') {
      setDeleteTarget(pos)
    } else if (['deposit', 'withdrawal', 'buy', 'sell', 'dividend'].includes(action)) {
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
    } catch (e) { toast('Fehler: ' + e.message, 'error') }
    setDeleteTarget(null)
  }, [deleteTarget, onRefresh, toast])

  return (
    <SectionCard dot="#7a8698" title="Liquidität" action={<AddBtn onClick={() => setShowAdd(true)}>+ Konto</AddBtn>}>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className={THEAD}>
              <th className={`text-left pl-[18px] pr-3 py-2.5 font-medium`}>Bank / IBAN</th>
              <th className={`text-right ${TH}`}>Währ.</th>
              <th className={`text-right ${TH}`}>Saldo</th>
              <th className={`text-right ${TH}`}>Wert CHF</th>
              <th className={`text-right ${TH}`}>Anteil</th>
              <th className="px-3 py-2.5 w-10" />
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => {
              const isSecurity = !!p.count_as_cash
              return (
                <tr key={p.id} className="border-b border-border-row hover:bg-hover transition-colors">
                  <td className="pl-[18px] pr-3 py-3">
                    <div className="text-text-primary text-[12.5px] flex items-center gap-2">
                      {p.bank_name || p.name}
                      {isSecurity && (
                        <span className="font-mono text-[9px] text-etf bg-etf/10 rounded px-1.5 py-0.5">ETF · live</span>
                      )}
                    </div>
                    <div className="font-mono text-[10px] text-text-faint">
                      {isSecurity ? p.ticker : (p.iban ? p.iban.replace(/(.{4})/g, '$1 ').trim() : '–')}
                    </div>
                  </td>
                  <td className="px-3 py-3 text-right font-mono text-[11.5px] text-text-muted">{p.currency}</td>
                  <td className="px-3 py-3 text-right font-mono text-text-muted tabular-nums whitespace-nowrap text-xs">
                    {isSecurity
                      ? (p.shares ? `${formatNumber(p.shares, p.shares % 1 !== 0 ? 2 : 0)} × ${formatNumber(p.current_price ?? 0, 2)}` : '–')
                      : (p.currency !== 'CHF' ? `${p.currency} ${formatNumber(p.cost_basis_chf)}` : formatCHF(p.cost_basis_chf))}
                  </td>
                  <td className="px-3 py-3 text-right font-mono text-text-primary tabular-nums">{formatCHF(p.market_value_chf)}</td>
                  <td className="px-3 py-3 text-right font-mono text-text-muted tabular-nums">{p.weight_pct.toFixed(1)}%</td>
                  <td className="px-3 py-3 text-center">
                    <button onClick={(e) => openCtxFor(e, p)} className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-white/10 transition-colors" title="Aktionen" aria-label="Aktionen öffnen">
                      <MoreVertical size={15} />
                    </button>
                  </td>
                </tr>
              )
            })}
            {positions.length > 0 && (
              <tr className="bg-table-head border-t border-border-2">
                <td className="pl-[18px] pr-3 py-2.5 text-text-secondary font-medium text-xs" colSpan={3}>Total</td>
                <td className="px-3 py-2.5 text-right font-mono text-text-primary font-semibold tabular-nums">{formatCHF(totalCash)}</td>
                <td className="px-3 py-2.5 text-right font-mono text-text-muted tabular-nums">{totalMarketValue ? (totalCash / totalMarketValue * 100).toFixed(1) : 0}%</td>
                <td />
              </tr>
            )}
            {positions.length === 0 && (
              <tr><td colSpan={6} className="p-6 text-center text-text-muted text-sm">Keine Cash-Konten vorhanden.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {ctxMenu && <ContextMenu x={ctxMenu.x} y={ctxMenu.y} onAction={handleAction} onClose={() => setCtxMenu(null)} positionType={ctxMenu.position?.type} />}
      {editPosition && <EditPositionModal position={editPosition} onClose={() => setEditPosition(null)} onSaved={() => onRefresh?.()} />}
      {txnModal && <TransactionModal position={txnModal.position} type={txnModal.type} onClose={() => setTxnModal(null)} onSaved={() => onRefresh?.()} />}
      {stopLossTarget && <StopLossModal position={stopLossTarget} onClose={() => setStopLossTarget(null)} onSaved={() => onRefresh?.()} />}
      {deleteTarget && <DeleteConfirm name={deleteTarget.name} onConfirm={confirmDelete} onCancel={() => setDeleteTarget(null)} />}
      {showAdd && <AddPositionModal onClose={() => setShowAdd(false)} onSaved={() => onRefresh?.()} allowedTypes={["cash"]} />}
    </SectionCard>
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
      } catch { setEditPosition(pos) }
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
    } catch (e) { toast('Fehler: ' + e.message, 'error') }
    setDeleteTarget(null)
  }, [deleteTarget, onRefresh, toast])

  return (
    <SectionCard dot="#45c08a" title="Vorsorge" action={<AddBtn onClick={() => setShowAdd(true)}>+ Konto</AddBtn>}>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className={THEAD}>
              <th className="text-left pl-[18px] pr-3 py-2.5 font-medium">Konto</th>
              <th className={`text-left ${TH}`}>Anbieter</th>
              <th className={`text-right ${TH}`}>Betrag CHF</th>
              <th className={`text-right ${TH}`}>Anteil</th>
              <th className="px-3 py-2.5 w-10" />
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => (
              <tr key={p.id} className="border-b border-border-row hover:bg-hover transition-colors">
                <td className="pl-[18px] pr-3 py-3 text-text-primary text-[12.5px]">{p.name}</td>
                <td className="px-3 py-3 text-text-muted text-xs">{p.bank_name || '–'}</td>
                <td className="px-3 py-3 text-right font-mono text-text-primary tabular-nums">{formatCHF(p.market_value_chf)}</td>
                <td className="px-3 py-3 text-right font-mono text-text-muted tabular-nums">{p.weight_pct.toFixed(1)}%</td>
                <td className="px-3 py-3 text-center">
                  <button onClick={(e) => openCtxFor(e, p)} className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-white/10 transition-colors" title="Aktionen" aria-label="Aktionen öffnen">
                    <MoreVertical size={15} />
                  </button>
                </td>
              </tr>
            ))}
            {positions.length > 0 && (
              <tr className="bg-table-head border-t border-border-2">
                <td className="pl-[18px] pr-3 py-2.5 text-text-secondary font-medium text-xs" colSpan={2}>Total</td>
                <td className="px-3 py-2.5 text-right font-mono text-text-primary font-semibold tabular-nums">{formatCHF(totalPension)}</td>
                <td className="px-3 py-2.5 text-right font-mono text-text-muted tabular-nums">{totalMarketValue ? (totalPension / totalMarketValue * 100).toFixed(1) : 0}%</td>
                <td />
              </tr>
            )}
            {positions.length === 0 && (
              <tr><td colSpan={5} className="p-6 text-center text-text-muted text-sm">Keine Vorsorge-Positionen vorhanden.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="px-[18px] py-2.5 border-t border-border-row">
        <p className="text-[11px] text-text-muted">Gebundene Vorsorge (Säule 3a) — nicht liquide, nicht in der Cash-Quote.</p>
      </div>

      {ctxMenu && <ContextMenu x={ctxMenu.x} y={ctxMenu.y} onAction={handleAction} onClose={() => setCtxMenu(null)} positionType="pension" />}
      {editPosition && <EditPositionModal position={editPosition} onClose={() => setEditPosition(null)} onSaved={() => onRefresh?.()} />}
      {txnModal && <TransactionModal position={txnModal.position} type={txnModal.type} onClose={() => setTxnModal(null)} onSaved={() => onRefresh?.()} />}
      {deleteTarget && <DeleteConfirm name={deleteTarget.name} onConfirm={confirmDelete} onCancel={() => setDeleteTarget(null)} />}
      {showAdd && <AddPositionModal onClose={() => setShowAdd(false)} onSaved={() => onRefresh?.()} allowedTypes={["pension"]} />}
    </SectionCard>
  )
}
