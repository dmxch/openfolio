import { useState } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import { useToast } from '../../components/Toast'
import { Download, Upload } from 'lucide-react'
import { authFetch, API_BASE, Section } from './shared'
import ImportWizard from '../../components/ImportWizard'

export default function DataTab() {
  const { logout } = useAuth()
  const addToast = useToast()
  const [showImport, setShowImport] = useState(false)

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
      <Section title="Daten importieren">
        <p className="text-sm text-text-secondary mb-3">
          CSV-Dateien von Swissquote, Interactive Brokers oder Pocket einlesen.
          Der Wizard erkennt das Format automatisch und legt fehlende Positionen
          und Transaktionen an.
        </p>
        <button
          onClick={() => setShowImport(true)}
          className="flex items-center gap-2 bg-primary hover:bg-primary/90 text-white rounded-lg px-4 py-2 text-sm"
        >
          <Upload size={16} />
          Transaktionen importieren (CSV)
        </button>
      </Section>

      <Section title="Daten exportieren">
        <p className="text-sm text-text-secondary mb-3">
          Lade dein gesamtes Portfolio oder die Transaktionshistorie als
          CSV herunter — kompatibel mit Excel und anderen Tools.
        </p>
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

      {showImport && (
        <ImportWizard
          onClose={() => setShowImport(false)}
          onSuccess={() => {
            addToast('Import abgeschlossen', 'success')
            setShowImport(false)
          }}
        />
      )}
    </div>
  )
}
