import { useState, useEffect } from 'react'
import { useToast } from '../../components/Toast'
import { authFetch, API_BASE, Section, Select } from './shared'

export default function PortfolioTab() {
  const addToast = useToast()
  const [settings, setSettings] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadSettings()
  }, [])

  async function loadSettings() {
    try {
      const res = await authFetch(`${API_BASE}/settings`)
      if (res.ok) setSettings(await res.json())
    } catch {} finally {
      setLoading(false)
    }
  }

  async function updateSetting(key, value) {
    try {
      const res = await authFetch(`${API_BASE}/settings`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [key]: value }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail)
      }
      const data = await res.json()
      setSettings(data)
      addToast('Gespeichert', 'success')
    } catch (err) {
      addToast(err.message, 'error')
    }
  }

  if (loading) return <p className="text-sm text-text-muted">Lade...</p>

  return (
    <div className="space-y-6 max-w-2xl">
      <Section title="Broker">
        <Select
          value={settings?.broker || 'swissquote'}
          onChange={(v) => updateSetting('broker', v)}
          options={[
            { value: 'swissquote', label: 'Swissquote' },
            { value: 'interactive_brokers', label: 'Interactive Brokers' },
            { value: 'other', label: 'Anderer' },
          ]}
        />
      </Section>

      <Section title="Stop-Loss Methode (Standard)">
        <Select
          value={settings?.default_stop_loss_method || 'trailing_pct'}
          onChange={(v) => updateSetting('default_stop_loss_method', v)}
          options={[
            { value: 'trailing_pct', label: 'Trailing Stop (%)' },
            { value: 'higher_low', label: 'Higher Low' },
            { value: 'ma_based', label: 'MA-basiert' },
          ]}
        />
      </Section>

      <Section title="Stop-Loss Review">
        <div className="space-y-3">
          <div>
            <label htmlFor="settings-sl-review-distance" className="block text-sm text-text-secondary mb-1">Review-Abstand (%)</label>
            <input
              id="settings-sl-review-distance"
              type="number"
              value={settings?.stop_loss_review_distance_pct || 15}
              onChange={(e) => updateSetting('stop_loss_review_distance_pct', parseFloat(e.target.value))}
              className="bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary w-24"
              min="1"
              max="50"
            />
          </div>
          <div>
            <label htmlFor="settings-sl-review-days" className="block text-sm text-text-secondary mb-1">Max. Tage ohne Review</label>
            <input
              id="settings-sl-review-days"
              type="number"
              value={settings?.stop_loss_review_max_days || 14}
              onChange={(e) => updateSetting('stop_loss_review_max_days', parseInt(e.target.value))}
              className="bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary w-24"
              min="1"
              max="90"
            />
          </div>
        </div>
      </Section>
    </div>
  )
}
