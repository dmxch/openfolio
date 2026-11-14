import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ register: vi.fn() }) }))

import Register from '../Register'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Register: Einladungscode (K088)', () => {
  it('zeigt als Platzhalter das Format der neuen Codes', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ json: async () => ({ mode: 'invite_only' }) }))
    render(<MemoryRouter><Register /></MemoryRouter>)

    const input = await screen.findByLabelText('Einladungscode')
    // Codes lauten seit K088 «OF-<Zufall>», nicht mehr «OPEN-FO-<Jahr>-XXXX».
    expect(input.placeholder).toMatch(/^OF-/)
    expect(input.placeholder).not.toContain('OPEN-FO')
  })
})
