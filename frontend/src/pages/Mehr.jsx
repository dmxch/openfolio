import { NavLink } from 'react-router-dom'
import { LogOut, ChevronRight } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import DividendBadge from '../components/DividendBadge'
import PageHeader from '../components/ui/PageHeader'

// Mobile-Overflow ("Mehr"): alle Sekundär-Ziele, die nicht in der Bottom-Nav sind.
const GROUPS = [
  { label: 'Research', items: [
    { to: '/branchen', label: 'Branchen', code: 'BR', color: '#5b8def' },
    { to: '/smart-money', label: 'Smart Money', code: 'SM', color: '#45c08a' },
    { to: '/eps-scanner', label: 'EPS-Scanner', code: 'EP', color: '#e0a64b' },
  ] },
  { label: 'Verwaltung', items: [
    { to: '/transactions', label: 'Transaktionen', code: 'TX', color: '#29c3b1', dividendBadge: true },
    { to: '/orders', label: 'Offene Orders', code: 'OO', color: '#b06ee8' },
    { to: '/reports', label: 'Report-Vault', code: 'RV', color: '#6b8aa0' },
  ] },
  { label: 'System', items: [
    { to: '/settings', label: 'Einstellungen', code: 'ES', color: '#9aa6b6' },
    { to: '/hilfe', label: 'Hilfe', code: 'HI', color: '#9aa6b6' },
    { to: '/glossar', label: 'Glossar', code: 'GL', color: '#9aa6b6' },
    { to: '/rechtliches', label: 'Rechtliches', code: 'RE', color: '#9aa6b6' },
  ] },
]

const tint = (hex, a = 0.14) => {
  const n = parseInt(hex.slice(1), 16)
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`
}

function Row({ to, label, code, color, dividendBadge }) {
  return (
    <NavLink
      to={to}
      className="flex items-center gap-[13px] px-[15px] py-[14px] border-b border-border-row last:border-b-0 hover:bg-hover transition-colors"
    >
      <span className="w-[30px] h-[30px] rounded-[9px] flex items-center justify-center font-mono text-[11px] font-semibold flex-none" style={{ color, background: tint(color) }}>
        {code}
      </span>
      <span className="flex-1 text-sm text-text-primary">{label}</span>
      {dividendBadge && <DividendBadge />}
      <ChevronRight size={16} className="text-text-faint" />
    </NavLink>
  )
}

export default function Mehr() {
  const { user, logout } = useAuth()
  const initials = (user?.email || '?').slice(0, 2).toUpperCase()
  const groups = user?.is_admin
    ? [...GROUPS, { label: 'Admin', items: [{ to: '/admin', label: 'Admin', code: 'AD', color: '#5b8def' }] }]
    : GROUPS

  return (
    <div className="pb-10">
      <PageHeader title="Mehr" showSearch={false} showBell={false} />
      <div className="flex flex-col gap-4">
        {/* Profil */}
        <div className="flex items-center gap-[13px] bg-card border border-border rounded-card p-4">
          <div className="w-[46px] h-[46px] rounded-full bg-active-tint border border-border-hover flex items-center justify-center text-base font-semibold text-link flex-none">
            {initials}
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-[15px] font-semibold text-text-primary truncate">{user?.email}</div>
            <div className="text-xs text-text-faint">Privat · CHF</div>
          </div>
        </div>

        {groups.map((g) => (
          <div key={g.label}>
            <div className="font-mono text-[10px] tracking-[0.08em] uppercase text-text-faint px-1 pb-2">{g.label}</div>
            <div className="bg-card border border-border rounded-card overflow-hidden">
              {g.items.map((it) => <Row key={it.to} {...it} />)}
            </div>
          </div>
        ))}

        <button
          onClick={logout}
          className="flex items-center justify-center gap-2 bg-card border border-border rounded-card py-3 text-sm text-danger hover:bg-hover transition-colors"
        >
          <LogOut size={16} /> Abmelden
        </button>

        <p className="text-center font-mono text-[11px] text-text-faint pt-1">OpenFolio · v{__APP_VERSION__}</p>
      </div>
    </div>
  )
}
