import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const addToast = vi.fn()
const logout = vi.fn()

vi.mock('../../../hooks/useApi', () => ({ authFetch: vi.fn() }))
vi.mock('../../../components/Toast', () => ({ useToast: () => addToast }))
vi.mock('../../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: { email: 'a@example.com', mfa_enabled: true }, logout, refreshSession: vi.fn() }),
}))
vi.mock('react-router', () => ({ useNavigate: () => vi.fn() }))

import { authFetch } from '../../../hooks/useApi'
import AccountTab from '../AccountTab'

const SESSIONS = [
  { id: 's1', user_agent: 'Firefox 140', ip_address: '10.0.0.1', created_at: '2026-11-01T10:00:00Z' },
  { id: 's2', user_agent: 'Safari 19', ip_address: '10.0.0.2', created_at: '2026-11-02T10:00:00Z' },
]

// deleteResponse: Antwort des Servers auf DELETE /auth/sessions[/id].
function mockServer(deleteResponse) {
  authFetch.mockImplementation(async (url, options = {}) => {
    if (options.method === 'DELETE') return deleteResponse
    return { ok: true, json: async () => SESSIONS }
  })
}

async function renderTab() {
  render(<AccountTab />)
  await screen.findByText('Firefox')
}

beforeEach(() => {
  addToast.mockReset()
  logout.mockReset()
  authFetch.mockReset()
})

describe('AccountTab: Sitzungen beenden (K151)', () => {
  it('meldet keinen Erfolg, wenn der Server den Widerruf ablehnt', async () => {
    mockServer({ ok: false, status: 429, json: async () => ({ detail: 'Zu viele Anfragen' }) })
    await renderTab()
    fireEvent.click(screen.getAllByRole('button', { name: 'Beenden' })[0])

    await waitFor(() => expect(addToast).toHaveBeenCalledWith('Sitzung konnte nicht beendet werden', 'error'))
    expect(addToast).not.toHaveBeenCalledWith('Sitzung beendet', 'success')
    // Die Sitzung lebt auf dem Server weiter und bleibt in der Liste.
    expect(screen.getByText('Firefox')).toBeTruthy()
  })

  it('entfernt die Sitzung, wenn der Server den Widerruf bestätigt', async () => {
    mockServer({ ok: true, status: 200, json: async () => ({}) })
    await renderTab()
    fireEvent.click(screen.getAllByRole('button', { name: 'Beenden' })[0])

    await waitFor(() => expect(addToast).toHaveBeenCalledWith('Sitzung beendet', 'success'))
    expect(authFetch).toHaveBeenCalledWith('/api/auth/sessions/s1', { method: 'DELETE' })
    expect(screen.queryByText('Firefox')).toBeNull()
    expect(screen.getByText('Safari')).toBeTruthy()
  })

  it('meldet «Alle Sitzungen beendet» nicht bei einer Ablehnung und meldet nicht ab', async () => {
    mockServer({ ok: false, status: 429, json: async () => ({}) })
    await renderTab()
    fireEvent.click(screen.getByRole('button', { name: 'Alle Sitzungen beenden' }))
    fireEvent.click(screen.getByRole('button', { name: 'Alle beenden' }))

    await waitFor(() => expect(addToast).toHaveBeenCalledWith('Fehler beim Beenden der Sitzungen', 'error'))
    expect(addToast).not.toHaveBeenCalledWith('Alle Sitzungen beendet', 'success')
    expect(logout).not.toHaveBeenCalled()
  })

  it('meldet nach bestätigtem Widerruf aller Sitzungen ab', async () => {
    mockServer({ ok: true, status: 200, json: async () => ({}) })
    await renderTab()
    fireEvent.click(screen.getByRole('button', { name: 'Alle Sitzungen beenden' }))
    fireEvent.click(screen.getByRole('button', { name: 'Alle beenden' }))

    await waitFor(() => expect(logout).toHaveBeenCalledTimes(1))
    expect(addToast).toHaveBeenCalledWith('Alle Sitzungen beendet', 'success')
  })
})
