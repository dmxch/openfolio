import { useState, useEffect } from 'react'
import { Tag, Loader2, Check, AlertTriangle, HelpCircle, X } from 'lucide-react'
import { useToast } from './Toast'
import { authFetch } from '../hooks/useApi'
import { formatCHF } from '../lib/format'
import useScrollLock from '../hooks/useScrollLock'
import useFocusTrap from '../hooks/useFocusTrap'

const INPUT = 'bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-primary/50 focus:border-primary'

export default function PositionTypeWizard({ onClose, onSaved }) {
  useScrollLock(true)
  const trapRef = useFocusTrap(true)
  const [positions, setPositions] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState({}) // ticker -> 'core' | 'satellite' | ''
  const [showInfo, setShowInfo] = useState(false)
  const toast = useToast()

  useEffect(() => {
    const load = async () => {
      try {
        const res = await authFetch('/api/portfolio/positions-without-type')
        if (res.ok) {
          const data = await res.json()
          setPositions(data)
          const initial = {}
          data.forEach((p) => { initial[p.ticker] = '' })
          setForm(initial)
        }
      } catch {}
      setLoading(false)
    }
    load()
  }, [])

  const setType = (ticker, type) => {
    setForm(prev => ({ ...prev, [ticker]: type }))
  }

  const allFilled = positions.every((p) => form[p.ticker] === 'core' || form[p.ticker] === 'satellite')

  const handleSave = async () => {
    setSaving(true)
    try {
      const items = positions.map((p) => ({
        ticker: p.ticker,
        position_type: form[p.ticker],
      }))
      const res = await authFetch('/api/portfolio/position-type/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ items }),
      })
      if (!res.ok) {
        const data = await res.json()
        throw new Error(data.detail || 'Fehler beim Speichern')
      }
      toast('Positions-Typ für alle Positionen gesetzt', 'success')
      onSaved?.()
      onClose()
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
        <div className="bg-card border border-border rounded-xl shadow-2xl p-12">
          <Loader2 size={24} className="animate-spin text-primary mx-auto" />
        </div>
      </div>
    )
  }

  if (!positions.length) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div
        ref={trapRef}
        role="dialog"
        aria-modal="true"
        aria-label="Positions-Typ festlegen"
        className="bg-card border border-border rounded-xl shadow-2xl w-full max-w-3xl mx-4 max-h-[90vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-6 py-5 border-b border-border">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-primary/15 flex items-center justify-center">
              <Tag size={20} className="text-primary" />
            </div>
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-bold text-text-primary">Positions-Typ festlegen</h2>
                <button
                  onClick={() => setShowInfo(!showInfo)}
                  className="w-5 h-5 rounded-full bg-card-alt text-text-muted flex items-center justify-center hover:text-primary transition-colors"
                  aria-label="Was bedeutet Core und Satellite?"
                >
                  <HelpCircle size={14} />
                </button>
              </div>
              <p className="text-sm text-text-muted">
                Core = langfristig, fundamentaler Verkaufstrigger. Satellite = taktisch, technischer Stop-Loss.
              </p>
            </div>
          </div>
        </div>

        {/* Info Panel */}
        {showInfo && (
          <div className="px-6 py-4 border-b border-border bg-card-alt/30">
            <div className="flex justify-between items-start mb-3">
              <h3 className="font-semibold text-sm text-text-primary">Was bedeutet Core und Satellite?</h3>
              <button onClick={() => setShowInfo(false)} className="text-text-muted hover:text-text-primary transition-colors" aria-label="Schliessen">
                <X size={16} />
              </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
              <div className="bg-primary/5 border border-primary/20 rounded-lg p-3">
                <span className="text-sm font-semibold text-primary">Core (Ziel: 70%)</span>
                <p className="text-xs text-text-secondary mt-1">
                  Langfristige Qualitätsaktien und breite ETFs. Unternehmen mit starkem
                  Geschäftsmodell, stabilem Cashflow und Pricing Power. Verkauf nur wenn
                  die fundamentale These gebrochen ist — nicht wegen Kursrückgängen.
                </p>
                <p className="text-xs text-text-muted mt-2">Stop-Loss: Optional. Review: Quartalsweise.</p>
              </div>

              <div className="bg-warning/5 border border-warning/20 rounded-lg p-3">
                <span className="text-sm font-semibold text-warning">Satellite (Ziel: 30%)</span>
                <p className="text-xs text-text-secondary mt-1">
                  Taktische Breakout-Trades mit engem Stop-Loss. Kürzere Haltedauer,
                  höheres Risiko, höheres Renditepotenzial. Technischer Stop-Loss ist
                  Pflicht (5–12% unter Einstieg).
                </p>
                <p className="text-xs text-text-muted mt-2">Stop-Loss: Pflicht. Review: Wöchentlich.</p>
              </div>
            </div>

            <p className="text-xs text-text-muted">
              Nicht sicher? Wähle <b className="text-text-secondary">Core</b> als Standard. Du kannst den Typ jederzeit im Portfolio ändern.
            </p>
          </div>
        )}

        {/* Table */}
        <div className="flex-1 overflow-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-text-muted bg-card-alt/30">
                <th className="text-left p-3 font-medium">Ticker</th>
                <th className="text-left p-3 font-medium">Name</th>
                <th className="text-right p-3 font-medium">Stück</th>
                <th className="text-right p-3 font-medium">Wert CHF</th>
                <th className="p-3 font-medium text-center">Typ</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => (
                <tr key={p.ticker} className="border-b border-border/50 hover:bg-card-alt/50 transition-colors">
                  <td className="p-3 font-mono text-primary font-medium">{p.ticker}</td>
                  <td className="p-3 text-text-primary">{p.name}</td>
                  <td className="p-3 text-right text-text-secondary tabular-nums">{p.shares}</td>
                  <td className="p-3 text-right text-text-secondary tabular-nums">{p.market_value_chf > 0 ? formatCHF(p.market_value_chf) : '—'}</td>
                  <td className="p-3">
                    <div className="flex gap-2 justify-center">
                      <button
                        onClick={() => setType(p.ticker, 'core')}
                        title="Langfristige Qualitätsposition — Stop-Loss optional"
                        className={`px-3 py-1 rounded text-xs font-medium border transition-colors ${
                          form[p.ticker] === 'core'
                            ? 'bg-primary text-white border-primary'
                            : 'border-border text-text-muted hover:border-primary hover:text-primary'
                        }`}
                      >
                        Core
                      </button>
                      <button
                        onClick={() => setType(p.ticker, 'satellite')}
                        title="Taktischer Trade — Stop-Loss Pflicht"
                        className={`px-3 py-1 rounded text-xs font-medium border transition-colors ${
                          form[p.ticker] === 'satellite'
                            ? 'bg-warning text-white border-warning'
                            : 'border-border text-text-muted hover:border-warning hover:text-warning'
                        }`}
                      >
                        Satellite
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-border">
          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm rounded-lg border border-border text-text-secondary hover:bg-card-alt transition-colors"
            >
              Später
            </button>
            <span className="text-xs text-text-muted hidden sm:inline">— Du kannst den Typ jederzeit im Portfolio ändern</span>
          </div>
          <button
            onClick={handleSave}
            disabled={saving || !allFilled}
            className="px-4 py-2 text-sm rounded-lg font-medium bg-primary text-white hover:bg-primary/80 transition-colors disabled:opacity-40 flex items-center gap-2"
          >
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
            Alle speichern
          </button>
        </div>
      </div>
    </div>
  )
}
