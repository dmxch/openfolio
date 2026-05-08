import { createContext, useContext } from 'react'
import { useApi } from '../hooks/useApi'
import { useAuth } from './AuthContext'

/**
 * Context für den Pending-Dividenden-Counter.
 *
 * Drei Komponenten brauchen denselben Counter:
 *   - DividendBadge in der Sidebar
 *   - PendingDividendsWidget auf dem Dashboard
 *   - ConfirmDividendModal beim Submit (Counter -1)
 *
 * useApi refetcht nicht von alleine — daher MUSS jede mutierende Aktion
 * (Confirm/Dismiss) clientseitig den `refetch()` triggern. Sonst zeigt das
 * Badge nach Confirm den alten Counter bis zum nächsten Page-Reload.
 */
const DividendCountContext = createContext({ count: 0, refetch: () => {} })

export function useDividendCount() {
  return useContext(DividendCountContext)
}

export function DividendCountProvider({ children }) {
  const { isAuthenticated } = useAuth()
  // Skip-Fetch wenn nicht eingeloggt — sonst würde useApi 401 auf der Login-Seite werfen
  const { data, refetch } = useApi('/dividends/count', { skip: !isAuthenticated })
  const count = data?.pending_count ?? 0

  return (
    <DividendCountContext.Provider value={{ count, refetch }}>
      {children}
    </DividendCountContext.Provider>
  )
}
