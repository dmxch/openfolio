/* OpenFolio Service Worker — minimal.
 *
 * Zweck: macht die App installierbar (PWA-Kriterium: registrierter SW mit
 * fetch-Handler) und liefert eine Offline-Fallback-Shell.
 *
 * WICHTIG (Korrektheits-Invariante): /api wird NIEMALS gecacht. Finanzdaten
 * sind bewusst no-store — ein Cache wuerde stale/offline Zahlen ausliefern.
 * Statische Dateien laufen stale-while-revalidate; Navigationen network-first
 * mit Offline-Fallback auf die App-Shell. Kein Web-Push hier (separates
 * Projekt) — dieser SW ist bewusst schlank.
 *
 * /assets/ wird hier NICHT abgelegt: Die Dateinamen tragen einen Hash, jede
 * Version braechte neue Eintraege, die niemand mehr loescht. nginx liefert sie
 * ein Jahr als immutable aus; der HTTP-Cache des Browsers haelt sie auch offline.
 *
 * Der Cache-Name aendert sich nur, wenn alte Eintraege verworfen werden sollen:
 * activate loescht jeden anderen Cache. v2 raeumt die Hash-Assets ab, die v1
 * ueber alle Releases gesammelt hat.
 */
const CACHE = 'openfolio-shell-v2';
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
  // /assets/ ebenfalls durchreichen: siehe Kopfkommentar.
  if (
    request.method !== 'GET' ||
    url.origin !== self.location.origin ||
    url.pathname.startsWith('/api/') ||
    url.pathname.startsWith('/assets/')
  ) {
    return;
  }

  // Navigationsanfragen: network-first, offline -> App-Shell.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((resp) => {
          // Die Shell bei jedem Seitenaufruf erneuern. install laeuft nur, wenn
          // sich sw.js aendert; sonst bliebe der Offline-Fallback auf dem Stand
          // der Erstinstallation und verwiese auf Chunks, die es nicht mehr gibt.
          // nginx liefert fuer jede SPA-Route dasselbe index.html, darum ein
          // fester Schluessel. Nur HTML: eine direkt geoeffnete Datei
          // (/changelog.md, ein Icon) darf die Shell nicht ersetzen.
          const type = resp.headers.get('content-type') || '';
          if (resp.status === 200 && resp.type === 'basic' && !resp.redirected && type.includes('text/html')) {
            const copy = resp.clone();
            event.waitUntil(caches.open(CACHE).then((c) => c.put('/index.html', copy)));
          }
          return resp;
        })
        .catch(() => caches.match('/index.html'))
    );
    return;
  }

  // Uebrige statische Dateien (Manifest, Icons, changelog.md): stale-while-revalidate.
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
