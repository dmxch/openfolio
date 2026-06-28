import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Mail, ArrowLeft } from 'lucide-react'
import Logo from '../components/ui/Logo'
import Button from '../components/ui/Button'

const AUTH_BG = { background: 'radial-gradient(900px 500px at 50% -10%,#0e1622 0%,#0a0d12 60%)' }

export default function ForgotPassword() {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      const res = await fetch('/api/auth/forgot-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || 'Fehler beim Senden')
      }
      setSent(true)
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-6" style={AUTH_BG}>
      <Logo size={32} wordmarkSize={19} className="mb-6" />

      <div className="w-[380px] max-w-full bg-card border border-border rounded-card p-[26px] shadow-xl">
        <h1 className="text-[18px] font-semibold text-text-primary">Passwort vergessen</h1>

        {sent ? (
          <div>
            <div className="mt-4 p-3 rounded-lg bg-success/10 border border-success/30 text-sm text-success mb-4">
              Falls ein Account mit dieser E-Mail existiert, haben wir dir einen Link gesendet. Prüfe auch den Spam-Ordner.
            </div>
            <Link to="/login" className="inline-flex items-center gap-1.5 text-sm text-primary hover:underline">
              <ArrowLeft size={14} /> Zurück zur Anmeldung
            </Link>
          </div>
        ) : (
          <>
            <p className="text-sm text-text-secondary mt-1 mb-5">
              Gib deine E-Mail-Adresse ein. Du erhältst einen Link zum Zurücksetzen.
            </p>

            {error && (
              <div className="mb-4 p-3 rounded-lg bg-danger/10 border border-danger/30 text-sm text-danger">
                {error}
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label htmlFor="forgot-email" className="block text-[13px] text-text-secondary mb-1.5">E-Mail</label>
                <div className="relative">
                  <Mail size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
                  <input
                    id="forgot-email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    autoFocus
                    autoComplete="email"
                    className="w-full bg-surface border border-border rounded-lg pl-10 pr-3 py-2.5 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
                  />
                </div>
              </div>

              <Button
                variant="primary"
                type="submit"
                disabled={submitting}
                className="w-full justify-center py-2.5 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {submitting ? 'Wird gesendet...' : 'Link senden'}
              </Button>
            </form>

            <p className="text-center text-sm text-text-muted mt-5">
              <Link to="/login" className="inline-flex items-center gap-1.5 text-primary hover:underline">
                <ArrowLeft size={14} /> Zurück zur Anmeldung
              </Link>
            </p>
          </>
        )}
      </div>
    </div>
  )
}
