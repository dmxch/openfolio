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

export default function IntegrationsTab() {
  const addToast = useToast()
  const [settings, setSettings] = useState(null)
  const [fredKey, setFredKey] = useState('')
  const [fredSaving, setFredSaving] = useState(false)
  const [fredTesting, setFredTesting] = useState(false)
  const [fredTestResult, setFredTestResult] = useState(null)
  const [loading, setLoading] = useState(true)

  // AI Provider state
  const [aiProvider, setAiProvider] = useState('')
  const [aiModel, setAiModel] = useState('')
  const [aiKey, setAiKey] = useState('')
  const [aiOllamaUrl, setAiOllamaUrl] = useState('http://localhost:11434')
  const [aiSaving, setAiSaving] = useState(false)
  const [aiTesting, setAiTesting] = useState(false)
  const [aiTestResult, setAiTestResult] = useState(null)

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



  async function handleSaveFredKey(e) {
    e.preventDefault()
    setFredSaving(true)
    try {
      const res = await authFetch(`${API_BASE}/settings/fred-api-key`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: fredKey }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail)
      }
      const data = await res.json()
      setSettings((prev) => ({ ...prev, has_fred_api_key: data.has_fred_api_key, fred_api_key_masked: data.fred_api_key_masked }))
      setFredKey('')
      setFredTestResult(null)
      addToast('FRED API Key gespeichert. Indikatoren werden aktualisiert.', 'success')
    } catch (err) {
      addToast(err.message, 'error')
    } finally {
      setFredSaving(false)
    }
  }

  async function handleRemoveFredKey() {
    setFredSaving(true)
    try {
      await authFetch(`${API_BASE}/settings/fred-api-key`, { method: 'DELETE' })
      setSettings((prev) => ({ ...prev, has_fred_api_key: false, fred_api_key_masked: '' }))
      setFredTestResult(null)
      addToast('FRED API Key entfernt', 'success')
    } catch (err) {
      addToast(err.message, 'error')
    } finally {
      setFredSaving(false)
    }
  }

  async function handleTestFredKey() {
    setFredTesting(true)
    setFredTestResult(null)
    try {
      const res = await authFetch(`${API_BASE}/settings/fred-api-key/test`, { method: 'POST' })
      const data = await res.json()
      if (res.ok) {
        setFredTestResult({ ok: true, message: data.message })
      } else {
        setFredTestResult({ ok: false, message: data.detail })
      }
    } catch (err) {
      setFredTestResult({ ok: false, message: err.message })
    } finally {
      setFredTesting(false)
    }
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

  // AI Provider handlers
  async function handleSaveAiProvider(e) {
    e.preventDefault()
    setAiSaving(true)
    try {
      const body = { provider: aiProvider, model: aiModel }
      if (aiProvider === 'ollama') {
        body.ollama_url = aiOllamaUrl
      } else if (aiKey) {
        body.api_key = aiKey
      }
      const res = await authFetch(`${API_BASE}/settings/ai-provider`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail)
      }
      const data = await res.json()
      setSettings(data)
      setAiKey('')
      setAiTestResult(null)
      addToast('KI-Provider gespeichert', 'success')
    } catch (err) {
      addToast(err.message, 'error')
    } finally {
      setAiSaving(false)
    }
  }

  async function handleRemoveAiProvider() {
    setAiSaving(true)
    try {
      await authFetch(`${API_BASE}/settings/ai-provider`, { method: 'DELETE' })
      setSettings((prev) => ({ ...prev, ai_provider: null, ai_model: null, has_ai_api_key: false, ai_api_key_masked: null, ai_ollama_url: null }))
      setAiProvider('')
      setAiModel('')
      setAiTestResult(null)
      addToast('KI-Provider entfernt', 'success')
    } catch (err) {
      addToast(err.message, 'error')
    } finally {
      setAiSaving(false)
    }
  }

  async function handleTestAiProvider() {
    setAiTesting(true)
    setAiTestResult(null)
    try {
      const res = await authFetch(`${API_BASE}/settings/ai-provider/test`, { method: 'POST' })
      const data = await res.json()
      setAiTestResult(data)
    } catch (err) {
      setAiTestResult({ ok: false, message: err.message })
    } finally {
      setAiTesting(false)
    }
  }

  const AI_MODELS = {
    anthropic: [
      { value: 'claude-haiku-4-5-20251001', label: 'Claude Haiku 3.5 (günstigst)' },
      { value: 'claude-sonnet-4-20250514', label: 'Claude Sonnet 4' },
      { value: 'claude-opus-4-0-20250514', label: 'Claude Opus 4' },
    ],
    openai: [
      { value: 'gpt-4o-mini', label: 'GPT-4o mini (günstigst)' },
      { value: 'gpt-4o', label: 'GPT-4o' },
      { value: 'gpt-3.5-turbo', label: 'GPT-3.5 Turbo' },
    ],
  }

  if (loading) return <p className="text-sm text-text-muted">Lade...</p>

  return (
    <div className="space-y-6 max-w-2xl">
      <Section title="FRED API Key">
        <p className="text-sm text-text-secondary mb-3">
          Wird für die Makro-Indikatoren benötigt (Buffett Indicator, Arbeitslosenquote, Zinsstruktur). Dein Key wird verschlüsselt gespeichert.
        </p>
        <p className="text-xs text-text-secondary mb-4">
          Kostenlos erstellen: <a href="https://fred.stlouisfed.org/docs/api/api_key.html" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">fred.stlouisfed.org</a>
        </p>

        {settings?.has_fred_api_key ? (
          <div className="space-y-3">
            <div className="flex items-center gap-3">
              <div className="flex-1 bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-muted font-mono">
                {settings.fred_api_key_masked}
              </div>
              <button
                type="button"
                onClick={handleTestFredKey}
                disabled={fredTesting}
                className="flex items-center gap-1.5 bg-card-alt hover:bg-border/50 text-text-primary rounded-lg px-3 py-2 text-sm border border-border disabled:opacity-40"
              >
                {fredTesting ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle size={14} />}
                Testen
              </button>
              <button
                onClick={handleRemoveFredKey}
                disabled={fredSaving}
                className="text-danger hover:text-danger/80 text-sm px-3 py-2"
              >
                Entfernen
              </button>
            </div>
            <form onSubmit={handleSaveFredKey} className="flex items-center gap-2">
              <label htmlFor="fred-key-replace" className="sr-only">FRED API Key</label>
              <input
                id="fred-key-replace"
                type="password"
                value={fredKey}
                onChange={(e) => setFredKey(e.target.value)}
                placeholder="Neuen Key eingeben zum Ersetzen..."
                className="flex-1 bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 font-mono"
              />
              <button
                type="submit"
                disabled={!fredKey || fredSaving}
                className="bg-primary hover:bg-primary/90 text-white rounded-lg px-4 py-2 text-sm disabled:opacity-40"
              >
                Ersetzen
              </button>
            </form>
            {fredTestResult && (
              <div className={`flex items-center gap-2 p-2 rounded-lg text-sm ${fredTestResult.ok ? 'bg-success/10 text-success' : 'bg-danger/10 text-danger'}`}>
                {fredTestResult.ok ? <CheckCircle size={14} /> : <XCircle size={14} />}
                {fredTestResult.message}
              </div>
            )}
          </div>
        ) : (
          <form onSubmit={handleSaveFredKey} className="flex items-center gap-2">
            <label htmlFor="fred-key-new" className="sr-only">FRED API Key</label>
            <input
              id="fred-key-new"
              type="password"
              value={fredKey}
              onChange={(e) => setFredKey(e.target.value)}
              placeholder="FRED API Key..."
              className="flex-1 bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 font-mono"
            />
            <button
              type="submit"
              disabled={!fredKey || fredSaving}
              className="bg-primary hover:bg-primary/90 text-white rounded-lg px-4 py-2 text-sm disabled:opacity-40"
            >
              Speichern
            </button>
          </form>
        )}
      </Section>

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

      <Section title="KI-Zusammenfassung (optional)">
        <p className="text-sm text-text-secondary mb-3">
          Wird für den News-Newsletter benötigt. Die KI fasst Nachrichten pro Aktie zusammen und bewertet die Kursrelevanz. Dein API Key wird verschlüsselt gespeichert.
        </p>
        <p className="text-xs text-text-secondary mb-4">
          Kosten: ca. $0.01–0.05 pro Newsletter (Haiku/mini). Ohne KI-Provider ist der Newsletter deaktiviert.
        </p>

        {settings?.ai_provider ? (
          <div className="space-y-3">
            <div className="flex items-center gap-3 flex-wrap">
              <div className="bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary">
                {settings.ai_provider === 'anthropic' ? 'Anthropic' : settings.ai_provider === 'openai' ? 'OpenAI' : 'Ollama'} — {settings.ai_model}
              </div>
              {settings.has_ai_api_key && (
                <span className="text-xs text-text-muted font-mono">{settings.ai_api_key_masked}</span>
              )}
              <button
                type="button"
                onClick={handleTestAiProvider}
                disabled={aiTesting}
                className="flex items-center gap-1.5 bg-card-alt hover:bg-border/50 text-text-primary rounded-lg px-3 py-2 text-sm border border-border disabled:opacity-40"
              >
                {aiTesting ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle size={14} />}
                Testen
              </button>
              <button
                onClick={handleRemoveAiProvider}
                disabled={aiSaving}
                className="text-danger hover:text-danger/80 text-sm px-3 py-2"
              >
                Entfernen
              </button>
            </div>
            {aiTestResult && (
              <div className={`p-3 rounded-lg text-sm ${aiTestResult.ok ? 'bg-success/10 text-success' : 'bg-danger/10 text-danger'}`}>
                {aiTestResult.ok ? <CheckCircle size={14} className="inline mr-1.5" /> : <XCircle size={14} className="inline mr-1.5" />}
                {aiTestResult.message}
              </div>
            )}
          </div>
        ) : (
          <form onSubmit={handleSaveAiProvider} className="space-y-3">
            <div>
              <label htmlFor="ai-provider" className="block text-sm text-text-secondary mb-1">Provider</label>
              <select
                id="ai-provider"
                value={aiProvider}
                onChange={(e) => { setAiProvider(e.target.value); setAiModel(''); setAiKey('') }}
                className="bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary w-full"
              >
                <option value="">Bitte wählen...</option>
                <option value="anthropic">Anthropic (Claude)</option>
                <option value="openai">OpenAI (GPT)</option>
                <option value="ollama">Ollama (lokal)</option>
              </select>
            </div>

            {aiProvider && aiProvider !== 'ollama' && (
              <div>
                <label htmlFor="ai-model" className="block text-sm text-text-secondary mb-1">Modell</label>
                <select
                  id="ai-model"
                  value={aiModel}
                  onChange={(e) => setAiModel(e.target.value)}
                  className="bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary w-full"
                >
                  <option value="">Modell wählen...</option>
                  {(AI_MODELS[aiProvider] || []).map(m => (
                    <option key={m.value} value={m.value}>{m.label}</option>
                  ))}
                </select>
              </div>
            )}

            {aiProvider === 'ollama' && (
              <>
                <div>
                  <label htmlFor="ai-model-ollama" className="block text-sm text-text-secondary mb-1">Modell (z.B. llama3, mistral, gemma2)</label>
                  <input
                    id="ai-model-ollama"
                    type="text"
                    value={aiModel}
                    onChange={(e) => setAiModel(e.target.value)}
                    placeholder="llama3"
                    className="bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary w-full font-mono"
                  />
                </div>
                <div>
                  <label htmlFor="ai-ollama-url" className="block text-sm text-text-secondary mb-1">Ollama URL</label>
                  <input
                    id="ai-ollama-url"
                    type="text"
                    value={aiOllamaUrl}
                    onChange={(e) => setAiOllamaUrl(e.target.value)}
                    placeholder="http://localhost:11434"
                    className="bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary w-full font-mono"
                  />
                </div>
              </>
            )}

            {aiProvider && aiProvider !== 'ollama' && (
              <div>
                <label htmlFor="ai-key" className="block text-sm text-text-secondary mb-1">API Key</label>
                <input
                  id="ai-key"
                  type="password"
                  value={aiKey}
                  onChange={(e) => setAiKey(e.target.value)}
                  placeholder={aiProvider === 'anthropic' ? 'sk-ant-...' : 'sk-...'}
                  className="bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary w-full font-mono"
                />
              </div>
            )}

            {aiProvider && (
              <button
                type="submit"
                disabled={!aiProvider || !aiModel || (aiProvider !== 'ollama' && !aiKey) || aiSaving}
                className="bg-primary hover:bg-primary/90 text-white rounded-lg px-4 py-2 text-sm disabled:opacity-40"
              >
                Speichern
              </button>
            )}
          </form>
        )}
      </Section>
    </div>
  )
}
