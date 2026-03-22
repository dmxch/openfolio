import { useState, useEffect } from 'react'
import { useApi, apiPost } from '../hooks/useApi'
import { CheckCircle, XCircle, MinusCircle, Loader2, X, AlertTriangle, Info, Zap, ExternalLink, Eye, Clock, CircleCheck, Plus, Check } from 'lucide-react'
import { useToast } from './Toast'
import G from './GlossarTooltip'

const GROUP_ORDER = ['Moving Averages', 'Breakout', 'Relative Stärke', 'Volumen & Liquidität', 'Fundamentals']

const SIGNAL_CONFIG = {
  ETF_KAUFSIGNAL: { bg: 'bg-teal-500/15', border: 'border-teal-500', text: 'text-teal-400', icon: CircleCheck, label: 'ETF unter 200-DMA — Kaufkriterien erfüllt' },
  KAUFSIGNAL: { bg: 'bg-success/15', border: 'border-success', text: 'text-success', icon: CircleCheck, label: 'Kaufkriterien erfüllt (Breakout bestätigt)' },
  WATCHLIST: { bg: 'bg-warning/15', border: 'border-warning', text: 'text-warning', icon: Eye, label: 'Warten auf Breakout' },
  BEOBACHTEN: { bg: 'bg-card-alt', border: 'border-border', text: 'text-text-secondary', icon: Clock, label: 'Setup nicht stark genug' },
  'KEIN SETUP': { bg: 'bg-danger/15', border: 'border-danger', text: 'text-danger', icon: XCircle, label: 'Kriterien nicht erfüllt' },
}

function SignalBadge({ signal, signalLabel, setupQuality, score, maxScore }) {
  const config = SIGNAL_CONFIG[signal] || SIGNAL_CONFIG['KEIN SETUP']
  const Icon = config.icon

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="text-xs text-text-muted">
        <G term="Setup-Score">Setup</G>: <span className="font-mono font-medium text-text-secondary">{score}/{maxScore}</span> <span className="opacity-75">({setupQuality})</span>
      </div>
      <div className={`rounded-xl border-2 ${config.border} ${config.bg} px-5 py-3 text-center min-w-[140px]`}>
        <Icon size={22} className={`${config.text} mx-auto mb-1`} />
        <p className={`${config.text} font-bold text-sm`}><G term={signal}>{signal}</G></p>
        <p className={`${config.text} opacity-75 text-[11px] mt-0.5`}>{signalLabel || config.label}</p>
      </div>
    </div>
  )
}

function GroupSection({ group, criteria }) {
  const passed = criteria.filter((c) => c.passed === true).length
  const total = criteria.filter((c) => c.passed !== null).length

  return (
    <div className="rounded-lg border border-border bg-card-alt/30 p-4">
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-sm font-semibold text-text-primary">{
          group === 'Moving Averages' ? <G term="Moving Averages">{group}</G> :
          group === 'Breakout' ? <G term="Breakout">{group}</G> :
          group === 'Relative Stärke' ? <G term="Mansfield RS">{group}</G> :
          group === 'Volumen & Liquidität' ? <><G term="Volumen">Volumen</G> & <G term="Liquidität">Liquidität</G></> :
          group === 'Fundamentals' ? <G term="Fundamentals">{group}</G> :
          group
        }</h4>
        <span className={`text-xs font-mono px-2 py-0.5 rounded ${
          total === 0 ? 'bg-card-alt text-text-muted' :
          passed === total ? 'bg-success/15 text-success' :
          passed > 0 ? 'bg-warning/15 text-warning' :
          'bg-danger/15 text-danger'
        }`}>
          {passed}/{total}
        </span>
      </div>
      <div className="space-y-1.5">
        {criteria.map((c) => (
          <div key={c.id} className="flex items-start gap-2.5 py-1">
            <div className="mt-0.5 flex-shrink-0">
              {c.passed === true ? (
                <CheckCircle size={15} className="text-success" />
              ) : c.passed === false ? (
                <XCircle size={15} className="text-danger" />
              ) : (
                <MinusCircle size={15} className="text-text-muted" />
              )}
            </div>
            <div className="flex-1 min-w-0">
              <p className={`text-sm leading-tight ${
                c.passed === true ? 'text-text-primary' :
                c.passed === false ? 'text-text-secondary' :
                'text-text-muted'
              }`}>{c.name}</p>
              <p className="text-[11px] text-text-muted mt-0.5 truncate">{c.detail}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function AlertList({ alerts }) {
  if (!alerts?.length) return null

  const icons = { danger: AlertTriangle, warning: Info, success: Zap }
  const styles = {
    danger: 'bg-danger/10 border-danger/30 text-danger',
    warning: 'bg-warning/10 border-warning/30 text-warning',
    success: 'bg-success/10 border-success/30 text-success',
  }

  return (
    <div className="space-y-2">
      {alerts.map((a, i) => {
        const Icon = icons[a.type] || Info
        return (
          <div key={i} className={`flex items-center gap-2.5 rounded-lg border px-4 py-2.5 text-sm ${styles[a.type] || styles.warning}`}>
            <Icon size={15} className="flex-shrink-0" />
            {a.text}
          </div>
        )
      })}
    </div>
  )
}

function CompanyDescription({ profile }) {
  const [expanded, setExpanded] = useState(false)

  const formatEmployees = (n) => {
    if (!n) return null
    return n.toLocaleString('de-CH')
  }

  return (
    <div>
      <div className={expanded ? '' : 'line-clamp-2'}>
        <p className="text-sm text-text-secondary leading-relaxed">{profile.description}</p>
      </div>
      <button
        onClick={() => setExpanded(!expanded)}
        className="text-xs text-primary cursor-pointer mt-1"
      >
        {expanded ? 'Weniger' : 'Mehr anzeigen'}
      </button>

      <div className="flex items-center gap-2 mt-3 flex-wrap">
        {profile.industry && (
          <span className="px-2 py-0.5 rounded text-xs bg-card-alt text-text-secondary">{profile.industry}</span>
        )}
        {profile.country && (
          <span className="px-2 py-0.5 rounded text-xs bg-card-alt text-text-secondary">{profile.country}</span>
        )}
        {profile.fullTimeEmployees && (
          <span className="px-2 py-0.5 rounded text-xs bg-card-alt text-text-secondary">
            {formatEmployees(profile.fullTimeEmployees)} Mitarbeiter
          </span>
        )}
        {profile.website && (
          <a href={profile.website} target="_blank" rel="noopener noreferrer"
            className="px-2 py-0.5 rounded text-xs bg-card-alt text-primary hover:text-primary/80 inline-flex items-center gap-1">
            Website <ExternalLink size={10} />
          </a>
        )}
      </div>

      <div className="flex items-center gap-4 mt-2 text-xs text-text-muted flex-wrap">
        {profile.trailingPE != null && (
          <span>P/E: <span className="font-mono text-text-secondary">{profile.trailingPE.toFixed(1)}</span></span>
        )}
        {profile.forwardPE != null && (
          <span>Fwd P/E: <span className="font-mono text-text-secondary">{profile.forwardPE.toFixed(1)}</span></span>
        )}
        {profile.dividendYield != null && (
          <span>Div. Yield: <span className="font-mono text-text-secondary">{(profile.dividendYield * 100).toFixed(2)}%</span></span>
        )}
        {profile.beta != null && (
          <span>Beta: <span className="font-mono text-text-secondary">{profile.beta.toFixed(2)}</span></span>
        )}
      </div>
    </div>
  )
}

export default function StockScoreCard({ ticker, onClose, onWatchlistChange }) {
  const { data, loading, error, refetch } = useApi(`/analysis/score/${ticker}`)
  const { data: profile } = useApi(`/stock/${ticker}/profile`)
  const { data: watchlist } = useApi('/analysis/watchlist')
  const [inWatchlist, setInWatchlist] = useState(false)
  const [addingToWl, setAddingToWl] = useState(false)
  const toast = useToast()

  useEffect(() => {
    if (watchlist && ticker) {
      const items = watchlist?.items || watchlist || []
      setInWatchlist(items.some((w) => w.ticker === ticker.toUpperCase()))
    }
  }, [watchlist, ticker])

  if (loading) {
    return (
      <div className="rounded-lg border border-border bg-card p-8">
        <div className="flex items-center gap-3 justify-center">
          <Loader2 size={22} className="animate-spin text-primary" />
          <span className="text-text-secondary">Analysiere <span className="font-mono text-primary">{ticker}</span> — 18 Kriterien werden geprüft...</span>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-lg border border-danger/30 bg-danger/10 p-6">
        <div className="flex items-center justify-between">
          <p className="text-danger text-sm">Fehler bei Analyse von {ticker}: {error}</p>
          {onClose && (
            <button onClick={onClose} className="text-danger/60 hover:text-danger ml-4">
              <X size={18} />
            </button>
          )}
        </div>
      </div>
    )
  }

  const { name, sector, industry, price, currency, market_cap, score, max_score, pct, rating, criteria, alerts, mansfield_rs, range_52w, breakout, signal, signal_label, setup_quality } = data

  // Group criteria
  const grouped = {}
  for (const c of criteria) {
    const g = c.group || 'Sonstige'
    if (!grouped[g]) grouped[g] = []
    grouped[g].push(c)
  }

  const formatMCap = (v) => {
    if (!v) return '–'
    if (v >= 1e12) return `${(v / 1e12).toFixed(1)}T`
    if (v >= 1e9) return `${(v / 1e9).toFixed(1)}B`
    return `${(v / 1e6).toFixed(0)}M`
  }

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      {/* Header */}
      <div className="p-5 border-b border-border">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1">
            <div className="flex items-center gap-3 flex-wrap">
              <span className="text-xl font-bold font-mono text-primary">{ticker}</span>
              <span className="text-lg text-text-primary">{name}</span>
            </div>
            <div className="flex items-center gap-3 mt-1.5 text-sm text-text-muted flex-wrap">
              {sector && <span>{sector}</span>}
              {industry && <><span className="text-border">|</span><span>{industry}</span></>}
              {price != null && <><span className="text-border">|</span><span className="font-mono">{price.toFixed(2)} {currency}</span></>}
              {market_cap && <><span className="text-border">|</span><span>MCap {formatMCap(market_cap)}</span></>}
            </div>
          </div>
          <div className="flex items-center gap-3 flex-shrink-0">
            <SignalBadge
              signal={signal}
              signalLabel={signal_label}
              setupQuality={setup_quality || rating}
              score={score}
              maxScore={max_score}
            />
            {inWatchlist ? (
              <span className="flex items-center gap-1 py-1.5 px-3 bg-success/15 text-success border border-success/30 rounded-lg text-xs">
                <Check size={13} />
                In Watchlist
              </span>
            ) : (
              <button
                onClick={async () => {
                  setAddingToWl(true)
                  try {
                    await apiPost('/analysis/watchlist', { ticker: ticker.toUpperCase(), name: name || ticker, sector: sector || null })
                    setInWatchlist(true)
                    toast('Zur Watchlist hinzugefügt', 'success')
                    onWatchlistChange?.()
                  } catch (e) {
                    toast('Fehler: ' + e.message, 'error')
                  } finally {
                    setAddingToWl(false)
                  }
                }}
                disabled={addingToWl}
                className="flex items-center gap-1 py-1.5 px-3 bg-primary/15 text-primary border border-primary/30 rounded-lg text-xs hover:bg-primary/25 transition-colors disabled:opacity-50"
              >
                {addingToWl ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
                Watchlist
              </button>
            )}
            {onClose && (
              <button onClick={onClose} className="text-text-muted hover:text-text-primary transition-colors" aria-label="Schliessen">
                <X size={20} />
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Company Description */}
      {profile?.description && (
        <div className="p-5 border-b border-border">
          <CompanyDescription profile={profile} />
        </div>
      )}

      {/* Alerts */}
      {alerts?.length > 0 && (
        <div className="p-5 border-b border-border">
          <AlertList alerts={alerts} />
        </div>
      )}


      {/* Failed criteria summary */}
      {(() => {
        const failed = criteria.filter((c) => c.passed === false)
        if (!failed.length) return null
        return (
          <div className="px-5 py-3 border-b border-border">
            <div className="flex items-center gap-2 mb-2">
              <XCircle size={14} className="text-danger" />
              <span className="text-xs font-medium text-text-secondary">{failed.length} Kriterien nicht erfüllt</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {failed.map((c) => (
                <span key={c.id} className="text-[11px] px-2 py-0.5 rounded bg-danger/10 text-danger border border-danger/20">
                  {c.name}
                </span>
              ))}
            </div>
          </div>
        )
      })()}

      {/* Criteria grouped */}
      <div className="p-5">
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {GROUP_ORDER.map((g) =>
            grouped[g] ? <GroupSection key={g} group={g} criteria={grouped[g]} /> : null
          )}
        </div>
      </div>

    </div>
  )
}
