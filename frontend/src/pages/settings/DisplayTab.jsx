import { useState, useEffect } from 'react'
import { useToast } from '../../components/Toast'
import { authFetch, API_BASE, Section, Select } from './shared'
import FilterChips from '../../components/ui/FilterChips'
import { configureFormats } from '../../lib/format'

const NUMBER_FORMATS = [
  { key: 'ch', label: 'CH', example: "1'000.50" },
  { key: 'de', label: 'DE', example: '1.000,50' },
  { key: 'en', label: 'EN', example: '1,000.50' },
]

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

  const numberFormat = settings?.number_format || 'ch'
  const activeExample = NUMBER_FORMATS.find((f) => f.key === numberFormat)?.example

  return (
    <div className="space-y-[18px]">
      <Section title="Zahlenformat">
        <FilterChips
          options={NUMBER_FORMATS}
          value={numberFormat}
          onChange={(v) => updateSetting('number_format', v)}
        />
        {activeExample && (
          <p className="text-xs text-text-muted mt-3 font-mono tabular-nums">
            Vorschau: {activeExample}
          </p>
        )}
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

      <Section title="Theme">
        <p className="text-sm text-text-secondary">
          OpenFolio nutzt durchgehend ein dunkles Theme — optimiert für lange
          Analyse-Sessions und kontrastreiche Charts.
        </p>
      </Section>
    </div>
  )
}
