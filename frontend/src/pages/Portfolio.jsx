import { useState, useCallback, useEffect } from 'react'
import { useSearchParams, useNavigate, Link } from 'react-router-dom'
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
import { formatCHF, formatNumber, formatPct, pnlColor } from '../lib/format'
import DeleteConfirm from '../components/DeleteConfirm'
import Skeleton from '../components/Skeleton'
import PageHeader from '../components/ui/PageHeader'
import StatTile from '../components/ui/StatTile'
import Button from '../components/ui/Button'
import { TypeBadge, tint } from '../components/ui/Badge'
import { RefreshCw, Plus, MoreVertical } from 'lucide-react'

// Anlageklassen-Metadaten (Label + Akzentfarbe) fuer die Mobile-Ansicht.
// Farben = Cheatsheet/Badge-Map, damit Dots/Balken/Badges konsistent sind.
const CLASS_META = {
  stock: { label: 'Aktien', color: '#5b8def' },
  etf: { label: 'ETF', color: '#29c3b1' },
  crypto: { label: 'Krypto', color: '#b06ee8' },
  commodity: { label: 'Edelmetalle', color: '#e0a64b' },
  real_estate: { label: 'Immobilien', color: '#6b8aa0' },
  private_equity: { label: 'Private Equity', color: '#8a7de0' },
  cash: { label: 'Cash', color: '#7a8698' },
  pension: { label: 'Vorsorge', color: '#45c08a' },
}
const CLASS_ORDER = ['stock', 'etf', 'crypto', 'commodity', 'real_estate', 'private_equity', 'cash', 'pension']
const classMeta = (key) => CLASS_META[key] || { label: key, color: '#7a8698' }
// Effektive Klasse: Geldmarkt-/T-Bill-ETFs (count_as_cash) zaehlen als Cash —
// identisch zur Server-Allokation (allocations.by_type).
const effClass = (p) => (p.count_as_cash ? 'cash' : p.type)

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
  // Mobile-only: Anlageklassen-Filter fuer die Positions-Kartenliste.
  const [mobileFilter, setMobileFilter] = useState('all')

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

  // --- Mobile-Ableitungen (reine Darstellung derselben echten Daten) ---
  // Allokations-Balken: serverseitige Klassen-Allokation wiederverwenden.
  const allocByType = (summary?.allocations?.by_type || []).filter((a) => (a.pct || 0) > 0)
  // Positionsliste fuer die Kartenansicht: gehaltene Titel + Konten, geschlossene raus.
  const mobileList = positions.filter(
    (p) => p.type === 'cash' || p.type === 'pension' || p.count_as_cash || (p.shares || 0) > 0
  )
  const mobileClasses = CLASS_ORDER.filter((k) => mobileList.some((p) => effClass(p) === k))
  const mobileChips = [{ key: 'all', label: 'Alle' }, ...mobileClasses.map((k) => ({ key: k, label: classMeta(k).label }))]
  const mobileFiltered = mobileFilter === 'all' ? mobileList : mobileList.filter((p) => effClass(p) === mobileFilter)

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

      {/* ===== Desktop (>= md) — unveraendert ===== */}
      <div className="hidden md:flex md:flex-col gap-[18px]">
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

      {/* ===== Mobile (< md) — kompakte Darstellung derselben Daten ===== */}
      <div className="md:hidden flex flex-col gap-[14px]">
        {/* 1) Netto-Vermoegen-Hero (Tagesveraenderung liegt nicht in der Summary → weggelassen) */}
        <div className="bg-gradient-to-br from-[#13203a] to-card border border-border rounded-card p-5">
          <div className="font-mono text-[10.5px] tracking-[0.06em] uppercase text-text-label mb-2">Netto-Vermoegen</div>
          <div className="font-mono text-[30px] font-semibold tracking-[-0.01em] leading-none text-text-bright">{formatCHF(total)}</div>
          <div className="mt-2.5 text-[11.5px] text-text-faint">Inkl. Cash &amp; Vorsorge</div>
        </div>

        {/* 2) Mini-Stat-Tiles (Realisiert YTD existiert nicht in der Summary → durch Positionen ersetzt) */}
        <div className="grid grid-cols-3 gap-[10px]">
          <StatTile
            label="Unrealisiert"
            value={formatPct(unrealPct)}
            tone={totalPnl >= 0 ? 'success' : 'danger'}
          />
          <StatTile label="Cash-Quote" value={`${cashPct.toFixed(1)}%`} tone="bright" />
          <StatTile label="Positionen" value={tradable.length} tone="bright" />
        </div>

        {/* 3) Allokations-Balken nach Anlageklasse + Legende */}
        {allocByType.length > 0 && (
          <div className="bg-card border border-border rounded-card p-4">
            <div className="font-mono text-[10.5px] tracking-[0.06em] uppercase text-text-label mb-3">Allokation</div>
            <div className="flex h-2.5 rounded-full overflow-hidden bg-card-2">
              {allocByType.map((a) => (
                <div key={a.name} style={{ width: `${a.pct}%`, background: classMeta(a.name).color }} />
              ))}
            </div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-2 mt-3.5">
              {allocByType.map((a) => (
                <div key={a.name} className="flex items-center gap-2 text-[11.5px] min-w-0">
                  <span className="w-2 h-2 rounded-[2px] flex-none" style={{ background: classMeta(a.name).color }} />
                  <span className="text-text-secondary truncate flex-1">{classMeta(a.name).label}</span>
                  <span className="font-mono text-text-primary tabular-nums flex-none">{a.pct.toFixed(1)}%</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 4) Klassen-Filter (horizontaler Scroller) */}
        {mobileChips.length > 1 && (
          <div className="flex gap-2 overflow-x-auto -mx-4 px-4 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {mobileChips.map((c) => (
              <button
                key={c.key}
                onClick={() => setMobileFilter(c.key)}
                className={`flex-none whitespace-nowrap rounded-full px-3.5 py-1.5 text-[12px] font-medium border transition-colors ${
                  mobileFilter === c.key
                    ? 'bg-active-tint border-border-active text-link'
                    : 'bg-surface border-border text-text-secondary'
                }`}
              >
                {c.label}
              </button>
            ))}
          </div>
        )}

        {/* 5) Positionen als antippbare Karten */}
        <div className="flex flex-col gap-2">
          {mobileFiltered.map((p) => <MobilePosCard key={p.id} p={p} />)}
          {mobileFiltered.length === 0 && (
            <div className="bg-card border border-border rounded-card p-8 text-center text-text-muted text-sm">
              Keine Positionen in dieser Anlageklasse.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// Mobile: antippbare Positions-Karte. Wertpapiere verlinken auf die Detailseite,
// reine Konten (Cash/Vorsorge) bleiben ohne Link.
function MobilePosCard({ p }) {
  const cls = effClass(p)
  const meta = classMeta(cls)
  const code = (p.ticker || p.name || '?').replace(/[^A-Za-z0-9]/g, '').slice(0, 2).toUpperCase() || '?'
  const isAccount = p.type === 'cash' || p.type === 'pension'
  const linkable = !!p.ticker && ['stock', 'etf', 'crypto', 'commodity'].includes(p.type)

  const inner = (
    <>
      <span
        className="w-9 h-9 rounded-[9px] flex items-center justify-center font-mono text-[11px] font-semibold flex-none"
        style={{ color: meta.color, background: tint(meta.color) }}
      >
        {code}
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="font-mono text-[13px] font-medium text-text-primary truncate">{p.ticker || p.name}</span>
          <TypeBadge label={meta.label} className="flex-none" />
        </div>
        {p.ticker && p.name && <div className="text-[11.5px] text-text-faint truncate">{p.name}</div>}
      </div>
      <div className="text-right flex-none">
        <div className="font-mono text-[13px] text-text-primary tabular-nums">{formatCHF(p.market_value_chf)}</div>
        {isAccount ? (
          <div className="font-mono text-[11.5px] text-text-faint tabular-nums">
            {p.weight_pct != null ? `${p.weight_pct.toFixed(1)}%` : ''}
          </div>
        ) : (
          <div className={`font-mono text-[11.5px] tabular-nums ${pnlColor(p.pnl_pct)}`}>{formatPct(p.pnl_pct)}</div>
        )}
      </div>
    </>
  )

  const base = 'flex items-center gap-3 bg-card border border-border rounded-card px-3.5 py-3 transition-colors'
  return linkable ? (
    <Link to={`/stock/${encodeURIComponent(p.ticker)}`} className={`${base} active:bg-hover`}>{inner}</Link>
  ) : (
    <div className={base}>{inner}</div>
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
                  <td className="px-3 py-3 text-right font-mono text-text-primary tabular-nums">{formatNumber(p.market_value_chf)}</td>
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
                <td className="px-3 py-2.5 text-right font-mono text-text-primary font-semibold tabular-nums">{formatNumber(totalCash)}</td>
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
                <td className="px-3 py-2.5 text-right font-mono text-text-primary font-semibold tabular-nums">{formatNumber(totalPension)}</td>
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
