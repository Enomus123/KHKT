const CACHE_NAME = 'toco-v1';
const urlsToCache = [
  '/',
  '/static/app/images/toco_idle_2026.png',
  '/static/app/images/tam-mobile.jpg'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(urlsToCache))
  );
});

self.addEventListener('fetch', event => {
  event.respondWith(
    caches.match(event.request).then(response => response || fetch(event.request))
  );
});