/** Button-Primitive im Redesign-Look. variant: primary | secondary | ghost. */
const VARIANTS = {
  primary:
    'bg-primary-btn border border-primary-btn-border text-white font-semibold px-[14px] py-2 hover:bg-primary-btn-border',
  secondary:
    'bg-surface border border-border text-text-secondary px-[13px] py-2 hover:border-border-hover',
  ghost:
    'border border-transparent text-text-muted px-[13px] py-2 hover:text-text-primary hover:bg-hover',
}

export default function Button({ variant = 'secondary', icon: Icon, className = '', children, ...props }) {
  return (
    <button
      className={`inline-flex items-center gap-[7px] rounded-lg text-[12.5px] font-medium transition-colors ${VARIANTS[variant] || VARIANTS.secondary} ${className}`}
      {...props}
    >
      {Icon && <Icon size={15} />}
      {children}
    </button>
  )
}
