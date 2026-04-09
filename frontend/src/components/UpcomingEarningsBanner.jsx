import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { Sun, Moon, Calendar } from 'lucide-react'
import { formatDate } from '../lib/format'

const TIME_ICON = {
  bmo: Sun,
  amc: Moon,
}

export default function UpcomingEarningsBanner() {
  const { data, loading, error } = useApi('/portfolio/upcoming-earnings?days=7')
  if (loading || error || !data?.earnings?.length) return null

  return (
    <div className="bg-card border border-border rounded-2xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <Calendar size={16} className="text-primary" />
        <h3 className="text-sm font-semibold text-text-primary">Naechste Earnings (7 Tage)</h3>
      </div>
      <div className="flex flex-wrap gap-3">
        {data.earnings.map((e) => {
          const Icon = TIME_ICON[e.earnings_time]
          return (
            <Link
              key={`${e.ticker}-${e.earnings_date}`}
              to={`/stock/${e.ticker}`}
              className="flex items-center gap-2 bg-body border border-border rounded-lg px-3 py-2 hover:border-primary/50 transition-colors"
            >
              <span className="font-mono text-sm font-semibold text-text-primary">{e.ticker}</span>
              <span className="text-xs text-text-muted">{formatDate(e.earnings_date)}</span>
              {Icon && <Icon size={14} className="text-text-muted" title={e.earnings_time_label} />}
              {e.eps_estimate != null && (
                <span className="text-xs text-text-muted">EPS {e.eps_estimate}</span>
              )}
            </Link>
          )
        })}
      </div>
    </div>
  )
}
