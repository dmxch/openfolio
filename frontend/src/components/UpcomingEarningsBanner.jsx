import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { Sun, Moon, Calendar } from 'lucide-react'
import { formatDate } from '../lib/format'
import Card from './ui/Card'
import TickerChip from './ui/TickerChip'

const TIME_ICON = {
  bmo: Sun,
  amc: Moon,
}

export default function UpcomingEarningsBanner() {
  const { data, loading, error } = useApi('/portfolio/upcoming-earnings?days=7')
  if (loading || error || !data?.earnings?.length) return null

  return (
    <>
      {/* DESKTOP */}
      <Card className="hidden md:block overflow-hidden">
        <div className="px-[18px] py-4 border-b border-border-2 flex items-center gap-2.5">
          <Calendar size={15} className="text-primary" />
          <h3 className="text-sm font-semibold text-text-primary">Earnings diese Woche</h3>
          <span className="font-mono text-[10.5px] text-text-faint">{data.earnings.length}</span>
        </div>
        <div className="p-[18px] flex gap-3 overflow-x-auto">
          {data.earnings.map((e) => {
            const Icon = TIME_ICON[e.earnings_time]
            return (
              <Link
                key={`${e.ticker}-${e.earnings_date}`}
                to={`/stock/${e.ticker}`}
                title={e.earnings_time_label}
                className="flex flex-col gap-2 min-w-[150px] shrink-0 bg-card-2 border border-border-2 rounded-lg px-3 py-2.5 hover:border-border-hover transition-colors"
              >
                <div className="flex items-center justify-between gap-2">
                  <TickerChip>{e.ticker}</TickerChip>
                  {Icon && <Icon size={14} className="text-text-muted flex-shrink-0" />}
                </div>
                <span className="inline-flex w-fit items-center font-mono text-[10.5px] text-link bg-primary/10 rounded px-1.5 py-0.5">
                  {formatDate(e.earnings_date)}
                </span>
                {e.name && <span className="text-[11px] text-text-muted truncate">{e.name}</span>}
                {e.eps_estimate != null && (
                  <span className="text-[11px] text-text-secondary font-mono">EPS {e.eps_estimate}</span>
                )}
              </Link>
            )
          })}
        </div>
      </Card>

      {/* MOBILE — horizontaler Scroller */}
      <div className="md:hidden">
        <div className="flex items-center gap-2 px-1 mb-2">
          <Calendar size={14} className="text-primary" />
          <h3 className="text-[13px] font-semibold text-text-primary">Earnings diese Woche</h3>
          <span className="font-mono text-[10.5px] text-text-faint">{data.earnings.length}</span>
        </div>
        <div className="-mx-4 px-4 flex gap-2.5 overflow-x-auto">
          {data.earnings.map((e) => {
            const Icon = TIME_ICON[e.earnings_time]
            return (
              <Link
                key={`m-${e.ticker}-${e.earnings_date}`}
                to={`/stock/${e.ticker}`}
                title={e.earnings_time_label}
                className="flex-none w-[140px] flex flex-col gap-1.5 bg-card-2 border border-border-2 rounded-lg px-3 py-2.5"
              >
                <div className="flex items-center justify-between gap-2">
                  <TickerChip>{e.ticker}</TickerChip>
                  {Icon && <Icon size={13} className="text-text-muted flex-shrink-0" />}
                </div>
                <span className="inline-flex w-fit items-center font-mono text-[10px] text-link bg-primary/10 rounded px-1.5 py-0.5">
                  {formatDate(e.earnings_date)}
                </span>
                {e.name && <span className="text-[11px] text-text-muted truncate">{e.name}</span>}
                {e.eps_estimate != null && (
                  <span className="text-[11px] text-text-secondary font-mono">EPS {e.eps_estimate}</span>
                )}
              </Link>
            )
          })}
        </div>
      </div>
    </>
  )
}
