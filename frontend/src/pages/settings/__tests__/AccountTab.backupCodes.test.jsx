import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const addToast = vi.fn()
const refreshSession = vi.fn()
let user

vi.mock('../../../hooks/useApi', () => ({ authFetch: vi.fn() }))
vi.mock('../../../components/Toast', () => ({ useToast: () => addToast }))
vi.mock('../../../contexts/AuthContext', () => ({
  useAuth: () => ({ user, logout: vi.fn(), refreshSession }),
}))
vi.mock('react-router', () => ({ useNavigate: () => vi.fn() }))

import { authFetch } from '../../../hooks/useApi'
import AccountTab from '../AccountTab'

const URL = '/api/auth/mfa/regenerate-backup-codes'
const NEW_CODES = Array.from({ length: 8 }, (_, i) => `ABF1955${i}-AF17CDD${i}`)

// regenerateResponse: Antwort des Servers auf POST /auth/mfa/regenerate-backup-codes.
function mockServer(regenerateResponse) {
  authFetch.mockImplementation(async (url) => {
    if (url === URL) return regenerateResponse
    return { ok: true, json: async () => [] }
  })
}

function regenerateCalls() {
  return authFetch.mock.calls.filter(([url]) => url === URL)
}

async function openForm() {
  render(<AccountTab />)
  fireEvent.click(await screen.findByRole('button', { name: 'Neue Backup-Codes erzeugen' }))
  return screen.getByLabelText('Authenticator-Code')
}

beforeEach(() => {
  addToast.mockReset()
  refreshSession.mockReset().mockResolvedValue(true)
  authFetch.mockReset()
  user = { email: 'a@example.com', mfa_enabled: true, backup_codes_remaining: 1 }
})

describe('AccountTab: neue Backup-Codes erzeugen', () => {
  it('zeigt den Button nur bei aktiver Zwei-Faktor-Authentifizierung', () => {
    user = { email: 'a@example.com', mfa_enabled: false }
    mockServer({ ok: true, json: async () => ({ backup_codes: NEW_CODES }) })
    render(<AccountTab />)

    expect(screen.queryByRole('button', { name: 'Neue Backup-Codes erzeugen' })).toBeNull()
    expect(screen.getByRole('button', { name: 'MFA aktivieren' })).toBeTruthy()
  })

  it('sendet nichts, bevor ein ganzer Authenticator-Code im Feld steht', async () => {
    mockServer({ ok: true, json: async () => ({ backup_codes: NEW_CODES }) })
    const input = await openForm()
    const submit = screen.getByRole('button', { name: 'Codes erzeugen' })

    expect(submit.disabled).toBe(true)
    fireEvent.change(input, { target: { value: '12a34' } })
    expect(input.value).toBe('1234')
    expect(submit.disabled).toBe(true)
    fireEvent.submit(input.closest('form'))

    expect(regenerateCalls()).toHaveLength(0)
  })

  it('warnt vor dem Senden, dass die bisherigen Codes ungültig werden', async () => {
    mockServer({ ok: true, json: async () => ({ backup_codes: NEW_CODES }) })
    await openForm()

    expect(screen.getByText(/Die bisherigen Codes sind danach ungültig/)).toBeTruthy()
  })

  it('sendet den Authenticator-Code, zeigt die neuen Codes und frischt die Anzeige auf', async () => {
    mockServer({ ok: true, json: async () => ({ backup_codes: NEW_CODES }) })
    const input = await openForm()

    fireEvent.change(input, { target: { value: '123456' } })
    fireEvent.click(screen.getByRole('button', { name: 'Codes erzeugen' }))

    const dialog = await screen.findByRole('dialog', { name: 'Backup-Codes' })
    for (const code of NEW_CODES) expect(dialog.textContent).toContain(code)
    expect(regenerateCalls()).toHaveLength(1)
    expect(JSON.parse(regenerateCalls()[0][1].body)).toEqual({ totp_code: '123456' })
    expect(regenerateCalls()[0][1].method).toBe('POST')
    // Das Formular ist zu; der Button steht wieder da.
    expect(screen.queryByLabelText('Authenticator-Code')).toBeNull()
    expect(screen.getByRole('button', { name: 'Neue Backup-Codes erzeugen' })).toBeTruthy()
  })

  it('lädt das Profil erst mit «Fertig» neu und verwirft dann die Codes', async () => {
    // Ein Neuladen bei offenem Fenster könnte bei abgelaufener Sitzung zum Login werfen.
    // Die alten Codes sind dann schon gelöscht, und die neuen hätte niemand gesehen.
    mockServer({ ok: true, json: async () => ({ backup_codes: NEW_CODES }) })
    const input = await openForm()
    fireEvent.change(input, { target: { value: '123456' } })
    fireEvent.click(screen.getByRole('button', { name: 'Codes erzeugen' }))
    await screen.findByRole('dialog', { name: 'Backup-Codes' })

    expect(refreshSession).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Fertig' }))

    await waitFor(() => expect(refreshSession).toHaveBeenCalledTimes(1))
    expect(screen.queryByRole('dialog', { name: 'Backup-Codes' })).toBeNull()
    expect(document.body.textContent).not.toContain(NEW_CODES[0])
  })

  it('sendet bei einem Doppelklick nur eine Anfrage', async () => {
    // Jede Anfrage löscht die Codes der vorherigen: Zwei Antworten, aber nur eine Liste im Fenster.
    let resolve
    authFetch.mockImplementation((url) => (url === URL
      ? new Promise((r) => { resolve = r })
      : Promise.resolve({ ok: true, json: async () => [] })))
    const input = await openForm()
    fireEvent.change(input, { target: { value: '123456' } })

    fireEvent.submit(input.closest('form'))
    fireEvent.submit(input.closest('form'))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Abbrechen' }).disabled).toBe(true))
    fireEvent.submit(input.closest('form'))

    expect(regenerateCalls()).toHaveLength(1)
    resolve({ ok: true, json: async () => ({ backup_codes: NEW_CODES }) })
    await screen.findByRole('dialog', { name: 'Backup-Codes' })
  })

  it('meldet die Ablehnung des Servers und zeigt keine Codes', async () => {
    mockServer({ ok: false, status: 401, json: async () => ({ detail: 'Ungültiger MFA-Code' }) })
    const input = await openForm()

    fireEvent.change(input, { target: { value: '000000' } })
    fireEvent.click(screen.getByRole('button', { name: 'Codes erzeugen' }))

    await waitFor(() => expect(addToast).toHaveBeenCalledWith('Ungültiger MFA-Code', 'error'))
    expect(screen.queryByRole('dialog', { name: 'Backup-Codes' })).toBeNull()
    expect(refreshSession).not.toHaveBeenCalled()
    // Das Formular bleibt offen: Der nächste Code lässt sich gleich eingeben.
    expect(screen.getByLabelText('Authenticator-Code')).toBeTruthy()
  })

  it('meldet einen Fehler ohne JSON-Antwort mit einem eigenen Text', async () => {
    mockServer({ ok: false, status: 502, json: async () => { throw new Error('kein JSON') } })
    const input = await openForm()

    fireEvent.change(input, { target: { value: '123456' } })
    fireEvent.click(screen.getByRole('button', { name: 'Codes erzeugen' }))

    await waitFor(() => expect(addToast).toHaveBeenCalledWith('Backup-Codes konnten nicht erzeugt werden', 'error'))
  })

  it('schliesst das Formular mit «Abbrechen» und leert das Feld', async () => {
    mockServer({ ok: true, json: async () => ({ backup_codes: NEW_CODES }) })
    const input = await openForm()
    fireEvent.change(input, { target: { value: '123456' } })

    fireEvent.click(screen.getByRole('button', { name: 'Abbrechen' }))
    fireEvent.click(screen.getByRole('button', { name: 'Neue Backup-Codes erzeugen' }))

    expect(screen.getByLabelText('Authenticator-Code').value).toBe('')
    expect(regenerateCalls()).toHaveLength(0)
  })
})
