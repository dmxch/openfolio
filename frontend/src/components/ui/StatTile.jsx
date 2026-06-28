/**
 * Kennzahl-Kachel: Mono-Mikro-Label + grosse Zahl + optionale Delta-Zeile.
 * `tone` faerbt Wert + Sub (success/danger/warning/primary) — sonst Primaertext.
 */
const TONE = {
  success: 'text-success',
  danger: 'text-danger',
  warning: 'text-warning',
  primary: 'text-primary',
  bright: 'text-text-bright',
  default: 'text-text-primary',
}

export default function StatTile({ label, value, sub, tone = 'default', mono = true, subTone }) {
  const valueColor = TONE[tone] || TONE.default
  const subColor = TONE[subTone || tone] || 'text-text-muted'
  return (
    <div className="bg-card border border-border rounded-card p-[15px]">
      <div className="font-mono text-[10.5px] tracking-[0.06em] uppercase text-text-label mb-[7px]">
        {label}
      </div>
      <div className={`text-[22px] font-semibold tracking-[-0.01em] leading-none ${mono ? 'font-mono' : ''} ${valueColor}`}>
        {value}
      </div>
      {sub != null && sub !== '' && (
        <div className={`text-[11.5px] font-mono mt-[5px] ${subColor}`}>{sub}</div>
      )}
    </div>
  )
}
