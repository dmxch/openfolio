import { useState, useEffect } from 'react'
import { useToast } from '../../components/Toast'
import { authFetch, API_BASE, Section, Select } from './shared'
import { configureFormats } from '../../lib/format'

export default function DisplayTab() {
  const addToast = useToast()
  const [settings, setSettings] = useState(null)

  useEffect(() => {
    authFetch(`${API_BASE}/settings`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => d && setSettings(d))
  }, [])

  async function updateSetting(key, value) {
    try {
      const res = await authFetch(`${API_BASE}/settings`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [key]: value }),
      })
      if (res.ok) {
        const updated = await res.json()
        setSettings(updated)
        configureFormats({ number_format: updated.number_format, date_format: updated.date_format })
        addToast('Gespeichert', 'success')
      }
    } catch (err) {
      addToast(err.message, 'error')
    }
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <Section title="Zahlenformat">
        <Select
          value={settings?.number_format || 'ch'}
          onChange={(v) => updateSetting('number_format', v)}
          options={[
            { value: 'ch', label: "Schweiz (1'000.50)" },
            { value: 'de', label: 'Deutschland (1.000,50)' },
            { value: 'en', label: 'Englisch (1,000.50)' },
          ]}
        />
      </Section>

      <Section title="Datumsformat">
        <Select
          value={settings?.date_format || 'dd.mm.yyyy'}
          onChange={(v) => updateSetting('date_format', v)}
          options={[
            { value: 'dd.mm.yyyy', label: 'DD.MM.YYYY (31.12.2025)' },
            { value: 'yyyy-mm-dd', label: 'YYYY-MM-DD (2025-12-31)' },
          ]}
        />
      </Section>
    </div>
  )
}
