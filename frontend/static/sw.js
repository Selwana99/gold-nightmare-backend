/* Service worker — basic offline support for static assets */
const CACHE_VERSION = 'gn-vision-v2.0.0';
const STATIC_ASSETS = [
  '/',
  '/static/css/main.css',
  '/static/js/i18n.js',
  '/static/js/api.js',
  '/static/js/auth.js',
  '/static/js/render.js',
  '/static/locales/ar.json',
  '/static/locales/en.json',
  '/static/icons/icon.svg',
  '/static/manifest.json',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION).then((cache) =>
      cache.addAll(STATIC_ASSETS).catch((err) => console.warn('SW: cache failed', err))
    )
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  // Don't cache API or POST requests
  if (request.method !== 'GET') return;
  if (request.url.includes('/api/')) return;

  event.respondWith(
    caches.match(request).then((cached) => {
      const networkFetch = fetch(request).then((response) => {
        // Cache successful responses for static assets
        if (response.status === 200 && request.url.includes('/static/')) {
          const clone = response.clone();
          caches.open(CACHE_VERSION).then((cache) => cache.put(request, clone));
        }
        return response;
      }).catch(() => cached);
      return cached || networkFetch;
    })
  );
});
