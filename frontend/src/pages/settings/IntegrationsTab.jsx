import { useState, useEffect } from 'react'
import { useToast } from '../../components/Toast'
import { CheckCircle, XCircle, Loader2, Send } from 'lucide-react'
import { authFetch, API_BASE, Section } from './shared'

const SMTP_PRESETS = {
  gmail: { label: 'Gmail', host: 'smtp.gmail.com', port: 587 },
  outlook: { label: 'Outlook / Microsoft 365', host: 'smtp.office365.com', port: 587 },
  proton: { label: 'Proton Mail (Bridge)', host: 'smtp.protonmail.ch', port: 587 },
  yahoo: { label: 'Yahoo Mail', host: 'smtp.mail.yahoo.com', port: 587 },
  gmx: { label: 'GMX', host: 'mail.gmx.net', port: 587 },
  bluewin: { label: 'Bluewin (Swisscom)', host: 'smtpauths.bluewin.ch', port: 465 },
}

// Konfigurationsdaten fuer die drei externen API-Keys (FRED, FMP, Finnhub).
// Jeder Eintrag steuert einen `<ApiKeyConfig>`-Block. Endpoint-Pfad wird unter
// /api/settings/<endpoint>(/test) gemappt.
const API_KEY_CONFIGS = [
  {
    id: 'fred',
    label: 'FRED API Key',
    endpoint: 'fred-api-key',
    hasField: 'has_fred_api_key',
    maskedField: 'fred_api_key_masked',
    signupUrl: 'https://fred.stlouisfed.org/docs/api/api_key.html',
    signupLabel: 'fred.stlouisfed.org',
    description: 'Wird für die US-Makro-Indikatoren (Buffett Indicator, Arbeitslosenquote, Zinsstruktur, Yield Curve) und die CH 10Y-Rendite im /macro/ch Endpoint genutzt. Der Key ist gratis.',
    placeholder: 'FRED API Key...',
  },
  {
    id: 'fmp',
    label: 'FMP API Key (Financial Modeling Prep)',
    endpoint: 'fmp-api-key',
    hasField: 'has_fmp_api_key',
    maskedField: 'fmp_api_key_masked',
    signupUrl: 'https://site.financialmodelingprep.com/developer/docs',
    signupLabel: 'financialmodelingprep.com',
    description: 'Wird für Fundamentaldaten (Income Statement, Cashflow, Bilanz) auf den Stock-Detail-Seiten genutzt. Free-Tier: 250 Requests pro Tag.',
    placeholder: 'FMP API Key...',
  },
  {
    id: 'finnhub',
    label: 'Finnhub API Key',
    endpoint: 'finnhub-api-key',
    hasField: 'has_finnhub_api_key',
    maskedField: 'finnhub_api_key_masked',
    signupUrl: 'https://finnhub.io/register',
    signupLabel: 'finnhub.io',
    description: 'Wird für Earnings-Termine im /portfolio/upcoming-earnings Endpoint genutzt — strukturierte Daten mit bmo/amc-Tageszeit. Free-Tier: 60 Requests pro Minute. Ohne Key fällt der Endpoint auf yfinance zurück (ohne Tageszeit).',
    placeholder: 'Finnhub API Key...',
  },
]


function ApiKeyConfig({ config, settings, onUpdate }) {
  const addToast = useToast()
  const [keyInput, setKeyInput] = useState('')
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState(null)

  const isConfigured = !!settings?.[config.hasField]
  const masked = settings?.[config.maskedField]

  async function handleSave(e) {
    e.preventDefault()
    setSaving(true)
    try {
      const res = await authFetch(`${API_BASE}/settings/${config.endpoint}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: keyInput }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail)
      }
      const data = await res.json()
      onUpdate({
        [config.hasField]: data[config.hasField],
        [config.maskedField]: data[config.maskedField],
      })
      setKeyInput('')
      setTestResult(null)
      addToast(`${config.label} gespeichert`, 'success')
    } catch (err) {
      addToast(err.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  async function handleRemove() {
    setSaving(true)
    try {
      await authFetch(`${API_BASE}/settings/${config.endpoint}`, { method: 'DELETE' })
      onUpdate({ [config.hasField]: false, [config.maskedField]: '' })
      setTestResult(null)
      addToast(`${config.label} entfernt`, 'success')
    } catch (err) {
      addToast(err.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  async function handleTest() {
    setTesting(true)
    setTestResult(null)
    try {
      const res = await authFetch(`${API_BASE}/settings/${config.endpoint}/test`, { method: 'POST' })
      const data = await res.json()
      if (res.ok) {
        setTestResult({ ok: true, message: data.message })
      } else {
        setTestResult({ ok: false, message: data.detail })
      }
    } catch (err) {
      setTestResult({ ok: false, message: err.message })
    } finally {
      setTesting(false)
    }
  }

  return (
    <Section title={config.label}>
      <p className="text-sm text-text-secondary mb-3">{config.description}</p>
      <p className="text-xs text-text-secondary mb-4">
        Kostenlos erstellen:{' '}
        <a
          href={config.signupUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary hover:underline"
        >
          {config.signupLabel}
        </a>
      </p>

      {isConfigured ? (
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            <div className="flex-1 bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-muted font-mono">
              {masked}
            </div>
            <button
              type="button"
              onClick={handleTest}
              disabled={testing}
              className="flex items-center gap-1.5 bg-card-alt hover:bg-border/50 text-text-primary rounded-lg px-3 py-2 text-sm border border-border disabled:opacity-40"
            >
              {testing ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle size={14} />}
              Testen
            </button>
            <button
              onClick={handleRemove}
              disabled={saving}
              className="text-danger hover:text-danger/80 text-sm px-3 py-2"
            >
              Entfernen
            </button>
          </div>
          <form onSubmit={handleSave} className="flex items-center gap-2">
            <label htmlFor={`${config.id}-key-replace`} className="sr-only">{config.label}</label>
            <input
              id={`${config.id}-key-replace`}
              type="password"
              value={keyInput}
              onChange={(e) => setKeyInput(e.target.value)}
              placeholder="Neuen Key eingeben zum Ersetzen..."
              className="flex-1 bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 font-mono"
            />
            <button
              type="submit"
              disabled={!keyInput || saving}
              className="bg-primary hover:bg-primary/90 text-white rounded-lg px-4 py-2 text-sm disabled:opacity-40"
            >
              Ersetzen
            </button>
          </form>
          {testResult && (
            <div className={`flex items-center gap-2 p-2 rounded-lg text-sm ${testResult.ok ? 'bg-success/10 text-success' : 'bg-danger/10 text-danger'}`}>
              {testResult.ok ? <CheckCircle size={14} /> : <XCircle size={14} />}
              {testResult.message}
            </div>
          )}
        </div>
      ) : (
        <form onSubmit={handleSave} className="flex items-center gap-2">
          <label htmlFor={`${config.id}-key-new`} className="sr-only">{config.label}</label>
          <input
            id={`${config.id}-key-new`}
            type="password"
            value={keyInput}
            onChange={(e) => setKeyInput(e.target.value)}
            placeholder={config.placeholder}
            className="flex-1 bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 font-mono"
          />
          <button
            type="submit"
            disabled={!keyInput || saving}
            className="bg-primary hover:bg-primary/90 text-white rounded-lg px-4 py-2 text-sm disabled:opacity-40"
          >
            Speichern
          </button>
        </form>
      )}
    </Section>
  )
}


export default function IntegrationsTab() {
  const addToast = useToast()
  const [settings, setSettings] = useState(null)
  const [loading, setLoading] = useState(true)

  // SMTP state
  const [smtp, setSmtp] = useState(null)
  const [smtpForm, setSmtpForm] = useState({ provider: '', host: '', port: 587, username: '', password: '', from_email: '', use_tls: true })
  const [smtpSaving, setSmtpSaving] = useState(false)
  const [smtpTesting, setSmtpTesting] = useState(false)
  const [smtpTestResult, setSmtpTestResult] = useState(null)

  useEffect(() => {
    Promise.all([
      authFetch(`${API_BASE}/settings`).then((r) => r.ok ? r.json() : null),
      authFetch(`${API_BASE}/settings/smtp`).then((r) => r.ok ? r.json() : null),
    ]).then(([s, sm]) => {
      if (s) setSettings(s)
      if (sm) {
        setSmtp(sm)
        if (sm.configured) {
          setSmtpForm({ provider: sm.provider || '', host: sm.host, port: sm.port, username: sm.username, password: '', from_email: sm.from_email || '', use_tls: sm.use_tls })
        }
      }
    }).finally(() => setLoading(false))
  }, [])

  function patchSettings(patch) {
    setSettings((prev) => ({ ...(prev || {}), ...patch }))
  }

  function handlePresetChange(provider) {
    const preset = SMTP_PRESETS[provider]
    if (preset) {
      setSmtpForm((prev) => ({ ...prev, provider, host: preset.host, port: preset.port }))
    } else {
      setSmtpForm((prev) => ({ ...prev, provider: '' }))
    }
  }

  async function handleSaveSmtp(e) {
    e.preventDefault()
    if (!smtpForm.host || !smtpForm.username || !smtpForm.password) {
      addToast('Host, Benutzername und Passwort sind erforderlich', 'error')
      return
    }
    setSmtpSaving(true)
    try {
      const res = await authFetch(`${API_BASE}/settings/smtp`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(smtpForm),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail)
      }
      const data = await res.json()
      setSmtp(data)
      setSmtpForm((prev) => ({ ...prev, password: '' }))
      addToast('SMTP-Konfiguration gespeichert', 'success')
    } catch (err) {
      addToast(err.message, 'error')
    } finally {
      setSmtpSaving(false)
    }
  }

  async function handleDeleteSmtp() {
    try {
      await authFetch(`${API_BASE}/settings/smtp`, { method: 'DELETE' })
      setSmtp({ configured: false })
      setSmtpForm({ provider: '', host: '', port: 587, username: '', password: '', from_email: '', use_tls: true })
      addToast('SMTP-Konfiguration entfernt', 'success')
    } catch (err) {
      addToast(err.message, 'error')
    }
  }

  async function handleTestSmtp() {
    setSmtpTesting(true)
    setSmtpTestResult(null)
    try {
      const res = await authFetch(`${API_BASE}/settings/smtp/test`, { method: 'POST' })
      const data = await res.json()
      if (res.ok) {
        setSmtpTestResult({ ok: true, message: data.message })
      } else {
        setSmtpTestResult({ ok: false, message: data.detail })
      }
    } catch (err) {
      setSmtpTestResult({ ok: false, message: err.message })
    } finally {
      setSmtpTesting(false)
    }
  }

  if (loading) return <p className="text-sm text-text-muted">Lade...</p>

  return (
    <div className="space-y-6 max-w-2xl">
      {API_KEY_CONFIGS.map((config) => (
        <ApiKeyConfig
          key={config.id}
          config={config}
          settings={settings}
          onUpdate={patchSettings}
        />
      ))}

      <Section title="E-Mail (SMTP)">
        <p className="text-sm text-text-secondary mb-4">
          Konfiguriere deinen E-Mail-Server für Alert-Benachrichtigungen per E-Mail. Das Passwort wird verschlüsselt gespeichert.
        </p>

        {smtp?.configured && (
          <div className="flex items-center gap-2 mb-4 p-2 bg-success/10 border border-success/20 rounded-lg">
            <CheckCircle size={14} className="text-success" />
            <span className="text-sm text-success">SMTP konfiguriert ({smtp.host}:{smtp.port})</span>
          </div>
        )}

        <form onSubmit={handleSaveSmtp} className="space-y-3">
          <div>
            <label htmlFor="smtp-provider" className="block text-sm text-text-secondary mb-1">Anbieter (Preset)</label>
            <select
              id="smtp-provider"
              value={smtpForm.provider}
              onChange={(e) => handlePresetChange(e.target.value)}
              className="w-full bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
            >
              <option value="">Manuell konfigurieren</option>
              {Object.entries(SMTP_PRESETS).map(([k, v]) => (
                <option key={k} value={k}>{v.label}</option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-[1fr,100px] gap-2">
            <div>
              <label htmlFor="smtp-host" className="block text-sm text-text-secondary mb-1">SMTP Host</label>
              <input
                id="smtp-host"
                type="text"
                value={smtpForm.host}
                onChange={(e) => setSmtpForm((p) => ({ ...p, host: e.target.value }))}
                placeholder="smtp.example.com"
                className="w-full bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
                required
              />
            </div>
            <div>
              <label htmlFor="smtp-port" className="block text-sm text-text-secondary mb-1">Port</label>
              <input
                id="smtp-port"
                type="number"
                value={smtpForm.port}
                onChange={(e) => setSmtpForm((p) => ({ ...p, port: parseInt(e.target.value) || 587 }))}
                className="w-full bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
              />
            </div>
          </div>

          <div>
            <label htmlFor="smtp-username" className="block text-sm text-text-secondary mb-1">Benutzername / E-Mail</label>
            <input
              id="smtp-username"
              type="text"
              value={smtpForm.username}
              onChange={(e) => setSmtpForm((p) => ({ ...p, username: e.target.value }))}
              placeholder="user@example.com"
              className="w-full bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
              required
            />
          </div>

          <div>
            <label htmlFor="smtp-password" className="block text-sm text-text-secondary mb-1">Passwort / App-Passwort</label>
            <input
              id="smtp-password"
              type="password"
              value={smtpForm.password}
              onChange={(e) => setSmtpForm((p) => ({ ...p, password: e.target.value }))}
              placeholder={smtp?.configured ? '(unverändert — nur ausfüllen zum Ändern)' : 'SMTP-Passwort'}
              className="w-full bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
              required={!smtp?.configured}
            />
          </div>

          <div>
            <label htmlFor="smtp-from-email" className="block text-sm text-text-secondary mb-1">Absender-Adresse (optional)</label>
            <input
              id="smtp-from-email"
              type="email"
              value={smtpForm.from_email}
              onChange={(e) => setSmtpForm((p) => ({ ...p, from_email: e.target.value }))}
              placeholder="Falls abweichend vom Benutzernamen"
              className="w-full bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
            />
          </div>

          <label className="flex items-center gap-2 text-sm text-text-secondary cursor-pointer">
            <input
              type="checkbox"
              checked={smtpForm.use_tls}
              onChange={(e) => setSmtpForm((p) => ({ ...p, use_tls: e.target.checked }))}
              className="accent-primary"
            />
            TLS / STARTTLS verwenden
          </label>

          <div className="flex gap-2 pt-1">
            <button
              type="submit"
              disabled={smtpSaving}
              className="bg-primary hover:bg-primary/90 text-white rounded-lg px-4 py-2 text-sm disabled:opacity-40"
            >
              {smtpSaving ? 'Speichere...' : 'SMTP speichern'}
            </button>

            {smtp?.configured && (
              <>
                <button
                  type="button"
                  onClick={handleTestSmtp}
                  disabled={smtpTesting}
                  className="flex items-center gap-1.5 bg-card-alt hover:bg-border/50 text-text-primary rounded-lg px-4 py-2 text-sm border border-border disabled:opacity-40"
                >
                  {smtpTesting ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                  Test senden
                </button>
                <button
                  type="button"
                  onClick={handleDeleteSmtp}
                  className="text-danger hover:text-danger/80 text-sm px-3 py-2"
                >
                  Entfernen
                </button>
              </>
            )}
          </div>

          {smtpTestResult && (
            <div className={`flex items-center gap-2 p-2 rounded-lg text-sm ${smtpTestResult.ok ? 'bg-success/10 text-success' : 'bg-danger/10 text-danger'}`}>
              {smtpTestResult.ok ? <CheckCircle size={14} /> : <XCircle size={14} />}
              {smtpTestResult.message}
            </div>
          )}
        </form>
      </Section>

    </div>
  )
}
