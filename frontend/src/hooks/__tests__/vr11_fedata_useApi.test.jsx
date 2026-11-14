import { StrictMode } from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { useApi, authFetch, authFetchRetry, fetchShared, apiPost } from '../useApi'
import { setTokens, clearTokens } from '../../contexts/AuthContext'

function response(body, status = 200, headers = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (name) => headers[name] ?? null },
    json: async () => body,
  }
}

// Antwort, die erst auf Zuruf kommt — für Zustände "Request läuft noch".
function deferred() {
  let resolve
  const promise = new Promise((r) => { resolve = r })
  return { promise, resolve }
}

function callsTo(url) {
  return fetch.mock.calls.filter(([u]) => u === url)
}

let tokenSeq = 0

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
  vi.stubGlobal('location', { href: 'http://localhost/', pathname: '/' })
  localStorage.clear()
  // Jeder Test bekommt eine eigene Sitzung: der geteilte GET-Cache hängt am
  // Access-Token, Einträge eines früheren Tests passen damit nie.
  tokenSeq += 1
  setTokens(`access-${tokenSeq}`, `rf-${tokenSeq}`)
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  clearTokens()
})

// --- K075: Sitzung nur bei 401 beenden ---------------------------------------
describe('Refresh: nur 401 beendet die Sitzung (K075)', () => {
  function mockRefresh(refreshResponse) {
    fetch.mockImplementation(async (url) => {
      if (url === '/api/auth/refresh') return refreshResponse
      return response({ detail: 'expired' }, 401)
    })
  }

  it.each([502, 503, 500, 429])('behält den Refresh-Token bei %i und meldet einen Fehler', async (status) => {
    localStorage.setItem('rf', 'rf-keep')
    mockRefresh(response({}, status))

    await expect(authFetch('/api/portfolio/summary')).rejects.toMatchObject({ isNetworkError: true })

    expect(localStorage.getItem('rf')).toBe('rf-keep')
    expect(window.location.href).toBe('http://localhost/')
  })

  it('behält den Refresh-Token bei einer unlesbaren Antwort', async () => {
    localStorage.setItem('rf', 'rf-keep')
    mockRefresh({ ok: true, status: 200, headers: { get: () => null }, json: async () => { throw new SyntaxError('Unexpected token <') } })

    await expect(authFetch('/api/portfolio/summary')).rejects.toMatchObject({ isNetworkError: true })

    expect(localStorage.getItem('rf')).toBe('rf-keep')
    expect(window.location.href).toBe('http://localhost/')
  })

  it('versucht den Refresh beim nächsten Request erneut', async () => {
    localStorage.setItem('rf', 'rf-keep')
    let refreshCalls = 0
    fetch.mockImplementation(async (url, options) => {
      if (url === '/api/auth/refresh') {
        refreshCalls += 1
        return refreshCalls === 1
          ? response({}, 502)
          : response({ access_token: 'access-new', refresh_token: 'rf-new' })
      }
      return options?.headers?.Authorization === 'Bearer access-new'
        ? response({ ok: true })
        : response({ detail: 'expired' }, 401)
    })

    await expect(authFetch('/api/portfolio/summary')).rejects.toMatchObject({ isNetworkError: true })
    const res = await authFetch('/api/portfolio/summary')

    expect(res.status).toBe(200)
    expect(localStorage.getItem('rf')).toBe('rf-new')
  })

  it('beendet die Sitzung bei 401', async () => {
    localStorage.setItem('rf', 'rf-revoked')
    mockRefresh(response({ detail: 'Ungültiger oder abgelaufener Refresh-Token' }, 401))

    const res = await authFetch('/api/portfolio/summary')

    expect(res.status).toBe(401)
    expect(localStorage.getItem('rf')).toBeNull()
    expect(window.location.href).toBe('/login')
  })
})

// --- K050: Daten gehören zu ihrem Endpunkt -----------------------------------
describe('useApi liefert nur Daten des aktuellen Endpunkts (K050)', () => {
  it('zeigt nach einem Pfadwechsel keine Daten des alten Endpunkts', async () => {
    const second = deferred()
    fetch.mockImplementation(async (url) => {
      if (url === '/api/analysis/score/AAPL') return response({ name: 'Apple' })
      if (url === '/api/analysis/score/MSFT') return second.promise
      throw new Error(`unexpected ${url}`)
    })

    const { result, rerender } = renderHook(({ endpoint }) => useApi(endpoint), {
      initialProps: { endpoint: '/analysis/score/AAPL' },
    })
    await waitFor(() => expect(result.current.data).toEqual({ name: 'Apple' }))

    rerender({ endpoint: '/analysis/score/MSFT' })
    // Schon im ersten Render mit dem neuen Endpunkt: nichts von AAPL.
    expect(result.current.data).toBeNull()
    expect(result.current.loading).toBe(true)

    await act(async () => { second.resolve(response({ name: 'Microsoft' })) })
    await waitFor(() => expect(result.current.data).toEqual({ name: 'Microsoft' }))
    expect(result.current.loading).toBe(false)
  })

  it('bleibt leer, wenn der neue Endpunkt mit einem Fehler antwortet', async () => {
    fetch.mockImplementation(async (url) => {
      if (url === '/api/analysis/score/AAPL') return response({ name: 'Apple' })
      return response({ detail: 'not found' }, 404)
    })

    const { result, rerender } = renderHook(({ endpoint }) => useApi(endpoint), {
      initialProps: { endpoint: '/analysis/score/AAPL' },
    })
    await waitFor(() => expect(result.current.data).toEqual({ name: 'Apple' }))

    rerender({ endpoint: '/analysis/score/NOPE' })
    await waitFor(() => expect(result.current.error).toBe('HTTP 404'))

    expect(result.current.data).toBeNull()
    expect(result.current.loading).toBe(false)
  })

  it('behält beim Blättern die alte Seite, bis die neue da ist — nicht nach einem Fehler', async () => {
    const page2 = deferred()
    fetch.mockImplementation(async (url) => {
      if (url === '/api/transactions?page=1') return response({ items: [1] })
      if (url === '/api/transactions?page=2') return page2.promise
      return response({}, 500)
    })

    const { result, rerender } = renderHook(({ endpoint }) => useApi(endpoint), {
      initialProps: { endpoint: '/transactions?page=1' },
    })
    await waitFor(() => expect(result.current.data).toEqual({ items: [1] }))

    rerender({ endpoint: '/transactions?page=2' })
    expect(result.current.loading).toBe(true)
    expect(result.current.data).toEqual({ items: [1] })

    await act(async () => { page2.resolve(response({ items: [2] })) })
    await waitFor(() => expect(result.current.data).toEqual({ items: [2] }))

    rerender({ endpoint: '/transactions?page=3' })
    await waitFor(() => expect(result.current.error).toBe('HTTP 500'))
    expect(result.current.data).toBeNull()
  })

  it('behält die Daten, wenn ein Refetch desselben Endpunkts scheitert', async () => {
    let calls = 0
    fetch.mockImplementation(async () => {
      calls += 1
      return calls === 1 ? response({ value: 1 }) : response({}, 503)
    })

    const { result } = renderHook(() => useApi('/portfolio/summary'))
    await waitFor(() => expect(result.current.data).toEqual({ value: 1 }))

    await act(async () => { await result.current.refetch() })

    expect(result.current.error).toBe('HTTP 503')
    expect(result.current.data).toEqual({ value: 1 })
  })

  it('lädt auch unter StrictMode (Effekte laufen im Dev-Server doppelt)', async () => {
    fetch.mockResolvedValue(response({ value: 1 }))

    const { result } = renderHook(() => useApi('/portfolio/summary'), { wrapper: StrictMode })

    await waitFor(() => expect(result.current.data).toEqual({ value: 1 }))
    expect(result.current.loading).toBe(false)
  })

  it('lädt nicht, solange skip gesetzt ist, und startet danach', async () => {
    fetch.mockResolvedValue(response({ value: 1 }))

    const { result, rerender } = renderHook(({ skip }) => useApi('/portfolio/daily-change', { skip }), {
      initialProps: { skip: true },
    })
    expect(result.current.loading).toBe(false)
    expect(fetch).not.toHaveBeenCalled()

    rerender({ skip: false })
    expect(result.current.loading).toBe(true)
    await waitFor(() => expect(result.current.data).toEqual({ value: 1 }))
  })
})

// --- K068: gleiche GETs werden geteilt ---------------------------------------
describe('useApi teilt laufende und frische GETs (K068)', () => {
  it('schickt für zwei gleichzeitige Abnehmer nur einen Request', async () => {
    fetch.mockResolvedValue(response({ total_return_pct: 4.2 }))

    const a = renderHook(() => useApi('/portfolio/total-return'))
    const b = renderHook(() => useApi('/portfolio/total-return'))

    await waitFor(() => expect(a.result.current.data).toEqual({ total_return_pct: 4.2 }))
    await waitFor(() => expect(b.result.current.data).toEqual({ total_return_pct: 4.2 }))
    expect(callsTo('/api/portfolio/total-return')).toHaveLength(1)
  })

  it('bedient einen später gemounteten Abnehmer aus der frischen Antwort', async () => {
    fetch.mockResolvedValue(response({ value: 1 }))

    const a = renderHook(() => useApi('/portfolio/summary'))
    await waitFor(() => expect(a.result.current.data).toEqual({ value: 1 }))

    const b = renderHook(() => useApi('/portfolio/summary'))
    await waitFor(() => expect(b.result.current.data).toEqual({ value: 1 }))

    expect(callsTo('/api/portfolio/summary')).toHaveLength(1)
  })

  it('lädt neu, wenn die Antwort älter als die TTL ist', async () => {
    fetch.mockResolvedValue(response({ value: 1 }))
    const now = vi.spyOn(Date, 'now')
    now.mockReturnValue(1_000_000)

    const a = renderHook(() => useApi('/portfolio/summary'))
    await waitFor(() => expect(a.result.current.data).toEqual({ value: 1 }))

    now.mockReturnValue(1_000_000 + 6_000)
    const b = renderHook(() => useApi('/portfolio/summary'))
    await waitFor(() => expect(b.result.current.data).toEqual({ value: 1 }))

    expect(callsTo('/api/portfolio/summary')).toHaveLength(2)
  })

  it('verwirft den Cache nach einer Mutation', async () => {
    fetch.mockImplementation(async (url, options) => (
      options?.method === 'POST' ? response({ id: 1 }) : response({ value: 1 })
    ))

    const a = renderHook(() => useApi('/portfolio/summary'))
    await waitFor(() => expect(a.result.current.data).toEqual({ value: 1 }))

    await apiPost('/transactions', { ticker: 'AAPL' })

    const b = renderHook(() => useApi('/portfolio/summary'))
    await waitFor(() => expect(b.result.current.data).toEqual({ value: 1 }))
    expect(callsTo('/api/portfolio/summary')).toHaveLength(2)
  })

  it('reicht keine Antwort der vorigen Sitzung an den nächsten Nutzer', async () => {
    fetch.mockResolvedValueOnce(response({ owner: 'A' }))
    const a = renderHook(() => useApi('/portfolio/summary'))
    await waitFor(() => expect(a.result.current.data).toEqual({ owner: 'A' }))
    a.unmount()

    // Logout und Login eines anderen Nutzers im selben Tab.
    clearTokens()
    setTokens('access-other-user', 'rf-other-user')
    fetch.mockResolvedValueOnce(response({ owner: 'B' }))

    const b = renderHook(() => useApi('/portfolio/summary'))
    await waitFor(() => expect(b.result.current.data).toEqual({ owner: 'B' }))
    expect(callsTo('/api/portfolio/summary')).toHaveLength(2)
  })

  it('refetch umgeht den Cache', async () => {
    let calls = 0
    fetch.mockImplementation(async () => {
      calls += 1
      return response({ value: calls })
    })

    const { result } = renderHook(() => useApi('/portfolio/summary'))
    await waitFor(() => expect(result.current.data).toEqual({ value: 1 }))

    await act(async () => { await result.current.refetch() })

    expect(result.current.data).toEqual({ value: 2 })
  })

  it('cacht keine Fehler', async () => {
    fetch.mockResolvedValueOnce(response({}, 500)).mockResolvedValueOnce(response({ value: 1 }))

    const a = renderHook(() => useApi('/portfolio/summary'))
    await waitFor(() => expect(a.result.current.error).toBe('HTTP 500'))

    const b = renderHook(() => useApi('/portfolio/summary'))
    await waitFor(() => expect(b.result.current.data).toEqual({ value: 1 }))
  })

  it('bricht den Request erst ab, wenn ihn niemand mehr braucht', async () => {
    const pending = deferred()
    fetch.mockImplementation(async () => pending.promise)

    const a = renderHook(() => useApi('/portfolio/total-return'))
    const b = renderHook(() => useApi('/portfolio/total-return'))
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
    const { signal } = fetch.mock.calls[0][1]

    a.unmount()
    expect(signal.aborted).toBe(false)

    b.unmount()
    expect(signal.aborted).toBe(true)
  })

  it('fetchShared teilt den Request mit useApi', async () => {
    fetch.mockResolvedValue(response({ value: 1 }))

    const hook = renderHook(() => useApi('/portfolio/summary'))
    const json = await fetchShared('/portfolio/summary')
    await waitFor(() => expect(hook.result.current.data).toEqual({ value: 1 }))

    expect(json).toEqual({ value: 1 })
    expect(callsTo('/api/portfolio/summary')).toHaveLength(1)
  })

  it('fetchShared lehnt bei HTTP-Fehlern ab', async () => {
    fetch.mockResolvedValue(response({}, 502))

    await expect(fetchShared('/portfolio/summary')).rejects.toThrow('HTTP 502')
  })
})

// --- X23: 429/503 wiederholen ------------------------------------------------
describe('authFetchRetry wiederholt bei 429 und 503 (X23)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  it('wartet Retry-After ab und liefert dann die Antwort', async () => {
    fetch
      .mockResolvedValueOnce(response({}, 429, { 'Retry-After': '1' }))
      .mockResolvedValueOnce(response({ score: 12 }))

    const pending = authFetchRetry('/api/analysis/score/AAPL')
    await vi.advanceTimersByTimeAsync(999)
    expect(fetch).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)

    const res = await pending
    expect(res.status).toBe(200)
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it('wartet ohne Retry-After 2 s (503 vom Proxy)', async () => {
    fetch
      .mockResolvedValueOnce(response({}, 503))
      .mockResolvedValueOnce(response({ score: 12 }))

    const pending = authFetchRetry('/api/analysis/score/AAPL')
    await vi.advanceTimersByTimeAsync(1_999)
    expect(fetch).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)

    expect((await pending).status).toBe(200)
  })

  it('gibt nach drei Wiederholungen auf', async () => {
    fetch.mockResolvedValue(response({}, 429))

    const pending = authFetchRetry('/api/analysis/score/AAPL')
    await vi.advanceTimersByTimeAsync(10_000)

    expect((await pending).status).toBe(429)
    expect(fetch).toHaveBeenCalledTimes(4)
  })

  it('wiederholt andere Fehler nicht', async () => {
    fetch.mockResolvedValue(response({}, 404))

    const res = await authFetchRetry('/api/analysis/score/NOPE')

    expect(res.status).toBe(404)
    expect(fetch).toHaveBeenCalledTimes(1)
  })
})
