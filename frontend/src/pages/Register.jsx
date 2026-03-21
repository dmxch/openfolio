import { useState, useEffect } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { Mail, CheckCircle, Ticket } from 'lucide-react'
import PasswordInput from '../components/PasswordInput'
import PasswordStrength from '../components/PasswordStrength'

export default function Register() {
  const { register } = useAuth()
  const navigate = useNavigate()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [inviteCode, setInviteCode] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [regMode, setRegMode] = useState(null)
  const [termsAccepted, setTermsAccepted] = useState(false)

  useEffect(() => {
    fetch('/api/auth/registration-mode')
      .then((r) => r.json())
      .then((data) => setRegMode(data.mode))
      .catch(() => {})
  }, [])

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')

    if (password !== confirmPassword) {
      setError('Passwörter stimmen nicht überein')
      return
    }

    setSubmitting(true)
    try {
      await register(email, password, regMode === 'invite_only' ? inviteCode : undefined)
      sessionStorage.setItem('registerSuccess', 'Konto erfolgreich erstellt. Bitte anmelden.')
      navigate('/login')
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const passwordChecks = [
    { label: '12+ Zeichen', ok: password.length >= 12 },
    { label: 'Grossbuchstabe', ok: /[A-Z]/.test(password) },
    { label: 'Kleinbuchstabe', ok: /[a-z]/.test(password) },
    { label: 'Zahl', ok: /\d/.test(password) },
    { label: 'Sonderzeichen', ok: /[!@#$%^&*()_+\-=\[\]{}|;:,.<>?]/.test(password) },
  ]

  if (regMode === 'disabled') {
    return (
      <div className="min-h-screen bg-body flex items-center justify-center px-4">
        <div className="w-full max-w-sm">
          <div className="text-center mb-8">
            <h1 className="text-2xl font-bold text-text-primary">OpenFolio</h1>
            <p className="text-sm text-text-muted mt-1">Portfolio & Marktanalyse</p>
          </div>
          <div className="bg-card border border-border rounded-xl p-6 text-center">
            <p className="text-sm text-text-muted mb-4">Registrierung ist derzeit geschlossen.</p>
            <Link to="/login" className="text-sm text-primary hover:underline">Zur Anmeldung</Link>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-body flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-text-primary">OpenFolio</h1>
          <p className="text-sm text-text-muted mt-1">Portfolio & Marktanalyse</p>
        </div>

        <div className="bg-card border border-border rounded-xl p-6">
          <h2 className="text-lg font-semibold text-text-primary mb-4">Registrieren</h2>

          {error && (
            <div className="mb-4 p-3 rounded-lg bg-danger/10 border border-danger/30 text-sm text-danger">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {regMode === 'invite_only' && (
              <div>
                <label htmlFor="register-invite" className="block text-sm text-text-secondary mb-1">Einladungscode</label>
                <div className="relative">
                  <Ticket size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
                  <input
                    id="register-invite"
                    type="text"
                    value={inviteCode}
                    onChange={(e) => setInviteCode(e.target.value)}
                    required
                    className="w-full bg-body border border-border rounded-lg pl-10 pr-3 py-2.5 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 font-mono"
                    placeholder="OPEN-FO-2026-XXXX"
                  />
                </div>
              </div>
            )}

            <div>
              <label htmlFor="register-email" className="block text-sm text-text-secondary mb-1">E-Mail</label>
              <div className="relative">
                <Mail size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
                <input
                  id="register-email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  autoFocus={regMode !== 'invite_only'}
                  autoComplete="email"
                  className="w-full bg-body border border-border rounded-lg pl-10 pr-3 py-2.5 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
                />
              </div>
            </div>

            <div>
              <label htmlFor="register-password" className="block text-sm text-text-secondary mb-1">Passwort</label>
              <PasswordInput
                id="register-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
              />
              <PasswordStrength password={password} />
            </div>

            <div>
              <label htmlFor="register-confirm-password" className="block text-sm text-text-secondary mb-1">Passwort bestätigen</label>
              <PasswordInput
                id="register-confirm-password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                autoComplete="new-password"
              />
            </div>

            <label className="flex items-start gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={termsAccepted}
                onChange={(e) => setTermsAccepted(e.target.checked)}
                className="mt-0.5"
              />
              <span className="text-xs text-text-muted leading-relaxed">
                Ich habe die{' '}
                <Link to="/nutzungsbedingungen" target="_blank" className="text-primary hover:underline">Nutzungsbedingungen</Link>
                {' '}und den{' '}
                <Link to="/disclaimer" target="_blank" className="text-primary hover:underline">Haftungsausschluss</Link>
                {' '}gelesen und akzeptiere diese.
              </span>
            </label>

            <button
              type="submit"
              disabled={submitting || !passwordChecks.every((c) => c.ok) || !termsAccepted}
              className="w-full bg-primary hover:bg-primary/90 text-white rounded-lg py-2.5 text-sm font-medium transition-colors disabled:opacity-50"
            >
              {submitting ? 'Wird registriert...' : 'Konto erstellen'}
            </button>
          </form>

          <p className="text-center text-sm text-text-muted mt-4">
            Bereits registriert?{' '}
            <Link to="/login" className="text-primary hover:underline">
              Anmelden
            </Link>
          </p>
        </div>
      </div>
    </div>
  )
}
