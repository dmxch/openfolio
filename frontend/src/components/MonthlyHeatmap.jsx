import { CHART_COLORS } from '../lib/chartColors'
import G from './GlossarTooltip'

const MONTH_LABELS = ['J', 'F', 'M', 'A', 'M', 'J', 'J', 'A', 'S', 'O', 'N', 'D']

function getCellColor(val) {
  if (val > 5) return 'rgba(16, 185, 129, 0.7)'
  if (val > 2) return 'rgba(5, 150, 105, 0.6)'
  if (val >= 0) return 'rgba(6, 95, 70, 0.55)'
  if (val >= -2) return 'rgba(127, 29, 29, 0.55)'
  if (val >= -5) return 'rgba(185, 28, 28, 0.6)'
  return 'rgba(239, 68, 68, 0.7)'
}

export default function MonthlyHeatmap({ data, loading }) {
  if (loading) return null

  // Support both old format (array) and new format ({months, annual_totals})
  const months = Array.isArray(data) ? data : data?.months
  const annualTotals = Array.isArray(data) ? null : data?.annual_totals

  if (!months || months.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-card p-8 text-center">
        <p className="text-sm text-text-muted">Noch keine Monatsrenditen verfügbar.</p>
      </div>
    )
  }

  // Group by year
  const byYear = {}
  for (const d of months) {
    if (!byYear[d.year]) byYear[d.year] = {}
    byYear[d.year][d.month] = d.return_pct
  }

  const years = Object.keys(byYear).sort((a, b) => a - b)

  return (
    <div className="rounded-lg border border-white/[0.06] bg-card overflow-hidden shadow-[0_1px_3px_rgba(0,0,0,0.3)]">
      <div className="p-4 border-b border-white/[0.08]">
        <h3 className="text-sm font-medium text-text-secondary">Monatsrenditen</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-white/[0.08] text-slate-400 text-[11px] uppercase tracking-wider">
              <th className="p-2 text-left font-medium">Jahr</th>
              {MONTH_LABELS.map((m, i) => (
                <th key={i} className="p-2 text-center font-medium w-14">{m}</th>
              ))}
              <th className="p-2 text-center font-medium w-16"><G term="MWR">Total</G></th>
            </tr>
          </thead>
          <tbody>
            {years.map((year) => {
              const monthData = byYear[year]
              // Use XIRR from backend if available, otherwise compound Modified Dietz
              let yearTotal
              if (annualTotals && annualTotals[year] != null) {
                yearTotal = annualTotals[year]
              } else {
                let compounded = 1
                for (let m = 1; m <= 12; m++) {
                  if (monthData[m] !== undefined) {
                    compounded *= (1 + monthData[m] / 100)
                  }
                }
                yearTotal = (compounded - 1) * 100
              }

              return (
                <tr key={year} className="border-b border-border/50">
                  <td className="p-2 text-text-primary font-medium tabular-nums">{year}</td>
                  {Array.from({ length: 12 }, (_, i) => {
                    const val = monthData[i + 1]
                    if (val === undefined) {
                      return <td key={i} className="p-2" />
                    }
                    return (
                      <td
                        key={i}
                        className="p-2 text-center text-white font-semibold tabular-nums"
                        style={{ backgroundColor: getCellColor(val) }}
                      >
                        {val.toFixed(1)}
                      </td>
                    )
                  })}
                  <td
                    className="p-2 text-center text-white font-medium tabular-nums"
                    style={{ backgroundColor: getCellColor(yearTotal) }}
                  >
                    {yearTotal.toFixed(1)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
