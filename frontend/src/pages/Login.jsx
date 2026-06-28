import { useState, useEffect } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { Mail } from 'lucide-react'
import PasswordInput from '../components/PasswordInput'
import Logo from '../components/ui/Logo'
import Button from '../components/ui/Button'

const AUTH_BG = { background: 'radial-gradient(900px 500px at 50% -10%,#0e1622 0%,#0a0d12 60%)' }

export default function Login() {
  const { login, mfaRequired, loginWithMfa, cancelMfa } = useAuth()
  const navigate = useNavigate()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [totpCode, setTotpCode] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [useBackupCode, setUseBackupCode] = useState(false)
  const [regMode, setRegMode] = useState(null)
  const [smtpConfigured, setSmtpConfigured] = useState(false)
  const [successMsg, setSuccessMsg] = useState('')

  // Drop buffered plaintext credentials if the MFA step is abandoned
  // (navigation away from the login page).
  useEffect(() => () => cancelMfa(), [cancelMfa])

  useEffect(() => {
    const msg = sessionStorage.getItem('registerSuccess')
    if (msg) {
      setSuccessMsg(msg)
      sessionStorage.removeItem('registerSuccess')
    }
  }, [])

  useEffect(() => {
    fetch('/api/auth/registration-mode')
      .then((r) => r.json())
      .then((data) => {
        setRegMode(data.mode)
        setSmtpConfigured(data.smtp_configured)
      })
      .catch(() => {})
  }, [])

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setSubmitting(true)

    try {
      let result
      if (mfaRequired) {
        result = await loginWithMfa(totpCode)
      } else {
        result = await login(email, password)
      }

      if (result?.mfaRequired) {
        setSubmitting(false)
        return
      }

      // Check force_password_change
      if (result?.user?.force_password_change) {
        navigate('/change-password')
        return
      }

      // Direct navigation for MFA setup to avoid triple redirect (/login → / → /settings)
      if (result?.user?.mfa_setup_required) {
        navigate('/settings')
        return
      }

      navigate('/')
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const showRegisterLink = regMode !== 'disabled'
  const registerHint = regMode === 'invite_only'
    ? 'Registrierung nur mit Einladung'
    : 'Registrieren'

  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-6" style={AUTH_BG}>
      <Logo size={32} wordmarkSize={19} className="mb-6" />

      <div className="w-[380px] max-w-full bg-card border border-border rounded-card p-[26px] shadow-xl">
        <h1 className="text-[18px] font-semibold text-text-primary">
          {mfaRequired ? 'Bestätigung' : 'Anmelden'}
        </h1>
        <p className="text-sm text-text-secondary mt-1 mb-5">
          {mfaRequired
            ? 'Gib den Code aus deiner Authenticator-App ein.'
            : 'Melde dich bei deinem Konto an.'}
        </p>

        {successMsg && (
          <div className="mb-4 p-3 rounded-lg bg-success/10 border border-success/30 text-sm text-success">
            {successMsg}
          </div>
        )}

        {error && (
          <div className="mb-4 p-3 rounded-lg bg-danger/10 border border-danger/30 text-sm text-danger">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          {!mfaRequired ? (
            [
              <div key="email">
                <label htmlFor="login-email" className="block text-[13px] text-text-secondary mb-1.5">E-Mail</label>
                <div className="relative">
                  <Mail size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
                  <input
                    id="login-email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    autoFocus
                    autoComplete="email"
                    className="w-full bg-surface border border-border rounded-lg pl-10 pr-3 py-2.5 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
                    placeholder="admin@openfolio.local"
                  />
                </div>
              </div>,
              <div key="password">
                <div className="flex items-center justify-between mb-1.5">
                  <label htmlFor="login-password" className="block text-[13px] text-text-secondary">Passwort</label>
                  {smtpConfigured && (
                    <Link to="/forgot-password" className="text-xs text-primary hover:underline">
                      Passwort vergessen?
                    </Link>
                  )}
                </div>
                <PasswordInput
                  id="login-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                />
              </div>,
            ]
          ) : (
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label htmlFor="login-mfa-code" className="block text-[13px] text-text-secondary">
                  {useBackupCode ? 'Backup-Code' : 'Authenticator-Code'}
                </label>
                <button
                  type="button"
                  onClick={() => { setUseBackupCode(!useBackupCode); setTotpCode('') }}
                  className="text-xs text-primary hover:underline"
                >
                  {useBackupCode ? 'Authenticator verwenden' : 'Backup-Code verwenden'}
                </button>
              </div>
              {useBackupCode ? (
                <input
                  id="login-mfa-code"
                  type="text"
                  value={totpCode}
                  onChange={(e) => setTotpCode(e.target.value.toUpperCase().slice(0, 9))}
                  required
                  autoFocus
                  maxLength={9}
                  className="w-full bg-surface border border-border rounded-lg px-3 py-3 text-center font-mono text-lg tracking-[0.3em] text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
                  placeholder="XXXX-XXXX"
                />
              ) : (
                <input
                  id="login-mfa-code"
                  type="text"
                  value={totpCode}
                  onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  required
                  autoFocus
                  maxLength={6}
                  pattern="\d{6}"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  className="w-full bg-surface border border-border rounded-lg px-3 py-3 text-center font-mono text-2xl tracking-[0.4em] text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
                  placeholder="000000"
                />
              )}
            </div>
          )}

          <Button
            variant="primary"
            type="submit"
            disabled={submitting}
            className="w-full justify-center py-2.5 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {submitting ? 'Wird angemeldet...' : mfaRequired ? 'Bestätigen' : 'Anmelden'}
          </Button>

          {mfaRequired && (
            <button
              type="button"
              onClick={() => { cancelMfa(); setTotpCode(''); setError('') }}
              className="w-full text-center text-[13px] text-text-muted hover:text-text-primary transition-colors"
            >
              ← Zurück
            </button>
          )}
        </form>

        {showRegisterLink && (
          <p className="text-center text-sm text-text-muted mt-5">
            Noch kein Konto?{' '}
            <Link to="/register" className="text-primary hover:underline">
              {registerHint}
            </Link>
          </p>
        )}
        <p className="text-center text-xs text-text-faint mt-4 space-x-2">
          <Link to="/datenschutz" className="hover:text-text-secondary transition-colors">Datenschutz</Link>
          <span>·</span>
          <Link to="/disclaimer" className="hover:text-text-secondary transition-colors">Disclaimer</Link>
          <span>·</span>
          <Link to="/impressum" className="hover:text-text-secondary transition-colors">Impressum</Link>
        </p>
      </div>
    </div>
  )
}
