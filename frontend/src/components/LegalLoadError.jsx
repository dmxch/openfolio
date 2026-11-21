// Gemeinsamer Hinweis fuer einen fehlgeschlagenen Abruf der Anmeldedaten.
export default function LegalLoadError({ onRetry, className = '' }) {
  return (
    <div role="alert" className={`flex items-center justify-between gap-3 rounded-lg bg-danger/10 border border-danger/30 p-3 text-sm text-danger ${className}`}>
      <span>Die Angaben dieser Instanz konnten nicht geladen werden.</span>
      <button type="button" onClick={onRetry} className="shrink-0 underline hover:no-underline">Erneut laden</button>
    </div>
  )
}
