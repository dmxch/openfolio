import { useState, useEffect } from 'react'
import { useToast } from '../../components/Toast'
import { Mail, Smartphone } from 'lucide-react'
import { authFetch, API_BASE, Section, Toggle } from './shared'

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
  { key: 'allocation', label: 'Bucket-Allokation', desc: 'Warnt bei Abweichung vom Ziel-Anteil eines Buckets (target_pct in Bucket-Einstellungen)' },
  { key: 'price_alert', label: 'Preis-Alarme', desc: 'Benachrichtigungen für Preis-Alarme (Watchlist & Positionen)' },
  { key: 'breakout', label: 'Breakout-Alerts (Watchlist)', desc: 'E-Mail wenn eine Aktie auf der Watchlist einen Donchian-Breakout hat' },
  { key: 'pending_dividend', label: 'Offene Dividenden', desc: 'Wöchentlicher Digest mit nicht erfassten Dividenden laut Ex-Date' },
  { key: 'drawdown_brake_bucket', label: 'Drawdown-Bremse pro Bucket', desc: 'Mail wenn ein Bucket die in den Bucket-Einstellungen konfigurierte Drawdown-Schwelle erreicht. Max 1 Mail pro Bucket und Tag.' },
  { key: 'bucket_total_drift', label: 'Bucket-Soll-Anteil ueberschritten', desc: 'Mail wenn ein Bucket den konfigurierten Maximalanteil am Gesamtportfolio (max_total_pct in Bucket-Einstellungen) ueberschreitet. Max 1 Mail pro Bucket und Tag.' },
]

export default function AlertsTab({ onTabChange }) {
  const addToast = useToast()
  const [prefs, setPrefs] = useState([])
  const [settings, setSettings] = useState(null)
  const [ntfyConfigured, setNtfyConfigured] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      authFetch(`${API_BASE}/settings/alert-preferences`).then((r) => r.ok ? r.json() : []),
      authFetch(`${API_BASE}/settings`).then((r) => r.ok ? r.json() : null),
      authFetch(`${API_BASE}/settings/ntfy`).then((r) => r.ok ? r.json() : null),
    ]).then(([p, s, nt]) => {
      setPrefs(p)
      if (s) setSettings(s)
      // Push-Spalte nur sichtbar wenn ntfy konfiguriert UND aktiv (is_enabled).
      // Aus Spec Section 7.2: "Nur sichtbar wenn ntfyConfigured === true".
      // Bei Pausiert-Status (is_enabled=false) blenden wir die Spalte ein,
      // damit der Nutzer seine Push-Auswahl nicht verliert wenn er kurz
      // pausiert — die Pushes werden im Pausiert-Modus serverseitig
      // unterbunden, die Pref-Werte bleiben aber bestehen.
      setNtfyConfigured(!!nt?.configured)
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

  // Grid-Layout je nachdem ob Push-Spalte sichtbar ist
  const gridCols = ntfyConfigured ? 'grid-cols-[1fr_64px_64px_64px_64px]' : 'grid-cols-[1fr_64px_64px_64px]'

  return (
    <div className="space-y-[18px]">
      {!ntfyConfigured && (
        <div className="flex items-center gap-2 p-3 bg-card-2 border border-border rounded-lg text-sm text-text-secondary">
          <Smartphone size={14} />
          <span>Push-Benachrichtigungen nicht konfiguriert.</span>
          {onTabChange ? (
            <button
              type="button"
              onClick={() => onTabChange('integrations')}
              className="text-link hover:underline ml-1"
            >
              Jetzt einrichten →
            </button>
          ) : null}
        </div>
      )}

      <Section title={`Benachrichtigungen (${enabledCount}/${ALERT_CATEGORIES.length} aktiv)`}>
        <div>
          <div className={`grid ${gridCols} gap-2 font-mono text-[10px] uppercase tracking-[0.05em] text-text-faint px-2 pb-2 border-b border-border-2`}>
            <span>Kategorie</span>
            <span className="text-center">Aktiv</span>
            <span className="text-center">In-App</span>
            <span className="text-center flex items-center justify-center gap-1"><Mail size={11} /> E-Mail</span>
            {ntfyConfigured && (
              <span className="text-center flex items-center justify-center gap-1"><Smartphone size={11} /> Push</span>
            )}
          </div>
          <div className="divide-y divide-border-row">
            {ALERT_CATEGORIES.map(({ key, label, desc }) => {
              const p = prefMap[key] || { is_enabled: true, notify_in_app: true, notify_email: false, notify_push: false }
              return (
                <div key={key} className={`grid ${gridCols} gap-2 items-center py-2.5 px-2 hover:bg-hover rounded transition-colors`}>
                  <div>
                    <div className="text-sm text-text-primary">{label}</div>
                    <div className="text-xs text-text-muted">{desc}</div>
                  </div>
                  <div className="flex justify-center">
                    <Toggle
                      ariaLabel={`${label} aktiv`}
                      checked={p.is_enabled}
                      onChange={(v) => updatePref(key, 'is_enabled', v)}
                    />
                  </div>
                  <div className="flex justify-center">
                    <Toggle
                      ariaLabel={`${label} In-App`}
                      checked={p.notify_in_app}
                      onChange={(v) => updatePref(key, 'notify_in_app', v)}
                      disabled={!p.is_enabled}
                    />
                  </div>
                  <div className="flex justify-center">
                    <Toggle
                      ariaLabel={`${label} E-Mail`}
                      checked={p.notify_email}
                      onChange={(v) => updatePref(key, 'notify_email', v)}
                      disabled={!p.is_enabled}
                    />
                  </div>
                  {ntfyConfigured && (
                    <div className="flex justify-center">
                      <Toggle
                        ariaLabel={`${label} Push`}
                        checked={!!p.notify_push}
                        onChange={(v) => updatePref(key, 'notify_push', v)}
                        disabled={!p.is_enabled}
                      />
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      </Section>

      <Section title="Schwellenwerte">
        <div className="space-y-4">
          <div>
            <label htmlFor="settings-stop-proximity" className="block text-xs font-medium text-text-muted mb-1">Stop-Proximity Warnung (%)</label>
            <p className="text-xs text-text-secondary mb-1.5">Warnt wenn der Kurs weniger als X% über dem Stop ist</p>
            <input
              id="settings-stop-proximity"
              type="number"
              value={settings?.alert_stop_proximity_pct ?? 3}
              onChange={(e) => updateSetting('alert_stop_proximity_pct', parseFloat(e.target.value))}
              className="bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text-primary w-24 focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors"
              min="1"
              max="20"
              step="0.5"
            />
          </div>
          <div>
            <label htmlFor="settings-satellite-loss" className="block text-xs font-medium text-text-muted mb-1">Satellite Verlust-Warnung (%)</label>
            <p className="text-xs text-text-secondary mb-1.5">Warnung ab diesem Verlust (ohne Stop-Loss)</p>
            <input
              id="settings-satellite-loss"
              type="number"
              value={Math.abs(settings?.alert_satellite_loss_pct ?? 15)}
              onChange={(e) => updateSetting('alert_satellite_loss_pct', -Math.abs(parseFloat(e.target.value)))}
              className="bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text-primary w-24 focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors"
              min="5"
              max="50"
              step="1"
            />
          </div>
          <div>
            <label htmlFor="settings-core-loss" className="block text-xs font-medium text-text-muted mb-1">Core Verlust-Warnung (%)</label>
            <p className="text-xs text-text-secondary mb-1.5">Warnung ab diesem Verlust (ohne Stop-Loss)</p>
            <input
              id="settings-core-loss"
              type="number"
              value={Math.abs(settings?.alert_core_loss_pct ?? 25)}
              onChange={(e) => updateSetting('alert_core_loss_pct', -Math.abs(parseFloat(e.target.value)))}
              className="bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text-primary w-24 focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors"
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
