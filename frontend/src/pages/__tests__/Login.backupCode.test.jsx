import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

const loginWithMfa = vi.fn()
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ login: vi.fn(), mfaRequired: true, loginWithMfa, cancelMfa: vi.fn() }),
}))
vi.mock('../../hooks/useOnlineStatus', () => ({ default: () => true }))

import Login from '../Login'

// Format aus generate_backup_codes (backend/services/auth_service.py): 8 Hex, Bindestrich, 8 Hex.
const BACKUP_CODE = 'ABCD1234-EF567890'

beforeEach(() => {
  loginWithMfa.mockReset().mockResolvedValue({})
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ mode: 'open' }) }))
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function openBackupField() {
  render(<MemoryRouter><Login /></MemoryRouter>)
  fireEvent.click(screen.getByRole('button', { name: 'Backup-Code verwenden' }))
  return screen.getByLabelText('Backup-Code')
}

async function submit(input) {
  fireEvent.submit(input.closest('form'))
  await waitFor(() => expect(loginWithMfa).toHaveBeenCalledTimes(1))
  return loginWithMfa.mock.calls[0][0]
}

describe('Login: Backup-Code', () => {
  it('sendet einen 17-stelligen Code unverkürzt', async () => {
    const input = openBackupField()
    fireEvent.change(input, { target: { value: BACKUP_CODE } })

    expect(input.value).toBe(BACKUP_CODE)
    expect(await submit(input)).toBe(BACKUP_CODE)
  })

  it('begrenzt das Feld nicht unter die Länge eines Codes', () => {
    const input = openBackupField()
    // Das Feld war auf 9 Zeichen begrenzt und zeigte «XXXX-XXXX».
    expect(input.maxLength === -1 || input.maxLength >= BACKUP_CODE.length).toBe(true)
    expect(input.placeholder).toHaveLength(BACKUP_CODE.length)
  })

  it.each([
    ['Kleinbuchstaben', 'abcd1234-ef567890'],
    ['ohne Bindestrich', 'ABCD1234EF567890'],
    ['mit Leerzeichen', ' abcd1234 ef567890 '],
  ])('bringt die Eingabe in die Form des Codes: %s', async (_name, typed) => {
    const input = openBackupField()
    fireEvent.change(input, { target: { value: typed } })

    expect(await submit(input)).toBe(BACKUP_CODE)
  })

  it('lässt den Authenticator-Code bei 6 Ziffern', () => {
    render(<MemoryRouter><Login /></MemoryRouter>)
    const input = screen.getByLabelText('Authenticator-Code')
    fireEvent.change(input, { target: { value: '12a34567' } })
    expect(input.value).toBe('123456')
  })
})
