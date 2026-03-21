import { useState, useEffect, useRef, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useApi, apiPost, apiPatch, apiDelete, authFetch } from '../hooks/useApi'
import { formatDate, formatDateRelative } from '../lib/format'
import { Shield, Users, Settings, Trash2, Lock, LockOpen, ShieldCheck, ShieldOff, MoreVertical, Plus, Copy, Loader2, Mail, Key } from 'lucide-react'
import { useToast } from '../components/Toast'

function PortalDropdown({ anchorRef, children, onClose }) {
  const [pos, setPos] = useState(null)

  useEffect(() => {
    function update() {
      if (!anchorRef.current) return
      const rect = anchorRef.current.getBoundingClientRect()
      setPos({ top: rect.bottom + 4, right: window.innerWidth - rect.right })
    }
    update()
    window.addEventListener('scroll', update, true)
    window.addEventListener('resize', update)
    return () => {
      window.removeEventListener('scroll', update, true)
      window.removeEventListener('resize', update)
    }
  }, [anchorRef])

  if (!pos) return null

  return createPortal(
    <>
      <div className="fixed inset-0 z-[9998]" onClick={onClose} />
      <div className="fixed z-[9999]" style={{ top: pos.top, right: pos.right }}>
        {children}
      </div>
    </>,
    document.body
  )
}

function UserActions({ u, currentUser, onRefresh }) {
  const [open, setOpen] = useState(false)
  const [confirmAction, setConfirmAction] = useState(null)
  const [confirmEmail, setConfirmEmail] = useState('')
  const [tempPw, setTempPw] = useState(null)
  const [loading, setLoading] = useState(false)
  const btnRef = useRef(null)
  const toast = useToast()

  const isSelf = u.id === currentUser?.id
  const closeAll = useCallback(() => { setOpen(false); setConfirmAction(null); setConfirmEmail(''); setTempPw(null) }, [])

  async function handleAction(action) {
    setLoading(true)
    try {
      if (action === 'reset-email') {
        await apiPost(`/admin/users/${u.id}/reset-password`)
        setConfirmAction(null)
        onRefresh()
      } else if (action === 'temp-password') {
        const res = await authFetch(`/api/admin/users/${u.id}/temp-password`, { method: 'POST' })
        const data = await res.json()
        setTempPw(data.temp_password)
        setConfirmAction(null)
        onRefresh()
      } else if (action === 'lock') {
        await apiPatch(`/admin/users/${u.id}/status`, { is_active: false })
        setConfirmAction(null)
        onRefresh()
      } else if (action === 'unlock') {
        await apiPatch(`/admin/users/${u.id}/status`, { is_active: true })
        setConfirmAction(null)
        onRefresh()
      } else if (action === 'toggle-admin') {
        await apiPatch(`/admin/users/${u.id}/admin`, { is_admin: !u.is_admin })
        setConfirmAction(null)
        onRefresh()
      } else if (action === 'delete') {
        await apiDelete(`/admin/users/${u.id}`)
        setConfirmAction(null)
        onRefresh()
      }
    } catch (err) {
      toast(err.message || 'Fehler', 'error')
    } finally {
      setLoading(false)
    }
  }

  const showPopover = open || confirmAction || tempPw

  return (
    <div className="relative">
      <button ref={btnRef} onClick={() => setOpen(!open)} className="p-1.5 rounded text-text-muted hover:text-text-primary hover:bg-card-alt transition-colors" aria-label="Aktionen öffnen">
        <MoreVertical size={14} />
      </button>
      {showPopover && (
        <PortalDropdown anchorRef={btnRef} onClose={closeAll}>
          {tempPw ? (
            <div className="w-80 bg-card border border-border rounded-lg shadow-xl p-4">
              <p className="text-sm text-text-primary font-medium mb-2">Temporäres Passwort</p>
              <div className="bg-body border border-border rounded px-3 py-2 font-mono text-success text-sm mb-2 flex items-center justify-between">
                {tempPw}
                <button onClick={() => navigator.clipboard.writeText(tempPw)} className="text-text-muted hover:text-primary ml-2" aria-label="Kopieren"><Copy size={14} /></button>
              </div>
              <p className="text-xs text-text-muted mb-3">Teile es dem User sicher mit. Der User wird beim nächsten Login aufgefordert, ein neues Passwort zu setzen.</p>
              <button onClick={closeAll} className="text-xs text-primary hover:underline">Schliessen</button>
            </div>
          ) : confirmAction === 'delete' ? (
            <div className="w-72 bg-card border border-danger/30 rounded-lg shadow-xl p-4">
              <p className="text-sm text-danger font-medium mb-2">User löschen?</p>
              <p className="text-xs text-text-muted mb-3">Alle Daten von <strong>{u.email}</strong> werden unwiderruflich gelöscht.</p>
              <label htmlFor="admin-delete-confirm" className="text-xs text-text-secondary mb-1 block">E-Mail zur Bestätigung eingeben:</label>
              <input id="admin-delete-confirm" value={confirmEmail} onChange={(e) => setConfirmEmail(e.target.value)} className="w-full bg-body border border-border rounded px-2 py-1.5 text-sm text-text-primary mb-3 focus:outline-none focus:border-danger" placeholder={u.email} />
              <div className="flex gap-2">
                <button onClick={() => { setConfirmAction(null); setConfirmEmail('') }} className="text-xs text-text-muted hover:text-text-primary">Abbrechen</button>
                <button onClick={() => handleAction('delete')} disabled={confirmEmail !== u.email || loading} className="text-xs bg-danger text-white px-3 py-1 rounded disabled:opacity-50">
                  {loading ? 'Lösche...' : 'Endgültig löschen'}
                </button>
              </div>
            </div>
          ) : confirmAction ? (
            <div className="w-72 bg-card border border-border rounded-lg shadow-xl p-4">
              <p className="text-sm text-text-primary mb-3">
                {{ 'reset-email': `Reset-Link an ${u.email} senden?`, 'temp-password': `Temporäres Passwort für ${u.email} setzen?`, lock: `User ${u.email} sperren? Der User kann sich nicht mehr anmelden.`, unlock: `User ${u.email} entsperren?`, 'toggle-admin': u.is_admin ? `Admin-Recht von ${u.email} entziehen?` : `${u.email} zum Admin machen?` }[confirmAction]}
              </p>
              <div className="flex gap-2">
                <button onClick={() => setConfirmAction(null)} className="text-xs text-text-muted hover:text-text-primary">Abbrechen</button>
                <button onClick={() => handleAction(confirmAction)} disabled={loading} className="text-xs bg-primary text-white px-3 py-1 rounded disabled:opacity-50">
                  {loading ? 'Laden...' : 'Bestätigen'}
                </button>
              </div>
            </div>
          ) : (
            <div className="w-56 bg-card border border-border rounded-lg shadow-xl py-1">
              <button onClick={() => { setOpen(false); setConfirmAction('reset-email') }} className="w-full text-left px-3 py-2 text-xs text-text-secondary hover:bg-card-alt flex items-center gap-2">
                <Mail size={13} /> Reset-Link senden
              </button>
              <button onClick={() => { setOpen(false); setConfirmAction('temp-password') }} className="w-full text-left px-3 py-2 text-xs text-text-secondary hover:bg-card-alt flex items-center gap-2">
                <Key size={13} /> Temporäres Passwort
              </button>
              <hr className="border-border my-1" />
              {u.is_active ? (
                <button onClick={() => { setOpen(false); setConfirmAction('lock') }} disabled={isSelf} className="w-full text-left px-3 py-2 text-xs text-text-secondary hover:bg-card-alt flex items-center gap-2 disabled:opacity-30">
                  <LockOpen size={13} /> Sperren
                </button>
              ) : (
                <button onClick={() => { setOpen(false); setConfirmAction('unlock') }} className="w-full text-left px-3 py-2 text-xs text-text-secondary hover:bg-card-alt flex items-center gap-2">
                  <Lock size={13} /> Entsperren
                </button>
              )}
              <button onClick={() => { setOpen(false); setConfirmAction('toggle-admin') }} disabled={isSelf} className="w-full text-left px-3 py-2 text-xs text-text-secondary hover:bg-card-alt flex items-center gap-2 disabled:opacity-30">
                {u.is_admin ? <ShieldOff size={13} /> : <ShieldCheck size={13} />}
                {u.is_admin ? 'Admin-Recht entziehen' : 'Zum Admin machen'}
              </button>
              <hr className="border-border my-1" />
              <button onClick={() => { setOpen(false); setConfirmAction('delete') }} disabled={isSelf} className="w-full text-left px-3 py-2 text-xs text-danger hover:bg-danger/10 flex items-center gap-2 disabled:opacity-30">
                <Trash2 size={13} /> User löschen
              </button>
            </div>
          )}
        </PortalDropdown>
      )}
    </div>
  )
}

function UsersTab() {
  const { user: currentUser } = useAuth()
  const { data, loading, refetch } = useApi('/admin/users')
  const [search, setSearch] = useState('')

  const users = (data?.users || []).filter((u) =>
    !search || u.email.toLowerCase().includes(search.toLowerCase())
  )

  function formatUserDate(iso) {
    if (!iso) return 'Nie'
    return formatDateRelative(iso)
  }

  return (
    <div>
      <div className="mb-4">
        <label htmlFor="admin-user-search" className="sr-only">User suchen</label>
        <input
          id="admin-user-search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="User suchen..."
          className="bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 w-64"
        />
      </div>

      {loading ? (
        <div className="text-center py-8"><Loader2 size={20} className="animate-spin text-text-muted mx-auto" /></div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-text-muted">
                <th className="text-left p-3 font-medium">E-Mail</th>
                <th className="text-left p-3 font-medium">Registriert</th>
                <th className="text-left p-3 font-medium">Letzter Login</th>
                <th className="text-left p-3 font-medium">Status</th>
                <th className="text-center p-3 font-medium">MFA</th>
                <th className="p-3 w-12"></th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b border-border/50 hover:bg-card-alt/50">
                  <td className="p-3 text-text-primary font-medium">{u.email}</td>
                  <td className="p-3 text-text-secondary">{formatUserDate(u.created_at)}</td>
                  <td className="p-3 text-text-secondary">{formatUserDate(u.last_login_at)}</td>
                  <td className="p-3">
                    {u.is_active ? (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-success/10 text-success">
                        Aktiv{u.is_admin ? ' (Admin)' : ''}
                      </span>
                    ) : (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-danger/10 text-danger">Gesperrt</span>
                    )}
                  </td>
                  <td className="p-3 text-center">
                    {u.mfa_enabled ? (
                      <span className="text-success text-xs">Aktiv</span>
                    ) : (
                      <span className="text-text-muted text-xs">Aus</span>
                    )}
                  </td>
                  <td className="p-3 relative">
                    <UserActions u={u} currentUser={currentUser} onRefresh={refetch} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function SettingsTab() {
  const { data: settingsData, refetch: refetchSettings } = useApi('/admin/settings')
  const { data: codesData, refetch: refetchCodes } = useApi('/admin/invite-codes')
  const [mode, setMode] = useState(null)
  const [saving, setSaving] = useState(false)
  const [generating, setGenerating] = useState(false)
  const toast = useToast()

  useEffect(() => {
    if (settingsData?.registration_mode && mode === null) {
      setMode(settingsData.registration_mode)
    }
  }, [settingsData])

  async function saveMode(newMode) {
    setMode(newMode)
    setSaving(true)
    try {
      await apiPatch('/admin/settings', { registration_mode: newMode })
      refetchSettings()
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  async function generateCode() {
    setGenerating(true)
    try {
      await apiPost('/admin/invite-codes')
      refetchCodes()
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setGenerating(false)
    }
  }

  async function deactivateCode(id) {
    try {
      await apiDelete(`/admin/invite-codes/${id}`)
      refetchCodes()
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  const codes = codesData?.codes || []

  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-border bg-card p-5">
        <h3 className="text-sm font-medium text-text-primary mb-4">Registrierung</h3>
        <div className="space-y-2">
          {[
            { value: 'open', label: 'Offen', desc: 'Jeder kann sich registrieren' },
            { value: 'invite_only', label: 'Geschlossen', desc: 'Nur mit Einladungscode' },
            { value: 'disabled', label: 'Deaktiviert', desc: 'Keine neuen Registrierungen' },
          ].map((opt) => (
            <label key={opt.value} className="flex items-start gap-3 cursor-pointer p-2 rounded hover:bg-card-alt/50">
              <input
                type="radio"
                name="reg_mode"
                value={opt.value}
                checked={mode === opt.value}
                onChange={() => saveMode(opt.value)}
                className="mt-0.5"
              />
              <div>
                <span className="text-sm text-text-primary font-medium">{opt.label}</span>
                <span className="text-xs text-text-muted ml-2">— {opt.desc}</span>
              </div>
            </label>
          ))}
        </div>
      </div>

      {mode === 'invite_only' && (
        <div className="rounded-lg border border-border bg-card p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-medium text-text-primary">Einladungscodes</h3>
            <button
              onClick={generateCode}
              disabled={generating}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-primary/10 text-primary hover:bg-primary/20 transition-colors disabled:opacity-50"
            >
              {generating ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
              Neuen Code generieren
            </button>
          </div>

          {codes.length > 0 ? (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-text-muted">
                  <th className="text-left p-2 font-medium">Code</th>
                  <th className="text-left p-2 font-medium">Erstellt</th>
                  <th className="text-left p-2 font-medium">Genutzt von</th>
                  <th className="text-left p-2 font-medium">Status</th>
                  <th className="p-2 w-10"></th>
                </tr>
              </thead>
              <tbody>
                {codes.map((c) => (
                  <tr key={c.id} className="border-b border-border/50">
                    <td className="p-2 font-mono text-text-primary text-xs">{c.code}</td>
                    <td className="p-2 text-text-secondary text-xs">{formatDate(c.created_at)}</td>
                    <td className="p-2 text-text-secondary text-xs">{c.used_by_email || '—'}</td>
                    <td className="p-2">
                      {c.used_by_email ? (
                        <span className="text-xs text-success">Eingelöst</span>
                      ) : c.is_active ? (
                        <span className="text-xs text-primary">Aktiv</span>
                      ) : (
                        <span className="text-xs text-text-muted">Deaktiviert</span>
                      )}
                    </td>
                    <td className="p-2">
                      {c.is_active && !c.used_by_email && (
                        <button onClick={() => deactivateCode(c.id)} className="text-text-muted hover:text-danger p-1" aria-label="Code deaktivieren">
                          <Trash2 size={12} />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="text-xs text-text-muted">Noch keine Codes erstellt.</p>
          )}
          <p className="text-xs text-text-muted mt-3">Einladungscodes sind einmalig verwendbar.</p>
        </div>
      )}
    </div>
  )
}

export default function Admin() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [tab, setTab] = useState('users')

  useEffect(() => {
    if (user && !user.is_admin) navigate('/portfolio')
  }, [user])

  if (!user?.is_admin) return null

  const tabs = [
    { key: 'users', label: 'User-Verwaltung', icon: Users },
    { key: 'settings', label: 'Einstellungen', icon: Settings },
  ]

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Shield size={20} className="text-primary" />
        <h1 className="text-xl font-bold text-text-primary">Admin-Panel</h1>
      </div>

      <div className="flex gap-1 p-1 bg-card-alt/50 rounded-lg w-fit border border-border">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md transition-colors ${
              tab === t.key ? 'bg-primary text-white' : 'text-text-muted hover:text-text-primary'
            }`}
          >
            <t.icon size={14} />
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'users' && <UsersTab />}
      {tab === 'settings' && <SettingsTab />}
    </div>
  )
}
