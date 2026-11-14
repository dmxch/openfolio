import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'

const auth = vi.hoisted(() => ({ logout: vi.fn(), refreshSession: vi.fn() }))
const navigate = vi.hoisted(() => vi.fn())

vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('../../hooks/useApi', () => ({ authFetch: vi.fn() }))
vi.mock('react-router', () => ({ useNavigate: () => navigate }))
vi.mock('qrcode.react', () => ({ QRCodeSVG: () => null }))

import { authFetch } from '../../hooks/useApi'
import MfaSetup from '../MfaSetup'

// Führt die Einrichtung bis zur Anzeige der Backup-Codes durch.
async function completeSetup() {
  render(<MfaSetup />)
  fireEvent.click(screen.getByRole('button', { name: 'MFA einrichten' }))
  fireEvent.change(await screen.findByLabelText('MFA-Code'), { target: { value: '123456' } })
  fireEvent.click(screen.getByRole('button', { name: 'Verifizieren' }))
  await screen.findByText('Backup-Codes')
}

beforeEach(() => {
  vi.resetAllMocks()
  authFetch.mockImplementation(async (url) => (
    url === '/api/auth/mfa/setup'
      ? { ok: true, json: async () => ({ secret: 'SECRET', qr_code_uri: 'otpauth://totp/x' }) }
      : { ok: true, json: async () => ({ mfa_enabled: true, backup_codes: ['aaaa-bbbb'] }) }
  ))
  vi.stubGlobal('location', { assign: vi.fn() })
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('MfaSetup: «Fertig» nach der Einrichtung (R-frontend-5)', () => {
  it('geht nach erfolgreichem Refresh ins Dashboard', async () => {
    auth.refreshSession.mockResolvedValue(true)
    await completeSetup()

    fireEvent.click(screen.getByRole('button', { name: 'Fertig' }))

    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/', { replace: true }))
    expect(window.location.assign).not.toHaveBeenCalled()
  })

  it('lädt die App neu, wenn der Refresh vorübergehend scheitert (502, 429, kein Netz)', async () => {
    // refreshSession liefert false: user.mfa_setup_required steht noch auf true.
    // Ein navigate('/') führte über ProtectedRoute zurück in die Einrichtung.
    auth.refreshSession.mockResolvedValue(false)
    await completeSetup()

    fireEvent.click(screen.getByRole('button', { name: 'Fertig' }))

    await waitFor(() => expect(window.location.assign).toHaveBeenCalledWith('/'))
    expect(navigate).not.toHaveBeenCalled()
  })
})
