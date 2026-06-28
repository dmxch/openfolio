import { NavLink, Link } from 'react-router-dom'
import { LogOut, X, MessageSquarePlus, Scale, Shield, Settings, HelpCircle, BookOpen } from 'lucide-react'
import { AlertBadge } from './AlertsBanner'
import DividendBadge from './DividendBadge'
import CacheStatus from './CacheStatus'
import { useAuth } from '../contexts/AuthContext'

const navGroups = [
  {
    label: 'Märkte',
    items: [
      { to: '/', label: 'Marktklima', end: true, tourId: 'sidebar-market' },
      { to: '/branchen', label: 'Branchen', tourId: 'sidebar-branchen' },
    ],
  },
  {
    label: 'Vermögen',
    items: [
      { to: '/portfolio', label: 'Portfolio', badge: true, tourId: 'sidebar-portfolio' },
      { to: '/performance', label: 'Performance', tourId: 'sidebar-performance' },
    ],
  },
  {
    label: 'Research',
    items: [
      { to: '/analysis', label: 'Watchlist', tourId: 'sidebar-watchlist' },
      { to: '/smart-money', label: 'Smart Money', tourId: 'sidebar-smart-money' },
      { to: '/eps-scanner', label: 'EPS-Scanner', tourId: 'sidebar-eps-scanner' },
    ],
  },
  {
    label: 'Verwaltung',
    items: [
      { to: '/transactions', label: 'Transaktionen', dividendBadge: true, tourId: 'sidebar-transactions' },
      { to: '/orders', label: 'Offene Orders', tourId: 'sidebar-orders' },
      { to: '/reports', label: 'Report-Vault', tourId: 'sidebar-reports' },
    ],
  },
]

function NavItem({ to, label, end, badge, dividendBadge, tourId, onNavigate }) {
  return (
    <NavLink
      to={to}
      end={end}
      onClick={onNavigate}
      data-tour={tourId || undefined}
      className={({ isActive }) =>
        `flex items-center gap-[11px] px-[10px] py-2 rounded-md text-[13.5px] transition-colors ${
          isActive
            ? 'bg-active-tint text-text-primary font-semibold shadow-[inset_3px_0_0_#5b8def]'
            : 'text-text-secondary font-medium hover:bg-hover hover:text-text-bright'
        }`
      }
    >
      {({ isActive }) => (
        <>
          <span
            className={`w-[6px] h-[6px] rounded-full flex-none ${
              isActive ? 'bg-primary shadow-[0_0_8px_#5b8def]' : 'bg-[#3a4453]'
            }`}
          />
          <span className="flex-1">{label}</span>
          {badge && <AlertBadge />}
          {dividendBadge && <DividendBadge />}
        </>
      )}
    </NavLink>
  )
}

function FooterLink({ to, href, icon: Icon, label, onNavigate }) {
  const cls =
    'flex items-center gap-[11px] px-[10px] py-2 rounded-md text-[13.5px] font-medium text-text-secondary hover:bg-hover hover:text-text-bright transition-colors'
  if (href) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" className={cls}>
        <Icon size={15} className="flex-none" />
        <span>{label}</span>
      </a>
    )
  }
  return (
    <NavLink to={to} onClick={onNavigate} className={({ isActive }) => `${cls} ${isActive ? 'text-text-primary' : ''}`}>
      <Icon size={15} className="flex-none" />
      <span>{label}</span>
    </NavLink>
  )
}

export default function Sidebar({ onNavigate }) {
  const { user, logout } = useAuth()
  const initials = (user?.email || '?').slice(0, 2).toUpperCase()

  return (
    <aside className="h-screen w-60 bg-sidebar border-r border-border-soft flex flex-col">
      {/* Logo */}
      <div className="flex items-center gap-[10px] px-5 pt-[18px] pb-4">
        <div className="w-[26px] h-[26px] rounded-[7px] flex items-center justify-center font-mono font-semibold text-sm text-[#06140d] bg-gradient-to-br from-[#5b8def] to-[#29c3b1]">
          O
        </div>
        <div className="font-semibold text-[15px] tracking-[-0.01em] text-text-primary flex-1">OpenFolio</div>
        <button
          onClick={onNavigate}
          className="md:hidden p-1.5 rounded-lg text-text-muted hover:text-text-primary hover:bg-hover transition-colors"
          aria-label="Menu schliessen"
        >
          <X size={20} />
        </button>
      </div>

      {/* Grouped nav */}
      <nav className="flex-1 overflow-y-auto px-3 pb-3">
        {navGroups.map((group) => (
          <div key={group.label}>
            <div className="font-mono text-[10px] tracking-[0.12em] uppercase text-[#4d5868] px-[10px] pt-[13px] pb-1.5">
              {group.label}
            </div>
            {group.items.map((item) => (
              <NavItem key={item.to} {...item} onNavigate={onNavigate} />
            ))}
          </div>
        ))}
        {user?.is_admin && (
          <div>
            <div className="font-mono text-[10px] tracking-[0.12em] uppercase text-[#4d5868] px-[10px] pt-[13px] pb-1.5">
              System
            </div>
            <FooterLink to="/admin" icon={Shield} label="Admin" onNavigate={onNavigate} />
          </div>
        )}
      </nav>

      {/* Footer */}
      <div className="border-t border-border-soft px-3 py-2.5">
        <FooterLink to="/settings" icon={Settings} label="Einstellungen" onNavigate={onNavigate} />
        <FooterLink to="/hilfe" icon={HelpCircle} label="Hilfe" onNavigate={onNavigate} />
        <FooterLink to="/glossar" icon={BookOpen} label="Glossar" onNavigate={onNavigate} />
        <FooterLink href="https://github.com/dmxch/openfolio/issues/new/choose" icon={MessageSquarePlus} label="Feedback" />
        <FooterLink to="/rechtliches" icon={Scale} label="Rechtliches" onNavigate={onNavigate} />

        <div className="px-[10px] pt-2.5">
          <CacheStatus />
        </div>

        {user && (
          <div className="flex items-center gap-[10px] px-2 pt-2.5 pb-1">
            <div className="w-[30px] h-[30px] rounded-full bg-[#1c2738] border border-[#2c3645] flex items-center justify-center text-xs font-semibold text-[#9bb4e8] flex-none">
              {initials}
            </div>
            <div className="leading-tight min-w-0 flex-1">
              <div className="text-[12.5px] font-semibold text-text-primary truncate">{user.email}</div>
              <div className="text-[11px] text-text-faint">Privat · CHF</div>
            </div>
            <button
              onClick={logout}
              className="text-text-muted hover:text-text-primary transition-colors flex-none"
              title="Abmelden"
              aria-label="Abmelden"
            >
              <LogOut size={14} />
            </button>
          </div>
        )}

        <p className="text-[11px] text-text-faint px-2 pt-1.5 flex items-center justify-between">
          <Link to="/changelog" className="hover:text-text-secondary transition-colors">v{__APP_VERSION__}</Link>
          <kbd data-tour="sidebar-ctrlk" className="text-[10px] bg-surface border border-border rounded px-1.5 py-0.5 font-mono text-text-muted">Ctrl+K</kbd>
        </p>
      </div>
    </aside>
  )
}
