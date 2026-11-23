import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ user: { email: 'a@example.com' } }) }))
vi.mock('../../hooks/useApi', () => ({ authFetch: vi.fn() }))

import ChangePassword from '../ChangePassword'
import ResetPassword from '../ResetPassword'
import { PASSWORD_RULES, passwordMeetsRules } from '../../lib/passwordRules'

// Erfüllt die alten Regeln der zwei Seiten (8 Zeichen, Grossbuchstabe, Zahl),
// aber nicht die des Servers (12 Zeichen, Kleinbuchstabe, Sonderzeichen).
const OLD_RULES_ONLY = 'Passwort1'
const VALID = 'TestPassw0rd!2026'

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ valid: true }) }))
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Passwortregeln (lib/passwordRules)', () => {
  it('spiegelt validate_password des Servers', () => {
    expect(passwordMeetsRules(VALID)).toBe(true)
    expect(passwordMeetsRules('TestPassw0rd')).toBe(false) // kein Sonderzeichen
    expect(passwordMeetsRules('Test!Pw0rd1')).toBe(false) // 11 Zeichen
    expect(passwordMeetsRules('testpassw0rd!2026')).toBe(false) // kein Grossbuchstabe
    expect(passwordMeetsRules('TESTPASSW0RD!2026')).toBe(false) // kein Kleinbuchstabe
    expect(passwordMeetsRules('TestPassword!abcd')).toBe(false) // keine Zahl
  })

  it('nimmt jedes Sonderzeichen an, das der Server annimmt', () => {
    // Zeichenliste aus validate_password.
    for (const c of '!@#$%^&*()_+-=[]{}|;:,.<>?') {
      expect(passwordMeetsRules(`TestPassw0rd2026${c}`), c).toBe(true)
    }
  })
})

describe.each([
  ['ChangePassword', () => render(<MemoryRouter><ChangePassword /></MemoryRouter>)],
  ['ResetPassword', () => render(<MemoryRouter initialEntries={['/reset-password?token=t']}><ResetPassword /></MemoryRouter>)],
])('%s: Passwortregeln', (_name, renderPage) => {
  it('zeigt die Regeln des Servers und sperrt den Button bis alle erfüllt sind', async () => {
    renderPage()
    const input = await screen.findByLabelText('Neues Passwort')
    const button = screen.getByRole('button', { name: 'Passwort speichern' })

    fireEvent.change(input, { target: { value: OLD_RULES_ONLY } })
    for (const rule of PASSWORD_RULES) expect(screen.getByText(rule.label)).toBeTruthy()
    expect(screen.queryByText('Mindestens 8 Zeichen')).toBeNull()
    expect(button.disabled).toBe(true)

    fireEvent.change(input, { target: { value: VALID } })
    expect(button.disabled).toBe(false)
  })
})
