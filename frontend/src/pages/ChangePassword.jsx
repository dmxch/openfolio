import { useState } from 'react'
import { useNavigate } from 'react-router'
import { useAuth } from '../contexts/AuthContext'
import PasswordInput from '../components/PasswordInput'
import PasswordStrength from '../components/PasswordStrength'
import { passwordMeetsRules } from '../lib/passwordRules'
import { authFetch } from '../hooks/useApi'
import Logo from '../components/ui/Logo'
import Button from '../components/ui/Button'

const AUTH_BG = { background: 'radial-gradient(900px 500px at 50% -10%,#0e1622 0%,#0a0d12 60%)' }

export default function ChangePassword() {
  const { user } = useAuth()
  const navigate = useNavigate()

  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

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
    <div className="min-h-screen flex flex-col items-center justify-center p-6" style={AUTH_BG}>
      <Logo size={32} wordmarkSize={19} className="mb-6" />

      <div className="w-[380px] max-w-full bg-card border border-border rounded-card p-[26px] shadow-xl">
        <h1 className="text-[18px] font-semibold text-text-primary">Passwort ändern</h1>
        <p className="text-sm text-text-secondary mt-1 mb-5">
          Aus Sicherheitsgründen ist ein neues Passwort erforderlich.
        </p>

        {error && (
          <div className="mb-4 p-3 rounded-lg bg-danger/10 border border-danger/30 text-sm text-danger">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="change-password" className="block text-[13px] text-text-secondary mb-1.5">Neues Passwort</label>
            <PasswordInput
              id="change-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoFocus
              autoComplete="new-password"
            />
            <PasswordStrength password={password} />
          </div>

          <div>
            <label htmlFor="change-confirm-password" className="block text-[13px] text-text-secondary mb-1.5">Passwort bestätigen</label>
            <PasswordInput
              id="change-confirm-password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              autoComplete="new-password"
            />
          </div>

          <Button
            variant="primary"
            type="submit"
            disabled={submitting || !passwordMeetsRules(password)}
            className="w-full justify-center py-2.5 max-md:!min-h-[44px] disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {submitting ? 'Wird gespeichert...' : 'Passwort speichern'}
          </Button>
        </form>
      </div>
    </div>
  )
}
