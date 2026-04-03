import { useState, useEffect } from 'react'
import useFocusTrap from '../../hooks/useFocusTrap'
import useScrollLock from '../../hooks/useScrollLock'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../contexts/AuthContext'
import { useToast } from '../../components/Toast'
import { formatDate } from '../../lib/format'
import { Shield, LogOut, Trash2 } from 'lucide-react'
import { QRCodeSVG } from 'qrcode.react'
import { authFetch, API_BASE, Section, Input } from './shared'

export default function AccountTab() {
  const { user, logout, refreshSession } = useAuth()
  const navigate = useNavigate()
  const addToast = useToast()
  const [sessions, setSessions] = useState([])

  // Change password
  const [currentPw, setCurrentPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [confirmPw, setConfirmPw] = useState('')

  // Change email
  const [emailPw, setEmailPw] = useState('')
  const [newEmail, setNewEmail] = useState('')

  // MFA
  const [mfaSecret, setMfaSecret] = useState(null)
  const [mfaUri, setMfaUri] = useState(null)
  const [mfaCode, setMfaCode] = useState('')
  const [backupCodes, setBackupCodes] = useState(null)
  const backupTrapRef = useFocusTrap(!!backupCodes)
  useScrollLock(!!backupCodes)

  // Delete account
  const [deletePw, setDeletePw] = useState('')
  const [showDelete, setShowDelete] = useState(false)

  useEffect(() => {
    loadSessions()
  }, [])

  async function loadSessions() {
    try {
      const res = await authFetch(`${API_BASE}/auth/sessions`)
      if (res.ok) setSessions(await res.json())
    } catch { addToast('Sitzungen konnten nicht geladen werden', 'error') }
  }

  async function handleChangePassword(e) {
    e.preventDefault()
    if (newPw !== confirmPw) {
      addToast('Passwörter stimmen nicht überein', 'error')
      return
    }
    try {
      const res = await authFetch(`${API_BASE}/auth/change-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ current_password: currentPw, new_password: newPw }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail)
      }
      addToast('Passwort geändert', 'success')
      setCurrentPw('')
      setNewPw('')
      setConfirmPw('')
    } catch (err) {
      addToast(err.message, 'error')
    }
  }

  async function handleChangeEmail(e) {
    e.preventDefault()
    try {
      const res = await authFetch(`${API_BASE}/auth/change-email`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: emailPw, new_email: newEmail }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail)
      }
      addToast('E-Mail geändert', 'success')
      setEmailPw('')
      setNewEmail('')
    } catch (err) {
      addToast(err.message, 'error')
    }
  }

  async function handleSetupMfa() {
    try {
      const res = await authFetch(`${API_BASE}/auth/mfa/setup`, { method: 'POST' })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail)
      }
      const data = await res.json()
      setMfaSecret(data.secret)
      setMfaUri(data.qr_code_uri)
    } catch (err) {
      addToast(err.message, 'error')
    }
  }

  async function handleVerifyMfa(e) {
    e.preventDefault()
    try {
      const res = await authFetch(`${API_BASE}/auth/mfa/verify-setup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ totp_code: mfaCode }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail)
      }
      const data = await res.json()
      addToast('MFA aktiviert', 'success')
      setMfaSecret(null)
      setMfaUri(null)
      setMfaCode('')
      if (data.backup_codes) {
        setBackupCodes(data.backup_codes)
      }
    } catch (err) {
      addToast(err.message, 'error')
    }
  }

  async function handleRevokeSession(id) {
    try {
      await authFetch(`${API_BASE}/auth/sessions/${id}`, { method: 'DELETE' })
      setSessions((prev) => prev.filter((s) => s.id !== id))
      addToast('Sitzung beendet', 'success')
    } catch { addToast('Sitzung konnte nicht beendet werden', 'error') }
  }

  const [showRevokeAll, setShowRevokeAll] = useState(false)
  async function handleRevokeAllSessions() {
    try {
      await authFetch(`${API_BASE}/auth/sessions`, { method: 'DELETE' })
      setShowRevokeAll(false)
      addToast('Alle Sitzungen beendet', 'success')
      logout()
    } catch {
      addToast('Fehler beim Beenden der Sitzungen', 'error')
    }
  }

  async function handleDeleteAccount(e) {
    e.preventDefault()
    try {
      const res = await authFetch(`${API_BASE}/auth/account`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: deletePw }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail)
      }
      logout()
    } catch (err) {
      addToast(err.message, 'error')
    }
  }

  return (
    <div className="space-y-6 max-w-2xl">
      {/* Account Info */}
      <Section title="Konto">
        <div className="text-sm text-text-secondary">
          <p>E-Mail: <span className="text-text-primary">{user?.email}</span></p>
          <p className="mt-1">MFA: <span className={user?.mfa_enabled ? 'text-success' : 'text-text-muted'}>{user?.mfa_enabled ? 'Aktiviert' : 'Deaktiviert'}</span></p>
        </div>
      </Section>

      {/* Change Password */}
      <Section title="Passwort ändern">
        <form onSubmit={handleChangePassword} className="space-y-3">
          <Input label="Aktuelles Passwort" type="password" value={currentPw} onChange={setCurrentPw} />
          <Input label="Neues Passwort" type="password" value={newPw} onChange={setNewPw} />
          <Input label="Neues Passwort bestätigen" type="password" value={confirmPw} onChange={setConfirmPw} />
          <button type="submit" className="bg-primary hover:bg-primary/90 text-white rounded-lg px-4 py-2 text-sm">
            Passwort ändern
          </button>
        </form>
      </Section>

      {/* Change Email */}
      <Section title="E-Mail ändern">
        <form onSubmit={handleChangeEmail} className="space-y-3">
          <Input label="Passwort" type="password" value={emailPw} onChange={setEmailPw} />
          <Input label="Neue E-Mail" type="email" value={newEmail} onChange={setNewEmail} />
          <button type="submit" className="bg-primary hover:bg-primary/90 text-white rounded-lg px-4 py-2 text-sm">
            E-Mail ändern
          </button>
        </form>
      </Section>

      {/* MFA */}
      <Section title="Zwei-Faktor-Authentifizierung">
        {!mfaSecret ? (
          <div>
            <button onClick={handleSetupMfa} className="flex items-center gap-2 bg-card-alt hover:bg-border/50 text-text-primary rounded-lg px-4 py-2 text-sm border border-border">
              <Shield size={16} />
              {user?.mfa_enabled ? 'MFA neu einrichten' : 'MFA aktivieren'}
            </button>
            {user?.mfa_enabled && (
              <p className="text-xs text-text-secondary mt-2">
                Backup-Codes verbleibend: {user?.backup_codes_remaining ?? '–'}
              </p>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-sm text-text-secondary">
              Scanne den QR-Code mit deiner Authenticator-App oder gib den Schlüssel manuell ein:
            </p>
            {mfaUri && (
              <div className="bg-white rounded-lg p-4 w-fit">
                <QRCodeSVG value={mfaUri} size={200} level="M" />
              </div>
            )}
            <div className="bg-body border border-border rounded-lg p-3">
              <code className="text-xs text-text-primary break-all">{mfaSecret}</code>
            </div>
            <form onSubmit={handleVerifyMfa} className="flex gap-2">
              <label htmlFor="settings-mfa-code" className="sr-only">MFA-Code</label>
              <input
                id="settings-mfa-code"
                type="text"
                value={mfaCode}
                onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                placeholder="6-stelliger Code"
                maxLength={6}
                className="bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary w-40 tracking-widest"
              />
              <button type="submit" className="bg-primary hover:bg-primary/90 text-white rounded-lg px-4 py-2 text-sm">
                Verifizieren
              </button>
            </form>
          </div>
        )}
      </Section>

      {/* Backup Codes Modal */}
      {backupCodes && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div ref={backupTrapRef} role="dialog" aria-modal="true" aria-label="Backup-Codes" className="bg-card border border-border rounded-xl p-6 max-w-sm w-full">
            <h3 className="text-lg font-semibold text-text-primary mb-2">Backup-Codes</h3>
            <p className="text-sm text-text-secondary mb-4">
              Speichere diese Codes sicher ab. Jeder Code kann nur einmal verwendet werden.
            </p>
            <div className="grid grid-cols-2 gap-2 mb-4">
              {backupCodes.map((code, i) => (
                <div key={i} className="bg-body border border-border rounded-lg px-3 py-2 text-center font-mono text-sm text-text-primary">
                  {code}
                </div>
              ))}
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => {
                  navigator.clipboard.writeText(backupCodes.join('\n'))
                  addToast('Codes kopiert', 'success')
                }}
                className="flex-1 bg-card-alt hover:bg-border/50 text-text-primary rounded-lg px-4 py-2 text-sm border border-border"
              >
                Kopieren
              </button>
              <button
                onClick={async () => {
                  setBackupCodes(null)
                  // After MFA setup: refresh user state and redirect new users to transactions
                  if (user?.mfa_setup_required) {
                    await refreshSession()
                    navigate('/transactions')
                  }
                }}
                className="flex-1 bg-primary hover:bg-primary/90 text-white rounded-lg px-4 py-2 text-sm"
              >
                Fertig
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Sessions */}
      <Section title="Aktive Sitzungen">
        <div className="space-y-2">
          {sessions.map((s) => (
            <div key={s.id} className="flex items-center justify-between bg-body border border-border rounded-lg p-3">
              <div className="text-xs text-text-secondary">
                <p className="text-text-primary text-sm">{s.user_agent?.split(' ')[0] || 'Unbekannt'}</p>
                <p>{s.ip_address} &middot; {formatDate(s.created_at)}</p>
              </div>
              <button onClick={() => handleRevokeSession(s.id)} className="text-danger hover:text-danger/80 text-xs">
                Beenden
              </button>
            </div>
          ))}
          {sessions.length === 0 && <p className="text-sm text-text-muted">Keine aktiven Sitzungen</p>}
          {sessions.length > 1 && (
            <button
              onClick={() => setShowRevokeAll(true)}
              className="mt-3 flex items-center gap-2 text-danger hover:text-danger/80 text-xs font-medium transition-colors"
            >
              Alle Sitzungen beenden
            </button>
          )}
        </div>
        {showRevokeAll && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setShowRevokeAll(false)}>
            <div className="bg-card border border-border rounded-xl p-6 max-w-sm mx-4 shadow-xl" onClick={(e) => e.stopPropagation()}>
              <h3 className="text-lg font-semibold text-text-primary mb-2">Alle Sitzungen beenden?</h3>
              <p className="text-sm text-text-secondary mb-6">
                Alle aktiven Sitzungen werden beendet. Du wirst auf allen Geräten abgemeldet und musst dich neu anmelden.
              </p>
              <div className="flex justify-end gap-3">
                <button onClick={() => setShowRevokeAll(false)} className="px-4 py-2 text-sm rounded-lg border border-border text-text-secondary hover:bg-card-alt transition-colors">
                  Abbrechen
                </button>
                <button onClick={handleRevokeAllSessions} className="px-4 py-2 text-sm rounded-lg bg-danger text-white hover:bg-danger/90 transition-colors">
                  Alle beenden
                </button>
              </div>
            </div>
          </div>
        )}
      </Section>

      {/* Logout */}
      <Section title="Abmelden">
        <button onClick={logout} className="flex items-center gap-2 bg-card-alt hover:bg-border/50 text-text-primary rounded-lg px-4 py-2 text-sm border border-border">
          <LogOut size={16} />
          Abmelden
        </button>
      </Section>

      {/* Delete Account */}
      <Section title="Konto löschen">
        {!showDelete ? (
          <button onClick={() => setShowDelete(true)} className="flex items-center gap-2 text-danger hover:text-danger/80 text-sm">
            <Trash2 size={16} />
            Konto und alle Daten löschen
          </button>
        ) : (
          <form onSubmit={handleDeleteAccount} className="space-y-3">
            <p className="text-sm text-danger">Alle Daten werden unwiderruflich gelöscht.</p>
            <Input label="Passwort zur Bestätigung" type="password" value={deletePw} onChange={setDeletePw} />
            <div className="flex gap-2">
              <button type="submit" className="bg-danger hover:bg-danger/90 text-white rounded-lg px-4 py-2 text-sm">
                Endgültig löschen
              </button>
              <button type="button" onClick={() => setShowDelete(false)} className="text-text-secondary hover:text-text-primary text-sm">
                Abbrechen
              </button>
            </div>
          </form>
        )}
      </Section>
    </div>
  )
}
