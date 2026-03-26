import { useState, useCallback, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApi, apiDelete, authFetch } from '../hooks/useApi'
import { formatCHF, formatNumber, formatPct, pnlColor } from '../lib/format'
import EditPositionModal from './EditPositionModal'
import G from './GlossarTooltip'
import ContextMenu from './ContextMenu'
import { Bitcoin, Pencil, Trash2, TrendingUp, TrendingDown, MoreVertical, Plus, Upload } from 'lucide-react'
import DeleteConfirm from './DeleteConfirm'
import MiniChartTooltip from './MiniChartTooltip'
import { useToast } from './Toast'

function BtcDominanceCard({ value }) {
  return (
    <div className="rounded-lg border border-border bg-card-alt/30 p-4">
      <div className="text-xs text-text-muted mb-1"><G term="BTC Dominance">BTC Dominance</G></div>
      <div className="text-lg font-bold text-text-primary tabular-nums">
        {value != null ? `${value}%` : '–'}
      </div>
      {value != null && (
        <div className="mt-2 h-1.5 rounded-full bg-border overflow-hidden">
          <div
            className="h-full rounded-full bg-[#f7931a] transition-all"
            style={{ width: `${value}%` }}
          />
        </div>
      )}
    </div>
  )
}

function FearGreedCard({ value, label }) {
  const getStyle = (v) => {
    if (v == null) return { cls: 'bg-card-alt text-text-secondary', label: '–' }
    if (v <= 24) return { cls: 'bg-danger/10 text-danger', label: 'Extreme Fear' }
    if (v <= 44) return { cls: 'bg-warning/10 text-warning', label: 'Fear' }
    if (v <= 55) return { cls: 'bg-card-alt text-text-secondary', label: 'Neutral' }
    if (v <= 74) return { cls: 'bg-success/10 text-success', label: 'Greed' }
    return { cls: 'bg-success/10 text-success', label: 'Extreme Greed' }
  }

  const style = getStyle(value)

  return (
    <div className={`rounded-lg border border-border p-4 ${style.cls}`}>
      <div className="text-xs text-text-muted mb-1"><G term="Fear & Greed">Fear & Greed</G></div>
      <div className="text-lg font-bold tabular-nums">
        {value != null ? value : '–'}
      </div>
      <div className="text-xs font-medium">
        {label || style.label}
      </div>
    </div>
  )
}

function HalvingCard({ days, dateLabel }) {
  return (
    <div className="rounded-lg border border-border bg-card-alt/30 p-4">
      <div className="text-xs text-text-muted mb-1">Nächstes <G term="Halving">Halving</G></div>
      <div className="text-lg font-bold text-text-primary tabular-nums">
        {days != null ? `${days.toLocaleString('de-CH')} Tage` : '–'}
      </div>
      {dateLabel && (
        <div className="text-xs text-text-muted">~{dateLabel}</div>
      )}
    </div>
  )
}

function DxyCard({ value, changePct }) {
  const changeColor = changePct != null
    ? (changePct > 0 ? 'text-danger' : changePct < 0 ? 'text-success' : 'text-text-secondary')
    : ''

  return (
    <div className="rounded-lg border border-border bg-card-alt/30 p-4">
      <div className="text-xs text-text-muted mb-1"><G term="DXY">DXY</G> (US Dollar)</div>
      <div className="text-lg font-bold text-text-primary tabular-nums">
        {value != null ? value.toFixed(2) : '–'}
      </div>
      {changePct != null && (
        <div className={`text-xs font-medium tabular-nums flex items-center gap-1 ${changeColor}`}>
          {changePct < 0 ? <TrendingDown size={12} /> : <TrendingUp size={12} />}
          {changePct > 0 ? '+' : ''}{changePct.toFixed(2)}%
        </div>
      )}
    </div>
  )
}

function AthCard({ distancePct, athChf }) {
  const color = distancePct != null
    ? (distancePct > -10 ? 'text-danger' : distancePct > -40 ? 'text-warning' : 'text-success')
    : 'text-text-secondary'

  return (
    <div className="rounded-lg border border-border bg-card-alt/30 p-4">
      <div className="text-xs text-text-muted mb-1">BTC vs <G term="ATH">ATH</G></div>
      <div className={`text-lg font-bold tabular-nums ${color}`}>
        {distancePct != null ? `${distancePct > 0 ? '+' : ''}${distancePct.toFixed(1)}%` : '–'}
      </div>
      {athChf != null && (
        <div className="text-xs text-text-muted tabular-nums">
          ATH: CHF {athChf.toLocaleString('de-CH', { maximumFractionDigits: 0 })}
        </div>
      )}
    </div>
  )
}

function AddDropdown({ navigate }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border border-border text-text-secondary hover:border-primary hover:text-primary hover:bg-primary/5 transition-colors"
      >
        <Plus size={13} />
        <span className="hidden sm:inline">Position hinzufügen</span>
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 z-30 min-w-[180px] rounded-lg border border-border bg-card shadow-xl py-1 text-xs">
          <button
            onClick={() => { setOpen(false); navigate('/transactions?action=add') }}
            className="w-full text-left px-3 py-2 hover:bg-card-alt/50 text-text-secondary hover:text-text-primary flex items-center gap-2"
          >
            <Plus size={13} className="text-primary" /> Transaktion erfassen
          </button>
          <button
            onClick={() => { setOpen(false); navigate('/transactions?action=import') }}
            className="w-full text-left px-3 py-2 hover:bg-card-alt/50 text-text-secondary hover:text-text-primary flex items-center gap-2"
          >
            <Upload size={13} className="text-primary" /> CSV importieren
          </button>
        </div>
      )}
    </div>
  )
}

export default function CryptoWidget({ positions, onRefresh }) {
  const { data: metrics } = useApi('/market/crypto-metrics')
  const [ctxMenu, setCtxMenu] = useState(null)
  const [editPosition, setEditPosition] = useState(null)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const navigate = useNavigate()
  const toast = useToast()

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

  const totalValue = positions.reduce((s, p) => s + p.market_value_chf, 0)
  const totalPnl = positions.reduce((s, p) => s + p.pnl_chf, 0)
  const totalCost = positions.reduce((s, p) => s + p.cost_basis_chf, 0)
  const totalPnlPct = totalCost > 0 ? (totalPnl / totalCost) * 100 : 0

  const t1 = metrics?.tier1 || {}
  const t2 = metrics?.tier2 || {}

  return (
    <div className="rounded-lg border border-white/[0.06] border-t-2 border-t-orange-500/60 bg-card overflow-hidden shadow-[0_1px_3px_rgba(0,0,0,0.3)]">
      <div className="p-4 border-b border-white/[0.08] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Bitcoin size={20} className="text-orange-500" />
          <h3 className="text-lg font-semibold text-text-primary">Crypto</h3>
        </div>
        <AddDropdown navigate={navigate} />
      </div>

      {/* Market Metrics */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3 p-4">
        <BtcDominanceCard value={t1.btc_dominance} />
        <FearGreedCard value={t1.fear_greed_value} label={t1.fear_greed_label} />
        <HalvingCard days={t1.next_halving_days} dateLabel={t1.next_halving_date} />
        <DxyCard value={t1.dxy_value} changePct={t1.dxy_change_pct} />
        <AthCard distancePct={t2.btc_ath_distance_pct} athChf={t2.btc_ath_chf} />
      </div>

      {/* Positions Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-white/[0.08] text-slate-400 text-[11px] uppercase tracking-wider">
              <th className="text-left p-3 font-medium">Coin</th>
              <th className="text-right p-3 font-medium">Menge</th>
              <th className="text-right p-3 font-medium">Kurs CHF</th>
              <th className="text-right p-3 font-medium"><G term="24h %">24h %</G></th>
              <th className="text-right p-3 font-medium">Wert CHF</th>
              <th className="text-right p-3 font-medium">Perf %</th>
              <th className="text-right p-3 font-medium">Perf CHF</th>
              <th className="p-3 w-10" />
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => (
              <tr
                key={p.id}
                className="border-b border-border/50 hover:bg-card-alt/50 transition-colors cursor-pointer"
                onClick={() => navigate(`/stock/${encodeURIComponent(p.ticker)}`)}
              >
                <td className="p-3 text-text-primary font-medium"><MiniChartTooltip ticker={p.ticker}>{p.name}</MiniChartTooltip></td>
                <td className="p-3 text-right text-text-secondary tabular-nums">
                  {p.shares.toLocaleString('de-CH', { minimumFractionDigits: 2, maximumFractionDigits: 8 })} {p.ticker}
                </td>
                <td className="p-3 text-right text-text-secondary tabular-nums">
                  {p.current_price != null ? formatCHF(p.current_price) : '–'}
                </td>
                <td className={`p-3 text-right tabular-nums ${pnlColor(p.change_pct_24h)}`}>
                  {p.change_pct_24h != null ? formatPct(p.change_pct_24h) : '–'}
                </td>
                <td className="p-3 text-right text-text-primary font-medium tabular-nums">
                  {formatCHF(p.market_value_chf)}
                </td>
                <td className={`p-3 text-right font-medium tabular-nums ${pnlColor(p.pnl_pct)}`}>
                  {formatPct(p.pnl_pct)}
                </td>
                <td className={`p-3 text-right tabular-nums ${pnlColor(p.pnl_chf)}`}>
                  {formatCHF(p.pnl_chf)}
                </td>
                <td className="p-3 text-center">
                  <button
                    onClick={(e) => openCtxFor(e, p)}
                    className="p-1.5 rounded text-text-secondary hover:text-text-primary hover:bg-white/10 transition-colors"
                    title="Aktionen"
                    aria-label="Aktionen öffnen"
                  >
                    <MoreVertical size={16} />
                  </button>
                </td>
              </tr>
            ))}
            {positions.length > 0 && (
              <tr className="bg-card-alt/30 border-t border-border">
                <td className="p-3 text-text-primary font-medium" colSpan={4}>Total</td>
                <td className="p-3 text-right text-text-primary font-bold tabular-nums">
                  {formatCHF(totalValue)}
                </td>
                <td className={`p-3 text-right font-bold tabular-nums ${pnlColor(totalPnlPct)}`}>
                  {formatPct(totalPnlPct)}
                </td>
                <td className={`p-3 text-right font-bold tabular-nums ${pnlColor(totalPnl)}`}>
                  {formatCHF(totalPnl)}
                </td>
              </tr>
            )}
            {positions.length === 0 && (
              <tr>
                <td colSpan={8} className="p-8 text-center">
                  <p className="text-text-muted text-sm mb-1">Noch keine Crypto-Positionen.</p>
                  <p className="text-text-muted text-xs mb-4">Positionen werden automatisch aus Transaktionen erstellt.</p>
                  <div className="flex items-center justify-center gap-3">
                    <button
                      onClick={() => navigate('/transactions?action=add')}
                      className="flex items-center gap-1.5 px-4 py-2 text-sm rounded-lg border border-border text-text-secondary hover:border-primary hover:text-primary transition-colors"
                    >
                      <Plus size={14} />
                      Transaktion erfassen
                    </button>
                    <button
                      onClick={() => navigate('/transactions?action=import')}
                      className="flex items-center gap-1.5 px-4 py-2 text-sm rounded-lg bg-primary text-white hover:bg-primary/90 transition-colors"
                    >
                      <Upload size={14} />
                      CSV importieren
                    </button>
                  </div>
                </td>
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
        />
      )}

      {editPosition && (
        <EditPositionModal
          position={editPosition}
          onClose={() => setEditPosition(null)}
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
    </div>
  )
}
