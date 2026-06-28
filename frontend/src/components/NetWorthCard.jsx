import { useApi } from '../hooks/useApi'
import { formatCHF } from '../lib/format'
import { Scale, Loader2 } from 'lucide-react'

/**
 * Vermoegensbilanz — Aktiven (Wertschriften/Cash/Vorsorge/PE/Immobilien brutto)
 * minus Passiven (Hypothek) = Netto-Vermoegen. Bewusst KEIN eigener Riesen-Betrag:
 * die Netto-Summe == die Hero-Kachel "Netto-Vermoegen" oben; diese Karte liefert die
 * Aufschluesselung und vor allem die explizite Hypothek-Zeile.
 */
export default function NetWorthCard() {
  const { data, loading } = useApi('/analysis/net-worth')

  if (loading) {
    return (
      <div className="bg-card border border-border rounded-card">
        <div className="text-center py-10"><Loader2 size={18} className="animate-spin text-text-muted mx-auto" /></div>
      </div>
    )
  }
  if (!data || data.net_worth_chf == null) return null

  const comps = data.components || []

  return (
    <div className="bg-card border border-border rounded-card overflow-hidden">
      <div className="px-[18px] py-4 border-b border-border-2 flex items-center gap-2.5">
        <Scale size={16} className="text-primary" />
        <h3 className="text-sm font-semibold text-text-primary">Vermögensbilanz</h3>
      </div>

      <div className="p-[18px]">
        <div className="space-y-1.5">
          {comps.map((c) => (
            <div key={c.key} className="flex items-center justify-between text-sm">
              <span className="text-text-secondary">{c.label}</span>
              <span className={`font-mono tabular-nums ${c.kind === 'liability' ? 'text-danger' : 'text-text-primary'}`}>
                {formatCHF(c.value_chf)}
              </span>
            </div>
          ))}
          <div className="flex items-center justify-between pt-2.5 mt-1 border-t border-border-2">
            <span className="text-sm text-text-primary font-medium">Netto-Vermögen</span>
            <span className="text-base text-text-primary font-mono font-semibold tabular-nums">{formatCHF(data.net_worth_chf)}</span>
          </div>
        </div>

        {data.has_real_estate && (
          <p className="text-[11px] text-text-muted mt-3">
            Immobilienwert = geschätzter Brutto-Marktwert (nicht Vermögenssteuerwert); Hypothek nach Amortisation.
          </p>
        )}
      </div>
    </div>
  )
}
