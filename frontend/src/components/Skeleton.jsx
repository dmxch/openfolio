export default function Skeleton({ className = 'h-28' }) {
  return (
    <div role="status" aria-live="polite" aria-label="Wird geladen..." className={`rounded-lg border border-border bg-card animate-pulse ${className}`} />
  )
}
