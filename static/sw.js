const CACHE_NAME = 'biblia-app-v2';
const ASSETS = [
  '/',
  '/static/index.html',
  '/static/icon-192.png',
  '/static/icon-512.png',
  '/static/manifest.json'
];

// Install Event
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        return cache.addAll(ASSETS);
      })
      .then(() => self.skipWaiting())
  );
});

// Activate Event
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys.map(key => {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// Fetch Event (Network first, fallback to cache)
self.addEventListener('fetch', event => {
  // Only intercept requests for static files or HTML
  const url = new URL(event.request.url);
  if (url.pathname.startsWith('/static/') || url.pathname === '/') {
    event.respondWith(
      fetch(event.request)
        .then(response => {
          // Clone response and save to cache
          const resClone = response.clone();
          caches.open(CACHE_NAME).then(cache => {
            cache.put(event.request, resClone);
          });
          return response;
        })
        .catch(() => {
          // Fallback to cache if offline
          return caches.match(event.request);
        })
    );
  } else {
    // API calls go directly to the network
    event.respondWith(fetch(event.request));
  }
});
