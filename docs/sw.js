// Service Worker der App (Tobis Trikot Tracker, TTT): zeigt Pushes an und öffnet beim Antippen den passenden Link.
// Bewusst ohne Zwischenspeicher (Cache), damit Änderungen am Dashboard sofort ankommen.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));

self.addEventListener("push", e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (err) { d = {title: "TTT", body: e.data ? e.data.text() : ""}; }
  e.waitUntil(self.registration.showNotification(d.title || "TTT", {
    body: d.body || "",
    icon: "icon-192.png",
    badge: "icon-192.png",
    data: {url: d.url || "./#eingaenge"},
  }));
});

self.addEventListener("notificationclick", e => {
  e.notification.close();
  const url = new URL((e.notification.data && e.notification.data.url) || "./#eingaenge", self.registration.scope).href;
  e.waitUntil((async () => {
    const wins = await self.clients.matchAll({type: "window", includeUncontrolled: true});
    for (const w of wins) {
      if (w.url.startsWith(self.registration.scope) && url.startsWith(self.registration.scope)) {
        await w.focus();
        return w.navigate(url);
      }
    }
    return self.clients.openWindow(url);
  })());
});
