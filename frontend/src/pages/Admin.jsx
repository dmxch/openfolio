import { useState, useEffect, useRef, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useApi, apiPost, apiPatch, apiDelete, authFetch } from '../hooks/useApi'
import { formatDate, formatDateRelative } from '../lib/format'
import { Trash2, Lock, LockOpen, ShieldCheck, ShieldOff, MoreVertical, Plus, Copy, Loader2, Mail, Key } from 'lucide-react'
import { useToast } from '../components/Toast'
import PageHeader from '../components/ui/PageHeader'
import Card from '../components/ui/Card'
import StatTile from '../components/ui/StatTile'
import Button from '../components/ui/Button'
import { Badge, tint } from '../components/ui/Badge'

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
    <div className="relative flex justify-end">
      <button ref={btnRef} onClick={() => setOpen(!open)} className="p-1.5 rounded-lg text-text-muted hover:text-text-primary hover:bg-hover transition-colors" aria-label="Aktionen öffnen" aria-expanded={showPopover}>
        <MoreVertical size={15} />
      </button>
      {showPopover && (
        <PortalDropdown anchorRef={btnRef} onClose={closeAll}>
          {tempPw ? (
            <div className="w-80 bg-modal border border-border-hover rounded-[12px] shadow-2xl p-4">
              <p className="text-sm text-text-primary font-medium mb-2">Temporäres Passwort</p>
              <div className="bg-surface border border-border-2 rounded-lg px-3 py-2 font-mono text-success text-sm mb-2 flex items-center justify-between">
                {tempPw}
                <button onClick={() => navigator.clipboard.writeText(tempPw)} className="text-text-muted hover:text-primary ml-2" aria-label="Kopieren"><Copy size={14} /></button>
              </div>
              <p className="text-xs text-text-secondary mb-3">Teile es dem User sicher mit. Der User wird beim nächsten Login aufgefordert, ein neues Passwort zu setzen.</p>
              <button onClick={closeAll} className="text-xs text-primary hover:underline">Schliessen</button>
            </div>
          ) : confirmAction === 'delete' ? (
            <div className="w-72 bg-modal border border-danger/40 rounded-[12px] shadow-2xl p-4">
              <p className="text-sm text-danger font-medium mb-2">User löschen?</p>
              <p className="text-xs text-text-secondary mb-3">Alle Daten von <strong>{u.email}</strong> werden unwiderruflich gelöscht.</p>
              <label htmlFor="admin-delete-confirm" className="text-xs text-text-secondary mb-1 block">E-Mail zur Bestätigung eingeben:</label>
              <input id="admin-delete-confirm" value={confirmEmail} onChange={(e) => setConfirmEmail(e.target.value)} className="w-full bg-surface border border-border-2 rounded-lg px-2 py-1.5 text-sm text-text-primary mb-3 focus:outline-none focus:border-danger" placeholder={u.email} />
              <div className="flex gap-2">
                <button onClick={() => { setConfirmAction(null); setConfirmEmail('') }} className="text-xs text-text-secondary hover:text-text-primary">Abbrechen</button>
                <button onClick={() => handleAction('delete')} disabled={confirmEmail !== u.email || loading} className="text-xs bg-danger text-white px-3 py-1 rounded-lg disabled:opacity-50">
                  {loading ? 'Lösche...' : 'Endgültig löschen'}
                </button>
              </div>
            </div>
          ) : confirmAction ? (
            <div className="w-72 bg-modal border border-border-hover rounded-[12px] shadow-2xl p-4">
              <p className="text-sm text-text-primary mb-3">
                {{ 'reset-email': `Reset-Link an ${u.email} senden?`, 'temp-password': `Temporäres Passwort für ${u.email} setzen?`, lock: `User ${u.email} sperren? Der User kann sich nicht mehr anmelden.`, unlock: `User ${u.email} entsperren?`, 'toggle-admin': u.is_admin ? `Admin-Recht von ${u.email} entziehen?` : `${u.email} zum Admin machen?` }[confirmAction]}
              </p>
              <div className="flex gap-2">
                <button onClick={() => setConfirmAction(null)} className="text-xs text-text-secondary hover:text-text-primary">Abbrechen</button>
                <button onClick={() => handleAction(confirmAction)} disabled={loading} className="text-xs bg-primary text-white px-3 py-1 rounded-lg disabled:opacity-50">
                  {loading ? 'Laden...' : 'Bestätigen'}
                </button>
              </div>
            </div>
          ) : (
            <div className="w-56 bg-modal border border-border-hover rounded-[12px] shadow-2xl py-1">
              <button onClick={() => { setOpen(false); setConfirmAction('reset-email') }} className="w-full text-left px-3 py-2 text-xs text-text-secondary hover:bg-hover flex items-center gap-2">
                <Mail size={13} /> Reset-Link senden
              </button>
              <button onClick={() => { setOpen(false); setConfirmAction('temp-password') }} className="w-full text-left px-3 py-2 text-xs text-text-secondary hover:bg-hover flex items-center gap-2">
                <Key size={13} /> Temporäres Passwort
              </button>
              <hr className="border-border-2 my-1" />
              {u.is_active ? (
                <button onClick={() => { setOpen(false); setConfirmAction('lock') }} disabled={isSelf} className="w-full text-left px-3 py-2 text-xs text-text-secondary hover:bg-hover flex items-center gap-2 disabled:opacity-30">
                  <LockOpen size={13} /> Sperren
                </button>
              ) : (
                <button onClick={() => { setOpen(false); setConfirmAction('unlock') }} className="w-full text-left px-3 py-2 text-xs text-text-secondary hover:bg-hover flex items-center gap-2">
                  <Lock size={13} /> Entsperren
                </button>
              )}
              <button onClick={() => { setOpen(false); setConfirmAction('toggle-admin') }} disabled={isSelf} className="w-full text-left px-3 py-2 text-xs text-text-secondary hover:bg-hover flex items-center gap-2 disabled:opacity-30">
                {u.is_admin ? <ShieldOff size={13} /> : <ShieldCheck size={13} />}
                {u.is_admin ? 'Admin-Recht entziehen' : 'Zum Admin machen'}
              </button>
              <hr className="border-border-2 my-1" />
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

function userInitials(email) {
  const local = (email || '').split('@')[0]
  const parts = local.split(/[._\-+]+/).filter(Boolean)
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
  return (local.slice(0, 2) || '??').toUpperCase()
}

function formatUserDate(iso) {
  if (!iso) return 'Nie'
  return formatDateRelative(iso)
}

function SectionHeader({ dot, title, count, right }) {
  return (
    <div className="px-[18px] py-4 border-b border-border-2 flex items-center justify-between gap-4">
      <div className="flex items-center gap-2.5 min-w-0">
        {dot && <span className="w-[9px] h-[9px] rounded-[3px]" style={{ background: dot }} />}
        <span className="text-sm font-semibold text-text-primary whitespace-nowrap">{title}</span>
        {count != null && <span className="font-mono text-[11px] text-text-faint">{count}</span>}
      </div>
      {right}
    </div>
  )
}

function UsersCard({ data, loading, refetch, currentUser }) {
  const [search, setSearch] = useState('')
  const users = (data?.users || []).filter((u) =>
    !search || u.email.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <Card className="overflow-hidden">
      <SectionHeader
        dot="#5b8def"
        title="Nutzerverwaltung"
        count={users.length}
        right={
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Nutzer suchen..."
            aria-label="Nutzer suchen"
            className="bg-surface border border-border rounded-lg px-3 py-[7px] text-[12.5px] text-text-primary placeholder:text-text-muted focus:outline-none focus:border-border-hover w-56"
          />
        }
      />

      {loading ? (
        <div className="p-[18px] flex flex-col gap-2">
          {[0, 1, 2, 3].map((i) => <div key={i} className="h-12 rounded-lg bg-hover animate-pulse" />)}
        </div>
      ) : users.length === 0 ? (
        <p className="text-sm text-text-muted py-10 text-center">Keine Nutzer gefunden.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-table-head border-b border-border-2 font-mono text-[10px] tracking-[0.05em] uppercase text-text-faint">
                <th className="text-left px-[18px] py-[11px] font-medium">Nutzer</th>
                <th className="text-left px-3 py-[11px] font-medium">Rolle</th>
                <th className="text-center px-3 py-[11px] font-medium">MFA</th>
                <th className="text-left px-3 py-[11px] font-medium">Letzter Login</th>
                <th className="text-left px-3 py-[11px] font-medium">Status</th>
                <th className="px-3 py-[11px] w-12" />
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b border-border-row hover:bg-hover transition-colors">
                  <td className="px-[18px] py-3">
                    <div className="flex items-center gap-3 min-w-0">
                      <div className="w-8 h-8 rounded-lg bg-primary/15 text-primary flex items-center justify-center text-[11px] font-semibold font-mono shrink-0">
                        {userInitials(u.email)}
                      </div>
                      <div className="min-w-0">
                        <div className="text-text-primary text-[13px] truncate">{u.email}</div>
                        {u.force_password_change && (
                          <div className="text-[10.5px] text-warning mt-0.5">PW-Wechsel nötig</div>
                        )}
                      </div>
                    </div>
                  </td>
                  <td className="px-3 py-3">
                    {u.is_admin ? (
                      <Badge color="#5b8def" bg={tint('#5b8def')}>Admin</Badge>
                    ) : (
                      <Badge color="#7a8698" bg={tint('#7a8698')}>Nutzer</Badge>
                    )}
                  </td>
                  <td className="px-3 py-3 text-center font-mono">
                    {u.mfa_enabled ? <span className="text-success">✓</span> : <span className="text-text-faint">✕</span>}
                  </td>
                  <td className="px-3 py-3 font-mono text-[11.5px] text-text-secondary whitespace-nowrap">{formatUserDate(u.last_login_at)}</td>
                  <td className="px-3 py-3">
                    {u.is_active ? (
                      <Badge color="#45c08a" bg={tint('#45c08a')}>Aktiv</Badge>
                    ) : (
                      <Badge color="#e8625a" bg={tint('#e8625a')}>Gesperrt</Badge>
                    )}
                  </td>
                  <td className="px-3 py-3">
                    <UserActions u={u} currentUser={currentUser} onRefresh={refetch} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

function InviteCodesCard({ codes, onGenerate, onDeactivate, generating }) {
  return (
    <Card className="overflow-hidden flex flex-col">
      <SectionHeader
        dot="#29c3b1"
        title="Einladungscodes"
        count={codes.length}
        right={
          <Button variant="secondary" icon={generating ? undefined : Plus} onClick={onGenerate} disabled={generating}>
            {generating && <Loader2 size={14} className="animate-spin" />}
            Neuer Code
          </Button>
        }
      />
      {codes.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-table-head border-b border-border-2 font-mono text-[10px] tracking-[0.05em] uppercase text-text-faint">
                <th className="text-left px-[18px] py-[11px] font-medium">Code</th>
                <th className="text-left px-3 py-[11px] font-medium">Erstellt</th>
                <th className="text-left px-3 py-[11px] font-medium">Status</th>
                <th className="px-3 py-[11px] w-10" />
              </tr>
            </thead>
            <tbody>
              {codes.map((c) => (
                <tr key={c.id} className="border-b border-border-row hover:bg-hover transition-colors">
                  <td className="px-[18px] py-3 font-mono text-text-primary text-xs">{c.code}</td>
                  <td className="px-3 py-3 font-mono text-[11.5px] text-text-secondary whitespace-nowrap">{formatDate(c.created_at)}</td>
                  <td className="px-3 py-3">
                    {c.used_by_email ? (
                      <Badge color="#45c08a" bg={tint('#45c08a')}>Eingelöst</Badge>
                    ) : c.is_active ? (
                      <Badge color="#5b8def" bg={tint('#5b8def')}>Aktiv</Badge>
                    ) : (
                      <Badge color="#7a8698" bg={tint('#7a8698')}>Deaktiviert</Badge>
                    )}
                  </td>
                  <td className="px-3 py-3 text-right">
                    {c.is_active && !c.used_by_email && (
                      <button onClick={() => onDeactivate(c.id)} className="p-1.5 rounded-lg text-text-muted hover:text-danger hover:bg-danger/10 transition-colors" aria-label="Code widerrufen" title="Widerrufen">
                        <Trash2 size={13} />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-xs text-text-muted px-[18px] py-8 text-center">Noch keine Codes erstellt.</p>
      )}
      <p className="text-[11px] text-text-faint px-[18px] py-3 border-t border-border-2 mt-auto">Einladungscodes sind einmalig verwendbar.</p>
    </Card>
  )
}

function MaintenanceCard({ mode, onChangeMode, saving, worker, workerLoading }) {
  const regModes = [
    { value: 'open', label: 'Offen', desc: 'Jeder kann sich registrieren', tone: 'warning' },
    { value: 'invite_only', label: 'Geschlossen', desc: 'Nur mit Einladungscode', tone: 'default' },
    { value: 'disabled', label: 'Deaktiviert', desc: 'Keine neuen Registrierungen', tone: 'default' },
  ]
  const jobs = worker?.jobs || []
  const summary = worker?.summary || {}

  function jobDot(j) {
    if (j.is_failing) return '#e8625a'
    if (j.is_stale) return '#e0a64b'
    return '#45c08a'
  }

  return (
    <Card className="overflow-hidden">
      <SectionHeader dot="#e0a64b" title="Wartung & Sicherheit" />

      <div className="px-[18px] py-4 border-b border-border-2">
        <div className="flex items-center justify-between mb-3">
          <div className="font-mono text-[10.5px] tracking-[0.06em] uppercase text-text-label">Registrierung</div>
          {saving && <Loader2 size={13} className="animate-spin text-text-muted" />}
        </div>
        <div className="flex flex-col gap-1.5">
          {regModes.map((opt) => {
            const active = mode === opt.value
            return (
              <label
                key={opt.value}
                className={`flex items-start gap-3 cursor-pointer rounded-lg px-2.5 py-2 border transition-colors ${
                  active
                    ? opt.tone === 'warning'
                      ? 'border-warning/40 bg-warning/10'
                      : 'border-border-active bg-active-tint'
                    : 'border-transparent hover:bg-hover'
                }`}
              >
                <input
                  type="radio"
                  name="reg_mode"
                  value={opt.value}
                  checked={active}
                  onChange={() => onChangeMode(opt.value)}
                  className="mt-0.5"
                />
                <div>
                  <span className={`text-[13px] font-medium ${active && opt.tone === 'warning' ? 'text-warning' : 'text-text-primary'}`}>{opt.label}</span>
                  <span className="text-[11.5px] text-text-muted ml-2">— {opt.desc}</span>
                </div>
              </label>
            )
          })}
        </div>
      </div>

      <div className="px-[18px] py-4">
        <div className="flex items-center justify-between mb-3">
          <div className="font-mono text-[10.5px] tracking-[0.06em] uppercase text-text-label">Worker-Jobs</div>
          <span className="font-mono text-[11px] text-text-faint">
            {summary.total || 0} Jobs
            {summary.failing ? <span className="text-danger"> · {summary.failing} Fehler</span> : null}
            {summary.stale ? <span className="text-warning"> · {summary.stale} veraltet</span> : null}
          </span>
        </div>
        {workerLoading ? (
          <div className="flex flex-col gap-1.5">
            {[0, 1, 2].map((i) => <div key={i} className="h-7 rounded-lg bg-hover animate-pulse" />)}
          </div>
        ) : jobs.length === 0 ? (
          <p className="text-xs text-text-muted py-2">Keine Worker-Daten vorhanden.</p>
        ) : (
          <div className="flex flex-col gap-0.5 max-h-72 overflow-y-auto">
            {jobs.map((j) => (
              <div
                key={j.job_id}
                className={`flex items-center justify-between px-2.5 py-1.5 rounded-lg ${
                  j.is_failing ? 'bg-danger/10' : j.is_stale ? 'bg-warning/10' : 'hover:bg-hover'
                } transition-colors`}
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: jobDot(j) }} />
                  <span className="font-mono text-[11.5px] text-text-secondary truncate">{j.job_id}</span>
                </div>
                <span className="font-mono text-[11px] text-text-faint whitespace-nowrap ml-3">
                  {j.last_run_at ? formatDateRelative(j.last_run_at) : 'nie gelaufen'}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </Card>
  )
}

function AuditLogCard() {
  const [page, setPage] = useState(1)
  // useApi refetcht bei Endpoint-String-Wechsel automatisch -> page in die URL.
  const { data, loading } = useApi(`/admin/audit-log?page=${page}&per_page=50`)
  const entries = data?.entries || []
  const pages = data?.pages || 1

  return (
    <Card className="overflow-hidden">
      <SectionHeader dot="#7a8698" title="Audit-Log" count={data?.total ?? undefined} />
      {loading ? (
        <div className="p-[18px] flex flex-col gap-2">
          {[0, 1, 2, 3].map((i) => <div key={i} className="h-9 rounded-lg bg-hover animate-pulse" />)}
        </div>
      ) : entries.length === 0 ? (
        <p className="text-sm text-text-muted py-10 text-center">Noch keine Audit-Log-Einträge.</p>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-table-head border-b border-border-2 font-mono text-[10px] tracking-[0.05em] uppercase text-text-faint">
                  <th className="text-left px-[18px] py-[11px] font-medium">Zeitpunkt</th>
                  <th className="text-left px-3 py-[11px] font-medium">Admin</th>
                  <th className="text-left px-3 py-[11px] font-medium">Aktion</th>
                  <th className="text-left px-3 py-[11px] font-medium">Ziel-User</th>
                  <th className="text-left px-3 py-[11px] font-medium">Details</th>
                  <th className="text-left px-3 py-[11px] font-medium">IP</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e) => (
                  <tr key={e.id} className="border-b border-border-row hover:bg-hover transition-colors">
                    <td className="px-[18px] py-3 font-mono text-[11.5px] text-text-secondary whitespace-nowrap">{e.created_at ? formatDate(e.created_at) : '—'}</td>
                    <td className="px-3 py-3 text-text-primary text-xs">{e.admin_email || e.admin_id || 'System'}</td>
                    <td className="px-3 py-3 text-text-secondary font-mono text-xs">{e.action}</td>
                    <td className="px-3 py-3 text-text-secondary font-mono text-xs">{e.target_user_id || '—'}</td>
                    <td className="px-3 py-3 text-text-secondary text-xs">{e.details || '—'}</td>
                    <td className="px-3 py-3 text-text-secondary font-mono text-xs">{e.ip_address || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="px-[18px] py-3 border-t border-border-2 flex items-center justify-between text-sm">
            <span className="text-text-muted text-xs">{data?.total ?? 0} Einträge</span>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="px-3 py-1 rounded-lg bg-surface border border-border-2 text-text-secondary hover:border-border-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors text-xs"
              >
                Zurück
              </button>
              <span className="text-text-secondary text-xs font-mono tabular-nums px-2">{data?.page ?? page} / {pages}</span>
              <button
                onClick={() => setPage((p) => (p < pages ? p + 1 : p))}
                disabled={page >= pages}
                className="px-3 py-1 rounded-lg bg-surface border border-border-2 text-text-secondary hover:border-border-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors text-xs"
              >
                Weiter
              </button>
            </div>
          </div>
        </>
      )}
    </Card>
  )
}

function AdminConsole({ currentUser }) {
  const { data: usersData, loading: usersLoading, refetch: refetchUsers } = useApi('/admin/users')
  const { data: workerData, loading: workerLoading } = useApi('/admin/worker-health')
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

  const users = usersData?.users || []
  const totalUsers = usersData?.total ?? users.length
  const adminCount = users.filter((u) => u.is_admin).length
  const activeCount = users.filter((u) => u.is_active).length
  const lockedCount = users.filter((u) => !u.is_active).length
  const mfaCount = users.filter((u) => u.mfa_enabled).length

  const codes = codesData?.codes || []

  const wSummary = workerData?.summary || {}
  const wJobs = workerData?.jobs || []
  const workerStatus = wSummary.failing > 0 ? 'Fehler' : wSummary.stale > 0 ? 'Veraltet' : 'OK'
  const workerTone = wSummary.failing > 0 ? 'danger' : wSummary.stale > 0 ? 'warning' : 'success'
  const lastRun = wJobs.reduce((acc, j) => (j.last_run_at && (!acc || j.last_run_at > acc) ? j.last_run_at : acc), null)

  return (
    <div className="pb-10">
      <PageHeader
        title="Admin"
        subtitle="Nutzer · Einladungen · Worker"
        showBell={false}
        actions={
          <Button variant="primary" icon={Plus} onClick={generateCode} disabled={generating}>
            Nutzer einladen
          </Button>
        }
      />
      <div className="flex flex-col gap-[18px]">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-[14px]">
          <StatTile label="Nutzer" value={totalUsers} sub={`${adminCount} Admin${adminCount !== 1 ? 's' : ''}`} />
          <StatTile
            label="Aktiv"
            value={activeCount}
            sub={lockedCount ? `${lockedCount} gesperrt` : 'keine gesperrt'}
            subTone={lockedCount ? 'warning' : 'default'}
          />
          <StatTile
            label="MFA aktiv"
            value={mfaCount}
            tone={mfaCount ? 'success' : 'default'}
            sub={`von ${totalUsers}`}
          />
          <StatTile
            label="Worker"
            value={workerLoading ? '—' : workerStatus}
            tone={workerTone}
            mono={false}
            sub={lastRun ? `Letzter Lauf ${formatDateRelative(lastRun)}` : 'kein Lauf'}
          />
        </div>

        <UsersCard data={usersData} loading={usersLoading} refetch={refetchUsers} currentUser={currentUser} />

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-[18px] items-start">
          <InviteCodesCard codes={codes} onGenerate={generateCode} onDeactivate={deactivateCode} generating={generating} />
          <MaintenanceCard mode={mode} onChangeMode={saveMode} saving={saving} worker={workerData} workerLoading={workerLoading} />
        </div>

        <AuditLogCard />
      </div>
    </div>
  )
}

export default function Admin() {
  const { user } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    if (user && !user.is_admin) navigate('/portfolio')
  }, [user])

  if (!user?.is_admin) return null

  return <AdminConsole currentUser={user} />
}
