import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Mail, ArrowLeft } from 'lucide-react'

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
    <div className="min-h-screen bg-body flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-text-primary">OpenFolio</h1>
          <p className="text-sm text-text-muted mt-1">Portfolio & Marktanalyse</p>
        </div>

        <div className="bg-card border border-border rounded-xl p-6">
          <h2 className="text-lg font-semibold text-text-primary mb-2">Passwort vergessen</h2>

          {sent ? (
            <div>
              <div className="p-3 rounded-lg bg-success/10 border border-success/30 text-sm text-success mb-4">
                Falls ein Account mit dieser E-Mail existiert, haben wir dir einen Link gesendet. Prüfe auch den Spam-Ordner.
              </div>
              <Link to="/login" className="flex items-center gap-1.5 text-sm text-primary hover:underline">
                <ArrowLeft size={14} /> Zurück zur Anmeldung
              </Link>
            </div>
          ) : (
            <>
              <p className="text-sm text-text-muted mb-4">
                Gib deine E-Mail-Adresse ein. Du erhältst einen Link zum Zurücksetzen.
              </p>

              {error && (
                <div className="mb-4 p-3 rounded-lg bg-danger/10 border border-danger/30 text-sm text-danger">
                  {error}
                </div>
              )}

              <form onSubmit={handleSubmit} className="space-y-4">
                <div>
                  <label htmlFor="forgot-email" className="block text-sm text-text-secondary mb-1">E-Mail</label>
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
                      className="w-full bg-body border border-border rounded-lg pl-10 pr-3 py-2.5 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
                    />
                  </div>
                </div>

                <button
                  type="submit"
                  disabled={submitting}
                  className="w-full bg-primary hover:bg-primary/90 text-white rounded-lg py-2.5 text-sm font-medium transition-colors disabled:opacity-50"
                >
                  {submitting ? 'Wird gesendet...' : 'Link senden'}
                </button>
              </form>

              <p className="text-center text-sm text-text-muted mt-4">
                <Link to="/login" className="text-primary hover:underline">Zurück zur Anmeldung</Link>
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
