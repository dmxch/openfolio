import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { CheckCircle } from 'lucide-react'
import PasswordInput from '../components/PasswordInput'
import { authFetch } from '../hooks/useApi'

export default function ChangePassword() {
  const { user } = useAuth()
  const navigate = useNavigate()

  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

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
      const res = await authFetch('/api/auth/force-change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_password: password }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || 'Fehler beim Ändern')
      }
      // Reload user data to clear force_password_change flag
      window.location.href = '/'
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
          <h2 className="text-lg font-semibold text-text-primary mb-2">Passwort ändern</h2>
          <p className="text-sm text-text-muted mb-4">
            Du musst ein neues Passwort setzen, bevor du fortfahren kannst.
          </p>

          {error && (
            <div className="mb-4 p-3 rounded-lg bg-danger/10 border border-danger/30 text-sm text-danger">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="change-password" className="block text-sm text-text-secondary mb-1">Neues Passwort</label>
              <PasswordInput
                id="change-password"
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
              <label htmlFor="change-confirm-password" className="block text-sm text-text-secondary mb-1">Passwort bestätigen</label>
              <PasswordInput
                id="change-confirm-password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                autoComplete="new-password"
              />
            </div>

            <button
              type="submit"
              disabled={submitting || !passwordChecks.every((c) => c.ok)}
              className="w-full bg-primary hover:bg-primary/90 text-white rounded-lg py-2.5 text-sm font-medium transition-colors disabled:opacity-50"
            >
              {submitting ? 'Wird gespeichert...' : 'Passwort speichern'}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
