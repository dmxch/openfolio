import { NavLink } from 'react-router-dom'
import { BarChart3, Briefcase, Search, ArrowLeftRight, Settings, LogOut, Shield, X, HelpCircle, MessageSquarePlus, Scale } from 'lucide-react'
import { AlertBadge } from './AlertsBanner'
import CacheStatus from './CacheStatus'
import { useAuth } from '../contexts/AuthContext'

const navItems = [
  { to: '/', label: 'Markt & Sektoren', icon: BarChart3, tourId: 'sidebar-market' },
  { to: '/portfolio', label: 'Portfolio', icon: Briefcase, badge: true, tourId: 'sidebar-portfolio' },
  { to: '/analysis', label: 'Watchlist', icon: Search, tourId: 'sidebar-watchlist' },
  { to: '/transactions', label: 'Transaktionen', icon: ArrowLeftRight, tourId: 'sidebar-transactions' },
  { to: '/settings', label: 'Einstellungen', icon: Settings },
  { to: '/hilfe', label: 'Hilfe', icon: HelpCircle, tourId: 'sidebar-hilfe' },
]

export default function Sidebar({ onNavigate }) {
  const { user, logout } = useAuth()

  return (
    <aside className="h-screen w-60 bg-card border-r border-border flex flex-col">
      <div className="p-5 border-b border-border flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold text-text-primary">OpenFolio</h1>
          <p className="text-xs text-text-muted mt-0.5">Portfolio & Marktanalyse</p>
        </div>
        <button
          onClick={onNavigate}
          className="md:hidden p-1.5 rounded-lg text-text-muted hover:text-text-primary hover:bg-card-alt transition-colors"
          aria-label="Menu schliessen"
        >
          <X size={20} />
        </button>
      </div>
      <nav className="flex-1 py-4">
        {navItems.map(({ to, label, icon: Icon, badge, tourId }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            onClick={onNavigate}
            data-tour={tourId || undefined}
            className={({ isActive }) =>
              `flex items-center gap-3 px-5 py-3 text-sm transition-colors ${
                isActive
                  ? 'bg-border/50 text-text-primary border-l-[3px] border-primary'
                  : 'text-text-secondary hover:text-text-primary hover:bg-card-alt border-l-[3px] border-transparent'
              }`
            }
          >
            <Icon size={18} />
            <span className="flex-1">{label}</span>
            {badge && <AlertBadge />}
          </NavLink>
        ))}
        {user?.is_admin && (
          <NavLink
            to="/admin"
            onClick={onNavigate}
            className={({ isActive }) =>
              `flex items-center gap-3 px-5 py-3 text-sm transition-colors mt-2 border-t border-border/50 ${
                isActive
                  ? 'bg-border/50 text-text-primary border-l-[3px] border-primary'
                  : 'text-text-secondary hover:text-text-primary hover:bg-card-alt border-l-[3px] border-transparent'
              }`
            }
          >
            <Shield size={18} />
            <span>Admin</span>
          </NavLink>
        )}
      </nav>
      <div className="px-5 py-2">
        <a
          href="https://github.com/dmxch/openfolio/issues/new/choose"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-3 px-0 py-2 text-sm text-text-secondary hover:text-text-primary transition-colors"
        >
          <MessageSquarePlus size={18} />
          <span>Feedback</span>
        </a>
        <NavLink
          to="/rechtliches"
          onClick={onNavigate}
          className="flex items-center gap-3 px-0 py-2 text-sm text-text-secondary hover:text-text-primary transition-colors"
        >
          <Scale size={18} />
          <span>Rechtliches</span>
        </NavLink>
      </div>
      <div className="p-4 border-t border-border">
        <CacheStatus />
        {user && (
          <div className="mt-3 flex items-center justify-between">
            <span className="text-xs text-text-muted truncate">{user.email}</span>
            <button
              onClick={logout}
              className="text-text-muted hover:text-text-primary transition-colors"
              title="Abmelden"
              aria-label="Abmelden"
            >
              <LogOut size={14} />
            </button>
          </div>
        )}
        <p className="text-xs text-text-muted mt-2 flex items-center justify-between">
          <span>Open Source Portfolio Manager · v{__APP_VERSION__}</span>
          <kbd data-tour="sidebar-ctrlk" className="text-[10px] bg-card-alt border border-border rounded px-1.5 py-0.5 font-mono text-text-muted">Ctrl+K</kbd>
        </p>
      </div>
    </aside>
  )
}
