import { useState, useEffect } from 'react'
import useFocusTrap from '../hooks/useFocusTrap'
import useScrollLock from '../hooks/useScrollLock'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../components/Toast'
import { formatDate } from '../lib/format'
import { User, Briefcase, Monitor, Database, Shield, LogOut, Trash2, Download, Key, Bell, Mail, Send, CheckCircle, XCircle, Loader2 } from 'lucide-react'
import { QRCodeSVG } from 'qrcode.react'

const API_BASE = '/api'

async function authFetch(url, options = {}) {
  const { getAccessToken } = await import('../contexts/AuthContext')
  const token = getAccessToken()
  return fetch(url, {
    ...options,
    headers: {
      ...options.headers,
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  })
}

const TABS = [
  { id: 'account', label: 'Konto & Sicherheit', icon: User },
  { id: 'portfolio', label: 'Portfolio', icon: Briefcase },
  { id: 'alerts', label: 'Alerts', icon: Bell },
  { id: 'integrations', label: 'Integrationen', icon: Key },
  { id: 'display', label: 'Anzeige', icon: Monitor },
  { id: 'data', label: 'Daten', icon: Database },
]

export default function Settings() {
  const [activeTab, setActiveTab] = useState('account')

  return (
    <div>
      <h1 className="text-xl font-bold text-text-primary mb-6">Einstellungen</h1>

      <div className="flex gap-2 mb-6 border-b border-border overflow-x-auto">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setActiveTab(id)}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm whitespace-nowrap border-b-2 transition-colors ${
              activeTab === id
                ? 'border-primary text-primary'
                : 'border-transparent text-text-secondary hover:text-text-primary'
            }`}
          >
            <Icon size={16} />
            {label}
          </button>
        ))}
      </div>

      {activeTab === 'account' && <AccountTab />}
      {activeTab === 'portfolio' && <PortfolioTab />}
      {activeTab === 'alerts' && <AlertsTab />}
      {activeTab === 'integrations' && <IntegrationsTab />}
      {activeTab === 'display' && <DisplayTab />}
      {activeTab === 'data' && <DataTab />}
    </div>
  )
}

function AccountTab() {
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
    } catch {}
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
    } catch {}
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
              <p className="text-xs text-text-muted mt-2">
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

function PortfolioTab() {
  const addToast = useToast()
  const [settings, setSettings] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadSettings()
  }, [])

  async function loadSettings() {
    try {
      const res = await authFetch(`${API_BASE}/settings`)
      if (res.ok) setSettings(await res.json())
    } catch {} finally {
      setLoading(false)
    }
  }

  async function updateSetting(key, value) {
    try {
      const res = await authFetch(`${API_BASE}/settings`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [key]: value }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail)
      }
      const data = await res.json()
      setSettings(data)
      addToast('Gespeichert', 'success')
    } catch (err) {
      addToast(err.message, 'error')
    }
  }

  if (loading) return <p className="text-sm text-text-muted">Lade...</p>

  return (
    <div className="space-y-6 max-w-2xl">
      <Section title="Broker">
        <Select
          value={settings?.broker || 'swissquote'}
          onChange={(v) => updateSetting('broker', v)}
          options={[
            { value: 'swissquote', label: 'Swissquote' },
            { value: 'interactive_brokers', label: 'Interactive Brokers' },
            { value: 'other', label: 'Anderer' },
          ]}
        />
      </Section>

      <Section title="Stop-Loss Methode (Standard)">
        <Select
          value={settings?.default_stop_loss_method || 'trailing_pct'}
          onChange={(v) => updateSetting('default_stop_loss_method', v)}
          options={[
            { value: 'trailing_pct', label: 'Trailing Stop (%)' },
            { value: 'higher_low', label: 'Higher Low' },
            { value: 'ma_based', label: 'MA-basiert' },
          ]}
        />
      </Section>

      <Section title="Stop-Loss Review">
        <div className="space-y-3">
          <div>
            <label htmlFor="settings-sl-review-distance" className="block text-sm text-text-secondary mb-1">Review-Abstand (%)</label>
            <input
              id="settings-sl-review-distance"
              type="number"
              value={settings?.stop_loss_review_distance_pct || 15}
              onChange={(e) => updateSetting('stop_loss_review_distance_pct', parseFloat(e.target.value))}
              className="bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary w-24"
              min="1"
              max="50"
            />
          </div>
          <div>
            <label htmlFor="settings-sl-review-days" className="block text-sm text-text-secondary mb-1">Max. Tage ohne Review</label>
            <input
              id="settings-sl-review-days"
              type="number"
              value={settings?.stop_loss_review_max_days || 14}
              onChange={(e) => updateSetting('stop_loss_review_max_days', parseInt(e.target.value))}
              className="bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary w-24"
              min="1"
              max="90"
            />
          </div>
        </div>
      </Section>
    </div>
  )
}

const ALERT_CATEGORIES = [
  { key: 'stop_missing', label: 'Kein Stop-Loss gesetzt', desc: 'Warnt wenn eine Position keinen Stop-Loss hat' },
  { key: 'stop_unconfirmed', label: 'Stop nicht bei Broker bestätigt', desc: 'Warnt wenn der Stop-Loss nicht beim Broker hinterlegt ist' },
  { key: 'stop_proximity', label: 'Kurs nahe am Stop-Loss', desc: 'Warnt wenn der Kurs sich dem Stop-Loss nähert' },
  { key: 'stop_review', label: 'Stop-Loss Review', desc: 'Erinnerung zum Nachziehen des Stop-Loss' },
  { key: 'ma_critical', label: 'Unter 150-DMA (Schwur 1)', desc: 'Position unter der Investor Line — kritisch' },
  { key: 'etf_200dma_buy', label: 'ETF unter 200-DMA (Kaufkriterien)', desc: 'Kaufkriterien erfüllt wenn ein breiter Index-ETF unter die 200-Tage-Linie fällt' },
  { key: 'ma_warning', label: 'Unter 50-DMA (Trader Line)', desc: 'Position unter der Trader Line' },
  { key: 'position_limit', label: 'Positions-Limits', desc: 'Warnt bei Übergewichtung einzelner Positionen' },
  { key: 'sector_limit', label: 'Sektor-Limits', desc: 'Warnt bei Übergewichtung eines Sektors' },
  { key: 'loss', label: 'Grosse Verluste', desc: 'Warnt bei grossen Verlusten ohne Stop-Loss' },
  { key: 'market_climate', label: 'Marktklima', desc: 'Warnt bei bärischem Marktklima' },
  { key: 'vix', label: 'VIX / Volatilität', desc: 'Warnt bei hoher Volatilität (VIX)' },
  { key: 'earnings', label: 'Earnings-Termine', desc: 'Warnt vor bevorstehenden Earnings' },
  { key: 'allocation', label: 'Core/Satellite Allocation', desc: 'Warnt bei Abweichung von der Ziel-Gewichtung' },
  { key: 'position_type_missing', label: 'Positions-Typ fehlt', desc: 'Warnt wenn Core/Satellite nicht zugewiesen ist' },
  { key: 'price_alert', label: 'Preis-Alarme', desc: 'Benachrichtigungen für Preis-Alarme (Watchlist & Positionen)' },
  { key: 'breakout', label: 'Breakout-Alerts (Watchlist)', desc: 'E-Mail wenn eine Aktie auf der Watchlist einen Donchian-Breakout hat' },
]

function AlertsTab() {
  const addToast = useToast()
  const [prefs, setPrefs] = useState([])
  const [settings, setSettings] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      authFetch(`${API_BASE}/settings/alert-preferences`).then((r) => r.ok ? r.json() : []),
      authFetch(`${API_BASE}/settings`).then((r) => r.ok ? r.json() : null),
    ]).then(([p, s]) => {
      setPrefs(p)
      if (s) setSettings(s)
    }).finally(() => setLoading(false))
  }, [])

  async function updatePref(category, field, value) {
    try {
      const res = await authFetch(`${API_BASE}/settings/alert-preferences`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ category, [field]: value }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail)
      }
      const updated = await res.json()
      setPrefs((prev) => prev.map((p) => p.category === category ? updated : p))
    } catch (err) {
      addToast(err.message, 'error')
    }
  }

  async function updateSetting(key, value) {
    try {
      const res = await authFetch(`${API_BASE}/settings`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [key]: value }),
      })
      if (res.ok) {
        setSettings(await res.json())
        addToast('Gespeichert', 'success')
      }
    } catch (err) {
      addToast(err.message, 'error')
    }
  }

  if (loading) return <p className="text-sm text-text-muted">Lade...</p>

  const prefMap = {}
  for (const p of prefs) prefMap[p.category] = p
  const enabledCount = ALERT_CATEGORIES.filter((c) => prefMap[c.key]?.is_enabled !== false).length

  return (
    <div className="space-y-6 max-w-3xl">
      <Section title={`Benachrichtigungen (${enabledCount}/${ALERT_CATEGORIES.length} aktiv)`}>
        <div className="mb-3">
          <div className="grid grid-cols-[1fr,60px,60px,60px] gap-2 text-xs text-text-muted font-medium px-2 pb-2 border-b border-border">
            <span>Kategorie</span>
            <span className="text-center">Aktiv</span>
            <span className="text-center">In-App</span>
            <span className="text-center flex items-center justify-center gap-1"><Mail size={12} /> E-Mail</span>
          </div>
          <div className="divide-y divide-border/50">
            {ALERT_CATEGORIES.map(({ key, label, desc }) => {
              const p = prefMap[key] || { is_enabled: true, notify_in_app: true, notify_email: false }
              return (
                <div key={key} className="grid grid-cols-[1fr,60px,60px,60px] gap-2 items-center py-2 px-2 hover:bg-body rounded">
                  <div>
                    <div className="text-sm text-text-primary">{label}</div>
                    <div className="text-xs text-text-muted">{desc}</div>
                  </div>
                  <div className="flex justify-center">
                    <input
                      type="checkbox"
                      aria-label={`${label} aktiv`}
                      checked={p.is_enabled}
                      onChange={(e) => updatePref(key, 'is_enabled', e.target.checked)}
                      className="accent-primary"
                    />
                  </div>
                  <div className="flex justify-center">
                    <input
                      type="checkbox"
                      aria-label={`${label} In-App`}
                      checked={p.notify_in_app}
                      onChange={(e) => updatePref(key, 'notify_in_app', e.target.checked)}
                      className="accent-primary"
                      disabled={!p.is_enabled}
                    />
                  </div>
                  <div className="flex justify-center">
                    <input
                      type="checkbox"
                      aria-label={`${label} E-Mail`}
                      checked={p.notify_email}
                      onChange={(e) => updatePref(key, 'notify_email', e.target.checked)}
                      className="accent-primary"
                      disabled={!p.is_enabled}
                    />
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </Section>

      <Section title="Schwellenwerte">
        <div className="space-y-3">
          <div>
            <label htmlFor="settings-stop-proximity" className="block text-sm text-text-secondary mb-1">Stop-Proximity Warnung (%)</label>
            <p className="text-xs text-text-muted mb-1">Warnt wenn der Kurs weniger als X% über dem Stop ist</p>
            <input
              id="settings-stop-proximity"
              type="number"
              value={settings?.alert_stop_proximity_pct ?? 3}
              onChange={(e) => updateSetting('alert_stop_proximity_pct', parseFloat(e.target.value))}
              className="bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary w-24"
              min="1"
              max="20"
              step="0.5"
            />
          </div>
          <div>
            <label htmlFor="settings-satellite-loss" className="block text-sm text-text-secondary mb-1">Satellite Verlust-Warnung (%)</label>
            <p className="text-xs text-text-muted mb-1">Warnung ab diesem Verlust (ohne Stop-Loss)</p>
            <input
              id="settings-satellite-loss"
              type="number"
              value={Math.abs(settings?.alert_satellite_loss_pct ?? 15)}
              onChange={(e) => updateSetting('alert_satellite_loss_pct', -Math.abs(parseFloat(e.target.value)))}
              className="bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary w-24"
              min="5"
              max="50"
              step="1"
            />
          </div>
          <div>
            <label htmlFor="settings-core-loss" className="block text-sm text-text-secondary mb-1">Core Verlust-Warnung (%)</label>
            <p className="text-xs text-text-muted mb-1">Warnung ab diesem Verlust (ohne Stop-Loss)</p>
            <input
              id="settings-core-loss"
              type="number"
              value={Math.abs(settings?.alert_core_loss_pct ?? 25)}
              onChange={(e) => updateSetting('alert_core_loss_pct', -Math.abs(parseFloat(e.target.value)))}
              className="bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary w-24"
              min="5"
              max="50"
              step="1"
            />
          </div>
        </div>
      </Section>
    </div>
  )
}

const SMTP_PRESETS = {
  gmail: { label: 'Gmail', host: 'smtp.gmail.com', port: 587 },
  outlook: { label: 'Outlook / Microsoft 365', host: 'smtp.office365.com', port: 587 },
  proton: { label: 'Proton Mail (Bridge)', host: 'smtp.protonmail.ch', port: 587 },
  yahoo: { label: 'Yahoo Mail', host: 'smtp.mail.yahoo.com', port: 587 },
  gmx: { label: 'GMX', host: 'mail.gmx.net', port: 587 },
  bluewin: { label: 'Bluewin (Swisscom)', host: 'smtpauths.bluewin.ch', port: 465 },
}

function IntegrationsTab() {
  const addToast = useToast()
  const [settings, setSettings] = useState(null)
  const [fredKey, setFredKey] = useState('')
  const [fredSaving, setFredSaving] = useState(false)
  const [fredTesting, setFredTesting] = useState(false)
  const [fredTestResult, setFredTestResult] = useState(null)
  const [loading, setLoading] = useState(true)

  // SMTP state
  const [smtp, setSmtp] = useState(null)
  const [smtpForm, setSmtpForm] = useState({ provider: '', host: '', port: 587, username: '', password: '', from_email: '', use_tls: true })
  const [smtpSaving, setSmtpSaving] = useState(false)
  const [smtpTesting, setSmtpTesting] = useState(false)
  const [smtpTestResult, setSmtpTestResult] = useState(null)

  useEffect(() => {
    Promise.all([
      authFetch(`${API_BASE}/settings`).then((r) => r.ok ? r.json() : null),
      authFetch(`${API_BASE}/settings/smtp`).then((r) => r.ok ? r.json() : null),
    ]).then(([s, sm]) => {
      if (s) setSettings(s)
      if (sm) {
        setSmtp(sm)
        if (sm.configured) {
          setSmtpForm({ provider: sm.provider || '', host: sm.host, port: sm.port, username: sm.username, password: '', from_email: sm.from_email || '', use_tls: sm.use_tls })
        }
      }
    }).finally(() => setLoading(false))
  }, [])



  async function handleSaveFredKey(e) {
    e.preventDefault()
    setFredSaving(true)
    try {
      const res = await authFetch(`${API_BASE}/settings/fred-api-key`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: fredKey }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail)
      }
      const data = await res.json()
      setSettings((prev) => ({ ...prev, has_fred_api_key: data.has_fred_api_key, fred_api_key_masked: data.fred_api_key_masked }))
      setFredKey('')
      setFredTestResult(null)
      addToast('FRED API Key gespeichert. Indikatoren werden aktualisiert.', 'success')
    } catch (err) {
      addToast(err.message, 'error')
    } finally {
      setFredSaving(false)
    }
  }

  async function handleRemoveFredKey() {
    setFredSaving(true)
    try {
      await authFetch(`${API_BASE}/settings/fred-api-key`, { method: 'DELETE' })
      setSettings((prev) => ({ ...prev, has_fred_api_key: false, fred_api_key_masked: '' }))
      setFredTestResult(null)
      addToast('FRED API Key entfernt', 'success')
    } catch (err) {
      addToast(err.message, 'error')
    } finally {
      setFredSaving(false)
    }
  }

  async function handleTestFredKey() {
    setFredTesting(true)
    setFredTestResult(null)
    try {
      const res = await authFetch(`${API_BASE}/settings/fred-api-key/test`, { method: 'POST' })
      const data = await res.json()
      if (res.ok) {
        setFredTestResult({ ok: true, message: data.message })
      } else {
        setFredTestResult({ ok: false, message: data.detail })
      }
    } catch (err) {
      setFredTestResult({ ok: false, message: err.message })
    } finally {
      setFredTesting(false)
    }
  }

  function handlePresetChange(provider) {
    const preset = SMTP_PRESETS[provider]
    if (preset) {
      setSmtpForm((prev) => ({ ...prev, provider, host: preset.host, port: preset.port }))
    } else {
      setSmtpForm((prev) => ({ ...prev, provider: '' }))
    }
  }

  async function handleSaveSmtp(e) {
    e.preventDefault()
    if (!smtpForm.host || !smtpForm.username || !smtpForm.password) {
      addToast('Host, Benutzername und Passwort sind erforderlich', 'error')
      return
    }
    setSmtpSaving(true)
    try {
      const res = await authFetch(`${API_BASE}/settings/smtp`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(smtpForm),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail)
      }
      const data = await res.json()
      setSmtp(data)
      setSmtpForm((prev) => ({ ...prev, password: '' }))
      addToast('SMTP-Konfiguration gespeichert', 'success')
    } catch (err) {
      addToast(err.message, 'error')
    } finally {
      setSmtpSaving(false)
    }
  }

  async function handleDeleteSmtp() {
    try {
      await authFetch(`${API_BASE}/settings/smtp`, { method: 'DELETE' })
      setSmtp({ configured: false })
      setSmtpForm({ provider: '', host: '', port: 587, username: '', password: '', from_email: '', use_tls: true })
      addToast('SMTP-Konfiguration entfernt', 'success')
    } catch (err) {
      addToast(err.message, 'error')
    }
  }

  async function handleTestSmtp() {
    setSmtpTesting(true)
    setSmtpTestResult(null)
    try {
      const res = await authFetch(`${API_BASE}/settings/smtp/test`, { method: 'POST' })
      const data = await res.json()
      if (res.ok) {
        setSmtpTestResult({ ok: true, message: data.message })
      } else {
        setSmtpTestResult({ ok: false, message: data.detail })
      }
    } catch (err) {
      setSmtpTestResult({ ok: false, message: err.message })
    } finally {
      setSmtpTesting(false)
    }
  }

  if (loading) return <p className="text-sm text-text-muted">Lade...</p>

  return (
    <div className="space-y-6 max-w-2xl">
      <Section title="FRED API Key">
        <p className="text-sm text-text-secondary mb-3">
          Wird für die Makro-Indikatoren benötigt (Buffett Indicator, Arbeitslosenquote, Zinsstruktur). Dein Key wird verschlüsselt gespeichert.
        </p>
        <p className="text-xs text-text-muted mb-4">
          Kostenlos erstellen: <a href="https://fred.stlouisfed.org/docs/api/api_key.html" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">fred.stlouisfed.org</a>
        </p>

        {settings?.has_fred_api_key ? (
          <div className="space-y-3">
            <div className="flex items-center gap-3">
              <div className="flex-1 bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-muted font-mono">
                {settings.fred_api_key_masked}
              </div>
              <button
                type="button"
                onClick={handleTestFredKey}
                disabled={fredTesting}
                className="flex items-center gap-1.5 bg-card-alt hover:bg-border/50 text-text-primary rounded-lg px-3 py-2 text-sm border border-border disabled:opacity-40"
              >
                {fredTesting ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle size={14} />}
                Testen
              </button>
              <button
                onClick={handleRemoveFredKey}
                disabled={fredSaving}
                className="text-danger hover:text-danger/80 text-sm px-3 py-2"
              >
                Entfernen
              </button>
            </div>
            <form onSubmit={handleSaveFredKey} className="flex items-center gap-2">
              <label htmlFor="fred-key-replace" className="sr-only">FRED API Key</label>
              <input
                id="fred-key-replace"
                type="password"
                value={fredKey}
                onChange={(e) => setFredKey(e.target.value)}
                placeholder="Neuen Key eingeben zum Ersetzen..."
                className="flex-1 bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 font-mono"
              />
              <button
                type="submit"
                disabled={!fredKey || fredSaving}
                className="bg-primary hover:bg-primary/90 text-white rounded-lg px-4 py-2 text-sm disabled:opacity-40"
              >
                Ersetzen
              </button>
            </form>
            {fredTestResult && (
              <div className={`flex items-center gap-2 p-2 rounded-lg text-sm ${fredTestResult.ok ? 'bg-success/10 text-success' : 'bg-danger/10 text-danger'}`}>
                {fredTestResult.ok ? <CheckCircle size={14} /> : <XCircle size={14} />}
                {fredTestResult.message}
              </div>
            )}
          </div>
        ) : (
          <form onSubmit={handleSaveFredKey} className="flex items-center gap-2">
            <label htmlFor="fred-key-new" className="sr-only">FRED API Key</label>
            <input
              id="fred-key-new"
              type="password"
              value={fredKey}
              onChange={(e) => setFredKey(e.target.value)}
              placeholder="FRED API Key..."
              className="flex-1 bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 font-mono"
            />
            <button
              type="submit"
              disabled={!fredKey || fredSaving}
              className="bg-primary hover:bg-primary/90 text-white rounded-lg px-4 py-2 text-sm disabled:opacity-40"
            >
              Speichern
            </button>
          </form>
        )}
      </Section>

      <Section title="E-Mail (SMTP)">
        <p className="text-sm text-text-secondary mb-4">
          Konfiguriere deinen E-Mail-Server für Alert-Benachrichtigungen per E-Mail. Das Passwort wird verschlüsselt gespeichert.
        </p>

        {smtp?.configured && (
          <div className="flex items-center gap-2 mb-4 p-2 bg-success/10 border border-success/20 rounded-lg">
            <CheckCircle size={14} className="text-success" />
            <span className="text-sm text-success">SMTP konfiguriert ({smtp.host}:{smtp.port})</span>
          </div>
        )}

        <form onSubmit={handleSaveSmtp} className="space-y-3">
          <div>
            <label htmlFor="smtp-provider" className="block text-sm text-text-secondary mb-1">Anbieter (Preset)</label>
            <select
              id="smtp-provider"
              value={smtpForm.provider}
              onChange={(e) => handlePresetChange(e.target.value)}
              className="w-full bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
            >
              <option value="">Manuell konfigurieren</option>
              {Object.entries(SMTP_PRESETS).map(([k, v]) => (
                <option key={k} value={k}>{v.label}</option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-[1fr,100px] gap-2">
            <div>
              <label htmlFor="smtp-host" className="block text-sm text-text-secondary mb-1">SMTP Host</label>
              <input
                id="smtp-host"
                type="text"
                value={smtpForm.host}
                onChange={(e) => setSmtpForm((p) => ({ ...p, host: e.target.value }))}
                placeholder="smtp.example.com"
                className="w-full bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
                required
              />
            </div>
            <div>
              <label htmlFor="smtp-port" className="block text-sm text-text-secondary mb-1">Port</label>
              <input
                id="smtp-port"
                type="number"
                value={smtpForm.port}
                onChange={(e) => setSmtpForm((p) => ({ ...p, port: parseInt(e.target.value) || 587 }))}
                className="w-full bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
              />
            </div>
          </div>

          <div>
            <label htmlFor="smtp-username" className="block text-sm text-text-secondary mb-1">Benutzername / E-Mail</label>
            <input
              id="smtp-username"
              type="text"
              value={smtpForm.username}
              onChange={(e) => setSmtpForm((p) => ({ ...p, username: e.target.value }))}
              placeholder="user@example.com"
              className="w-full bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
              required
            />
          </div>

          <div>
            <label htmlFor="smtp-password" className="block text-sm text-text-secondary mb-1">Passwort / App-Passwort</label>
            <input
              id="smtp-password"
              type="password"
              value={smtpForm.password}
              onChange={(e) => setSmtpForm((p) => ({ ...p, password: e.target.value }))}
              placeholder={smtp?.configured ? '(unverändert — nur ausfüllen zum Ändern)' : 'SMTP-Passwort'}
              className="w-full bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
              required={!smtp?.configured}
            />
          </div>

          <div>
            <label htmlFor="smtp-from-email" className="block text-sm text-text-secondary mb-1">Absender-Adresse (optional)</label>
            <input
              id="smtp-from-email"
              type="email"
              value={smtpForm.from_email}
              onChange={(e) => setSmtpForm((p) => ({ ...p, from_email: e.target.value }))}
              placeholder="Falls abweichend vom Benutzernamen"
              className="w-full bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
            />
          </div>

          <label className="flex items-center gap-2 text-sm text-text-secondary cursor-pointer">
            <input
              type="checkbox"
              checked={smtpForm.use_tls}
              onChange={(e) => setSmtpForm((p) => ({ ...p, use_tls: e.target.checked }))}
              className="accent-primary"
            />
            TLS / STARTTLS verwenden
          </label>

          <div className="flex gap-2 pt-1">
            <button
              type="submit"
              disabled={smtpSaving}
              className="bg-primary hover:bg-primary/90 text-white rounded-lg px-4 py-2 text-sm disabled:opacity-40"
            >
              {smtpSaving ? 'Speichere...' : 'SMTP speichern'}
            </button>

            {smtp?.configured && (
              <>
                <button
                  type="button"
                  onClick={handleTestSmtp}
                  disabled={smtpTesting}
                  className="flex items-center gap-1.5 bg-card-alt hover:bg-border/50 text-text-primary rounded-lg px-4 py-2 text-sm border border-border disabled:opacity-40"
                >
                  {smtpTesting ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                  Test senden
                </button>
                <button
                  type="button"
                  onClick={handleDeleteSmtp}
                  className="text-danger hover:text-danger/80 text-sm px-3 py-2"
                >
                  Entfernen
                </button>
              </>
            )}
          </div>

          {smtpTestResult && (
            <div className={`flex items-center gap-2 p-2 rounded-lg text-sm ${smtpTestResult.ok ? 'bg-success/10 text-success' : 'bg-danger/10 text-danger'}`}>
              {smtpTestResult.ok ? <CheckCircle size={14} /> : <XCircle size={14} />}
              {smtpTestResult.message}
            </div>
          )}
        </form>
      </Section>
    </div>
  )
}

function DisplayTab() {
  const addToast = useToast()
  const [settings, setSettings] = useState(null)

  useEffect(() => {
    authFetch(`${API_BASE}/settings`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => d && setSettings(d))
  }, [])

  async function updateSetting(key, value) {
    try {
      const res = await authFetch(`${API_BASE}/settings`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [key]: value }),
      })
      if (res.ok) {
        setSettings(await res.json())
        addToast('Gespeichert', 'success')
      }
    } catch (err) {
      addToast(err.message, 'error')
    }
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <Section title="Zahlenformat">
        <Select
          value={settings?.number_format || 'ch'}
          onChange={(v) => updateSetting('number_format', v)}
          options={[
            { value: 'ch', label: "Schweiz (1'000.50)" },
            { value: 'de', label: 'Deutschland (1.000,50)' },
            { value: 'en', label: 'Englisch (1,000.50)' },
          ]}
        />
      </Section>

      <Section title="Datumsformat">
        <Select
          value={settings?.date_format || 'dd.mm.yyyy'}
          onChange={(v) => updateSetting('date_format', v)}
          options={[
            { value: 'dd.mm.yyyy', label: 'DD.MM.YYYY (31.12.2025)' },
            { value: 'yyyy-mm-dd', label: 'YYYY-MM-DD (2025-12-31)' },
          ]}
        />
      </Section>
    </div>
  )
}

function DataTab() {
  const { logout } = useAuth()
  const addToast = useToast()

  async function handleExport(type) {
    try {
      const res = await authFetch(`${API_BASE}/export/${type}`)
      if (!res.ok) throw new Error('Export fehlgeschlagen')
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${type}.csv`
      a.click()
      URL.revokeObjectURL(url)
      addToast('Export heruntergeladen', 'success')
    } catch (err) {
      addToast(err.message, 'error')
    }
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <Section title="Daten exportieren">
        <div className="flex gap-3">
          <button onClick={() => handleExport('portfolio')} className="flex items-center gap-2 bg-card-alt hover:bg-border/50 text-text-primary rounded-lg px-4 py-2 text-sm border border-border">
            <Download size={16} />
            Portfolio (CSV)
          </button>
          <button onClick={() => handleExport('transactions')} className="flex items-center gap-2 bg-card-alt hover:bg-border/50 text-text-primary rounded-lg px-4 py-2 text-sm border border-border">
            <Download size={16} />
            Transaktionen (CSV)
          </button>
        </div>
      </Section>
    </div>
  )
}

// --- Shared Components ---

function Section({ title, children }) {
  return (
    <div className="bg-card border border-border rounded-xl p-5">
      <h3 className="text-sm font-semibold text-text-primary mb-3">{title}</h3>
      {children}
    </div>
  )
}

function Input({ id, label, type = 'text', value, onChange }) {
  const inputId = id || `settings-${label.toLowerCase().replace(/[^a-z0-9]/g, '-')}`
  return (
    <div>
      <label htmlFor={inputId} className="block text-sm text-text-secondary mb-1">{label}</label>
      <input
        id={inputId}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required
        className="w-full bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
      />
    </div>
  )
}

function Select({ value, onChange, options }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  )
}
