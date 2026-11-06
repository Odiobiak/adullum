// Notifications on this device (window.Notify): turning them on, reminders,
// and letting go of them on sign-out.
//
// How it fits together: the browser agrees to notifications, web/sw.js is
// registered, the browser's push subscription is sent to POST /me/push, and
// from then on the server can reach this device (app/reminders.py decides
// when, app/push.py sends). Permission is only ever asked for from a tap,
// since browsers refuse a request that comes out of nowhere.
//
// iPhones only allow web notifications for a site added to the Home Screen
// (web/manifest.json makes that possible), so there the first tap explains
// how instead of failing quietly.
//
// Loaded after web/cave.js, whose helpers it borrows at call time.
(function () {
  const cave = () => window.Cave;
  const el = (...args) => cave().el(...args);
  const api = (...args) => cave().api(...args);
  const toast = (text) => cave().toast(text);
  const apiBase = () => (((document.getElementById("apiBase") || {}).value || "").trim() || location.origin).replace(/\/$/, "");

  const supported = () => "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  const isIOS = () => /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const installed = () => window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;

  let keyPromise = null;
  function publicKey() {
    keyPromise = keyPromise || fetch(`${apiBase()}/push/key`).then((r) => r.json()).then((d) => d.key || null).catch(() => null);
    return keyPromise;
  }

  // The server's key, as the bytes PushManager wants.
  function keyBytes(base64) {
    const padded = (base64 + "=".repeat((4 - (base64.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
    return Uint8Array.from(atob(padded), (c) => c.charCodeAt(0));
  }

  function sameKey(subscription, key) {
    const current = subscription.options && subscription.options.applicationServerKey;
    if (!current) return true;
    const a = new Uint8Array(current);
    const b = keyBytes(key);
    return a.length === b.length && a.every((v, i) => v === b[i]);
  }

  const register = () => navigator.serviceWorker.register("sw.js");

  async function subscribe(key) {
    const registration = await register();
    await navigator.serviceWorker.ready;
    let subscription = await registration.pushManager.getSubscription();
    // A subscription made with an older key can't be reached any more.
    if (subscription && !sameKey(subscription, key)) {
      await subscription.unsubscribe();
      subscription = null;
    }
    subscription = subscription || await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(key) });
    await api("/me/push", { method: "POST", body: subscription.toJSON() });
    return subscription;
  }

  function installHelp() {
    const sheet = el("div", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "installTitle" }, [
      el("h3", { id: "installTitle", text: "Reminders on iPhone" }),
      el("p", { class: "sheet-lede", text: "iPhone only sends reminders to apps on the Home Screen. Tap Share, then \"Add to Home Screen\", and open Adullum from there. Then tap the bell again." }),
      el("div", { class: "sheet-actions" }, el("button", { class: "btn btn-ember btn-sm", type: "button", text: "Got it", onclick: () => close() })),
    ]);
    const close = cave().overlay(sheet);
  }

  // Turns notifications on for this device. Call it from a tap. True when
  // this device can now be reached.
  async function enable() {
    if (!supported()) {
      if (isIOS() && !installed()) installHelp();
      else toast("This browser can't show notifications. You can add it to your calendar instead.");
      return false;
    }
    if (Notification.permission === "denied") {
      toast("Notifications are blocked for Adullum. Allow them in this browser's site settings.");
      return false;
    }
    const permission = Notification.permission === "granted" ? "granted" : await Notification.requestPermission();
    if (permission !== "granted") return false;
    const key = await publicKey();
    if (!key) {
      toast("Notifications aren't set up on this server yet.");
      return false;
    }
    try {
      await subscribe(key);
      return true;
    } catch (err) {
      toast(err.message || "Couldn't turn notifications on.");
      return false;
    }
  }

  // Sets (or changes) a reminder; null if notifications couldn't be turned on.
  async function remind(reminder) {
    if (!(await enable())) return null;
    return api("/me/reminders", { method: "PUT", body: reminder });
  }
  const cancel = (key) => api(`/me/reminders?key=${encodeURIComponent(key)}`, { method: "DELETE" });
  async function list() {
    try {
      return await api("/me/reminders");
    } catch {
      return [];
    }
  }

  // On sign-out: this device stops getting that person's notifications.
  // `headers` are the signed-in headers, taken before the session is cleared.
  async function forget(headers) {
    if (!supported()) return;
    try {
      const registration = await navigator.serviceWorker.getRegistration();
      const subscription = registration && await registration.pushManager.getSubscription();
      if (!subscription) return;
      await fetch(`${apiBase()}/me/push/remove`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await headers) },
        body: JSON.stringify({ endpoint: subscription.endpoint }),
      }).catch(() => {});
      await subscription.unsubscribe();
    } catch { /* nothing more to do */ }
  }

  // Already allowed on this device and signed in: quietly make sure the
  // server has this device, and for this person.
  async function refresh() {
    if (!supported() || Notification.permission !== "granted" || !cave().signedIn()) return;
    const key = await publicKey();
    if (!key) return;
    try {
      await subscribe(key);
    } catch { /* tried again next visit */ }
  }

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.addEventListener("message", (e) => {
      if (e.data && e.data.type === "adullum:open" && /^#[\w/\-.:]*$/.test(e.data.url || "")) location.hash = e.data.url;
    });
  }
  document.addEventListener("DOMContentLoaded", () => setTimeout(refresh, 2000));

  window.Notify = { supported, enable, remind, cancel, list, forget };
})();
