import { useState, useEffect, useRef } from 'react'
import useFocusTrap from '../../hooks/useFocusTrap'
import useScrollLock from '../../hooks/useScrollLock'
import useEscClose from '../../hooks/useEscClose'
import { useToast } from '../../components/Toast'
import { Copy, Trash2, Plus, AlertCircle, KeyRound, AlertTriangle, X, Loader2 } from 'lucide-react'
import { authFetch, API_BASE, Section, Toggle } from './shared'
import Button from '../../components/ui/Button'
import { Badge } from '../../components/ui/Badge'
import { formatDate } from '../../lib/format'

function RevokeConfirm({ tokenName, onConfirm, onCancel }) {
  const [revoking, setRevoking] = useState(false)
  useEscClose(onCancel)
  useScrollLock(true)
  const trapRef = useFocusTrap(true)

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-[#04070c]/[0.72] backdrop-blur-sm" role="presentation" onClick={onCancel}>
      <div ref={trapRef} role="dialog" aria-modal="true" aria-label="Token widerrufen" className="bg-modal border border-danger/40 rounded-[14px] shadow-2xl p-6 max-w-sm w-full mx-4" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start gap-3 mb-4">
          <div className="p-2 rounded-full bg-danger/10">
            <AlertTriangle size={20} className="text-danger" />
          </div>
          <div className="flex-1">
            <h3 className="text-sm font-semibold text-text-primary">Token widerrufen?</h3>
            <p className="text-sm text-text-secondary mt-1">
              <span className="font-medium">{tokenName}</span> wird sofort ungültig. Externe Konsumenten verlieren den Zugriff.
            </p>
          </div>
          <button onClick={onCancel} className="text-text-muted hover:text-text-primary" aria-label="Schliessen">
            <X size={16} />
          </button>
        </div>
        <div className="flex gap-2 justify-end">
          <Button variant="secondary" onClick={onCancel} disabled={revoking}>Abbrechen</Button>
          <button
            onClick={async () => { setRevoking(true); try { await onConfirm() } finally { setRevoking(false) } }}
            disabled={revoking}
            className="inline-flex items-center gap-2 px-4 py-2 text-[12.5px] rounded-lg bg-danger text-white hover:bg-danger/90 transition-colors font-medium disabled:opacity-40"
          >
            {revoking && <Loader2 size={14} className="animate-spin" />}
            Widerrufen
          </button>
        </div>
      </div>
    </div>
  )
}

export default function ApiTokensTab() {
  const addToast = useToast()
  const [tokens, setTokens] = useState([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [name, setName] = useState('')
  const [expiresInDays, setExpiresInDays] = useState('')
  const [writeAccess, setWriteAccess] = useState(false)
  const [creating, setCreating] = useState(false)
  const [newToken, setNewToken] = useState(null)
  const [revokeTarget, setRevokeTarget] = useState(null)

  // Aktuelle Instanz-URL (z.B. https://openfolio.cc) — dient als Base URL
  // fuer alle External-API-Aufrufe. window.location.origin ist immer korrekt,
  // egal ob Self-Hosted auf localhost, LAN oder oeffentlicher Domain.
  const externalApiBase = `${window.location.origin}/api/v1/external`

  const createTrapRef = useFocusTrap(showCreate)
  const newTokenTrapRef = useFocusTrap(!!newToken)
  useScrollLock(showCreate || !!newToken)

  useEffect(() => {
    loadTokens()
  }, [])

  async function loadTokens() {
    setLoading(true)
    try {
      const res = await authFetch(`${API_BASE}/settings/api-tokens`)
      if (res.ok) {
        const data = await res.json()
        setTokens(data)
      }
    } catch (e) {
      addToast('Tokens konnten nicht geladen werden', 'error')
    } finally {
      setLoading(false)
    }
  }

  async function handleCreate(e) {
    e.preventDefault()
    if (!name.trim()) {
      addToast('Bitte einen Namen vergeben', 'error')
      return
    }
    setCreating(true)
    try {
      const body = { name: name.trim(), write_access: writeAccess }
      if (expiresInDays && parseInt(expiresInDays) > 0) {
        body.expires_in_days = parseInt(expiresInDays)
      }
      const res = await authFetch(`${API_BASE}/settings/api-tokens`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || 'Erstellung fehlgeschlagen')
      }
      const data = await res.json()
      setNewToken(data)
      setShowCreate(false)
      setName('')
      setExpiresInDays('')
      setWriteAccess(false)
      await loadTokens()
    } catch (err) {
      addToast(err.message, 'error')
    } finally {
      setCreating(false)
    }
  }

  async function handleRevoke(tokenId) {
    try {
      const res = await authFetch(`${API_BASE}/settings/api-tokens/${tokenId}`, { method: 'DELETE' })
      if (!res.ok && res.status !== 204) {
        throw new Error('Widerruf fehlgeschlagen')
      }
      addToast('Token widerrufen', 'success')
      setRevokeTarget(null)
      await loadTokens()
    } catch (err) {
      addToast(err.message, 'error')
    }
  }

  async function handleCopy(text) {
    try {
      await navigator.clipboard.writeText(text)
      addToast('In Zwischenablage kopiert', 'success')
    } catch {
      addToast('Kopieren fehlgeschlagen', 'error')
    }
  }

  if (loading) return <p className="text-sm text-text-muted">Lade...</p>

  return (
    <div className="space-y-[18px]">
      <Section title="Externe API-Tokens">
        <p className="text-sm text-text-secondary mb-3">
          API-Tokens erlauben externen Konsumenten (z.B. einer anderen Claude-Code-Instanz, eigenen Skripten)
          den read-only Zugriff auf dein Portfolio, deine Performance, Immobilien, Vorsorge und die
          Screening-Ergebnisse über eine versionierte REST-API.
        </p>

        <div className="mb-4 p-3 bg-card-2 border border-border rounded-lg">
          <div className="font-mono text-[10.5px] tracking-[0.06em] uppercase text-text-label mb-1.5">Base URL für diese Instanz</div>
          <div className="flex items-center gap-2">
            <code className="flex-1 text-sm text-text-primary font-mono break-all">
              {externalApiBase}
            </code>
            <Button
              variant="secondary"
              icon={Copy}
              onClick={() => handleCopy(externalApiBase)}
              className="shrink-0"
              aria-label="Base URL kopieren"
              title="Base URL kopieren"
            >
              Kopieren
            </Button>
          </div>
        </div>

        <p className="text-xs text-text-secondary mb-4">
          Authentisiere dich mit dem Header <code className="bg-card-2 px-1 py-0.5 rounded font-mono">X-API-Key: ofk_...</code>.
          Tokens sind read-only, können jederzeit widerrufen werden und unterliegen einem strengeren Rate-Limit (30/min).
        </p>

        <div className="mb-4">
          <Button variant="primary" icon={Plus} onClick={() => setShowCreate(true)}>
            Token erzeugen
          </Button>
        </div>

        {tokens.length === 0 ? (
          <p className="text-sm text-text-muted italic">Keine Tokens vorhanden.</p>
        ) : (
          <div className="space-y-2">
            {tokens.map((t) => (
              <div
                key={t.id}
                className="flex items-center gap-3 bg-surface border border-border rounded-lg px-3 py-2.5"
              >
                <KeyRound size={16} className="text-text-muted shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-text-primary font-medium truncate flex items-center gap-1.5">
                    <span className="truncate">{t.name}</span>
                    <Badge color="#7a8698" bg="rgba(122,134,152,0.13)" className="shrink-0 uppercase tracking-wide">Lesen</Badge>
                    {(t.scopes || []).includes('write') && (
                      <Badge color="#5b8def" bg="rgba(91,141,239,0.15)" border="rgba(91,141,239,0.4)" className="shrink-0 uppercase tracking-wide">Schreiben</Badge>
                    )}
                  </div>
                  <div className="text-xs text-text-muted font-mono">{t.prefix}...</div>
                </div>
                <div className="text-xs text-text-muted text-right shrink-0">
                  <div>Erstellt: {t.created_at ? formatDate(t.created_at) : '-'}</div>
                  <div>
                    {t.last_used_at ? `Zuletzt: ${formatDate(t.last_used_at)}` : 'Noch nie genutzt'}
                  </div>
                  {t.expires_at && <div>Läuft ab: {formatDate(t.expires_at)}</div>}
                </div>
                <button
                  type="button"
                  onClick={() => setRevokeTarget(t)}
                  className="text-danger hover:text-danger/80 p-2"
                  aria-label={`Token ${t.name} widerrufen`}
                  title="Widerrufen"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title="Beispiel-Verwendung">
        <p className="text-sm text-text-secondary mb-2">
          Nach dem Erstellen eines Tokens kannst du ihn so einsetzen:
        </p>
        <div className="relative">
          <pre className="bg-card-2 border border-border rounded-lg p-3 pr-12 text-xs text-text-primary overflow-x-auto font-mono">
{`curl -H "X-API-Key: ofk_..." \\
  ${externalApiBase}/portfolio/summary`}
          </pre>
          <button
            type="button"
            onClick={() => handleCopy(`curl -H "X-API-Key: ofk_..." ${externalApiBase}/portfolio/summary`)}
            className="absolute top-2 right-2 text-text-muted hover:text-text-primary p-1.5 rounded hover:bg-hover"
            aria-label="Beispiel kopieren"
            title="Beispiel kopieren"
          >
            <Copy size={12} />
          </button>
        </div>
        <p className="text-xs text-text-muted mt-3">
          Verfuegbare Endpoints: <code className="font-mono">/portfolio/summary</code>, <code className="font-mono">/positions</code>,
          <code className="font-mono"> /performance/history</code>, <code className="font-mono">/performance/total-return</code>,
          <code className="font-mono"> /analysis/score/{'{ticker}'}</code>, <code className="font-mono">/immobilien</code>,
          <code className="font-mono"> /vorsorge</code>, <code className="font-mono">/screening/latest</code> u.a.
          Volle Liste und Beispiel-Responses in{' '}
          <a
            href="https://github.com/dmxch/openfolio/blob/main/docs/EXTERNAL_API.md"
            target="_blank"
            rel="noopener noreferrer"
            className="text-link hover:underline"
          >
            docs/EXTERNAL_API.md
          </a>.
        </p>
      </Section>

      {/* Create Modal */}
      {showCreate && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-[#04070c]/[0.72] backdrop-blur-sm p-4">
          <div
            ref={createTrapRef}
            className="bg-modal border border-border-hover rounded-[14px] shadow-2xl p-6 max-w-md w-full"
            role="dialog"
            aria-modal="true"
            aria-labelledby="create-token-title"
          >
            <h3 id="create-token-title" className="text-base font-semibold text-text-primary mb-4">
              Neuen API-Token erstellen
            </h3>
            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label htmlFor="token-name" className="block text-xs font-medium text-text-muted mb-1">
                  Name (z.B. "Claude Code Laptop")
                </label>
                <input
                  id="token-name"
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  maxLength={100}
                  required
                  autoFocus
                  className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors"
                />
              </div>
              <div>
                <label htmlFor="token-expires" className="block text-xs font-medium text-text-muted mb-1">
                  Ablauf in Tagen (optional)
                </label>
                <input
                  id="token-expires"
                  type="number"
                  min="1"
                  max="3650"
                  value={expiresInDays}
                  onChange={(e) => setExpiresInDays(e.target.value)}
                  placeholder="Leer lassen für kein Ablaufdatum"
                  className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors"
                />
              </div>
              <div className="border border-border rounded-lg p-3 bg-card-2 space-y-3">
                <div className="text-sm font-medium text-text-primary">Berechtigungen</div>
                <div className="flex items-start gap-3">
                  <Toggle checked disabled ariaLabel="Lesen (immer aktiv)" onChange={() => {}} />
                  <div className="text-sm text-text-secondary">
                    <span className="font-medium text-text-primary">Lesen</span> (immer aktiv)
                    <span className="block text-xs text-text-muted">Portfolio, Watchlist, Performance, Screening.</span>
                  </div>
                </div>
                <div className="flex items-start gap-3">
                  <Toggle
                    checked={writeAccess}
                    onChange={(v) => setWriteAccess(v)}
                    ariaLabel="Schreiben — Notizen und Alarme"
                  />
                  <div className="text-sm text-text-secondary">
                    <span className="font-medium text-text-primary">Schreiben</span> — Notizen und Alarme
                    <span className="block text-xs text-text-muted">
                      Erlaubt externen Clients (z.B. Claude Code), Watchlist-Notizen zu setzen sowie
                      Preis-Alarme zu erstellen, zu aktualisieren und zu löschen. Notizen werden für
                      diesen Token auch lesbar zurückgegeben.
                    </span>
                  </div>
                </div>
              </div>
              <div className="flex gap-2 justify-end items-center">
                <button
                  type="button"
                  onClick={() => { setShowCreate(false); setName(''); setExpiresInDays(''); setWriteAccess(false) }}
                  className="text-text-secondary hover:text-text-primary px-4 py-2 text-sm"
                >
                  Abbrechen
                </button>
                <Button variant="primary" type="submit" disabled={creating || !name.trim()}>
                  {creating ? 'Erstelle...' : 'Erstellen'}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Plaintext-Token-Anzeige */}
      {newToken && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-[#04070c]/[0.72] backdrop-blur-sm p-4">
          <div
            ref={newTokenTrapRef}
            className="bg-modal border border-border-hover rounded-[14px] shadow-2xl p-6 max-w-xl w-full"
            role="dialog"
            aria-modal="true"
            aria-labelledby="new-token-title"
          >
            <h3 id="new-token-title" className="text-base font-semibold text-text-primary mb-3">
              Token erstellt
            </h3>
            <div className="flex items-start gap-2 mb-4 p-3 bg-warning/10 border border-warning/30 rounded-lg">
              <AlertCircle size={16} className="text-warning shrink-0 mt-0.5" />
              <p className="text-xs text-warning">
                Dieser Token wird nur <strong>einmal</strong> angezeigt. Kopiere ihn jetzt und bewahre ihn sicher auf
                (z.B. in einem Passwort-Manager). Du kannst ihn später nicht mehr einsehen.
              </p>
            </div>
            <div className="mb-4">
              <label className="block text-xs font-medium text-text-muted mb-1">Token ({newToken.name})</label>
              <div className="flex items-center gap-2">
                <code className="flex-1 bg-card-2 border border-border rounded-lg px-3 py-2 text-xs text-text-primary font-mono break-all">
                  {newToken.token}
                </code>
                <Button
                  variant="primary"
                  icon={Copy}
                  onClick={() => handleCopy(newToken.token)}
                  className="shrink-0"
                  aria-label="Token in Zwischenablage kopieren"
                >
                  Kopieren
                </Button>
              </div>
            </div>
            <div className="flex justify-end">
              <Button variant="secondary" onClick={() => setNewToken(null)}>Schliessen</Button>
            </div>
          </div>
        </div>
      )}
      {revokeTarget && (
        <RevokeConfirm
          tokenName={revokeTarget.name}
          onConfirm={() => handleRevoke(revokeTarget.id)}
          onCancel={() => setRevokeTarget(null)}
        />
      )}
    </div>
  )
}
