import { useState, useEffect } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { Mail, Shield } from 'lucide-react'
import PasswordInput from '../components/PasswordInput'

export default function Login() {
  const { login, mfaRequired, loginWithMfa } = useAuth()
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
    <div className="min-h-screen bg-body flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-text-primary">OpenFolio</h1>
          <p className="text-sm text-text-muted mt-1">Portfolio & Marktanalyse</p>
        </div>

        <div className="bg-card border border-border rounded-xl p-6">
          <h2 className="text-lg font-semibold text-text-primary mb-4">
            {mfaRequired ? 'MFA-Code eingeben' : 'Anmelden'}
          </h2>

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
              <>
                <div>
                  <label htmlFor="login-email" className="block text-sm text-text-secondary mb-1">E-Mail</label>
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
                      className="w-full bg-body border border-border rounded-lg pl-10 pr-3 py-2.5 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
                      placeholder="admin@openfolio.local"
                    />
                  </div>
                </div>

                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label htmlFor="login-password" className="block text-sm text-text-secondary">Passwort</label>
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
                </div>
              </>
            ) : (
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label htmlFor="login-mfa-code" className="block text-sm text-text-secondary">
                    {useBackupCode ? 'Backup-Code' : 'Authenticator Code'}
                  </label>
                  <button
                    type="button"
                    onClick={() => { setUseBackupCode(!useBackupCode); setTotpCode('') }}
                    className="text-xs text-primary hover:underline"
                  >
                    {useBackupCode ? 'Authenticator verwenden' : 'Backup-Code verwenden'}
                  </button>
                </div>
                <div className="relative">
                  <Shield size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
                  {useBackupCode ? (
                    <input
                      id="login-mfa-code"
                      type="text"
                      value={totpCode}
                      onChange={(e) => setTotpCode(e.target.value.toUpperCase().slice(0, 9))}
                      required
                      autoFocus
                      maxLength={9}
                      className="w-full bg-body border border-border rounded-lg pl-10 pr-3 py-2.5 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 tracking-widest text-center"
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
                      className="w-full bg-body border border-border rounded-lg pl-10 pr-3 py-2.5 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 tracking-widest text-center"
                      placeholder="000000"
                    />
                  )}
                </div>
              </div>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="w-full bg-primary hover:bg-primary/90 text-white rounded-lg py-2.5 text-sm font-medium transition-colors disabled:opacity-50"
            >
              {submitting ? 'Wird angemeldet...' : mfaRequired ? 'Verifizieren' : 'Anmelden'}
            </button>
          </form>

          {showRegisterLink && (
            <p className="text-center text-sm text-text-muted mt-4">
              Noch kein Konto?{' '}
              <Link to="/register" className="text-primary hover:underline">
                {registerHint}
              </Link>
            </p>
          )}
          <p className="text-center text-xs text-text-secondary mt-4 space-x-2">
            <Link to="/datenschutz" className="hover:text-text-secondary transition-colors">Datenschutz</Link>
            <span>·</span>
            <Link to="/disclaimer" className="hover:text-text-secondary transition-colors">Disclaimer</Link>
            <span>·</span>
            <Link to="/impressum" className="hover:text-text-secondary transition-colors">Impressum</Link>
          </p>
        </div>
      </div>
    </div>
  )
}
