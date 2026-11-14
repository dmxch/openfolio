import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import { AuthProvider, useAuth, clearTokens } from '../AuthContext'

function response(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => null },
    json: async () => body,
  }
}

function Probe() {
  const { user, loading } = useAuth()
  return <div data-testid="state">{loading ? 'loading' : user ? user.email : 'anonymous'}</div>
}

async function renderProvider() {
  render(<AuthProvider><Probe /></AuthProvider>)
  // Mount-Effekt und die Kette der fetch-Promises abarbeiten.
  await act(async () => { await vi.advanceTimersByTimeAsync(0) })
}

function refreshCalls() {
  return fetch.mock.calls.filter(([url]) => url === '/api/auth/refresh')
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal('fetch', vi.fn())
  localStorage.clear()
  clearTokens()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  clearTokens()
})

describe('AuthProvider: Sitzung beim Start wiederherstellen (K075)', () => {
  it.each([502, 503, 500, 429])('behält den Refresh-Token bei %i', async (status) => {
    localStorage.setItem('rf', 'rf-keep')
    fetch.mockResolvedValue(response({}, status))

    await renderProvider()

    expect(screen.getByTestId('state').textContent).toBe('anonymous')
    expect(localStorage.getItem('rf')).toBe('rf-keep')
  })

  it('versucht es nach der Wartezeit erneut und meldet den Nutzer an', async () => {
    localStorage.setItem('rf', 'rf-keep')
    let backendUp = false
    fetch.mockImplementation(async (url) => {
      if (!backendUp) return response({}, 502)
      if (url === '/api/auth/refresh') return response({ access_token: 'access-new', refresh_token: 'rf-new' })
      if (url === '/api/auth/me') return response({ email: 'harry@example.com' })
      throw new Error(`unexpected ${url}`)
    })

    await renderProvider()
    expect(screen.getByTestId('state').textContent).toBe('anonymous')
    expect(refreshCalls()).toHaveLength(1)

    backendUp = true
    await act(async () => { await vi.advanceTimersByTimeAsync(2_000) })

    expect(refreshCalls()).toHaveLength(2)
    expect(screen.getByTestId('state').textContent).toBe('harry@example.com')
    expect(localStorage.getItem('rf')).toBe('rf-new')
  })

  it('wiederholt, wenn der Refresh gelingt, das Profil aber mit 502 antwortet', async () => {
    localStorage.setItem('rf', 'rf-old')
    let meUp = false
    let rotation = 0
    fetch.mockImplementation(async (url) => {
      if (url === '/api/auth/refresh') {
        rotation += 1
        return response({ access_token: `access-${rotation}`, refresh_token: `rf-${rotation}` })
      }
      return meUp ? response({ email: 'harry@example.com' }) : response({}, 502)
    })

    await renderProvider()
    expect(screen.getByTestId('state').textContent).toBe('anonymous')
    expect(localStorage.getItem('rf')).toBe('rf-1')

    meUp = true
    await act(async () => { await vi.advanceTimersByTimeAsync(2_000) })

    expect(screen.getByTestId('state').textContent).toBe('harry@example.com')
    expect(localStorage.getItem('rf')).toBe('rf-2')
  })

  it('wiederholt auch nach einem Netzfehler', async () => {
    localStorage.setItem('rf', 'rf-keep')
    fetch.mockRejectedValue(new TypeError('Failed to fetch'))

    await renderProvider()
    expect(localStorage.getItem('rf')).toBe('rf-keep')

    await act(async () => { await vi.advanceTimersByTimeAsync(2_000) })
    expect(refreshCalls()).toHaveLength(2)
  })

  it('gibt nach der letzten Wartezeit auf', async () => {
    localStorage.setItem('rf', 'rf-keep')
    fetch.mockResolvedValue(response({}, 503))

    await renderProvider()
    await act(async () => { await vi.advanceTimersByTimeAsync(10 * 60_000) })

    // Erster Versuch plus sieben Wiederholungen.
    expect(refreshCalls()).toHaveLength(8)
    expect(localStorage.getItem('rf')).toBe('rf-keep')
  })

  it('beendet die Sitzung bei 401 und wiederholt nicht', async () => {
    localStorage.setItem('rf', 'rf-revoked')
    fetch.mockResolvedValue(response({ detail: 'Ungültiger oder abgelaufener Refresh-Token' }, 401))

    await renderProvider()
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000) })

    expect(screen.getByTestId('state').textContent).toBe('anonymous')
    expect(localStorage.getItem('rf')).toBeNull()
    expect(refreshCalls()).toHaveLength(1)
  })

  it('stellt die Sitzung bei erreichbarem Server sofort wieder her', async () => {
    localStorage.setItem('rf', 'rf-old')
    fetch.mockImplementation(async (url) => (
      url === '/api/auth/refresh'
        ? response({ access_token: 'access-new', refresh_token: 'rf-new' })
        : response({ email: 'harry@example.com' })
    ))

    await renderProvider()

    expect(screen.getByTestId('state').textContent).toBe('harry@example.com')
    expect(localStorage.getItem('rf')).toBe('rf-new')
  })
})
