/* Avito Comparator — service worker.
 *
 * Стратегия:
 * - Статика и shell-страница кешируются (cache-first с обновлением).
 * - API-запросы (/search, /healthz, /export/...) НИКОГДА не кешируются.
 * - WebSocket-handshake (/socket.io/...) пропускается насквозь.
 *
 * Версия меняется при каждом релизе для инвалидации кеша.
 */

const VERSION = 'v1.0.0';
const STATIC_CACHE = `avito-cmp-static-${VERSION}`;

const PRECACHE_URLS = [
  '/',
  '/static/style.css',
  '/static/app.js',
  '/manifest.json',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => cache.addAll(PRECACHE_URLS).catch(() => null))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k.startsWith('avito-cmp-') && k !== STATIC_CACHE)
          .map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

function shouldBypass(url) {
  if (url.pathname.startsWith('/socket.io/')) return true;
  if (url.pathname.startsWith('/search')) return true;
  if (url.pathname.startsWith('/export')) return true;
  if (url.pathname.startsWith('/healthz')) return true;
  if (url.pathname.startsWith('/result/')) return true;
  return false;
}

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (shouldBypass(url)) return;

  event.respondWith(
    caches.match(req).then((cached) => {
      const fetchPromise = fetch(req)
        .then((res) => {
          if (res && res.status === 200 && res.type === 'basic') {
            const copy = res.clone();
            caches.open(STATIC_CACHE).then((cache) => cache.put(req, copy)).catch(() => null);
          }
          return res;
        })
        .catch(() => cached);
      return cached || fetchPromise;
    })
  );
});
