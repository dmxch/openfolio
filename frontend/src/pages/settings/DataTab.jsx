import { useState } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import { useToast } from '../../components/Toast'
import { Download } from 'lucide-react'
import { authFetch, API_BASE, Section } from './shared'

export default function DataTab() {
  const { logout } = useAuth()
  const addToast = useToast()

  async function handleExport(type) {
    try {
      const res = await authFetch(`${API_BASE}/export/${type}`)
      if (!res.ok) throw new Error('Export fehlgeschlagen')
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `openfolio-${type}-${new Date().toISOString().slice(0, 10)}.csv`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      addToast(err.message, 'error')
    }
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <Section title="Daten exportieren">
        <div className="flex gap-3">
          <button onClick={() => handleExport('positions')} className="flex items-center gap-2 bg-card-alt hover:bg-border/50 text-text-primary rounded-lg px-4 py-2 text-sm border border-border">
            <Download size={16} />
            Positionen (CSV)
          </button>
          <button onClick={() => handleExport('transactions')} className="flex items-center gap-2 bg-card-alt hover:bg-border/50 text-text-primary rounded-lg px-4 py-2 text-sm border border-border">
            <Download size={16} />
            Transaktionen (CSV)
          </button>
        </div>
      </Section>
    </div>
  )
}
