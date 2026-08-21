/* STARFACE WebApp — Service Worker
   Strategie: Nur statische Assets (Icons, Logo, Manifest) aus dem Cache.
   Alle Seiten/APIs laufen über das Netzwerk (Sessions, aktuelle Daten),
   damit nie veraltete oder fremde Daten angezeigt werden. */
const CACHE = "starface-webapp-v1";
const STATIC_ASSETS = [
  "/static/kits-logo.png",
  "/static/icon-192.png",
  "/static/icon-512.png",
  "/static/apple-touch-icon.png",
  "/static/favicon.ico",
  "/static/favicon-32x32.png",
  "/static/site.webmanifest"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(STATIC_ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET") return;
  if (url.origin !== self.location.origin) return;

  // Nur statische Assets aus dem Cache bedienen (cache-first), Rest Netzwerk.
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        if (cached) return cached;
        return fetch(event.request).then((response) => {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(event.request, copy));
          return response;
        });
      })
    );
  }
  // Seiten (HTML) und APIs: immer Netzwerk — keine veralteten Daten.
});
