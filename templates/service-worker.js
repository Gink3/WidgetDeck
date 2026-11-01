/* This cache holds a generic offline page and versioned public icons only. */
const CACHE = 'widgetdeck-pwa-v1-{{ revision }}';
const OFFLINE = {{ offline_url|tojson }};
const ICONS = {{ icons|tojson }};
const PUBLIC = [OFFLINE, ...ICONS].map(path => new URL(path, self.location.origin).href);
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(PUBLIC)));
});
self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    for (const name of await caches.keys()) {
      if (name.startsWith('widgetdeck-pwa-') && name !== CACHE) await caches.delete(name);
    }
    await self.clients.claim();
  })());
});
// A waiting update is activated only by the user's explicit update action.
self.addEventListener('message', event => {
  if (event.data?.type === 'WIDGETDECK_ACTIVATE') self.skipWaiting();
});
self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (PUBLIC.includes(url.href)) {
    event.respondWith(caches.open(CACHE).then(async cache => (await cache.match(request)) || fetch(request)));
    return;
  }
  // Never cache private HTML, documents, API responses or mutations. API failures
  // remain failures, including when their URLs are entered in the address bar.
  if (request.mode === 'navigate' && !url.pathname.includes('/api/') &&
      !url.pathname.startsWith('/api/') && !url.pathname.startsWith('/static/')) {
    event.respondWith(fetch(request).catch(async () => {
      const cache = await caches.open(CACHE);
      return (await cache.match(OFFLINE)) || Response.error();
    }));
  }
});
