import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router'
import { authFetch } from '../hooks/useApi'
import { dismissAlert, isDismissed, subscribeDismissals } from '../lib/alertDismissals'
import { AlertTriangle, Info, TrendingUp, ChevronDown, ChevronUp, X } from 'lucide-react'

const severityStyles = {
  critical: { bg: 'bg-danger/10', border: 'border-l-4 border-l-danger', glow: 'shadow-[0_0_15px_rgba(232,98,90,0.12)]', icon: <AlertTriangle size={16} className="text-danger shrink-0" /> },
  high: { bg: 'bg-warning/10', border: 'border-l-4 border-l-warning', glow: 'shadow-[0_0_12px_rgba(224,166,75,0.12)]', icon: <AlertTriangle size={16} className="text-warning shrink-0" /> },
  medium: { bg: 'bg-primary/10', border: 'border-l-4 border-l-primary', glow: 'shadow-[0_0_12px_rgba(91,141,239,0.10)]', icon: <Info size={16} className="text-primary shrink-0" /> },
  positive: { bg: 'bg-success/10', border: 'border-l-4 border-l-success', glow: 'shadow-[0_0_12px_rgba(69,192,138,0.10)]', icon: <TrendingUp size={16} className="text-success shrink-0" /> },
  info: { bg: 'bg-text-muted/10', border: 'border-l-4 border-l-text-muted', glow: '', icon: <Info size={16} className="text-text-muted shrink-0" /> },
}

const badgeColors = {
  critical: 'bg-danger',
  high: 'bg-warning',
  medium: 'bg-primary',
  positive: 'bg-success',
  info: 'bg-text-muted',
}

// Map alert category to click action
function getAlertAction(alert) {
  const cat = alert.category
  const ticker = alert.ticker
  if (!cat) return null

  // Industry/sector missing → edit position
  if (cat === 'industry_missing' || cat === 'etf_sector_missing') {
    return { type: 'edit_position', ticker, focus: 'industry' }
  }
  // Stop-loss alerts → edit stop-loss
  if (cat.startsWith('stop_loss') || cat === 'stop_proximity' || cat === 'stop_reached') {
    return { type: 'edit_stop_loss', ticker }
  }
  // MA / loss alerts → scroll to position
  if (cat === 'ma_critical' || cat === 'ma_warning' || cat === 'loss') {
    return ticker ? { type: 'scroll_to', ticker } : null
  }
  // Sector/position limit → scroll to allocation
  if (cat === 'sector_limit' || cat === 'position_limit' || cat.startsWith('allocation')) {
    return { type: 'scroll_to_section', section: 'allocation' }
  }
  // Price alerts → navigate to watchlist
  if (cat === 'price_alert') {
    return { type: 'navigate', path: '/watchlist', ticker }
  }
  // Earnings → stock detail
  if (cat === 'earnings' && ticker) {
    return { type: 'navigate', path: `/stock/${encodeURIComponent(ticker)}` }
  }
  // ETF 200-DMA → stock detail
  if (cat === 'etf_200dma_buy' && ticker) {
    return { type: 'navigate', path: `/stock/${encodeURIComponent(ticker)}` }
  }
  return null
}

// Globales Refresh-Signal: der Alerts-Store fetcht nur bei Mount eines
// Consumers — nach Mutationen die Alerts beeinflussen (Stop-Save,
// Positions-Edit) muss der Fetch explizit invalidiert werden, sonst bleibt
// der Banner bis zum harten Reload stehen.
export const ALERTS_REFRESH_EVENT = 'alerts:refresh'

export function notifyAlertsChanged() {
  window.dispatchEvent(new Event(ALERTS_REFRESH_EVENT))
}

// Stabiler Dismissal-Key: Index verschiebt sich wenn sich die Alert-Liste
// ändert (Refetch). Message bewusst nicht im Key — sie enthält variable
// Teile (Tage, Abstand) und würde Dismissals bei jedem Refetch aufheben.
function alertKey(alert) {
  return `${alert.category || 'misc'}:${alert.ticker || ''}:${alert.title}`
}

// ── Geteilter Alerts-Store ────────────────────────────────────────────────
// Sidebar-Badge und Banner MÜSSEN dieselbe Zahl zeigen. Vorher hatte jeder
// Consumer seinen eigenen useApi('/alerts')-Mount plus einen lokalen
// Dismissal-State: der Badge zählte weggeklickte Alerts weiter mit und blieb
// zusätzlich stehen, wenn sich die Alerts nach dem Sidebar-Mount änderten
// (Badge 6 vs. "3 Alerts" im Panel — Feedback 30.7.2026). Ein Store, ein
// Dismissal-Set, eine Wahrheit.
let storeData = null
let inflight = null
let refreshQueued = false
const storeListeners = new Set()

function emitStoreChange() {
  storeListeners.forEach((listener) => listener())
}

// Parallele Mounts (Sidebar + Banner) teilen sich einen Request.
function fetchAlerts() {
  if (inflight) {
    // Ein Refresh-Signal waehrend eines laufenden Fetches darf nicht in dessen
    // (vor der Mutation gestartete) Response laufen — nachziehen.
    refreshQueued = true
    return inflight
  }
  inflight = (async () => {
    try {
      const res = await authFetch('/api/alerts')
      if (!res.ok) return
      const json = await res.json()
      // Niemand hoert mehr zu (Logout waehrend des Fetches): Ergebnis
      // verwerfen, sonst erbt der naechste User im Tab diese Alerts.
      if (storeListeners.size === 0) return
      storeData = json
      emitStoreChange()
    } catch {
      // Netzfehler: alten Stand behalten, kein Badge-Flackern
    } finally {
      inflight = null
      if (refreshQueued) {
        refreshQueued = false
        if (storeListeners.size > 0) fetchAlerts()
      }
    }
  })()
  return inflight
}

function useAlertsStore() {
  const [, forceRender] = useState(0)

  useEffect(() => {
    const listener = () => forceRender((n) => n + 1)
    storeListeners.add(listener)
    const unsubscribeDismissals = subscribeDismissals(listener)
    const onRefresh = () => fetchAlerts()
    window.addEventListener(ALERTS_REFRESH_EVENT, onRefresh)
    // Jeder Mount holt frisch — der Banner-Mount (Portfolio-Seite) hält damit
    // auch den dauerhaft gemounteten Sidebar-Badge aktuell.
    fetchAlerts()
    return () => {
      storeListeners.delete(listener)
      unsubscribeDismissals()
      window.removeEventListener(ALERTS_REFRESH_EVENT, onRefresh)
      // Letzter Consumer weg (Logout / App-Shell unmount): Cache verwerfen,
      // sonst zeigt der Badge nach einem User-Wechsel im selben Tab kurz die
      // Alerts des Vorgängers.
      if (storeListeners.size === 0) {
        storeData = null
        refreshQueued = false
      }
    }
  }, [])

  const alerts = storeData?.alerts || []
  const visible = alerts.filter((a) => !isDismissed(alertKey(a)))
  return {
    visible,
    criticalCount: visible.filter((a) => a.severity === 'critical').length,
    dismiss: dismissAlert,
  }
}

export default function AlertsBanner({ onEditPosition, onEditStopLoss, onScrollTo }) {
  const { visible, dismiss } = useAlertsStore()
  const [expanded, setExpanded] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape' && expanded) setExpanded(false) }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [expanded])

  if (!visible.length) return null

  const highestSeverity = visible[0]?.severity || 'medium'
  const badgeColor = badgeColors[highestSeverity] || badgeColors.medium

  return (
    <div className="space-y-0" aria-live="polite">
      <button
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        aria-label={`${visible.length} Alerts anzeigen`}
        className={`w-full flex items-center justify-between px-4 py-2.5 rounded-lg text-sm ${severityStyles[highestSeverity].bg} ${severityStyles[highestSeverity].glow} border border-border hover:border-border-hover transition-colors`}
      >
        <div className="flex items-center gap-2">
          {severityStyles[highestSeverity].icon}
          <span className="text-text-primary font-medium">{visible.length} Alert{visible.length > 1 ? 's' : ''}</span>
          {!expanded && <span className="text-text-muted">— {visible[0]?.title}</span>}
        </div>
        <div className="flex items-center gap-2">
          <span className={`${badgeColor} text-white text-xs font-bold px-1.5 py-0.5 rounded-full`}>{visible.length}</span>
          {expanded ? <ChevronUp size={16} className="text-text-muted" /> : <ChevronDown size={16} className="text-text-muted" />}
        </div>
      </button>

      {expanded && (
        <div className="mt-2 space-y-1.5">
          {visible.map((alert) => {
            const key = alertKey(alert)
            const style = severityStyles[alert.severity] || severityStyles.medium
            const action = getAlertAction(alert)
            const handleClick = action ? () => {
              if (action.type === 'edit_position' && onEditPosition) {
                onEditPosition(action.ticker)
              } else if (action.type === 'edit_stop_loss' && onEditStopLoss) {
                onEditStopLoss(action.ticker)
              } else if (action.type === 'scroll_to' && onScrollTo) {
                onScrollTo(action.ticker)
              } else if (action.type === 'scroll_to_section' && onScrollTo) {
                onScrollTo(null, action.section)
              } else if (action.type === 'navigate') {
                navigate(action.path)
              }
            } : null
            return (
              <div
                key={key}
                className={`flex items-start gap-3 px-4 py-3 rounded-lg ${style.bg} ${style.border} ${action ? 'cursor-pointer hover:brightness-95 transition-all' : ''}`}
                onClick={handleClick}
                role={action ? 'button' : undefined}
              >
                <div className="mt-0.5">{style.icon}</div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-text-primary">
                    {alert.title}
                  </div>
                  <div className="text-xs text-text-secondary mt-0.5">{alert.message}</div>
                </div>
                {!(alert.severity === 'critical' && (alert.category === 'stop_loss_missing' || alert.category === 'stop_loss_unconfirmed')) && (
                  <button
                    onClick={(e) => { e.stopPropagation(); dismiss(key) }}
                    className="text-text-muted hover:text-text-primary shrink-0"
                    aria-label="Alert schliessen"
                  >
                    <X size={14} />
                  </button>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export function AlertBadge() {
  const { visible, criticalCount } = useAlertsStore()
  if (!visible.length) return null
  const color = criticalCount > 0 ? 'bg-danger' : 'bg-warning'
  return (
    <span className={`${color} text-white text-xs font-bold px-1.5 py-0.5 rounded-full`}>{visible.length}</span>
  )
}
