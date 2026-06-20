/* WeighBridge Setu service worker — offline app shell (Horizon 2).
 *
 * Strategy:
 *   - /api/*           → network only (never cached; the app handles failure +
 *                        the offline token queue covers token creation).
 *   - navigations      → network-first, fall back to cached index.html so the
 *                        app still loads with no internet.
 *   - other GET assets → cache-first with runtime caching (hashed JS/CSS get
 *                        cached on first load).
 */
// CACHE version is stamped with the git SHA by ci-deploy.sh on each deploy.
// Changing this string forces all browsers to update the service worker and
// discard the old cached shell — critical for deploying new frontend builds.
const CACHE = 'wb-shell-v2';
const SHELL = ['/', '/index.html'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  // API + cross-origin: straight to network, no caching.
  if (url.pathname.startsWith('/api/') || url.origin !== self.location.origin) return;

  // Navigations: network-first, fall back to the cached shell when offline.
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req).catch(() => caches.match('/index.html').then((r) => r || caches.match('/')))
    );
    return;
  }

  // Static assets: cache-first, populate cache on first fetch.
  event.respondWith(
    caches.match(req).then((cached) =>
      cached ||
      fetch(req).then((res) => {
        if (res && res.status === 200 && res.type === 'basic') {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return res;
      }).catch(() => cached)
    )
  );
});
