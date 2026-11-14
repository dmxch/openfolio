// @vitest-environment node
//
// Tests fuer public/sw.js. Die Datei liegt hier und nicht neben sw.js: Vite
// kopiert public/ unveraendert nach dist, ein Test dort ginge mit in den Build.
import { describe, it, expect, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const SW_SOURCE = readFileSync(fileURLToPath(new URL('../../public/sw.js', import.meta.url)), 'utf-8')
const ORIGIN = 'https://app.example'

function pathOf(request) {
  return typeof request === 'string' ? request : new URL(request.url).pathname
}

/** Laedt sw.js in einen nachgebauten Worker-Scope (Cache Storage im Speicher). */
function loadWorker(fetchImpl = vi.fn()) {
  const listeners = {}
  const stores = new Map()
  const caches = {
    open: async (name) => {
      if (!stores.has(name)) stores.set(name, new Map())
      const store = stores.get(name)
      return {
        put: async (request, resp) => { store.set(pathOf(request), resp) },
        addAll: async (urls) => { urls.forEach((u) => store.set(u, response({ body: 'install' }))) },
      }
    },
    keys: async () => [...stores.keys()],
    delete: async (name) => stores.delete(name),
    match: async (request) => {
      for (const store of stores.values()) {
        if (store.has(pathOf(request))) return store.get(pathOf(request))
      }
      return undefined
    },
  }
  const self = {
    location: { origin: ORIGIN },
    addEventListener: (type, fn) => { listeners[type] = fn },
    skipWaiting: async () => {},
    clients: { claim: async () => {} },
  }
  new Function('self', 'caches', 'fetch', SW_SOURCE)(self, caches, fetchImpl)

  async function lifecycle(type) {
    const pending = []
    listeners[type]({ waitUntil: (p) => pending.push(p) })
    await Promise.all(pending)
  }

  /** Loest ein fetch-Event aus und wartet, bis Antwort und Cache-Schreiben fertig sind. */
  async function dispatchFetch(path, { mode = 'no-cors', method = 'GET', origin = ORIGIN } = {}) {
    const pending = []
    const event = {
      request: { url: origin + path, method, mode },
      handled: false,
      response: undefined,
      respondWith(p) { event.handled = true; event.response = Promise.resolve(p) },
      waitUntil(p) { pending.push(p) },
    }
    listeners.fetch(event)
    const result = event.handled ? await event.response : undefined
    await Promise.all(pending)
    await new Promise((resolve) => setTimeout(resolve, 0))
    return { handled: event.handled, result }
  }

  const cachedPaths = () => [...stores.values()].flatMap((store) => [...store.keys()])
  return { stores, caches, fetchImpl, lifecycle, dispatchFetch, cachedPaths }
}

function response({ status = 200, type = 'basic', contentType = 'text/html', redirected = false, body = '' } = {}) {
  const resp = {
    status,
    type,
    redirected,
    body,
    headers: { get: (name) => (name.toLowerCase() === 'content-type' ? contentType : null) },
  }
  resp.clone = () => ({ ...resp })
  return resp
}

// --- K135: Hash-Assets sammeln sich nicht mehr im Cache Storage ---
describe('Service Worker: /assets/', () => {
  it('reicht Hash-Assets ans Netz durch und legt sie nicht ab', async () => {
    const sw = loadWorker(vi.fn().mockResolvedValue(response({ contentType: 'application/javascript' })))

    const { handled } = await sw.dispatchFetch('/assets/index-3f9a1c.js', { mode: 'cors' })

    expect(handled).toBe(false)
    expect(sw.fetchImpl).not.toHaveBeenCalled()
    expect(sw.cachedPaths()).toEqual([])
  })

  it('verwirft beim Aktivieren den alten Cache mit den gesammelten Assets', async () => {
    const sw = loadWorker()
    const old = await sw.caches.open('openfolio-shell-v1')
    await old.put('/assets/index-old111.js', response())
    await old.put('/assets/index-old222.js', response())

    await sw.lifecycle('install')
    await sw.lifecycle('activate')

    expect(sw.stores.has('openfolio-shell-v1')).toBe(false)
    expect(sw.stores.size).toBe(1)
    expect(sw.cachedPaths().some((p) => p.startsWith('/assets/'))).toBe(false)
  })

  it('haelt die uebrigen statischen Dateien weiter stale-while-revalidate', async () => {
    const sw = loadWorker(vi.fn().mockResolvedValue(response({ contentType: 'application/manifest+json' })))

    const { handled } = await sw.dispatchFetch('/manifest.webmanifest')

    expect(handled).toBe(true)
    expect(sw.cachedPaths()).toEqual(['/manifest.webmanifest'])
  })

  it('fasst /api, fremde Origins und schreibende Requests nicht an', async () => {
    const sw = loadWorker()

    expect((await sw.dispatchFetch('/api/portfolio/summary')).handled).toBe(false)
    expect((await sw.dispatchFetch('/logos/symbol/AAPL', { origin: 'https://assets.parqet.com' })).handled).toBe(false)
    expect((await sw.dispatchFetch('/manifest.webmanifest', { method: 'POST' })).handled).toBe(false)
    expect(sw.fetchImpl).not.toHaveBeenCalled()
    expect(sw.cachedPaths()).toEqual([])
  })
})

// --- X40: die Offline-Shell folgt dem zuletzt geladenen index.html ---
describe('Service Worker: Offline-Shell', () => {
  it('erneuert die Shell bei jeder erfolgreichen Navigation', async () => {
    const sw = loadWorker(vi.fn().mockResolvedValue(response({ body: 'release-2' })))
    await sw.lifecycle('install')

    const { result } = await sw.dispatchFetch('/portfolio', { mode: 'navigate' })

    expect(result.body).toBe('release-2')
    expect((await sw.caches.match('/index.html')).body).toBe('release-2')
    expect(sw.cachedPaths()).not.toContain('/portfolio')
  })

  it('liefert offline die zuletzt geladene Shell', async () => {
    const fetchImpl = vi.fn().mockResolvedValueOnce(response({ body: 'release-2' }))
    const sw = loadWorker(fetchImpl)
    await sw.lifecycle('install')
    await sw.dispatchFetch('/', { mode: 'navigate' })

    fetchImpl.mockRejectedValue(new TypeError('Failed to fetch'))
    const { result } = await sw.dispatchFetch('/performance', { mode: 'navigate' })

    expect(result.body).toBe('release-2')
  })

  it.each([
    ['eine direkt geoeffnete Datei ohne HTML', response({ contentType: 'text/markdown', body: 'x' })],
    ['eine Fehlerantwort', response({ status: 502, body: 'x' })],
    ['eine umgeleitete Antwort', response({ redirected: true, body: 'x' })],
    ['eine opake Antwort', response({ type: 'opaqueredirect', body: 'x' })],
  ])('ersetzt die Shell nicht durch %s', async (_label, resp) => {
    const sw = loadWorker(vi.fn().mockResolvedValue(resp))
    await sw.lifecycle('install')

    const { result } = await sw.dispatchFetch('/changelog.md', { mode: 'navigate' })

    expect(result).toBe(resp)
    expect((await sw.caches.match('/index.html')).body).toBe('install')
  })
})
