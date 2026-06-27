import { useApi } from '../hooks/useApi'
import { formatCHF } from '../lib/format'
import { Scale, Loader2 } from 'lucide-react'

const CARD = "rounded-lg border border-white/[0.06] bg-card p-4 shadow-[0_1px_3px_rgba(0,0,0,0.3)]"

/**
 * Vermoegensbilanz — Aktiven (Wertschriften/Cash/Vorsorge/PE/Immobilien brutto)
 * minus Passiven (Hypothek) = Netto-Vermoegen. Bewusst KEIN eigener Riesen-Betrag:
 * die Netto-Summe == die KPI-Kachel "Gesamtvermoegen" oben; diese Karte liefert die
 * Aufschluesselung und vor allem die explizite Hypothek-Zeile, die die Kachel still
 * im Equity verrechnet.
 */
export default function NetWorthCard() {
  const { data, loading } = useApi('/analysis/net-worth')

  if (loading) {
    return (
      <div className={CARD}>
        <div className="text-center py-6"><Loader2 size={18} className="animate-spin text-text-muted mx-auto" /></div>
      </div>
    )
  }
  if (!data || data.net_worth_chf == null) return null

  const comps = data.components || []

  return (
    <div className={CARD}>
      <div className="flex items-center gap-2 mb-3">
        <Scale size={16} className="text-primary" />
        <h3 className="text-sm font-semibold text-text-primary">Vermögensbilanz</h3>
      </div>

      <div className="space-y-1.5">
        {comps.map((c) => (
          <div key={c.key} className="flex items-center justify-between text-sm">
            <span className="text-text-secondary">{c.label}</span>
            <span className={`tabular-nums ${c.kind === 'liability' ? 'text-danger' : 'text-text-primary'}`}>
              {formatCHF(c.value_chf)}
            </span>
          </div>
        ))}
        <div className="flex items-center justify-between pt-2 mt-1 border-t border-border/50">
          <span className="text-sm text-text-primary font-medium">Netto-Vermögen</span>
          <span className="text-base text-text-primary font-bold tabular-nums">{formatCHF(data.net_worth_chf)}</span>
        </div>
      </div>

      {data.has_real_estate && (
        <p className="text-[11px] text-text-muted mt-2.5">
          Immobilienwert = geschätzter Brutto-Marktwert (nicht Vermögenssteuerwert); Hypothek nach Amortisation.
        </p>
      )}
    </div>
  )
}
