import { Loader2 } from 'lucide-react'

export default function LoadingSpinner({ size = 24, text, className = '' }) {
  return (
    <div className={`flex items-center justify-center gap-2 ${className}`} role="status" aria-live="polite">
      <Loader2 size={size} className="animate-spin text-text-muted" />
      {text && <span className="text-text-muted text-sm">{text}</span>}
    </div>
  )
}
