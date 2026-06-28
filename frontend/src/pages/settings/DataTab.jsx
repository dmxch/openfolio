import { useState } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import { useToast } from '../../components/Toast'
import { Download, Upload } from 'lucide-react'
import { authFetch, API_BASE, Section } from './shared'
import Button from '../../components/ui/Button'
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
    <div className="space-y-[18px]">
      <Section title="Daten importieren">
        <p className="text-sm text-text-secondary mb-4">
          CSV-Dateien von Swissquote, Interactive Brokers oder Pocket einlesen.
          Der Wizard erkennt das Format automatisch und legt fehlende Positionen
          und Transaktionen an.
        </p>
        <Button variant="primary" icon={Upload} onClick={() => setShowImport(true)}>
          Transaktionen importieren (CSV)
        </Button>
      </Section>

      <Section title="Daten exportieren">
        <p className="text-sm text-text-secondary mb-4">
          Lade dein gesamtes Portfolio oder die Transaktionshistorie als
          CSV herunter — kompatibel mit Excel und anderen Tools.
        </p>
        <div className="flex gap-3">
          <Button variant="secondary" icon={Download} onClick={() => handleExport('positions')}>
            Positionen (CSV)
          </Button>
          <Button variant="secondary" icon={Download} onClick={() => handleExport('transactions')}>
            Transaktionen (CSV)
          </Button>
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
