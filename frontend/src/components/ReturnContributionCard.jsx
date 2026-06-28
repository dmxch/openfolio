import { useCallback, useEffect, useState } from 'react'
import { useApi } from '../hooks/useApi'
import { formatNumber, pnlColor } from '../lib/format'

// Karte "Rendite-Beitrag je Bucket" fuer die Performance-Seite.
//
// Zeigt pro USER-Bucket dessen Beitrag zur Gesamtrendite (in Prozentpunkten)
// als divergierenden Balken, der von einer zentralen Null-Linie ausgeht:
// positiv nach rechts (bg-success), negativ nach links (bg-danger).
//
// Berechnung (rein client-seitig, KEIN eigener Endpoint):
//   Beitrag_bucket [pp] = (bucket_value / total_value) * bucket_return_pct
// Die Balkenbreite ist relativ zum groessten |Beitrag| skaliert.
//
// Datenquellen (identisch zu BucketComparisonBar):
//   /portfolio/buckets                                        → Bucket-Liste
//   /portfolio/buckets/{id}/benchmark-comparison?period=ytd   → bucket_return_pct
//   /portfolio/buckets/{id}/summary                           → total_value_chf
//
// Sichtbar nur, wenn der User mind. 1 user-Bucket hat (sonst return null).

// Unsichtbarer Daten-Holer pro Bucket: haelt seine eigenen useApi-Hooks (damit
// keine Hook-Aufrufe in einer Render-Schleife stehen) und reicht die Rohwerte
// via onData nach oben. Rendert selbst nichts — die Aggregation/Anzeige sitzt
// im Eltern-Component, weil sie Total + max(|Beitrag|) ueber alle Buckets braucht.
function ContributionCell({ bucket, onData }) {
  const { data: comp } = useApi(
    `/portfolio/buckets/${bucket.id}/benchmark-comparison?period=ytd`,
  )
  const { data: summary } = useApi(`/portfolio/buckets/${bucket.id}/summary`)

  // comp/summary aendern ihre Identitaet nur beim Fetch-Abschluss → kein
  // Render-Loop (onData ist stabil via useCallback im Eltern-Component).
  useEffect(() => {
    onData?.(bucket.id, { comp, summary })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bucket.id, comp, summary])

  return null
}

// Beitrag in Prozentpunkten formatieren: Vorzeichen + 2 Nachkommastellen + "pp".
// Negative bekommen ihr Minus aus formatNumber, positive ein explizites "+".
function formatPP(value) {
  if (value == null) return '–'
  const sign = value > 0 ? '+' : ''
  return `${sign}${formatNumber(value, 2)} pp`
}

export default function ReturnContributionCard() {
  const { data: bucketsData, loading: bucketsLoading } = useApi('/portfolio/buckets')

  // Rohdaten je Bucket (von den Zellen hochgereicht).
  const [cellData, setCellData] = useState({})
  const handleCellData = useCallback((id, payload) => {
    setCellData((prev) => ({ ...prev, [id]: payload }))
  }, [])

  if (bucketsLoading) {
    return (
      <div className="rounded-card border border-border bg-card p-[18px] animate-pulse">
        <div className="h-4 bg-hover rounded w-44 mb-2" />
        <div className="h-3 bg-hover rounded w-32 mb-5" />
        <div className="flex flex-col gap-3">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="flex items-center gap-2.5">
              <div className="h-3 w-[78px] shrink-0 bg-hover rounded" />
              <div className="h-[18px] flex-1 bg-hover rounded" />
              <div className="h-3 w-[64px] shrink-0 bg-hover rounded" />
            </div>
          ))}
        </div>
      </div>
    )
  }

  // Nur USER-Buckets (nicht-geloescht) — System-Rollen (real_estate,
  // private_equity, pension, liquid_default) tragen hier nicht bei.
  // Spiegelt die kind === 'user'-Filterung aus BucketComparisonBar.
  const userBuckets = (bucketsData?.buckets || []).filter(
    (b) => b.kind === 'user' && !b.deleted_at,
  )

  // Ohne user-Buckets ist die Beitrags-Aufteilung bedeutungslos.
  if (userBuckets.length === 0) return null

  // Zeilen-Rohwerte je Bucket aus den hochgereichten Zell-Daten ableiten.
  const baseRows = userBuckets.map((b) => {
    const cell = cellData[b.id]
    const value = cell?.summary?.total_value_chf ?? null
    const ret = cell?.comp?.bucket_return_pct ?? null
    return { bucket: b, value, ret }
  })

  // Nenner = Summe der Bucket-Werte (nur Buckets mit bekanntem Wert).
  const total = baseRows.reduce((sum, r) => sum + (r.value ?? 0), 0)

  const rows = baseRows.map((r) => {
    const contrib =
      r.value != null && r.ret != null && total > 0
        ? (r.value / total) * r.ret
        : null
    return { ...r, contrib }
  })

  // Skalierung der Balken relativ zum groessten Betrag.
  const maxAbs = rows.reduce(
    (m, r) => (r.contrib != null ? Math.max(m, Math.abs(r.contrib)) : m),
    0,
  )

  return (
    <div className="rounded-card border border-border bg-card p-[18px]">
      <h3 className="text-sm font-semibold text-text-primary mb-1">
        Rendite-Beitrag je Bucket
      </h3>
      <p className="text-xs text-text-muted mb-4">
        Beitrag zur Gesamtrendite · YTD
      </p>

      <div className="flex flex-col gap-[13px]">
        {rows.map(({ bucket, contrib }) => {
          // Halbe Track-Breite (max. 50 %) je nach Betrag relativ zum Maximum.
          const halfPct =
            contrib != null && maxAbs > 0
              ? (Math.abs(contrib) / maxAbs) * 50
              : 0
          const positive = contrib != null && contrib > 0
          const negative = contrib != null && contrib < 0

          return (
            <div key={bucket.id} className="flex items-center gap-2.5">
              <span
                className="w-[78px] shrink-0 text-[12.5px] text-text-secondary truncate"
                title={bucket.name}
              >
                {bucket.name}
              </span>

              <div className="relative flex-1 h-[18px]">
                {/* Senkrechte Null-Linie in der Mitte */}
                <div className="absolute top-0 bottom-0 left-1/2 w-px bg-border-hover" />
                {positive && (
                  <div
                    className="absolute top-0 h-[18px] rounded-[3px] bg-success"
                    style={{ left: '50%', width: `${halfPct}%` }}
                  />
                )}
                {negative && (
                  <div
                    className="absolute top-0 h-[18px] rounded-[3px] bg-danger"
                    style={{ right: '50%', width: `${halfPct}%` }}
                  />
                )}
              </div>

              <span
                className={`w-[64px] shrink-0 text-right font-mono text-[12.5px] font-semibold tabular-nums ${pnlColor(
                  contrib,
                )}`}
              >
                {formatPP(contrib)}
              </span>
            </div>
          )
        })}
      </div>

      {/* Unsichtbare Daten-Holer: ein Hook-Set pro Bucket, ausserhalb der
          Render-Schleife der Anzeige. Melden ihre Rohwerte nach oben. */}
      {userBuckets.map((b) => (
        <ContributionCell key={b.id} bucket={b} onData={handleCellData} />
      ))}
    </div>
  )
}
