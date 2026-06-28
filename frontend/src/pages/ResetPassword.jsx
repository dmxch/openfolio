import { useState, useEffect } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import { CheckCircle, AlertTriangle } from 'lucide-react'
import PasswordInput from '../components/PasswordInput'
import Logo from '../components/ui/Logo'
import Button from '../components/ui/Button'

const AUTH_BG = { background: 'radial-gradient(900px 500px at 50% -10%,#0e1622 0%,#0a0d12 60%)' }

export default function ResetPassword() {
  const [params] = useSearchParams()
  const token = params.get('token') || ''

  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)
  const [tokenValid, setTokenValid] = useState(null) // null=loading, true/false

  useEffect(() => {
    if (!token) { setTokenValid(false); return }
    fetch('/api/auth/validate-reset-token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
    })
      .then((r) => r.json())
      .then((data) => setTokenValid(data.valid))
      .catch(() => setTokenValid(false))
  }, [token])

  const passwordChecks = [
    { label: 'Mindestens 8 Zeichen', ok: password.length >= 8 },
    { label: 'Mindestens 1 Grossbuchstabe', ok: /[A-Z]/.test(password) },
    { label: 'Mindestens 1 Zahl', ok: /\d/.test(password) },
  ]

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')

    if (password !== confirmPassword) {
      setError('Passwörter stimmen nicht überein')
      return
    }

    setSubmitting(true)
    try {
      const res = await fetch('/api/auth/reset-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, new_password: password }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || 'Fehler beim Zurücksetzen')
      }
      setSuccess(true)
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
        {tokenValid === null ? (
          <p className="text-sm text-text-secondary text-center py-2">Wird überprüft...</p>
        ) : tokenValid === false ? (
          <div>
            <div className="flex items-center gap-2 mb-3">
              <AlertTriangle size={18} className="text-danger" />
              <h1 className="text-[18px] font-semibold text-text-primary">Ungültiger Link</h1>
            </div>
            <p className="text-sm text-text-secondary mb-5">
              Dieser Link ist ungültig oder abgelaufen.
            </p>
            <Link to="/forgot-password" className="text-sm text-primary hover:underline">
              Neuen Link anfordern
            </Link>
          </div>
        ) : success ? (
          <div>
            <div className="flex items-center gap-2 mb-3">
              <CheckCircle size={18} className="text-success" />
              <h1 className="text-[18px] font-semibold text-text-primary">Passwort geändert</h1>
            </div>
            <p className="text-sm text-text-secondary mb-5">
              Du kannst dich jetzt mit deinem neuen Passwort anmelden.
            </p>
            <Link to="/login" className="text-sm text-primary hover:underline">
              Zur Anmeldung
            </Link>
          </div>
        ) : (
          <>
            <h1 className="text-[18px] font-semibold text-text-primary">Neues Passwort setzen</h1>
            <p className="text-sm text-text-secondary mt-1 mb-5">Wähle ein neues, sicheres Passwort.</p>

            {error && (
              <div className="mb-4 p-3 rounded-lg bg-danger/10 border border-danger/30 text-sm text-danger">
                {error}
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label htmlFor="reset-password" className="block text-[13px] text-text-secondary mb-1.5">Neues Passwort</label>
                <PasswordInput
                  id="reset-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoFocus
                  autoComplete="new-password"
                />
                {password && (
                  <div className="mt-2 space-y-1">
                    {passwordChecks.map((c) => (
                      <div key={c.label} className={`flex items-center gap-1.5 text-xs ${c.ok ? 'text-success' : 'text-text-muted'}`}>
                        <CheckCircle size={12} />
                        {c.label}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div>
                <label htmlFor="reset-confirm-password" className="block text-[13px] text-text-secondary mb-1.5">Passwort bestätigen</label>
                <PasswordInput
                  id="reset-confirm-password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  autoComplete="new-password"
                />
              </div>

              <Button
                variant="primary"
                type="submit"
                disabled={submitting || !passwordChecks.every((c) => c.ok)}
                className="w-full justify-center py-2.5 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {submitting ? 'Wird gespeichert...' : 'Passwort speichern'}
              </Button>
            </form>
          </>
        )}
      </div>
    </div>
  )
}
