// Chart color constants matching tailwind.config.js theme
// Use these in Recharts components instead of hardcoded hex values
export const CHART_COLORS = {
  primary: '#5b8def',
  success: '#45c08a',
  successLight: '#5fcf9d',
  danger: '#e8625a',
  warning: '#e0a64b',
  muted: '#9aa6b6',
  textMuted: '#7a8698',
  grid: '#1c2331',
  card: '#11151d',
  cardAlt: '#141a23',
  benchmark: '#6b7280',
}

export const AXIS_TICK = { fill: CHART_COLORS.muted, fontSize: 10 }
export const AXIS_TICK_SM = { fill: CHART_COLORS.muted, fontSize: 11 }
