import { useState, useEffect } from 'react'
import { useToast } from '../../components/Toast'
import { Mail } from 'lucide-react'
import { authFetch, API_BASE, Section } from './shared'

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

export default function AlertsTab() {
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
