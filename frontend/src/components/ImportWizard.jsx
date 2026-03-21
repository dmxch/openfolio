import { useState, useCallback, useRef } from 'react'
import { Upload, X, Loader2, Check, AlertTriangle, ChevronLeft, ChevronRight, FileText, Trash2, Edit3 } from 'lucide-react'
import { formatCHFExact } from '../lib/format'
import { apiPostFormData, apiPost, authFetch } from '../hooks/useApi'
import useEscClose from '../hooks/useEscClose'
import StopLossWizard from './StopLossWizard'
import PositionTypeWizard from './PositionTypeWizard'
import DateInput from './DateInput'

const TYPE_LABELS = {
  buy: 'Kauf', sell: 'Verkauf', dividend: 'Dividende', fee: 'Gebühr',
  tax: 'Steuer', tax_refund: 'Steuererstattung', delivery_in: 'Einlieferung',
  delivery_out: 'Auslieferung', deposit: 'Einzahlung', withdrawal: 'Auszahlung',
  capital_gain: 'Kapitalgewinn', interest: 'Zinsertrag',
  fx_credit: 'FX Gutschrift', fx_debit: 'FX Belastung',
  fee_correction: 'Gebührenkorrektur',
}
const ASSET_TYPE_LABELS = {
  stock: 'Aktie',
  etf: 'ETF',
  crypto: 'Crypto',
  commodity: 'Edelmetall',
  cash: 'Cash',
  pension: 'Vorsorge',
  real_estate: 'Immobilien',
}

const TYPE_COLORS = {
  buy: 'bg-success/15 text-success',
  sell: 'bg-danger/15 text-danger',
  dividend: 'bg-primary/15 text-primary',
  fee: 'bg-warning/15 text-warning',
  tax: 'bg-warning/15 text-warning',
  tax_refund: 'bg-success/15 text-success',
  delivery_in: 'bg-primary/15 text-primary',
  delivery_out: 'bg-danger/15 text-danger',
  deposit: 'bg-card-alt text-text-secondary',
  withdrawal: 'bg-card-alt text-text-secondary',
  capital_gain: 'bg-success/15 text-success',
  interest: 'bg-primary/15 text-primary',
  fx_credit: 'bg-text-muted/15 text-text-muted',
  fx_debit: 'bg-text-muted/15 text-text-muted',
  fee_correction: 'bg-warning/15 text-warning',
}

const INPUT = 'bg-card border border-border rounded px-2 py-1 text-xs text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 w-full'

const MAPPING_FIELDS = [
  { key: 'date', label: 'Datum', required: true },
  { key: 'type', label: 'Typ', required: true },
  { key: 'ticker', label: 'Ticker', required: true },
  { key: 'shares', label: 'Anzahl', required: true },
  { key: 'price_per_share', label: 'Preis', required: true },
  { key: 'currency', label: 'Währung', required: true },
  { key: 'isin', label: 'ISIN', required: false },
  { key: 'fees_chf', label: 'Gebühren', required: false },
  { key: 'total_chf', label: 'Nettobetrag', required: false },
  { key: 'name', label: 'Name', required: false },
  { key: 'order_id', label: 'Auftragsnummer', required: false },
  { key: 'fx_rate_to_chf', label: 'FX-Rate', required: false },
  { key: 'notes', label: 'Notizen', required: false },
]

const OPENFOLIO_TYPES = [
  { value: 'buy', label: 'Kauf' },
  { value: 'sell', label: 'Verkauf' },
  { value: 'dividend', label: 'Dividende' },
  { value: 'capital_gain', label: 'Kapitalgewinn' },
  { value: 'fee', label: 'Gebühr' },
  { value: 'fee_correction', label: 'Gebührenkorrektur' },
  { value: 'tax', label: 'Steuer' },
  { value: 'tax_refund', label: 'Steuererstattung' },
  { value: 'interest', label: 'Zinsen' },
  { value: 'fx_credit', label: 'Forex-Gutschrift' },
  { value: 'fx_debit', label: 'Forex-Belastung' },
  { value: 'deposit', label: 'Einzahlung' },
  { value: 'withdrawal', label: 'Auszahlung' },
  { value: 'delivery_in', label: 'Einlieferung' },
  { value: 'delivery_out', label: 'Auslieferung' },
  { value: 'skip', label: 'Überspringen' },
]

export default function ImportWizard({ onClose, onSuccess }) {
  const [step, setStep] = useState(1)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [analysis, setAnalysis] = useState(null)
  const [columnMapping, setColumnMapping] = useState({})
  const [typeMapping, setTypeMapping] = useState({})
  const [hasForexPairs, setHasForexPairs] = useState(false)
  const [aggregatePartialFills, setAggregatePartialFills] = useState(false)
  const [preview, setPreview] = useState(null)
  const [result, setResult] = useState(null)
  const [file, setFile] = useState(null)
  const [files, setFiles] = useState([])
  const [fileProgress, setFileProgress] = useState([])
  const [dragOver, setDragOver] = useState(false)
  const [showStopLossWizard, setShowStopLossWizard] = useState(false)
  const [showTypeWizard, setShowTypeWizard] = useState(false)
  const [profileName, setProfileName] = useState('')
  const [profileSaved, setProfileSaved] = useState(false)
  const fileRef = useRef()

  const isSwissquote = analysis?.detected_broker === 'swissquote'
  const isRelai = analysis?.detected_broker === 'relai'
  const isAutoDetected = isSwissquote || isRelai

  // --- Step 1: Upload ---
  const handleFiles = useCallback(async (fileList) => {
    const validFiles = []
    for (const f of fileList) {
      const ext = f.name.split('.').pop().toLowerCase()
      if (ext !== 'csv') {
        setError(`${f.name}: Nur CSV-Dateien erlaubt`)
        return
      }
      if (f.size > 10 * 1024 * 1024) {
        setError(`${f.name}: Datei zu gross (max. 10 MB)`)
        return
      }
      validFiles.push(f)
    }
    if (validFiles.length === 0) return

    setFiles(validFiles)
    setError(null)
    setLoading(true)

    // First file: analyze to detect broker
    const firstFile = validFiles[0]
    setFile(firstFile)

    try {
      const formData = new FormData()
      formData.append('file', firstFile)
      const analysisData = await apiPostFormData('/import/analyze', formData)
      setAnalysis(analysisData)

      if (analysisData.detected_broker === 'swissquote') {
        // Swissquote detected — use existing parse endpoint
        if (validFiles.length === 1) {
          // Single file
          const parseForm = new FormData()
          parseForm.append('file', firstFile)
          const data = await apiPostFormData('/import/parse', parseForm)
          setPreview(data)
          setStep(4)
        } else {
          // Batch — process sequentially, merge results
          const progress = validFiles.map(f => ({ name: f.name, status: 'pending' }))
          setFileProgress([...progress])

          let mergedTransactions = []
          let mergedNewPositions = []
          let mergedWarnings = []
          let sourceType = 'csv'

          for (let i = 0; i < validFiles.length; i++) {
            progress[i] = { ...progress[i], status: 'loading' }
            setFileProgress([...progress])

            try {
              const fd = new FormData()
              fd.append('file', validFiles[i])
              const data = await apiPostFormData('/import/parse', fd)

              const offset = mergedTransactions.length
              const txns = data.transactions.map((t, idx) => ({ ...t, row_index: offset + idx }))
              mergedTransactions = [...mergedTransactions, ...txns]

              const existingKeys = new Set(mergedNewPositions.map(p => p.key || p.ticker))
              for (const np of (data.new_positions || [])) {
                if (!existingKeys.has(np.key || np.ticker)) {
                  mergedNewPositions.push(np)
                  existingKeys.add(np.key || np.ticker)
                }
              }

              for (const w of (data.warnings || [])) {
                mergedWarnings.push(`${validFiles[i].name}: ${w}`)
              }

              if (data.source_type === 'csv') sourceType = 'csv'
              progress[i] = { ...progress[i], status: 'done' }
            } catch (err) {
              progress[i] = { ...progress[i], status: 'error', error: err.message }
              mergedWarnings.push(`${validFiles[i].name}: ${err.message || 'Fehlgeschlagen'}`)
            }
            setFileProgress([...progress])
          }

          if (mergedTransactions.length > 0) {
            setPreview({
              source_type: sourceType,
              filename: validFiles.map(f => f.name).join(', '),
              total_rows: mergedTransactions.length,
              transactions: mergedTransactions,
              new_positions: mergedNewPositions,
              warnings: mergedWarnings,
            })
            setStep(4)
          } else {
            const fileErrors = progress.filter(p => p.status === 'error').map(p => p.error).filter(Boolean)
            const uniqueErrors = [...new Set(fileErrors)]
            setError(uniqueErrors.length > 0 ? uniqueErrors.join(' | ') : 'Keine Transaktionen gefunden')
          }

          setFileProgress([])
        }
      } else if (analysisData.detected_broker === 'relai') {
        // Relai detected — skip mapping, use suggested mappings directly
        const parseRes = await apiPost('/import/parse-with-mapping', {
          upload_id: analysisData.upload_id,
          column_mapping: analysisData.suggested_mapping,
          type_mapping: analysisData.suggested_type_mapping,
          has_forex_pairs: false,
          aggregate_partial_fills: false,
          broker_defaults: analysisData.broker_defaults,
          total_chf_formula: analysisData.total_chf_formula || 'standard',
        })
        setPreview(parseRes)
        setStep(4)
      } else {
        // Non-Swissquote — only single file allowed
        if (validFiles.length > 1) {
          setError('Batch-Import nur für erkannte Broker-Formate (z.B. Swissquote)')
          setLoading(false)
          return
        }

        // Pre-fill mappings from analysis
        setColumnMapping(analysisData.suggested_mapping || {})
        setTypeMapping(analysisData.suggested_type_mapping || {})
        // Default aggregatePartialFills on if order_id is mapped
        if (analysisData.suggested_mapping?.order_id) {
          setAggregatePartialFills(true)
        }
        setStep(2)
      }
    } catch (err) {
      setError(err.message || 'Upload fehlgeschlagen')
    } finally {
      setLoading(false)
    }
  }, [])

  const handleFile = useCallback((f) => {
    if (f) handleFiles([f])
  }, [handleFiles])

  const handleDrop = useCallback((e) => {
    e.preventDefault()
    setDragOver(false)
    const droppedFiles = Array.from(e.dataTransfer.files)
    if (droppedFiles.length > 0) handleFiles(droppedFiles)
  }, [handleFiles])

  // --- Step 2: Column Mapping helpers ---
  const getSampleValues = (csvHeader) => {
    if (!analysis?.sample_rows || !analysis?.headers) return []
    const colIdx = analysis.headers.indexOf(csvHeader)
    if (colIdx === -1) return []
    return analysis.sample_rows.slice(0, 3).map(row => row[colIdx]).filter(v => v != null && v !== '')
  }

  const usedColumns = Object.values(columnMapping).filter(v => v && v !== '')
  const hasDuplicateColumns = new Set(usedColumns).size !== usedColumns.length

  const allRequiredMapped = MAPPING_FIELDS
    .filter(f => f.required)
    .every(f => columnMapping[f.key] && columnMapping[f.key] !== '')

  const canProceedStep2 = allRequiredMapped && !hasDuplicateColumns

  // --- Step 3: Type Mapping — parse with mapping ---
  const handleParseWithMapping = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiPost('/import/parse-with-mapping', {
        upload_id: analysis.upload_id,
        column_mapping: columnMapping,
        type_mapping: typeMapping,
        has_forex_pairs: hasForexPairs,
        aggregate_partial_fills: aggregatePartialFills,
      })
      setPreview(data)
      setStep(4)
    } catch (err) {
      setError(err.message || 'Parsing fehlgeschlagen')
    } finally {
      setLoading(false)
    }
  }

  // --- Step 4: Preview helpers ---
  const removeRow = (idx) => {
    setPreview(prev => ({
      ...prev,
      transactions: prev.transactions.filter((_, i) => i !== idx),
      total_rows: prev.total_rows - 1,
    }))
  }

  const updateField = (idx, field, value) => {
    setPreview(prev => ({
      ...prev,
      transactions: prev.transactions.map((t, i) =>
        i === idx ? { ...t, [field]: value } : t
      ),
    }))
  }

  const toggleDuplicateOverride = (idx) => {
    setPreview(prev => ({
      ...prev,
      transactions: prev.transactions.map((t, i) =>
        i === idx ? { ...t, force_import: !t.force_import } : t
      ),
    }))
  }

  // --- Step 5: Confirm ---
  const handleConfirm = async () => {
    setLoading(true)
    setError(null)
    try {
      // Sync asset types from transactions to new_positions
      const newPositions = (preview.new_positions || []).map(np => {
        const txn = preview.transactions.find(t =>
          (t.ticker === np.ticker || t.isin === np.key) && t.suggested_asset_type
        )
        return txn ? { ...np, suggested_type: txn.suggested_asset_type } : np
      })

      const res = await apiPost('/import/confirm', {
        transactions: preview.transactions,
        new_positions: newPositions,
        fx_transactions: preview.swissquote_meta?.fx_pairs || [],
      })
      setResult(res)
      setStep(5)
    } catch (err) {
      setError(err.message || 'Import fehlgeschlagen')
    } finally {
      setLoading(false)
    }
  }

  // --- Save mapping profile ---
  const saveProfile = async () => {
    if (!profileName.trim()) return
    try {
      await apiPost('/import/profiles', {
        name: profileName.trim(),
        column_mapping: columnMapping,
        type_mapping: typeMapping,
        delimiter: analysis?.delimiter || ',',
        encoding: analysis?.encoding || 'utf-8',
        date_format: analysis?.detected_date_format || 'DD.MM.YYYY',
        has_forex_pairs: hasForexPairs,
        aggregate_partial_fills: aggregatePartialFills,
      })
      setProfileSaved(true)
    } catch (err) {
      setError(err.message || 'Profil speichern fehlgeschlagen')
    }
  }

  // --- Summary stats ---
  const txnSummary = preview ? (() => {
    const txns = preview.transactions
    const nonDup = txns.filter(t => !t.is_duplicate || t.force_import)
    const dupCount = txns.filter(t => t.is_duplicate && !t.force_import).length
    const total = nonDup.reduce((s, t) => s + (t.total_chf || 0), 0)
    const newPos = preview.new_positions?.length || 0
    return { count: nonDup.length, total, newPos, dupCount }
  })() : null

  // --- Step indicator ---
  const visibleSteps = isAutoDetected
    ? [{ n: 1, label: 'Upload' }, { n: 4, label: 'Preview' }, { n: 5, label: 'Import' }]
    : [{ n: 1, label: 'Upload' }, { n: 2, label: 'Spalten' }, { n: 3, label: 'Typen' }, { n: 4, label: 'Preview' }, { n: 5, label: 'Import' }]

  useEscClose(onClose)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-body/80 backdrop-blur-sm" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Transaktionen importieren"
        className="bg-card border border-border rounded-xl shadow-2xl w-full max-w-5xl mx-4 max-h-[90vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-border shrink-0">
          <div className="flex items-center gap-3">
            <Upload size={20} className="text-primary" />
            <h3 className="text-lg font-bold text-text-primary">Transaktionen importieren</h3>
          </div>
          <div className="flex items-center gap-4">
            {/* Step indicator */}
            <div className="flex items-center gap-2 text-xs">
              {visibleSteps.map((s, i) => (
                <div key={s.n} className="flex items-center gap-1.5">
                  <div className={`w-6 h-6 rounded-full flex items-center justify-center font-medium ${
                    step >= s.n ? 'bg-primary text-white' : 'bg-card-alt text-text-muted'
                  }`}>
                    {step > s.n ? <Check size={12} /> : i + 1}
                  </div>
                  <span className={`text-[10px] ${step >= s.n ? 'text-text-primary' : 'text-text-muted'}`}>{s.label}</span>
                  {i < visibleSteps.length - 1 && <div className={`w-6 h-px ${step > s.n ? 'bg-primary' : 'bg-border'}`} />}
                </div>
              ))}
            </div>
            <button onClick={onClose} className="text-text-muted hover:text-text-primary transition-colors" aria-label="Schliessen">
              <X size={20} />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-auto p-5">
          {/* Step 1: Upload */}
          {step === 1 && (
            <div className="flex flex-col items-center justify-center min-h-[300px]">
              <div
                onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleDrop}
                onClick={() => fileRef.current?.click()}
                className={`w-full max-w-lg border-2 border-dashed rounded-xl p-12 text-center cursor-pointer transition-colors ${
                  dragOver
                    ? 'border-primary bg-primary/5'
                    : 'border-border hover:border-primary/50 hover:bg-card-alt/30'
                }`}
              >
                {loading ? (
                  <div className="flex flex-col items-center gap-3">
                    <Loader2 size={32} className="animate-spin text-primary" />
                    <p className="text-sm text-text-secondary">
                      {files.length > 1 ? `${files.length} Dateien werden analysiert...` : 'Datei wird analysiert...'}
                    </p>
                    {fileProgress.length > 0 ? (
                      <div className="w-full max-w-xs space-y-1">
                        {fileProgress.map((fp, i) => (
                          <div key={i} className="flex items-center gap-2 text-xs">
                            {fp.status === 'loading' && <Loader2 size={10} className="animate-spin text-primary shrink-0" />}
                            {fp.status === 'done' && <Check size={10} className="text-success shrink-0" />}
                            {fp.status === 'error' && <AlertTriangle size={10} className="text-danger shrink-0" />}
                            {fp.status === 'pending' && <div className="w-2.5 h-2.5 rounded-full bg-border shrink-0" />}
                            <span className={`truncate ${fp.status === 'error' ? 'text-danger' : 'text-text-muted'}`}>{fp.name}</span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      file && <p className="text-xs text-text-muted">{file.name}</p>
                    )}
                  </div>
                ) : (
                  <>
                    <FileText size={40} className="mx-auto text-text-muted mb-3" />
                    <p className="text-sm text-text-primary font-medium mb-1">
                      CSV-Datei hier ablegen
                    </p>
                    <p className="text-xs text-text-muted">
                      oder klicken zum Auswählen — einzeln oder mehrere (max. 10 MB pro Datei)
                    </p>
                  </>
                )}
              </div>
              <input
                ref={fileRef}
                type="file"
                accept=".csv"
                multiple
                className="hidden"
                onChange={(e) => handleFiles(Array.from(e.target.files))}
              />
            </div>
          )}

          {/* Step 2: Column Mapping */}
          {step === 2 && analysis && (
            <div className="space-y-4">
              <p className="text-sm text-text-secondary">
                Ordne die CSV-Spalten den OpenFolio-Feldern zu. Pflichtfelder sind mit <span className="text-danger">★</span> markiert.
              </p>

              <div className="rounded-lg border border-border overflow-hidden">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-border bg-card-alt/30 text-text-muted">
                      <th className="text-left p-2 font-medium w-40">OpenFolio-Feld</th>
                      <th className="text-left p-2 font-medium w-52">CSV-Spalte</th>
                      <th className="text-left p-2 font-medium">Beispielwerte</th>
                    </tr>
                  </thead>
                  <tbody>
                    {MAPPING_FIELDS.map((field) => {
                      const selectedCol = columnMapping[field.key] || ''
                      const samples = selectedCol ? getSampleValues(selectedCol) : []
                      const isAssigned = selectedCol !== ''
                      const isDuplicate = isAssigned && usedColumns.filter(v => v === selectedCol).length > 1
                      return (
                        <tr key={field.key} className="border-b border-border/50">
                          <td className="p-2">
                            <span className={field.required && !isAssigned ? 'text-danger' : 'text-text-primary'}>
                              {field.required && <span className="text-danger mr-1">★</span>}
                              {field.label}
                            </span>
                          </td>
                          <td className="p-2">
                            <select
                              value={selectedCol}
                              onChange={(e) => setColumnMapping(prev => ({ ...prev, [field.key]: e.target.value }))}
                              className={`${INPUT} ${isDuplicate ? 'border-danger' : ''}`}
                            >
                              <option value="">— Nicht zugewiesen —</option>
                              {(analysis.headers || []).map((h) => (
                                <option key={h} value={h}>{h}</option>
                              ))}
                            </select>
                            {isDuplicate && (
                              <p className="text-[10px] text-danger mt-0.5">Spalte bereits verwendet</p>
                            )}
                          </td>
                          <td className="p-2 text-text-muted">
                            {samples.length > 0
                              ? samples.join(', ')
                              : <span className="italic">—</span>
                            }
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>

              {/* Options */}
              <div className="flex flex-col gap-2">
                <label className="flex items-center gap-2 text-xs text-text-secondary cursor-pointer">
                  <input
                    type="checkbox"
                    checked={hasForexPairs}
                    onChange={(e) => setHasForexPairs(e.target.checked)}
                    className="accent-primary"
                  />
                  CSV enthält Forex-Transaktionen
                </label>
                <label className="flex items-center gap-2 text-xs text-text-secondary cursor-pointer">
                  <input
                    type="checkbox"
                    checked={aggregatePartialFills}
                    onChange={(e) => setAggregatePartialFills(e.target.checked)}
                    className="accent-primary"
                  />
                  Teilausführungen aggregieren
                </label>
              </div>
            </div>
          )}

          {/* Step 3: Type Mapping */}
          {step === 3 && analysis && (
            <div className="space-y-4">
              <p className="text-sm text-text-secondary">
                Ordne die Transaktionstypen aus der CSV den OpenFolio-Typen zu.
              </p>

              <div className="rounded-lg border border-border overflow-hidden">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-border bg-card-alt/30 text-text-muted">
                      <th className="text-left p-2 font-medium">CSV-Wert</th>
                      <th className="text-left p-2 font-medium w-52">OpenFolio-Typ</th>
                      <th className="text-right p-2 font-medium w-20">Anzahl</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(analysis.unique_types || []).map((item) => (
                      <tr key={item.value} className="border-b border-border/50">
                        <td className="p-2 text-text-primary font-medium">{item.value}</td>
                        <td className="p-2">
                          <select
                            value={typeMapping[item.value] || ''}
                            onChange={(e) => setTypeMapping(prev => ({ ...prev, [item.value]: e.target.value }))}
                            className={INPUT}
                          >
                            <option value="">— Nicht zugewiesen —</option>
                            {OPENFOLIO_TYPES.map((t) => (
                              <option key={t.value} value={t.value}>{t.label}</option>
                            ))}
                          </select>
                        </td>
                        <td className="p-2 text-right text-text-muted">{item.count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Step 4: Preview & Edit */}
          {step === 4 && preview && (
            <div className="space-y-4">
              {/* Summary bar */}
              <div className="flex items-center gap-4 text-sm">
                <span className="text-text-secondary">
                  <span className="font-medium text-text-primary">{txnSummary.count}</span> Transaktionen
                </span>
                {txnSummary.dupCount > 0 && (
                  <span className="text-danger">
                    <span className="font-medium">{txnSummary.dupCount}</span> Duplikate
                  </span>
                )}
                {txnSummary.newPos > 0 && (
                  <span className="text-warning">
                    <span className="font-medium">{txnSummary.newPos}</span> neue Positionen
                  </span>
                )}
                <span className="text-text-secondary">
                  Total: <span className="font-medium text-text-primary">{formatCHFExact(txnSummary.total)}</span>
                </span>
                {preview.source_type === 'swissquote_csv' && (
                  <span className="text-xs text-text-muted ml-auto">
                    Swissquote CSV
                  </span>
                )}
              </div>

              {/* Warnings */}
              {preview.warnings?.length > 0 && (
                <div className="bg-warning/10 border border-warning/30 rounded-lg p-3">
                  <div className="flex items-center gap-2 text-warning text-xs font-medium mb-1">
                    <AlertTriangle size={14} />
                    Warnungen
                  </div>
                  {preview.warnings.map((w, i) => (
                    <p key={i} className="text-xs text-text-secondary">{w}</p>
                  ))}
                </div>
              )}

              {/* Swissquote summary */}
              {preview.swissquote_meta && (
                <div className="flex flex-wrap gap-3">
                  {preview.swissquote_meta.aggregated_count > 0 && (
                    <div className="rounded-lg border border-primary/30 bg-primary/5 px-3 py-2 text-xs">
                      <span className="font-medium text-primary">{preview.swissquote_meta.aggregated_count}</span>
                      <span className="text-text-secondary ml-1">Teilausführungen zusammengefasst</span>
                    </div>
                  )}
                  {preview.swissquote_meta.skipped_bonds_count > 0 && (
                    <div className="rounded-lg border border-warning/30 bg-warning/5 px-3 py-2 text-xs">
                      <span className="font-medium text-warning">{preview.swissquote_meta.skipped_bonds_count}</span>
                      <span className="text-text-secondary ml-1">Anleihen übersprungen</span>
                    </div>
                  )}
                  {preview.swissquote_meta.fx_pairs_count > 0 && (
                    <div className="rounded-lg border border-border bg-card-alt/30 px-3 py-2 text-xs">
                      <span className="font-medium text-text-primary">{preview.swissquote_meta.fx_pairs_count}</span>
                      <span className="text-text-secondary ml-1">Wechselkurse abgeleitet</span>
                      <span className="text-text-muted ml-2">
                        (<span className="inline-block w-1.5 h-1.5 rounded-full bg-success align-middle mr-0.5" />SQ
                        <span className="inline-block w-1.5 h-1.5 rounded-full bg-primary align-middle ml-1.5 mr-0.5" />Hist.
                        <span className="inline-block w-1.5 h-1.5 rounded-full bg-text-muted align-middle ml-1.5 mr-0.5" />CSV)
                      </span>
                    </div>
                  )}
                </div>
              )}

              {/* Skipped bonds detail */}
              {preview.swissquote_meta?.skipped_bonds?.length > 0 && (
                <details className="text-xs">
                  <summary className="cursor-pointer text-text-muted hover:text-text-primary">
                    {preview.swissquote_meta.skipped_bonds.length} übersprungene Anleihen anzeigen
                  </summary>
                  <div className="mt-2 rounded-lg border border-border overflow-hidden">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b border-border bg-card-alt/30 text-text-muted">
                          <th className="text-left p-2 font-medium">Datum</th>
                          <th className="text-left p-2 font-medium">Symbol</th>
                          <th className="text-left p-2 font-medium">Name</th>
                          <th className="text-left p-2 font-medium">Grund</th>
                        </tr>
                      </thead>
                      <tbody>
                        {preview.swissquote_meta.skipped_bonds.map((b, i) => (
                          <tr key={i} className="border-b border-border/50">
                            <td className="p-2 text-text-secondary">{b.date}</td>
                            <td className="p-2 font-mono text-text-primary">{b.symbol}</td>
                            <td className="p-2 text-text-secondary">{b.name}</td>
                            <td className="p-2 text-text-muted">{b.reason}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </details>
              )}

              {/* Derived FX rates detail */}
              {preview.swissquote_meta?.fx_pairs?.length > 0 && (
                <details className="text-xs">
                  <summary className="cursor-pointer text-text-muted hover:text-text-primary">
                    {preview.swissquote_meta.fx_pairs.length} abgeleitete Wechselkurse anzeigen
                  </summary>
                  <div className="mt-2 rounded-lg border border-border overflow-hidden">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b border-border bg-card-alt/30 text-text-muted">
                          <th className="text-left p-2 font-medium">Datum</th>
                          <th className="text-left p-2 font-medium">Paar</th>
                          <th className="text-right p-2 font-medium">Kurs</th>
                        </tr>
                      </thead>
                      <tbody>
                        {preview.swissquote_meta.fx_pairs.map((fx, i) => (
                          <tr key={i} className="border-b border-border/50">
                            <td className="p-2 text-text-secondary">{fx.date}</td>
                            <td className="p-2 font-mono text-text-primary">{fx.pair}</td>
                            <td className="p-2 text-right text-text-primary tabular-nums">{fx.rate?.toFixed(4)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </details>
              )}

              {/* CSV Mapping display */}
              {preview.csv_mapping && Object.keys(preview.csv_mapping).length > 0 && (
                <div className="bg-card-alt/30 border border-border rounded-lg p-3">
                  <p className="text-xs font-medium text-text-muted mb-2">Spalten-Zuordnung:</p>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(preview.csv_mapping).map(([field, col]) => (
                      <span key={field} className="text-xs bg-card border border-border rounded px-2 py-0.5">
                        <span className="text-primary">{field}</span>
                        <span className="text-text-muted mx-1">&larr;</span>
                        <span className="text-text-secondary">{col}</span>
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Transactions table */}
              <div className="rounded-lg border border-border">
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[1200px] text-xs">
                    <thead>
                      <tr className="border-b border-border text-text-muted bg-card-alt/30">
                        <th className="text-left p-2 font-medium w-10">#</th>
                        <th className="text-left p-2 font-medium w-[110px]">Datum</th>
                        <th className="text-left p-2 font-medium w-[90px]">Typ</th>
                        <th className="text-left p-2 font-medium w-[100px]">Ticker</th>
                        <th className="text-left p-2 font-medium">Name</th>
                        <th className="text-right p-2 font-medium w-[75px]">Anzahl</th>
                        <th className="text-right p-2 font-medium w-[90px]">Kurs</th>
                        <th className="text-center p-2 font-medium w-[50px]">Whg</th>
                        <th className="text-right p-2 font-medium w-[75px]">FX</th>
                        <th className="text-right p-2 font-medium w-[75px]">Gebühren</th>
                        <th className="text-right p-2 font-medium w-[70px]">Steuern</th>
                        <th className="text-right p-2 font-medium w-[100px]">Total CHF</th>
                        <th className="text-left p-2 font-medium w-[90px]">Klasse</th>
                        <th className="p-2 w-8" />
                      </tr>
                    </thead>
                    <tbody>
                      {preview.transactions.map((txn, idx) => {
                        const lowConf = (txn.confidence || 1) < 0.7
                        const isNew = txn.is_new_position
                        const isDup = txn.is_duplicate && !txn.force_import
                        return (
                          <tr
                            key={idx}
                            className={`border-b border-border/50 hover:bg-card-alt/50 transition-colors ${
                              isDup ? 'bg-danger/10 opacity-60' : lowConf ? 'bg-warning/5' : isNew ? 'bg-primary/5' : ''
                            }`}
                          >
                            <td className="p-2 text-text-muted">
                              {txn.is_duplicate ? (
                                <input
                                  type="checkbox"
                                  checked={!!txn.force_import}
                                  onChange={() => toggleDuplicateOverride(idx)}
                                  title="Trotzdem importieren"
                                  className="accent-primary"
                                />
                              ) : (idx + 1)}
                            </td>
                            <td className="p-2">
                              <DateInput
                                value={txn.date}
                                onChange={(v) => updateField(idx, 'date', v)}
                                className={`${INPUT} w-28`}
                              />
                            </td>
                            <td className="p-2">
                              <div className="flex items-center gap-1">
                                <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold ${TYPE_COLORS[txn.type] || 'bg-card-alt text-text-secondary'}`}>
                                  {TYPE_LABELS[txn.type] || txn.type}
                                </span>
                                {txn.is_duplicate && (
                                  <span className="text-[9px] font-bold bg-danger/20 text-danger px-1 rounded">Duplikat</span>
                                )}
                                {txn.is_aggregated && (
                                  <span className="text-[9px] font-bold bg-primary/20 text-primary px-1 rounded" title={`${txn.aggregated_count} Teilausführungen`}>
                                    {txn.aggregated_count}x
                                  </span>
                                )}
                              </div>
                            </td>
                            <td className="p-2">
                              <div className="flex items-center gap-1">
                                <input
                                  value={txn.ticker || ''}
                                  onChange={(e) => updateField(idx, 'ticker', e.target.value)}
                                  className={`${INPUT} w-24 font-mono`}
                                  placeholder="Ticker"
                                />
                                {isNew && (
                                  <span className="text-[9px] font-bold bg-primary/20 text-primary px-1 rounded">NEU</span>
                                )}
                              </div>
                            </td>
                            <td className="p-2">
                              <input
                                value={txn.name || ''}
                                onChange={(e) => updateField(idx, 'name', e.target.value)}
                                className={`${INPUT} w-32`}
                                placeholder="Name"
                              />
                            </td>
                            <td className="p-2 text-right">
                              <input
                                type="number"
                                step="any"
                                value={txn.shares}
                                onChange={(e) => updateField(idx, 'shares', parseFloat(e.target.value) || 0)}
                                className={`${INPUT} w-16 text-right`}
                              />
                            </td>
                            <td className="p-2 text-right">
                              <input
                                type="number"
                                step="any"
                                value={txn.price_per_share}
                                onChange={(e) => updateField(idx, 'price_per_share', parseFloat(e.target.value) || 0)}
                                className={`${INPUT} w-20 text-right`}
                              />
                            </td>
                            <td className="p-2 text-center text-text-muted">{txn.currency}</td>
                            <td className="p-2 text-right">
                              <div className="flex items-center gap-0.5">
                                <input
                                  type="number"
                                  step="any"
                                  value={txn.fx_rate_to_chf}
                                  onChange={(e) => updateField(idx, 'fx_rate_to_chf', parseFloat(e.target.value) || 1)}
                                  className={`${INPUT} w-16 text-right`}
                                />
                                {txn.fx_source && txn.currency !== 'CHF' && (
                                  <span
                                    className={`shrink-0 w-1.5 h-1.5 rounded-full ${
                                      txn.fx_source === 'swissquote_forex' ? 'bg-success' :
                                      txn.fx_source === 'yfinance_historical' ? 'bg-primary' :
                                      txn.fx_source === 'csv_derived' ? 'bg-text-muted' :
                                      'bg-warning'
                                    }`}
                                    title={
                                      txn.fx_source === 'swissquote_forex' ? 'Swissquote Forex-Kurs' :
                                      txn.fx_source === 'yfinance_historical' ? 'Historischer Kurs (yfinance)' :
                                      txn.fx_source === 'csv_derived' ? 'Aus CSV abgeleitet' :
                                      'Aktueller Marktkurs'
                                    }
                                  />
                                )}
                              </div>
                            </td>
                            <td className="p-2 text-right">
                              <input
                                type="number"
                                step="any"
                                value={txn.fees_chf}
                                onChange={(e) => updateField(idx, 'fees_chf', parseFloat(e.target.value) || 0)}
                                className={`${INPUT} w-16 text-right`}
                              />
                            </td>
                            <td className="p-2 text-right">
                              <input
                                type="number"
                                step="any"
                                value={txn.taxes_chf}
                                onChange={(e) => updateField(idx, 'taxes_chf', parseFloat(e.target.value) || 0)}
                                className={`${INPUT} w-16 text-right`}
                              />
                            </td>
                            <td className="p-2 text-right">
                              <input
                                type="number"
                                step="any"
                                value={txn.total_chf}
                                onChange={(e) => updateField(idx, 'total_chf', parseFloat(e.target.value) || 0)}
                                className={`${INPUT} w-24 text-right font-medium`}
                              />
                            </td>
                            <td className="p-2">
                              <select
                                value={txn.suggested_asset_type || 'stock'}
                                onChange={(e) => updateField(idx, 'suggested_asset_type', e.target.value)}
                                className={`${INPUT} w-24`}
                              >
                                {Object.entries(ASSET_TYPE_LABELS).map(([val, label]) => (
                                  <option key={val} value={val}>{label}</option>
                                ))}
                              </select>
                            </td>
                            <td className="p-2">
                              <button
                                onClick={() => removeRow(idx)}
                                className="p-1 rounded text-text-muted hover:text-danger hover:bg-danger/10 transition-colors"
                                title="Entfernen"
                              >
                                <X size={12} />
                              </button>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* New positions info */}
              {preview.new_positions?.length > 0 && (
                <div className="bg-primary/5 border border-primary/20 rounded-lg p-3">
                  <p className="text-xs font-medium text-primary mb-2">
                    Neue Positionen werden erstellt:
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {preview.new_positions.map((np, i) => (
                      <span key={i} className="text-xs bg-card border border-primary/30 rounded px-2 py-1">
                        <span className="font-mono text-primary font-medium">{np.ticker}</span>
                        <span className="text-text-muted ml-1">({np.suggested_type})</span>
                        {np.name && np.name !== np.ticker && (
                          <span className="text-text-secondary ml-1">— {np.name}</span>
                        )}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Step 5: Result */}
          {step === 5 && result && (
            <div className="flex flex-col items-center justify-center min-h-[300px] text-center">
              <div className="w-16 h-16 rounded-full bg-success/15 flex items-center justify-center mb-4">
                <Check size={32} className="text-success" />
              </div>
              <h4 className="text-lg font-bold text-text-primary mb-2">Import erfolgreich!</h4>
              <p className="text-sm text-text-secondary mb-1">
                <span className="font-medium text-text-primary">{result.created_transactions}</span> Transaktionen importiert
              </p>
              {result.created_positions > 0 && (
                <p className="text-sm text-text-secondary">
                  <span className="font-medium text-primary">{result.created_positions}</span> neue Positionen erstellt
                </p>
              )}

              {/* Save profile offer */}
              {analysis && !analysis.detected_broker && (
                <div className="mt-4 bg-card-alt/30 border border-border rounded-lg p-4">
                  {profileSaved ? (
                    <p className="text-sm text-success flex items-center gap-1.5">
                      <Check size={14} />
                      Profil gespeichert
                    </p>
                  ) : (
                    <>
                      <p className="text-sm text-text-secondary mb-2">Mapping als Profil speichern?</p>
                      <div className="flex items-center gap-2">
                        <label htmlFor="import-profile-name" className="sr-only">Profilname</label>
                        <input
                          id="import-profile-name"
                          value={profileName}
                          onChange={(e) => setProfileName(e.target.value)}
                          placeholder="Profilname"
                          className={INPUT + ' w-48'}
                        />
                        <button
                          onClick={saveProfile}
                          disabled={!profileName.trim()}
                          className="px-3 py-1 text-xs bg-primary text-white rounded hover:bg-primary/80 disabled:opacity-40 transition-colors"
                        >
                          Speichern
                        </button>
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Error */}
        {error && (
          <div className="mx-5 mb-3 text-sm text-danger bg-danger/10 border border-danger/30 rounded-lg px-3 py-2">
            {error}
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between p-5 border-t border-border shrink-0">
          <div>
            {step === 2 && (
              <button
                onClick={() => { setStep(1); setAnalysis(null); setFile(null); setFiles([]); setFileProgress([]); setError(null) }}
                className="flex items-center gap-1.5 text-sm text-text-secondary hover:text-text-primary transition-colors"
              >
                <ChevronLeft size={14} />
                Andere Datei
              </button>
            )}
            {step === 3 && (
              <button
                onClick={() => { setStep(2); setError(null) }}
                className="flex items-center gap-1.5 text-sm text-text-secondary hover:text-text-primary transition-colors"
              >
                <ChevronLeft size={14} />
                Spalten-Zuordnung
              </button>
            )}
            {step === 4 && (
              <button
                onClick={() => {
                  if (isSwissquote) {
                    setStep(1); setAnalysis(null); setPreview(null); setFile(null); setFiles([]); setFileProgress([]); setError(null)
                  } else {
                    setStep(3); setPreview(null); setError(null)
                  }
                }}
                className="flex items-center gap-1.5 text-sm text-text-secondary hover:text-text-primary transition-colors"
              >
                <ChevronLeft size={14} />
                {isSwissquote ? 'Andere Datei' : 'Typ-Zuordnung'}
              </button>
            )}
          </div>
          <div className="flex items-center gap-3">
            {step === 5 ? (
              <button
                onClick={async () => {
                  try {
                    const res = await authFetch('/api/portfolio/positions-without-type')
                    if (res.ok) {
                      const data = await res.json()
                      if (data.length > 0) {
                        setShowTypeWizard(true)
                        return
                      }
                    }
                  } catch {}
                  // No type wizard needed, check stop-loss
                  try {
                    const res = await authFetch('/api/portfolio/positions-without-stoploss')
                    if (res.ok) {
                      const data = await res.json()
                      if (data.length > 0) {
                        setShowStopLossWizard(true)
                        return
                      }
                    }
                  } catch {}
                  onSuccess?.()
                  onClose()
                }}
                className="flex items-center gap-2 bg-primary text-white rounded-lg px-5 py-2 text-sm font-medium hover:bg-primary/80 transition-colors"
              >
                Schliessen
              </button>
            ) : step === 4 ? (
              <button
                onClick={handleConfirm}
                disabled={loading || !preview?.transactions?.length}
                className="flex items-center gap-2 bg-primary text-white rounded-lg px-5 py-2 text-sm font-medium hover:bg-primary/80 transition-colors disabled:opacity-40"
              >
                {loading ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
                {txnSummary?.count || 0} Transaktionen importieren
              </button>
            ) : step === 3 ? (
              <button
                onClick={handleParseWithMapping}
                disabled={loading}
                className="flex items-center gap-2 bg-primary text-white rounded-lg px-5 py-2 text-sm font-medium hover:bg-primary/80 transition-colors disabled:opacity-40"
              >
                {loading ? <Loader2 size={14} className="animate-spin" /> : <ChevronRight size={14} />}
                Weiter
              </button>
            ) : step === 2 ? (
              <button
                onClick={() => { setError(null); setStep(3) }}
                disabled={!canProceedStep2}
                className="flex items-center gap-2 bg-primary text-white rounded-lg px-5 py-2 text-sm font-medium hover:bg-primary/80 transition-colors disabled:opacity-40"
              >
                <ChevronRight size={14} />
                Weiter
              </button>
            ) : (
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary transition-colors"
              >
                Abbrechen
              </button>
            )}
          </div>
        </div>
      </div>

      {showTypeWizard && (
        <PositionTypeWizard
          onClose={async () => {
            setShowTypeWizard(false)
            // Now check for stop-loss
            try {
              const res = await authFetch('/api/portfolio/positions-without-stoploss')
              if (res.ok) {
                const data = await res.json()
                if (data.length > 0) {
                  setShowStopLossWizard(true)
                  return
                }
              }
            } catch {}
            onSuccess?.()
            onClose()
          }}
          onSaved={() => onSuccess?.()}
        />
      )}

      {showStopLossWizard && (
        <StopLossWizard
          onClose={() => { setShowStopLossWizard(false); onSuccess?.(); onClose() }}
          onSaved={() => onSuccess?.()}
        />
      )}
    </div>
  )
}
