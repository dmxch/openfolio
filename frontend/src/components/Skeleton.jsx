export default function Skeleton({ className = 'h-28' }) {
  return (
    <div role="status" aria-live="polite" aria-label="Wird geladen..." className={`rounded-card border border-border-2 bg-card-2 animate-pulse ${className}`} />
  )
}
