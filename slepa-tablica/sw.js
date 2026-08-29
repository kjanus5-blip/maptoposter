/* Ślepa Tablica działa po pierwszym otwarciu bez sieci: silnik OCR i sama aplikacja
   siedzą w pamięci podręcznej przeglądarki. Talie i tak leżą w IndexedDB. */
const CACHE = "slepa-tablica-v1";
const CORE = [
  "./", "./index.html", "./manifest.webmanifest",
  "./icon-192.png", "./icon-512.png", "./icon-maskable.png",
  "./vendor/tesseract.min.js", "./vendor/worker.min.js",
  "./vendor/tesseract-core-simd-lstm.wasm.js", "./vendor/tesseract-core-lstm.wasm.js",
  "./vendor/tessdata/pol.traineddata.gz",
];

self.addEventListener("install", e => {
  e.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    // pojedynczy brakujący plik nie może wywrócić instalacji
    await Promise.allSettled(CORE.map(u => cache.add(new Request(u, {cache: "reload"}))));
    self.skipWaiting();
  })());
});

self.addEventListener("activate", e => {
  e.waitUntil((async () => {
    for (const k of await caches.keys()) if (k !== CACHE) await caches.delete(k);
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  const sameOrigin = url.origin === self.location.origin;

  // stronę bierzemy najpierw z sieci, żeby poprawki wchodziły od razu
  if (req.mode === "navigate" || (sameOrigin && url.pathname.endsWith("/index.html"))){
    e.respondWith((async () => {
      try {
        const fresh = await fetch(req);
        (await caches.open(CACHE)).put("./index.html", fresh.clone());
        return fresh;
      } catch { return (await caches.match("./index.html")) || Response.error(); }
    })());
    return;
  }

  // resztę (silnik, ikony, kroje pisma) z pamięci, a jak jej nie ma — z sieci
  e.respondWith((async () => {
    const hit = await caches.match(req, {ignoreVary: true});
    if (hit) return hit;
    try {
      const res = await fetch(req);
      if (res.ok && (sameOrigin || url.hostname.endsWith("gstatic.com") || url.hostname.endsWith("googleapis.com")))
        (await caches.open(CACHE)).put(req, res.clone());
      return res;
    } catch (err){ return hit || Response.error(); }
  })());
});
