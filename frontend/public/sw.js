/* OpenFolio Service Worker — minimal.
 *
 * Zweck: macht die App installierbar (PWA-Kriterium: registrierter SW mit
 * fetch-Handler) und liefert eine Offline-Fallback-Shell.
 *
 * WICHTIG (Korrektheits-Invariante): /api wird NIEMALS gecacht. Finanzdaten
 * sind bewusst no-store — ein Cache wuerde stale/offline Zahlen ausliefern.
 * Statische Assets laufen stale-while-revalidate; Navigationen network-first
 * mit Offline-Fallback auf die App-Shell. Kein Web-Push hier (separates
 * Projekt) — dieser SW ist bewusst schlank.
 */
const CACHE = 'openfolio-shell-v1';
const SHELL = ['/', '/index.html', '/manifest.webmanifest'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Nur eigene Origin, nur GET. /api NIE cachen -> Default (Netz) durchreichen.
  if (
    request.method !== 'GET' ||
    url.origin !== self.location.origin ||
    url.pathname.startsWith('/api/')
  ) {
    return;
  }

  // Navigationsanfragen: network-first, offline -> App-Shell.
  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(() => caches.match('/index.html')));
    return;
  }

  // Statische Assets: stale-while-revalidate.
  event.respondWith(
    caches.match(request).then((cached) => {
      const network = fetch(request)
        .then((resp) => {
          if (resp && resp.status === 200 && resp.type === 'basic') {
            const copy = resp.clone();
            caches.open(CACHE).then((c) => c.put(request, copy));
          }
          return resp;
        })
        .catch(() => cached);
      return cached || network;
    })
  );
});
