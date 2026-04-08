import { useState, useEffect, useRef } from 'react'
import useFocusTrap from '../../hooks/useFocusTrap'
import useScrollLock from '../../hooks/useScrollLock'
import { useToast } from '../../components/Toast'
import { Copy, Trash2, Plus, AlertCircle, KeyRound } from 'lucide-react'
import { authFetch, API_BASE, Section } from './shared'
import { formatDate } from '../../lib/format'

export default function ApiTokensTab() {
  const addToast = useToast()
  const [tokens, setTokens] = useState([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [name, setName] = useState('')
  const [expiresInDays, setExpiresInDays] = useState('')
  const [creating, setCreating] = useState(false)
  const [newToken, setNewToken] = useState(null)

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
      const body = { name: name.trim() }
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
      await loadTokens()
    } catch (err) {
      addToast(err.message, 'error')
    } finally {
      setCreating(false)
    }
  }

  async function handleRevoke(tokenId, tokenName) {
    if (!window.confirm(`Token "${tokenName}" wirklich widerrufen? Externe Konsumenten verlieren sofort den Zugriff.`)) {
      return
    }
    try {
      const res = await authFetch(`${API_BASE}/settings/api-tokens/${tokenId}`, { method: 'DELETE' })
      if (!res.ok && res.status !== 204) {
        throw new Error('Widerruf fehlgeschlagen')
      }
      addToast('Token widerrufen', 'success')
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
    <div className="space-y-6 max-w-3xl">
      <Section title="Externe API-Tokens">
        <p className="text-sm text-text-secondary mb-3">
          API-Tokens erlauben externen Konsumenten (z.B. einer anderen Claude-Code-Instanz, eigenen Skripten)
          den read-only Zugriff auf dein Portfolio, deine Performance und die Screening-Ergebnisse uber die
          versionierte REST-API unter <code className="bg-body px-1 py-0.5 rounded text-xs">/api/v1/external</code>.
        </p>
        <p className="text-xs text-text-secondary mb-4">
          Authentisiere dich mit dem Header <code className="bg-body px-1 py-0.5 rounded">X-API-Key: ofk_...</code>.
          Tokens sind read-only, koennen jederzeit widerrufen werden und unterliegen einem strengeren Rate-Limit (30/min).
        </p>

        <div className="mb-4">
          <button
            type="button"
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-1.5 bg-primary hover:bg-primary/90 text-white rounded-lg px-4 py-2 text-sm"
          >
            <Plus size={14} />
            Neuen Token erstellen
          </button>
        </div>

        {tokens.length === 0 ? (
          <p className="text-sm text-text-muted italic">Keine Tokens vorhanden.</p>
        ) : (
          <div className="space-y-2">
            {tokens.map((t) => (
              <div
                key={t.id}
                className="flex items-center gap-3 bg-body border border-border rounded-lg px-3 py-2"
              >
                <KeyRound size={16} className="text-text-muted shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-text-primary font-medium truncate">{t.name}</div>
                  <div className="text-xs text-text-muted font-mono">{t.prefix}...</div>
                </div>
                <div className="text-xs text-text-muted text-right shrink-0">
                  <div>Erstellt: {t.created_at ? formatDate(t.created_at) : '-'}</div>
                  <div>
                    {t.last_used_at ? `Zuletzt: ${formatDate(t.last_used_at)}` : 'Noch nie genutzt'}
                  </div>
                  {t.expires_at && <div>Laeuft ab: {formatDate(t.expires_at)}</div>}
                </div>
                <button
                  type="button"
                  onClick={() => handleRevoke(t.id, t.name)}
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
        <pre className="bg-body border border-border rounded-lg p-3 text-xs text-text-primary overflow-x-auto">
{`curl -H "X-API-Key: ofk_..." \\
  http://localhost:8000/api/v1/external/portfolio/summary`}
        </pre>
        <p className="text-xs text-text-muted mt-3">
          Verfuegbare Endpoints: <code>/portfolio/summary</code>, <code>/positions</code>,
          <code> /performance/history</code>, <code>/performance/total-return</code>,
          <code> /analysis/score/{'{ticker}'}</code>, <code>/screening/latest</code> u.a.
          Volle Liste in <code>docs/EXTERNAL_API.md</code>.
        </p>
      </Section>

      {/* Create Modal */}
      {showCreate && (
        <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4">
          <div
            ref={createTrapRef}
            className="bg-card border border-border rounded-xl p-6 max-w-md w-full"
            role="dialog"
            aria-modal="true"
            aria-labelledby="create-token-title"
          >
            <h3 id="create-token-title" className="text-base font-semibold text-text-primary mb-4">
              Neuen API-Token erstellen
            </h3>
            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label htmlFor="token-name" className="block text-sm text-text-secondary mb-1">
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
                  className="w-full bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
                />
              </div>
              <div>
                <label htmlFor="token-expires" className="block text-sm text-text-secondary mb-1">
                  Ablauf in Tagen (optional)
                </label>
                <input
                  id="token-expires"
                  type="number"
                  min="1"
                  max="3650"
                  value={expiresInDays}
                  onChange={(e) => setExpiresInDays(e.target.value)}
                  placeholder="Leer lassen fuer kein Ablaufdatum"
                  className="w-full bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
                />
              </div>
              <div className="flex gap-2 justify-end">
                <button
                  type="button"
                  onClick={() => { setShowCreate(false); setName(''); setExpiresInDays('') }}
                  className="text-text-secondary hover:text-text-primary px-4 py-2 text-sm"
                >
                  Abbrechen
                </button>
                <button
                  type="submit"
                  disabled={creating || !name.trim()}
                  className="bg-primary hover:bg-primary/90 text-white rounded-lg px-4 py-2 text-sm disabled:opacity-40"
                >
                  {creating ? 'Erstelle...' : 'Erstellen'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Plaintext-Token-Anzeige */}
      {newToken && (
        <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4">
          <div
            ref={newTokenTrapRef}
            className="bg-card border border-border rounded-xl p-6 max-w-xl w-full"
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
                (z.B. in einem Passwort-Manager). Du kannst ihn spaeter nicht mehr einsehen.
              </p>
            </div>
            <div className="mb-4">
              <label className="block text-sm text-text-secondary mb-1">Token ({newToken.name})</label>
              <div className="flex items-center gap-2">
                <code className="flex-1 bg-body border border-border rounded-lg px-3 py-2 text-xs text-text-primary font-mono break-all">
                  {newToken.token}
                </code>
                <button
                  type="button"
                  onClick={() => handleCopy(newToken.token)}
                  className="flex items-center gap-1.5 bg-primary hover:bg-primary/90 text-white rounded-lg px-3 py-2 text-sm shrink-0"
                  aria-label="Token in Zwischenablage kopieren"
                >
                  <Copy size={14} />
                  Kopieren
                </button>
              </div>
            </div>
            <div className="flex justify-end">
              <button
                type="button"
                onClick={() => setNewToken(null)}
                className="bg-card-alt hover:bg-border/50 border border-border text-text-primary rounded-lg px-4 py-2 text-sm"
              >
                Schliessen
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
