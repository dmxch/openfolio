import { useState } from 'react'
import { User, Briefcase, Bell, Key, Monitor, Database, KeyRound } from 'lucide-react'
import AccountTab from './settings/AccountTab'
import PortfolioTab from './settings/PortfolioTab'
import AlertsTab from './settings/AlertsTab'
import IntegrationsTab from './settings/IntegrationsTab'
import DisplayTab from './settings/DisplayTab'
import DataTab from './settings/DataTab'
import ApiTokensTab from './settings/ApiTokensTab'

const TABS = [
  { id: 'account', label: 'Konto & Sicherheit', icon: User },
  { id: 'portfolio', label: 'Portfolio', icon: Briefcase },
  { id: 'alerts', label: 'Alerts', icon: Bell },
  { id: 'integrations', label: 'Integrationen', icon: Key },
  { id: 'api-tokens', label: 'API-Tokens', icon: KeyRound },
  { id: 'display', label: 'Anzeige', icon: Monitor },
  { id: 'data', label: 'Daten', icon: Database },
]

export default function Settings() {
  const [activeTab, setActiveTab] = useState('account')

  return (
    <div>
      <h1 className="text-xl font-bold text-text-primary mb-6">Einstellungen</h1>

      <div role="tablist" aria-label="Einstellungen" className="flex gap-2 mb-6 border-b border-border overflow-x-auto">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            role="tab"
            id={`tab-${id}`}
            aria-selected={activeTab === id}
            aria-controls={`tabpanel-${id}`}
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

      <div role="tabpanel" id={`tabpanel-${activeTab}`} aria-labelledby={`tab-${activeTab}`}>
        {activeTab === 'account' && <AccountTab />}
        {activeTab === 'portfolio' && <PortfolioTab />}
        {activeTab === 'alerts' && <AlertsTab />}
        {activeTab === 'integrations' && <IntegrationsTab />}
        {activeTab === 'api-tokens' && <ApiTokensTab />}
        {activeTab === 'display' && <DisplayTab />}
        {activeTab === 'data' && <DataTab />}
      </div>
    </div>
  )
}
