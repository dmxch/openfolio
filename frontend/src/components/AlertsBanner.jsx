import { useState, useEffect, useCallback } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useApi, authFetch } from '../hooks/useApi'
import { AlertTriangle, Info, TrendingUp, ChevronDown, ChevronUp, X } from 'lucide-react'

const severityStyles = {
  critical: { bg: 'bg-danger/10', border: 'border-l-4 border-l-danger', glow: 'shadow-[0_0_15px_rgba(239,68,68,0.12)]', icon: <AlertTriangle size={16} className="text-danger shrink-0" /> },
  high: { bg: 'bg-warning/10', border: 'border-l-4 border-l-warning', glow: 'shadow-[0_0_12px_rgba(245,158,11,0.12)]', icon: <AlertTriangle size={16} className="text-warning shrink-0" /> },
  medium: { bg: 'bg-primary/10', border: 'border-l-4 border-l-primary', glow: 'shadow-[0_0_12px_rgba(59,130,246,0.10)]', icon: <Info size={16} className="text-primary shrink-0" /> },
  positive: { bg: 'bg-success/10', border: 'border-l-4 border-l-success', glow: 'shadow-[0_0_12px_rgba(34,197,94,0.10)]', icon: <TrendingUp size={16} className="text-success shrink-0" /> },
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

// Globales Refresh-Signal: useApi('/alerts') fetcht nur einmal pro Mount —
// nach Mutationen die Alerts beeinflussen (Stop-Save, Positions-Edit) muss
// der Fetch explizit invalidiert werden, sonst bleibt der Banner bis zum
// harten Reload stehen.
export const ALERTS_REFRESH_EVENT = 'alerts:refresh'

export function notifyAlertsChanged() {
  window.dispatchEvent(new Event(ALERTS_REFRESH_EVENT))
}

function useAlertsData() {
  const { data, refetch } = useApi('/alerts')
  useEffect(() => {
    window.addEventListener(ALERTS_REFRESH_EVENT, refetch)
    return () => window.removeEventListener(ALERTS_REFRESH_EVENT, refetch)
  }, [refetch])
  return data
}

// Stabiler Dismissal-Key: Index verschiebt sich wenn sich die Alert-Liste
// ändert (Refetch). Message bewusst nicht im Key — sie enthält variable
// Teile (Tage, Abstand) und würde Dismissals bei jedem Refetch aufheben.
function alertKey(alert) {
  return `${alert.category || 'misc'}:${alert.ticker || ''}:${alert.title}`
}

export default function AlertsBanner({ onEditPosition, onEditStopLoss, onScrollTo }) {
  const data = useAlertsData()
  const [expanded, setExpanded] = useState(false)
  const [dismissed, setDismissed] = useState(new Set())
  const [autoExpanded, setAutoExpanded] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape' && expanded) setExpanded(false) }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [expanded])

  // Track auto-expand state (no longer auto-expands — user clicks to see details)
  useEffect(() => {
    if (data?.critical_count > 0) setAutoExpanded(true)
  }, [data?.critical_count])

  if (!data?.alerts?.length) return null

  const visible = data.alerts.filter((a) => !dismissed.has(alertKey(a)))
  if (!visible.length) return null

  const highestSeverity = visible[0]?.severity || 'medium'
  const badgeColor = badgeColors[highestSeverity] || badgeColors.medium

  return (
    <div className="space-y-0" aria-live="polite">
      <button
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        aria-label={`${visible.length} Alerts anzeigen`}
        className={`w-full flex items-center justify-between px-4 py-2.5 rounded-lg text-sm ${severityStyles[highestSeverity].bg} ${severityStyles[highestSeverity].glow} border border-border hover:border-border/80 transition-colors`}
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
          {data.alerts.map((alert) => {
            const key = alertKey(alert)
            if (dismissed.has(key)) return null
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
                    onClick={(e) => { e.stopPropagation(); setDismissed((prev) => new Set([...prev, key])) }}
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
  const data = useAlertsData()
  if (!data?.count) return null
  const color = data.critical_count > 0 ? 'bg-danger' : 'bg-warning'
  return (
    <span className={`${color} text-white text-xs font-bold px-1.5 py-0.5 rounded-full`}>{data.count}</span>
  )
}
