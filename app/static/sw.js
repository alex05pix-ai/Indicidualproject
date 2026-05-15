/**
 * Service Worker для PWA Квартира-Компаратор
 * Кеширует статические ресурсы для офлайн-доступа
 */

const CACHE_NAME = 'kvartira-comparator-v1';
const STATIC_ASSETS = [
    '/',
    '/static/style.css',
    '/static/app.js',
    '/static/manifest.json',
    'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css',
    'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css',
    'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js',
];

// Установка — кешируем статику
self.addEventListener('install', function (event) {
    event.waitUntil(
        caches.open(CACHE_NAME).then(function (cache) {
            return cache.addAll(STATIC_ASSETS);
        }).catch(function (err) {
            console.log('Cache install error:', err);
        })
    );
    self.skipWaiting();
});

// Активация — удаляем старые кеши
self.addEventListener('activate', function (event) {
    event.waitUntil(
        caches.keys().then(function (names) {
            return Promise.all(
                names.filter(function (name) {
                    return name !== CACHE_NAME;
                }).map(function (name) {
                    return caches.delete(name);
                })
            );
        })
    );
    self.clients.claim();
});

// Стратегия: Network First для API, Cache First для статики
self.addEventListener('fetch', function (event) {
    const url = new URL(event.request.url);

    // API-запросы — только сеть
    if (url.pathname.startsWith('/search') ||
        url.pathname.startsWith('/status') ||
        url.pathname.startsWith('/history') ||
        url.pathname.startsWith('/autofill') ||
        url.pathname.startsWith('/export')) {
        event.respondWith(fetch(event.request));
        return;
    }

    // Статика — кеш с fallback на сеть
    event.respondWith(
        caches.match(event.request).then(function (cached) {
            if (cached) return cached;
            return fetch(event.request).then(function (response) {
                // Кешируем успешные ответы на статику
                if (response.status === 200 && url.pathname.startsWith('/static/')) {
                    const clone = response.clone();
                    caches.open(CACHE_NAME).then(function (cache) {
                        cache.put(event.request, clone);
                    });
                }
                return response;
            });
        }).catch(function () {
            // Офлайн — показываем главную страницу из кеша
            if (event.request.mode === 'navigate') {
                return caches.match('/');
            }
        })
    );
});
