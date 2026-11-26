import { useState } from 'react'
import { User, Briefcase, Bell, Key, Monitor, Database, KeyRound, FolderTree } from 'lucide-react'
import PageHeader from '../components/ui/PageHeader'
import AccountTab from './settings/AccountTab'
import PortfolioTab from './settings/PortfolioTab'
import BucketsTab from './settings/BucketsTab'
import AlertsTab from './settings/AlertsTab'
import IntegrationsTab from './settings/IntegrationsTab'
import DisplayTab from './settings/DisplayTab'
import DataTab from './settings/DataTab'
import ApiTokensTab from './settings/ApiTokensTab'

const TABS = [
  { id: 'account', label: 'Konto & Sicherheit', icon: User },
  { id: 'portfolio', label: 'Portfolio', icon: Briefcase },
  { id: 'buckets', label: 'Buckets', icon: FolderTree },
  { id: 'alerts', label: 'Alerts', icon: Bell },
  { id: 'integrations', label: 'Integrationen', icon: Key },
  { id: 'api-tokens', label: 'API-Tokens', icon: KeyRound },
  { id: 'display', label: 'Anzeige', icon: Monitor },
  { id: 'data', label: 'Daten', icon: Database },
]

export default function Settings() {
  const [activeTab, setActiveTab] = useState('account')
  const active = TABS.find((t) => t.id === activeTab)

  return (
    <div className="pb-10">
      <PageHeader title="Einstellungen" subtitle={active?.label} showBell={false} />

      <div className="grid grid-cols-1 md:grid-cols-[210px_1fr] gap-4 md:gap-6 items-start">
        {/* Tab-Navigation: ab md vertikal und sticky, mobil eine wischbare Zeile über dem Inhalt */}
        <nav
          role="tablist"
          aria-label="Einstellungen"
          className="flex gap-1 overflow-x-auto [scrollbar-width:none] min-w-0 -mx-1 px-1 pb-1 md:mx-0 md:px-0 md:pb-0 md:flex-col md:overflow-visible md:sticky md:top-[72px]"
        >
          {TABS.map(({ id, label, icon: Icon }) => {
            const on = activeTab === id
            return (
              <button
                key={id}
                role="tab"
                id={`tab-${id}`}
                aria-selected={on}
                aria-controls={`tabpanel-${id}`}
                onClick={(e) => {
                  setActiveTab(id)
                  // Mobil ist die Zeile breiter als der Bildschirm: den gewählten Tab ganz zeigen.
                  e.currentTarget.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
                }}
                className={`flex shrink-0 items-center gap-2.5 rounded-lg px-3 py-2 max-md:min-h-[40px] text-sm text-left whitespace-nowrap transition-colors md:shrink ${
                  on
                    ? 'bg-active-tint text-text-bright font-semibold shadow-[inset_3px_0_0_#5b8def]'
                    : 'text-text-secondary hover:bg-hover hover:text-text-primary'
                }`}
              >
                <Icon size={16} className={on ? 'text-primary' : 'text-text-muted'} />
                {label}
              </button>
            )
          })}
        </nav>

        {/* Inhalt */}
        <div role="tabpanel" id={`tabpanel-${activeTab}`} aria-labelledby={`tab-${activeTab}`} className="min-w-0 max-w-[720px]">
          {activeTab === 'account' && <AccountTab />}
          {activeTab === 'portfolio' && <PortfolioTab />}
          {activeTab === 'buckets' && <BucketsTab />}
          {activeTab === 'alerts' && <AlertsTab onTabChange={setActiveTab} />}
          {activeTab === 'integrations' && <IntegrationsTab />}
          {activeTab === 'api-tokens' && <ApiTokensTab />}
          {activeTab === 'display' && <DisplayTab />}
          {activeTab === 'data' && <DataTab />}
        </div>
      </div>
    </div>
  )
}
