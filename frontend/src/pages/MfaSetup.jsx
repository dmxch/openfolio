import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { authFetch } from '../hooks/useApi'
import { QRCodeSVG } from 'qrcode.react'
import { Shield, LogOut } from 'lucide-react'
import Logo from '../components/ui/Logo'
import Button from '../components/ui/Button'

const AUTH_BG = { background: 'radial-gradient(900px 500px at 50% -10%,#0e1622 0%,#0a0d12 60%)' }

// Dedizierte, erzwungene MFA-Einrichtung. Wird von ProtectedRoute angesteuert,
// wenn user.mfa_setup_required — bewusst NICHT die volle Settings-Seite, deren
// Daten-Endpoints das MFA-Gate ohnehin blockt. Nutzt nur die Allowlist-Endpoints
// (mfa/setup, mfa/verify-setup, logout).
export default function MfaSetup() {
  const { logout, refreshSession } = useAuth()
  const navigate = useNavigate()

  const [secret, setSecret] = useState(null)
  const [uri, setUri] = useState(null)
  const [code, setCode] = useState('')
  const [backupCodes, setBackupCodes] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function startSetup() {
    setError('')
    setBusy(true)
    try {
      const res = await authFetch('/api/auth/mfa/setup', { method: 'POST' })
      if (!res.ok) {
        const e = await res.json().catch(() => ({}))
        throw new Error(e.detail || 'Einrichtung fehlgeschlagen')
      }
      const data = await res.json()
      setSecret(data.secret)
      setUri(data.qr_code_uri)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function verify(e) {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      const res = await authFetch('/api/auth/mfa/verify-setup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ totp_code: code }),
      })
      if (!res.ok) {
        const er = await res.json().catch(() => ({}))
        throw new Error(er.detail || 'Ungültiger Code')
      }
      const data = await res.json()
      setBackupCodes(data.backup_codes || [])
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function finish() {
    // MFA ist jetzt aktiv -> Session/User neu laden (mfa_setup_required faellt
    // weg) und ins Dashboard.
    await refreshSession()
    navigate('/', { replace: true })
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-6" style={AUTH_BG}>
      <Logo size={32} wordmarkSize={19} className="mb-6" />

      <div className="w-[440px] max-w-full bg-card border border-border rounded-card p-[26px] shadow-xl">
        {!backupCodes && (
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Shield size={18} className="text-primary" />
              <h1 className="text-[18px] font-semibold text-text-primary">Zwei-Faktor-Authentifizierung einrichten</h1>
            </div>
            <p className="text-sm text-text-secondary mt-1 mb-5">
              Für dein Konto ist eine Zwei-Faktor-Authentifizierung erforderlich. Richte sie
              ein, um fortzufahren.
            </p>

            {error && (
              <div className="mb-4 p-3 rounded-lg bg-danger/10 border border-danger/30 text-sm text-danger">
                {error}
              </div>
            )}

            {!secret ? (
              <Button
                variant="primary"
                icon={Shield}
                onClick={startSetup}
                disabled={busy}
                className="w-full justify-center py-2.5 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {busy ? 'Wird vorbereitet...' : 'MFA einrichten'}
              </Button>
            ) : (
              <div className="space-y-3">
                <p className="text-sm text-text-secondary">
                  Scanne den QR-Code mit deiner Authenticator-App oder gib den Schlüssel manuell ein:
                </p>
                {uri && (
                  <div className="bg-white rounded-lg p-4 w-fit mx-auto">
                    <QRCodeSVG value={uri} size={200} level="M" />
                  </div>
                )}
                <div className="bg-card-2 border border-border rounded-lg p-3">
                  <code className="text-xs text-text-primary break-all font-mono">{secret}</code>
                </div>
                <form onSubmit={verify} className="flex gap-2">
                  <label htmlFor="mfa-setup-code" className="sr-only">MFA-Code</label>
                  <input
                    id="mfa-setup-code"
                    type="text"
                    value={code}
                    onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                    placeholder="6-stelliger Code"
                    maxLength={6}
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    autoFocus
                    className="flex-1 bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text-primary tracking-widest font-mono focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors"
                  />
                  <Button variant="primary" type="submit" disabled={busy}>Verifizieren</Button>
                </form>
              </div>
            )}
          </div>
        )}

        {backupCodes && (
          <div>
            <h1 className="text-[18px] font-semibold text-text-primary mb-2">Backup-Codes</h1>
            <p className="text-sm text-text-secondary mb-4">
              Speichere diese Codes sicher ab. Jeder Code kann nur einmal verwendet werden —
              sie sind dein Zugang, falls du deine Authenticator-App verlierst.
            </p>
            <div className="grid grid-cols-2 gap-2 mb-4">
              {backupCodes.map((c, i) => (
                <div key={i} className="bg-card-2 border border-border rounded-lg px-3 py-2 text-center font-mono text-sm text-text-primary">
                  {c}
                </div>
              ))}
            </div>
            <div className="flex gap-2">
              <Button
                variant="secondary"
                className="flex-1 justify-center"
                onClick={() => navigator.clipboard.writeText(backupCodes.join('\n'))}
              >
                Kopieren
              </Button>
              <Button variant="primary" className="flex-1 justify-center" onClick={finish}>
                Fertig
              </Button>
            </div>
          </div>
        )}

        <button
          type="button"
          onClick={logout}
          className="mt-5 w-full flex items-center justify-center gap-2 text-[13px] text-text-muted hover:text-text-primary transition-colors"
        >
          <LogOut size={14} /> Abmelden
        </button>
      </div>
    </div>
  )
}
