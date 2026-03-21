// Chart color constants matching tailwind.config.js theme
// Use these in Recharts components instead of hardcoded hex values
export const CHART_COLORS = {
  primary: '#3b82f6',
  success: '#10b981',
  successLight: '#22c55e',
  danger: '#ef4444',
  warning: '#f59e0b',
  muted: '#94a3b8',
  textMuted: '#9ca3af',
  grid: '#1e293b',
  card: '#111827',
  cardAlt: '#1a2235',
  benchmark: '#6b7280',
}

export const AXIS_TICK = { fill: CHART_COLORS.muted, fontSize: 10 }
export const AXIS_TICK_SM = { fill: CHART_COLORS.muted, fontSize: 11 }
