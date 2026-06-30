import { NavLink } from 'react-router-dom'
import { LineChart, Wallet, BarChart3, Search, MoreHorizontal } from 'lucide-react'

// Bottom-Tab-Bar — mobil inkl. Handy-Querformat. Desktop (desk) nutzt die Sidebar.
const items = [
  { to: '/', end: true, label: 'Markt', Icon: LineChart },
  { to: '/portfolio', label: 'Portfolio', Icon: Wallet },
  { to: '/performance', label: 'Rendite', Icon: BarChart3 },
  { to: '/analysis', label: 'Watchlist', Icon: Search },
  { to: '/mehr', label: 'Mehr', Icon: MoreHorizontal },
]

export default function MobileNav() {
  return (
    <nav
      className="desk:hidden fixed bottom-0 inset-x-0 z-40 flex items-stretch border-t border-border-soft bg-sidebar/95 backdrop-blur-md"
      style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
    >
      {items.map(({ to, end, label, Icon }) => (
        <NavLink key={to} to={to} end={end} className="flex-1 flex flex-col items-center gap-1 py-2 select-none">
          {({ isActive }) => (
            <>
              <Icon size={21} strokeWidth={2} className={isActive ? 'text-primary' : 'text-text-muted'} />
              <span className={`text-[10px] leading-none ${isActive ? 'text-primary font-semibold' : 'text-text-muted font-medium'}`}>
                {label}
              </span>
            </>
          )}
        </NavLink>
      ))}
    </nav>
  )
}
