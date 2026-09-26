/*
 * FitGains service worker.
 *
 * Conservative caching: navigation requests are network-first so pages are
 * always fresh, static assets are cache-first because they are versioned by
 * the collectstatic/manifest pipeline or change rarely. Only GET requests are
 * intercepted — POST/PUT/DELETE and API traffic go straight to the network.
 */

const STATIC_CACHE = 'fitgains-static-v1';
const PAGE_CACHE = 'fitgains-pages-v1';

const OFFLINE_URL = '/';

self.addEventListener('install', (event) => {
    event.waitUntil(self.skipWaiting());
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches
            .keys()
            .then((keys) =>
                Promise.all(
                    keys
                        .filter((k) => ![STATIC_CACHE, PAGE_CACHE].includes(k))
                        .map((k) => caches.delete(k))
                )
            )
            .then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', (event) => {
    const { request } = event;

    if (request.method !== 'GET' || !request.url.startsWith(self.location.origin)) {
        return;
    }

    const url = new URL(request.url);

    // Never cache API traffic or auth endpoints
    if (url.pathname.startsWith('/api/') || url.pathname.includes('/login')) {
        return;
    }

    // Static assets: cache-first
    if (url.pathname.startsWith('/static/')) {
        event.respondWith(
            caches.match(request).then(
                (cached) =>
                    cached ||
                    fetch(request).then((response) => {
                        if (response.ok) {
                            const clone = response.clone();
                            caches.open(STATIC_CACHE).then((c) => c.put(request, clone));
                        }
                        return response;
                    })
            )
        );
        return;
    }

    // Page navigations: network-first, fall back to the cached page
    if (request.mode === 'navigate') {
        event.respondWith(
            fetch(request)
                .then((response) => {
                    if (response.ok) {
                        const clone = response.clone();
                        caches.open(PAGE_CACHE).then((c) => c.put(request, clone));
                    }
                    return response;
                })
                .catch(async () => {
                    const cached = await caches.match(request);
                    return cached || caches.match(OFFLINE_URL);
                })
        );
    }
});
