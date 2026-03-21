import { BarChart3 } from 'lucide-react'

export default function EmptyState({ icon: Icon = BarChart3, title = 'Keine Daten', message, action }) {
  return (
    <div className="rounded-lg border border-border bg-card p-8 flex flex-col items-center justify-center text-center">
      <Icon size={32} className="text-text-muted mb-3" />
      <p className="text-sm font-medium text-text-secondary">{title}</p>
      {message && <p className="text-xs text-text-muted mt-1">{message}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  )
}
