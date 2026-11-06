// Adullum's service worker. It does one job: show the notifications the
// server sends (app/push.py) and, when one is tapped, open the right place in
// Adullum. Nothing is cached, so the site behaves exactly as it does without
// it. Registered by web/notify.js once someone turns notifications on.

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { body: event.data ? event.data.text() : "" };
  }
  event.waitUntil(self.registration.showNotification(data.title || "Adullum", {
    body: data.body || "",
    icon: "/icons/icon-192.png",
    badge: "/icons/badge-96.png",
    tag: data.tag || undefined,
    renotify: Boolean(data.tag),
    data: { url: typeof data.url === "string" && data.url.startsWith("#") ? data.url : "#home" },
  }));
});

// Tapping a notification brings an open Adullum window forward and moves it
// to the page (web/notify.js listens for the message), or opens a new one.
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const hash = (event.notification.data && event.notification.data.url) || "#home";
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    const open = windows.find((w) => new URL(w.url).origin === self.location.origin);
    if (open) {
      await open.focus();
      open.postMessage({ type: "adullum:open", url: hash });
      return;
    }
    await self.clients.openWindow(`/${hash}`);
  })());
});
