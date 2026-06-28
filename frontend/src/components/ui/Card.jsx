/**
 * Standard-Karte im Redesign-Look: bg-card, 1px border, radius 11px.
 * `as` erlaubt z.B. <Card as="button"> fuer klickbare Karten.
 */
export default function Card({ as: Tag = 'div', className = '', children, ...props }) {
  return (
    <Tag className={`bg-card border border-border rounded-card ${className}`} {...props}>
      {children}
    </Tag>
  )
}

/** Mono-Mikro-Label (uppercase, letter-spacing) wie in allen Karten-Headern. */
export function CardLabel({ className = '', children }) {
  return (
    <div className={`font-mono text-[10.5px] tracking-[0.06em] uppercase text-text-label ${className}`}>
      {children}
    </div>
  )
}

/** Karten-Titel (14px/600) + optionaler Untertitel. */
export function CardTitle({ title, subtitle, right, className = '' }) {
  return (
    <div className={`flex items-start justify-between ${className}`}>
      <div>
        <div className="text-sm font-semibold text-text-primary">{title}</div>
        {subtitle && <div className="text-xs text-text-muted mt-0.5">{subtitle}</div>}
      </div>
      {right}
    </div>
  )
}
