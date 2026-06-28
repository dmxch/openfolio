import { useState, useEffect } from 'react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer } from 'recharts'
import { useApi } from '../hooks/useApi'
import { formatCHF } from '../lib/format'
import { CHART_COLORS } from '../lib/chartColors'
import { Flame, Loader2 } from 'lucide-react'

const CARD = "rounded-lg border border-white/[0.06] bg-card p-4 shadow-[0_1px_3px_rgba(0,0,0,0.3)]"
const LS_KEY = 'openfolio_fire_assumptions'

const DEFAULTS = {
  capital_base: 'net_worth',
  annual_return_pct: 5,
  annual_savings_chf: 40000,
  withdrawal_rate_pct: 4,
  target_annual_spending_chf: 80000,
}

const BASE_LABEL = {
  liquid: 'Liquid (Wertschriften + Cash)',
  with_pension: '+ Vorsorge',
  net_worth: 'Netto-Vermögen (inkl. Immobilien)',
}

function loadAssumptions() {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (raw) return { ...DEFAULTS, ...JSON.parse(raw) }
  } catch { /* ignore */ }
  return DEFAULTS
}

function compact(n) {
  const a = Math.abs(n)
  if (a >= 1e6) return `${(n / 1e6).toFixed(1)}M`
  if (a >= 1e3) return `${Math.round(n / 1e3)}k`
  return `${Math.round(n)}`
}

export default function FireProjectionCard() {
  const [a, setA] = useState(loadAssumptions)

  useEffect(() => {
    try { localStorage.setItem(LS_KEY, JSON.stringify(a)) } catch { /* ignore */ }
  }, [a])

  // Debounce: nicht pro Keystroke fetchen (der Endpoint rechnet das Netto-Vermoegen).
  const [debounced, setDebounced] = useState(a)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(a), 350)
    return () => clearTimeout(t)
  }, [a])

  // Clamp auf die Backend-Bounds, damit stale/extreme localStorage-Werte kein 422 werfen.
  const clamp = (v, min, max) => Math.min(max, Math.max(min, Number(v) || 0))
  const qs = new URLSearchParams({
    capital_base: debounced.capital_base,
    annual_return_pct: clamp(debounced.annual_return_pct, -20, 30),
    annual_savings_chf: clamp(debounced.annual_savings_chf, 0, 100_000_000),
    withdrawal_rate_pct: Math.min(20, Math.max(0.1, Number(debounced.withdrawal_rate_pct) || 0.1)),
    target_annual_spending_chf: clamp(debounced.target_annual_spending_chf, 0, 100_000_000),
  }).toString()
  const { data, loading } = useApi(`/analysis/fire-projection?${qs}`)

  const set = (k) => (e) => {
    const v = e.target.value
    setA((prev) => ({ ...prev, [k]: k === 'capital_base' ? v : (v === '' ? 0 : Number(v)) }))
  }

  const num = "w-full bg-card-alt border border-border/50 rounded px-2 py-1 text-xs text-text-primary tabular-nums"
  const fire = data?.fire_number_chf
  const ytf = data?.years_to_fire
  const cov = data?.coverage_pct

  return (
    <div className={CARD}>
      <div className="flex items-center gap-2 mb-1">
        <Flame size={16} className="text-primary" />
        <h3 className="text-sm font-semibold text-text-primary">FIRE-/Kapital-Projektion</h3>
      </div>
      <p className="text-[11px] text-text-muted mb-3">
        Real (inflationsbereinigt, heutige CHF). Annahmen frei wählbar — werden lokal gespeichert.
      </p>

      {/* Annahmen */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-2 mb-3">
        <label className="text-[11px] text-text-muted">Kapitalbasis
          <select className={num} value={a.capital_base} onChange={set('capital_base')}>
            <option value="liquid">Liquid</option>
            <option value="with_pension">+ Vorsorge</option>
            <option value="net_worth">Netto-Vermögen</option>
          </select>
        </label>
        <label className="text-[11px] text-text-muted">Ziel-Ausgaben/Jahr
          <input type="number" className={num} value={a.target_annual_spending_chf} onChange={set('target_annual_spending_chf')} />
        </label>
        <label className="text-[11px] text-text-muted">Entnahmerate %
          <input type="number" step="0.1" className={num} value={a.withdrawal_rate_pct} onChange={set('withdrawal_rate_pct')} />
        </label>
        <label className="text-[11px] text-text-muted">Reale Rendite %
          <input type="number" step="0.1" className={num} value={a.annual_return_pct} onChange={set('annual_return_pct')} />
        </label>
        <label className="text-[11px] text-text-muted">Sparrate/Jahr
          <input type="number" className={num} value={a.annual_savings_chf} onChange={set('annual_savings_chf')} />
        </label>
      </div>

      {loading && !data ? (
        <div className="text-center py-6"><Loader2 size={18} className="animate-spin text-text-muted mx-auto" /></div>
      ) : data ? (
        <>
          {/* Kennzahlen */}
          <div className="grid grid-cols-3 gap-2 mb-3">
            <div>
              <div className="text-[10px] uppercase tracking-wide text-text-muted">FIRE-Zahl</div>
              <div className="text-base font-bold text-text-primary tabular-nums">{fire ? formatCHF(fire) : '—'}</div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wide text-text-muted">Heute / Deckung</div>
              <div className="text-base font-bold text-text-primary tabular-nums">
                {formatCHF(data.starting_capital_chf)}{cov != null && <span className="text-text-muted text-xs"> · {cov}%</span>}
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wide text-text-muted">Jahre bis FIRE</div>
              <div className="text-base font-bold text-primary tabular-nums">
                {ytf === 0 ? 'erreicht' : ytf != null ? `${ytf} J.` : `> ${data.assumptions?.horizon_years} J.`}
              </div>
            </div>
          </div>

          {/* Projektion */}
          <div className="h-40">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data.projection} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                <XAxis dataKey="year" tick={{ fontSize: 10, fill: CHART_COLORS.textMuted }} tickLine={false} axisLine={false} />
                <YAxis tickFormatter={compact} tick={{ fontSize: 10, fill: CHART_COLORS.textMuted }} tickLine={false} axisLine={false} width={36} />
                <Tooltip
                  formatter={(v) => formatCHF(v)}
                  labelFormatter={(y) => `Jahr ${y}`}
                  contentStyle={{ background: CHART_COLORS.cardAlt, border: 'none', borderRadius: 6, fontSize: 11 }}
                />
                {fire && <ReferenceLine y={fire} stroke={CHART_COLORS.success} strokeDasharray="4 3" label={{ value: 'FIRE', fontSize: 10, fill: CHART_COLORS.success, position: 'insideTopRight' }} />}
                <Line type="monotone" dataKey="capital_chf" stroke={CHART_COLORS.primary} strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <p className="text-[11px] text-text-muted mt-2">
            FIRE-Zahl = Ziel-Ausgaben / Entnahmerate ({a.withdrawal_rate_pct}% → {(100 / a.withdrawal_rate_pct).toFixed(0)}×). Projektion: Kapital × (1 + reale Rendite) + Sparrate.
            {a.capital_base === 'net_worth' && ' Netto-Vermögen inkl. Eigenheim-Equity und Private Equity überzeichnet FIRE (beide illiquide — generieren kein Entnahme-Einkommen).'}
          </p>
        </>
      ) : null}
    </div>
  )
}
