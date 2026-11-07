// Everything personal: sign-in, the home screen, the cave (the journal),
// reading plans, past conversations with Aquila, settings (profile, theme,
// what Aquila remembers), the signed-out page, and the extras under each
// answer. The cave's Prayers tab lives in web/prayers.js and its Refuge tab in
// web/refuge.js; this file hands them their panel. Notes, highlights, saved
// things and reading plans live in the Bible (web/reader.js, web/saved.js),
// which draws the plans page with renderPlans from here.
//
// Loaded before index.html's main script, so it only defines things here and
// reaches back into that script (window.AdullumApp) at call time. All talk with
// Supabase goes through our own API (see app/auth.py): this file holds the
// person's tokens and nothing else.
(function () {
  const STORE_KEY = "adullumSession";
  const THEME_NAMES = { dawn: "Dawn", lily: "Lily", olive: "Olive Grove", twilight: "Twilight", hearth: "Hearth", almond: "Almond", cedar: "Cedar" };
  // Thank-you themes for friends of the cave, people who give monthly
  // (web/support.js, app/support.py). Everyone else sees them in Settings
  // with a way to the Support page.
  const SUPPORTER_THEMES = new Set(["almond", "cedar"]);
  // Starting points offered under the plan builder. Tapping one fills the box.
  const PLAN_ABOUT = "Tell Aquila what you'd like to read, or what you're walking through, and how long you have. She'll lay it out day by day.";
  const PLAN_IDEAS = ["The Gospels in a month", "Two weeks on anxiety", "Psalms for hard nights", "Romans, slowly"];

  const ICON = {
    bookmark: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 3h12v18l-6-4-6 4z"/></svg>',
    graph: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="8" r="2.5"/><circle cx="10" cy="18" r="2.5"/><path d="M8.3 7l7.3.7M7 8.3l2.2 7.4M16.4 10l-4.8 6"/></svg>',
    speaker: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 5L6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"/></svg>',
    share: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v12M7 8l5-5 5 5"/><path d="M5 13v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6"/></svg>',
    check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
    download: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg>',
    book: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M4 21V5M9 7h6"/></svg>',
    heart: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/></svg>',
    edit: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16z"/><path d="M13.5 6.5l4 4"/></svg>',
    forward: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>',
    close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M7 7l10 10M17 7L7 17"/></svg>',
    info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M12 11v6M12 7.5v.01"/></svg>',
    alert: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true"><path d="M12 6.5v7M12 17.5v.01"/></svg>',
    // Aquila's memory: a clock turning back.
    memory: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3.5 12a8.5 8.5 0 1 0 2.5-6L3.5 8.5"/><path d="M3.5 4v4.5H8M12 8v4.5l3 2"/></svg>',
    chat: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/></svg>',
  };

  // ---------------------------------------------------------------------
  // Small helpers
  // ---------------------------------------------------------------------
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const app = () => window.AdullumApp;

  function el(tag, attrs = {}, children = []) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k === "html") node.innerHTML = v; // only ever our own static icon markup
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? "" : v);
    }
    for (const c of [].concat(children)) if (c !== null && c !== undefined && c !== false) node.append(c);
    return node;
  }

  function apiBase() {
    const input = $("#apiBase");
    return ((input && input.value) || location.origin).trim().replace(/\/$/, "");
  }
  function translation() {
    const input = $("#translation");
    return (input && input.value.trim()) || "BSB";
  }
  function localToday() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }

  function when(iso) {
    const d = new Date(iso);
    const days = Math.floor((Date.now() - d.getTime()) / 86400000);
    if (days < 1) return "Today";
    if (days === 1) return "Yesterday";
    if (days < 7) return `${days} days ago`;
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: days > 300 ? "numeric" : undefined });
  }
  function agoPhrase(iso) {
    const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
    if (days < 14) return `${days} days ago`;
    if (days < 60) return `${Math.round(days / 7)} weeks ago`;
    if (days < 365) return `${Math.round(days / 30)} months ago`;
    return "a while back";
  }
  function partOfDay() {
    const h = new Date().getHours();
    return h < 12 ? "morning" : h < 17 ? "afternoon" : "evening";
  }

  // "Matthew 1", "Matthew 2", "Matthew 3", "Mark 1" -> "Matthew 1-3", "Mark 1".
  // A plan stores one reference per chapter; people read runs of them.
  function compactRefs(refs) {
    const runs = [];
    for (const ref of refs || []) {
      const m = ref.match(/^(.*\S)\s+(\d+)$/);
      const last = runs[runs.length - 1];
      if (m && last && last.book === m[1] && Number(m[2]) === last.end + 1) last.end += 1;
      else if (m) runs.push({ book: m[1], start: Number(m[2]), end: Number(m[2]) });
      else runs.push({ label: ref });
    }
    return runs.map((r) => r.label || (r.start === r.end ? `${r.book} ${r.start}` : `${r.book} ${r.start}-${r.end}`));
  }

  // ---------------------------------------------------------------------
  // Toasts: a small card that slides in (from the bottom on a wide screen,
  // from the top on a phone, clear of the tab bar) and goes on its own.
  //   toast("Saved.")                                  a tick, the default
  //   toast(err.message, { tone: "error" })            stays a little longer
  //   toast("Write a little first.", { tone: "info" })
  //   toast("Kept.", { action: { label: "Open", href: "#journal" } })
  // The thin line along the bottom shows the time left; it holds while the
  // pointer or focus is on the card, and a swipe sideways sends it away.
  // Up to three stack; the same words again replace the one showing.
  // ---------------------------------------------------------------------
  const TOAST_MS = { done: 3800, info: 5000, error: 6500 };
  const TOAST_ICONS = { done: ICON.check, info: ICON.info, error: ICON.alert };

  function toastStack() {
    return $("#toasts") || document.body.appendChild(el("section", { id: "toasts", class: "toasts", "aria-label": "Notifications" }));
  }

  function toast(text, { tone = "done", action = null } = {}) {
    if (!TOAST_MS[tone]) tone = "done";
    const stack = toastStack();
    for (const old of stack.children) if (old.dataset.text === text) old.remove();
    while (stack.children.length >= 3) stack.firstElementChild.remove();

    const node = el("div", { class: `toast is-${tone}`, role: tone === "error" ? "alert" : "status", "data-text": text, style: `--toast-ms:${TOAST_MS[tone]}ms` });
    const leave = () => {
      if (node.classList.contains("is-leaving")) return;
      node.classList.add("is-leaving");
      setTimeout(() => node.remove(), 220);
    };
    const act = action && el(action.href ? "a" : "button", {
      class: "toast-action", text: action.label,
      ...(action.href ? { href: action.href } : { type: "button" }),
      onclick: () => { action.onClick?.(); leave(); },
    });
    node.append(
      el("span", { class: "toast-icon", "aria-hidden": "true", html: TOAST_ICONS[tone] }),
      el("p", { class: "toast-text", text }),
      act || "",
      el("button", { class: "toast-close", type: "button", "aria-label": "Dismiss", html: ICON.close, onclick: leave }),
      el("span", { class: "toast-timer", "aria-hidden": "true" }),
    );
    holdWhileHere(node, TOAST_MS[tone], leave);
    swipeAway(node, leave);
    stack.append(node);
  }

  // Runs `leave` after `ms`, holding the count while the pointer or focus is
  // on the card (the CSS line holds with it). Timed here rather than by the
  // line's animation, which reduced motion switches off.
  function holdWhileHere(node, ms, leave) {
    let left = ms, started = Date.now(), timer = setTimeout(leave, left);
    const here = { pointer: false, focus: false };
    const set = (key, value) => {
      const wasHeld = here.pointer || here.focus;
      here[key] = value;
      const held = here.pointer || here.focus;
      if (held && !wasHeld) {
        clearTimeout(timer);
        left -= Date.now() - started;
      } else if (!held && wasHeld) {
        started = Date.now();
        timer = setTimeout(leave, Math.max(left, 1500));
      }
    };
    // A mouse only: a finger's tap would otherwise hold it with nothing to let go.
    node.addEventListener("pointerenter", (e) => e.pointerType === "mouse" && set("pointer", true));
    node.addEventListener("pointerleave", (e) => e.pointerType === "mouse" && set("pointer", false));
    node.addEventListener("focusin", () => set("focus", true));
    node.addEventListener("focusout", (e) => !node.contains(e.relatedTarget) && set("focus", false));
  }

  // Drag a toast sideways; far enough and it goes, otherwise it springs back.
  function swipeAway(node, leave) {
    let startX = null;
    node.addEventListener("pointerdown", (e) => {
      if (e.pointerType === "mouse" || e.target.closest("button, a")) return;
      startX = e.clientX;
      node.setPointerCapture(e.pointerId);
      node.classList.add("is-dragging");
    });
    node.addEventListener("pointermove", (e) => {
      if (startX === null) return;
      const dx = e.clientX - startX;
      node.style.transform = `translateX(${dx}px)`;
      node.style.opacity = String(Math.max(0.2, 1 - Math.abs(dx) / 220));
    });
    const end = (e) => {
      if (startX === null) return;
      const far = Math.abs(e.clientX - startX) > 70;
      startX = null;
      node.classList.remove("is-dragging");
      node.style.transform = node.style.opacity = "";
      if (far) leave();
    };
    node.addEventListener("pointerup", end);
    node.addEventListener("pointercancel", end);
  }

  // Shows `content` in a dimmed overlay that closes on Escape or an outside
  // click. Returns the function that closes it.
  function overlay(content) {
    const wrap = el("div", { class: "sheet-overlay" }, content);
    const close = () => {
      wrap.remove();
      document.removeEventListener("keydown", onKey);
    };
    const onKey = (e) => e.key === "Escape" && close();
    wrap.addEventListener("click", (e) => e.target === wrap && close());
    document.addEventListener("keydown", onKey);
    document.body.append(wrap);
    const first = wrap.querySelector("textarea, input");
    if (first) setTimeout(() => first.focus(), 50);
    return close;
  }

  // ---------------------------------------------------------------------
  // Info buttons. Explanations sit behind a small (i) beside a title instead
  // of as paragraphs under it, so every screen stays light to read. Tapping
  // it opens a small popover with the text and, when there's more to say, a
  // "Learn more" link that opens the fuller explanation.
  //
  // Drawn content calls info() or titleInfo(). Static headings in index.html
  // carry data-info="..." and upgradeInfo() adds the button on load.
  // Keep anything that has to be seen straight away (safety, helplines,
  // what sharing exposes) on the page, not in here.
  // ---------------------------------------------------------------------
  const INFO_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v5.5"/><path d="M12 7.6v.1"/></svg>';
  const INFO_MARGIN = 12; // the closest the popover comes to the window's edge
  const INFO_WIDTH = 300;
  let openInfo = null; // { button, pop } while a popover is showing

  function closeInfo() {
    if (!openInfo) return;
    openInfo.pop.remove();
    openInfo.button.setAttribute("aria-expanded", "false");
    openInfo = null;
  }

  // Below the button when it fits, above it when it doesn't, and always
  // inside the window. The little arrow points back at the button.
  function placeInfo(button, pop) {
    const at = button.getBoundingClientRect();
    const width = Math.min(INFO_WIDTH, window.innerWidth - INFO_MARGIN * 2);
    pop.style.width = `${width}px`;
    const left = Math.max(INFO_MARGIN, Math.min(at.left + at.width / 2 - width / 2, window.innerWidth - width - INFO_MARGIN));
    const below = at.bottom + 8;
    const fitsBelow = below + pop.offsetHeight <= window.innerHeight - INFO_MARGIN;
    pop.style.left = `${left}px`;
    pop.style.top = `${fitsBelow ? below : Math.max(INFO_MARGIN, at.top - 8 - pop.offsetHeight)}px`;
    pop.style.setProperty("--arrow-x", `${at.left + at.width / 2 - left}px`);
    pop.classList.toggle("is-above", !fitsBelow);
  }

  // `text` is a string or a list of short paragraphs. `more` opens the fuller
  // explanation (a sheet, a page), under `moreLabel`.
  function info(text, { label = "More about this", more = null, moreLabel = "Learn more" } = {}) {
    const button = el("button", { class: "info-btn", type: "button", "aria-label": label, title: label, "aria-expanded": "false", html: INFO_ICON });
    button.addEventListener("click", (e) => {
      e.stopPropagation();
      if (openInfo && openInfo.button === button) return closeInfo();
      closeInfo();
      const pop = el("div", { class: "info-pop", role: "dialog", "aria-label": label }, [
        ...[].concat(text).map((t) => el("p", { text: t })),
        more ? el("button", { class: "info-more", type: "button", text: moreLabel, onclick: () => { closeInfo(); more(); } }) : null,
      ]);
      document.body.append(pop);
      placeInfo(button, pop);
      button.setAttribute("aria-expanded", "true");
      openInfo = { button, pop };
    });
    return button;
  }

  // A heading with its info button beside it.
  function titleInfo(heading, text, options = {}) {
    return el("div", { class: "title-info" }, [heading, info(text, { label: `About ${heading.textContent.trim()}`, ...options })]);
  }

  // The static headings in index.html that carry data-info.
  function upgradeInfo(root = document) {
    root.querySelectorAll("[data-info]").forEach((heading) => {
      const row = el("div", { class: "title-info" });
      heading.before(row); // take the heading's place, then move it in
      row.append(heading, info(heading.dataset.info, { label: `About ${heading.textContent.trim()}` }));
      heading.removeAttribute("data-info");
    });
  }

  document.addEventListener("click", (e) => {
    if (openInfo && !openInfo.pop.contains(e.target)) closeInfo();
  });
  // Capture, so Escape closes the popover before it reaches a sheet behind it.
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || !openInfo) return;
    const { button } = openInfo;
    closeInfo();
    button.focus();
    e.stopPropagation();
  }, true);
  window.addEventListener("resize", closeInfo);
  window.addEventListener("hashchange", closeInfo);
  document.addEventListener("scroll", closeInfo, true);

  // A sheet's title with its explanation behind an info button.
  function sheetTitle(id, title, text, options) {
    return titleInfo(el("h3", { id, text: title }), text, options);
  }

  // A one-line bar above a list: a quiet count on the left, and an optional
  // filter on the right. Takes far less room than a row of pills.
  function listBar(count, filter) {
    return el("div", { class: "list-bar" }, [el("span", { class: "list-count", text: count }), filter]);
  }

  // A small dropdown filter. `options` is [[value, label], ...]; `onPick`
  // gets the chosen value.
  function filterSelect(label, options, selected, onPick) {
    const select = el("select", { class: "filter-select", "aria-label": label }, options.map(([value, text]) =>
      el("option", { value, text, selected: value === selected })
    ));
    select.addEventListener("change", () => onPick(select.value));
    return select;
  }

  // A "⋯" button that opens a small menu of a card's less common actions
  // (Edit, Set aside, Delete), so a card shows one or two actions instead of
  // a row of pills. `items` is [{ label, onClick, danger }]; falsy items are
  // skipped. The menu closes on a pick, Escape, or a click anywhere else, and
  // the arrow keys move between its items.
  function moreMenu(label, items) {
    const wrap = el("div", { class: "more" });
    const button = el("button", {
      class: "more-btn", type: "button", "aria-label": label, "aria-haspopup": "menu", "aria-expanded": "false",
      html: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="19" cy="12" r="1.8"/></svg>',
    });
    let menu = null;

    function close() {
      if (!menu) return;
      menu.remove();
      menu = null;
      button.setAttribute("aria-expanded", "false");
      document.removeEventListener("click", onOutside, true);
      document.removeEventListener("keydown", onKey);
    }
    function onOutside(e) {
      if (!wrap.contains(e.target)) close();
    }
    function onKey(e) {
      if (e.key === "Escape") {
        close();
        button.focus();
        return;
      }
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
      e.preventDefault();
      const options = [...menu.querySelectorAll("button")];
      const at = options.indexOf(document.activeElement);
      const next = e.key === "ArrowDown" ? at + 1 : at - 1;
      options[(next + options.length) % options.length].focus();
    }

    button.addEventListener("click", () => {
      if (menu) return close();
      menu = el("div", { class: "more-menu", role: "menu" }, items.filter(Boolean).map((item) =>
        el("button", {
          class: `more-item${item.danger ? " danger" : ""}`, type: "button", role: "menuitem", text: item.label,
          onclick: () => { close(); item.onClick(); },
        })
      ));
      wrap.append(menu);
      unhide(menu, button);
      button.setAttribute("aria-expanded", "true");
      document.addEventListener("click", onOutside, true);
      document.addEventListener("keydown", onKey);
      menu.querySelector("button").focus();
    });
    wrap.append(button);
    return wrap;
  }

  // Opens a menu the other way when its first line would be hidden, off
  // screen or under a sticky bar (the reader bar covers menus that open up).
  function unhide(menu, button) {
    const covered = () => {
      const r = menu.getBoundingClientRect();
      if (r.top < 0 || r.bottom > window.innerHeight) return true;
      const hit = document.elementFromPoint(r.left + r.width / 2, r.top + 4);
      return !hit || !menu.contains(hit);
    };
    if (!covered()) return;
    const opensUp = menu.getBoundingClientRect().bottom <= button.getBoundingClientRect().top;
    menu.classList.add(opensUp ? "is-below" : "is-above");
    if (covered()) menu.classList.remove("is-below", "is-above");
  }

  // A local date ("2026-11-05") as a Date at midday, so no timezone can tip
  // it into the day before when it's formatted.
  function localDate(iso) {
    return new Date(`${iso}T12:00:00`);
  }

  // This week as seven small dots over their day letters, from the server's
  // marks (app/days.py::week_marks). A week is counted ("3 of 5 this week"),
  // never shown as a streak. With `onToggle`, today and the days before it are
  // buttons that mark or unmark that day; days still to come never are.
  function weekDots(marks, { label = "This week", onToggle } = {}) {
    return el("div", { class: "week-dots", role: "group", "aria-label": label }, marks.map((m) => {
      const name = localDate(m.day).toLocaleDateString(undefined, { weekday: "long" });
      const state = m.future ? "still to come" : m.done ? "done" : "not done";
      const cls = `wd${m.done ? " done" : ""}${m.today ? " today" : ""}${m.future ? " future" : ""}`;
      const dot = onToggle && !m.future
        ? el("button", { class: cls, type: "button", title: `${name}: ${state}`, "aria-label": `${name}${m.today ? ", today" : ""}`, "aria-pressed": String(m.done), onclick: () => onToggle(m) })
        : el("span", { class: cls, role: "img", title: `${name}: ${state}`, "aria-label": `${name}: ${state}` });
      return el("span", { class: "wd-col" }, [dot, el("span", { class: "wd-label", "aria-hidden": "true", text: m.label })]);
    }));
  }

  function formMessage() {
    const node = el("p", { class: "form-msg", role: "alert" });
    return {
      node,
      say(text, bad) {
        node.textContent = text || "";
        node.classList.toggle("bad", !!bad);
      },
    };
  }

  // ---------------------------------------------------------------------
  // Themes. index.html's early script applies the saved one before paint;
  // this keeps every picker and the saved choice in step.
  // ---------------------------------------------------------------------
  function setTheme(t) {
    if (!THEME_NAMES[t]) t = "dawn";
    document.documentElement.dataset.theme = t;
    $$("[data-set-theme]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.setTheme === t)));
    try {
      localStorage.setItem("adullumTheme", t);
    } catch {
      /* private window: the theme lasts for this visit */
    }
  }
  document.addEventListener(
    "click",
    (e) => {
      const sw = e.target.closest("[data-set-theme]");
      if (!sw) return;
      e.stopPropagation();
      if (SUPPORTER_THEMES.has(sw.dataset.setTheme) && !isFriend()) {
        toast(`${THEME_NAMES[sw.dataset.setTheme]} is a thank-you for friends of the cave.`, { tone: "info" });
        location.hash = "support";
        return;
      }
      setTheme(sw.dataset.setTheme);
    },
    true
  );

  // ---------------------------------------------------------------------
  // Session. Wrapped in try/catch because private windows and blocked
  // storage throw on access; the site still works signed out.
  // ---------------------------------------------------------------------
  function readSession() {
    try {
      return JSON.parse(localStorage.getItem(STORE_KEY) || "null");
    } catch {
      return null;
    }
  }
  function writeSession(s) {
    try {
      if (s) localStorage.setItem(STORE_KEY, JSON.stringify(s));
      else localStorage.removeItem(STORE_KEY);
    } catch {
      /* storage unavailable: signed in for this tab only */
    }
    session = s;
  }
  let session = readSession();
  let profile = null;
  let lastName = "";
  const signedIn = () => !!session;

  let refreshing = null;
  async function freshToken() {
    if (!session) return null;
    const soon = Math.floor(Date.now() / 1000) + 60;
    if (session.expires_at && session.expires_at > soon) return session.access_token;
    // One refresh at a time, however many requests want a token at once.
    if (!refreshing) {
      refreshing = fetch(`${apiBase()}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: session.refresh_token }),
      })
        .then(async (r) => {
          if (!r.ok) throw new Error("expired");
          writeSession((await r.json()).session);
        })
        .catch(() => endSession())
        .finally(() => (refreshing = null));
    }
    await refreshing;
    return session ? session.access_token : null;
  }

  async function authHeaders() {
    const token = await freshToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  async function api(path, { method = "GET", body } = {}) {
    const headers = { ...(await authHeaders()) };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const resp = await fetch(`${apiBase()}${path}`, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
    let data = null;
    try {
      data = await resp.json();
    } catch {
      /* empty body */
    }
    if (resp.status === 401 && session) endSession();
    if (!resp.ok) {
      const detail = data && data.detail;
      throw new Error(typeof detail === "string" ? detail : Array.isArray(detail) ? "Please check what you entered." : `Something went wrong (${resp.status}).`);
    }
    return data;
  }

  // A session that expired or was revoked: drop it quietly and redraw as a guest.
  function endSession() {
    writeSession(null);
    profile = null;
    updateChrome();
    if (app()) app().render();
  }

  async function startSession(s, { welcome } = {}) {
    writeSession(s);
    await loadProfile();
    if (welcome) toast(welcome);
    app().go("home");
  }

  function signOut() {
    lastName = displayName();
    // This device stops getting their notifications. The headers are taken
    // now, while the session still exists (web/notify.js).
    if (window.Notify) window.Notify.forget(authHeaders());
    writeSession(null);
    profile = null;
    updateChrome();
    app().go("signedout");
  }

  // Magic links and Google land back here with tokens in the URL fragment
  // (implicit flow, see app/auth.py). Read them once, then scrub the URL so
  // the tokens never sit in the address bar or history.
  function consumeRedirect() {
    if (!location.hash || location.hash.length < 2) return;
    const params = new URLSearchParams(location.hash.slice(1));
    if (params.get("access_token")) {
      const expiresIn = Number(params.get("expires_in") || 3600);
      writeSession({
        access_token: params.get("access_token"),
        refresh_token: params.get("refresh_token"),
        expires_at: Number(params.get("expires_at")) || Math.floor(Date.now() / 1000) + expiresIn,
        user: null,
      });
      history.replaceState(null, "", location.pathname + location.search + "#home");
      setTimeout(() => toast("You're signed in."), 300);
    } else if (params.get("error_description")) {
      history.replaceState(null, "", location.pathname + location.search + "#signin");
      setTimeout(() => toast(params.get("error_description").replace(/\+/g, " "), { tone: "error" }), 300);
    }
  }

  async function loadProfile() {
    if (!signedIn()) return null;
    try {
      const me = await api("/me");
      profile = { ...me.profile, email: me.user.email, is_admin: !!me.is_admin, desk_waiting: me.desk_waiting };
      if (session && !session.user) writeSession({ ...session, user: me.user });
      // Keep the person's time zone, so Amens' evening digest arrives in their
      // evening (app/one_another.py::run_digest). Quietly, and only when it moved.
      const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
      if (zone && profile.time_zone !== zone && "time_zone" in profile) {
        api("/me", { method: "PATCH", body: { time_zone: zone } }).then(() => { profile.time_zone = zone; }).catch(() => {});
      }
      // web/reader.js listens for this to apply the saved translation.
      document.dispatchEvent(new CustomEvent("adullum:profile", { detail: profile }));
      // A supporter theme saved on this device stays only for those it's unlocked for.
      if (SUPPORTER_THEMES.has(document.documentElement.dataset.theme) && !isFriend()) setTheme("dawn");
    } catch {
      /* the header falls back to the email initial */
    }
    updateChrome();
    return profile;
  }

  function displayName() {
    return (profile && profile.display_name) || "";
  }
  function email() {
    return (profile && profile.email) || (session && session.user && session.user.email) || "";
  }
  // Who is signed in, for the Support page's checkout link. Empty for guests.
  function account() {
    if (!signedIn()) return {};
    return { id: (profile && profile.id) || (session && session.user && session.user.id) || "", email: email() };
  }
  // When this person became a friend of the cave (a monthly supporter), or
  // null. Null for guests and before the supporters migration has run.
  function supporterSince() {
    return (signedIn() && profile && profile.supporter_since) || null;
  }
  // Whether this person is a friend of the cave: a monthly supporter, or one of
  // the admins (ADMIN_EMAILS), who look after Adullum and count as friends
  // without giving. Friends get the ember on their chip, "Friend of the cave"
  // in the menu and the Almond and Cedar themes, and aren't asked to give.
  // supporterSince() stays the giving date alone, so an admin is never told
  // they've supported since a month they didn't.
  function isFriend() {
    return !!supporterSince() || !!(signedIn() && profile && profile.is_admin);
  }

  // Up to two initials for the account chip: "Odiche Obiakarije" is "OO",
  // "Ruth" is "R", and with no name yet, the first letter of the email.
  function initials(name, fallback) {
    const words = (name || "").trim().split(/\s+/).filter(Boolean);
    const letters = words.length > 1 ? words[0][0] + words[words.length - 1][0] : (words[0] || fallback || "A")[0];
    return letters.toUpperCase();
  }

  function updateChrome() {
    const name = displayName();
    const initialsNode = $("#meInitials");
    if (initialsNode) initialsNode.textContent = initials(name, email());
    const me = $("#meBtn");
    if (me) me.title = name || email() || "Your account";
    if ($("#menuName")) $("#menuName").textContent = name || "Your account";
    if ($("#menuEmail")) $("#menuEmail").textContent = email();
    // Friends of the cave carry a small ember on their chip, and the menu says so.
    if (me) me.classList.toggle("supporter", isFriend());
    if ($("#menuFriend")) $("#menuFriend").hidden = !isFriend();
    // The admin desk link is only there for the people in ADMIN_EMAILS.
    const desk = $("#menuDesk");
    if (desk) {
      desk.hidden = !(profile && profile.is_admin);
      const waiting = profile && profile.desk_waiting;
      desk.textContent = waiting ? `Admin desk (${waiting} waiting)` : "Admin desk";
    }
  }

  // ---------------------------------------------------------------------
  // Sign in / join
  // ---------------------------------------------------------------------
  let authMode = "signin";
  let authMethod = "link";
  let providersLoaded = false;

  function renderAuth() {
    const join = authMode === "join";
    $("#authForm").hidden = authMode === "sent";
    $("#authSent").hidden = authMode !== "sent";
    $("#authHeading").textContent = join ? "Create your account" : "Welcome back";
    $("#authSub").textContent = join
      ? "Free, private, and yours: a journal, your conversations, and reading plans."
      : "Your journal, conversations and plans are where you left them.";
    $("#nameRow").hidden = !join;
    $("#pwRow").hidden = authMethod !== "password";
    $("#authPassword").autocomplete = join ? "new-password" : "current-password";
    $$("[data-method]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.method === authMethod)));
    $("#authPrimary").textContent = authMethod === "link" ? "Email me a sign-in link" : join ? "Create account" : "Sign in";
    $("#switchPrompt").textContent = join ? "Already have an account?" : "New here?";
    $("#switchMode").textContent = join ? "Sign in" : "Create one";
  }
  function say(id, text, bad) {
    const m = $(id);
    m.textContent = text || "";
    m.classList.toggle("bad", !!bad);
  }

  function wireAuth() {
    $$("[data-method]").forEach((b) =>
      b.addEventListener("click", () => {
        authMethod = b.dataset.method;
        say("#authMsg", "");
        renderAuth();
      })
    );
    $("#switchMode").addEventListener("click", () => app().go(authMode === "join" ? "signin" : "join"));
    $("#diffEmail").addEventListener("click", () => {
      authMode = "signin";
      renderAuth();
      $("#authEmail").focus();
    });

    const busy = (on) => ($("#authPrimary").disabled = on);
    async function sendLink() {
      const address = $("#authEmail").value.trim();
      await api("/auth/magic-link", { method: "POST", body: { email: address, display_name: $("#authName").value.trim() || null } });
      $("#sentTo").textContent = address;
      authMode = "sent";
      renderAuth();
    }

    $("#authForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const address = $("#authEmail").value.trim();
      const password = $("#authPassword").value;
      if (!address) return say("#authMsg", "Add your email first.", true);
      if (authMethod === "password" && password.length < 6) return say("#authMsg", "Passwords need at least 6 characters.", true);
      say("#authMsg", "");
      busy(true);
      try {
        if (authMethod === "link") {
          await sendLink();
        } else if (authMode === "join") {
          const res = await api("/auth/signup", { method: "POST", body: { email: address, password, display_name: $("#authName").value.trim() || null } });
          if (res.status === "confirm_email") say("#authMsg", "Almost there. Confirm your email from the message we just sent, then sign in.");
          else await startSession(res.session, { welcome: "Your account is ready." });
        } else {
          const res = await api("/auth/signin", { method: "POST", body: { email: address, password } });
          await startSession(res.session, { welcome: "Welcome back." });
        }
      } catch (err) {
        say("#authMsg", err.message, true);
      } finally {
        busy(false);
      }
    });

    $("#sendAgain").addEventListener("click", async () => {
      try {
        await sendLink();
        toast("Sent again. Give it a minute.");
      } catch (err) {
        toast(err.message, { tone: "error" });
      }
    });

    $("#codeForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        const res = await api("/auth/verify", { method: "POST", body: { email: $("#sentTo").textContent, code: $("#authCode").value.trim() } });
        await startSession(res.session, { welcome: "You're signed in." });
      } catch (err) {
        say("#codeMsg", err.message, true);
      }
    });
  }

  async function showSignin(route) {
    authMode = route === "join" ? "join" : "signin";
    say("#authMsg", "");
    renderAuth();
    if (!providersLoaded) {
      providersLoaded = true;
      try {
        const p = await (await fetch(`${apiBase()}/auth/providers`)).json();
        $("#googleBlock").hidden = !p.google;
      } catch {
        /* no Google button, email still works */
      }
    }
  }

  // ---------------------------------------------------------------------
  // Verses fetched for display (always the real text of the translation)
  // ---------------------------------------------------------------------
  let votd = null;
  async function verseOfTheDay() {
    if (votd && votd.today === localToday()) return votd;
    const res = await fetch(`${apiBase()}/verse-of-the-day?today=${localToday()}&translation=${encodeURIComponent(translation())}`);
    if (!res.ok) throw new Error("no verse");
    votd = { ...(await res.json()), today: localToday() };
    return votd;
  }
  async function verseText(ref) {
    const res = await fetch(`${apiBase()}/verse?ref=${encodeURIComponent(ref)}&translation=${encodeURIComponent(translation())}`);
    if (!res.ok) throw new Error("not found");
    const data = await res.json();
    return { ref, text: data.verses.map((v) => v.text).join(" "), translation: data.translation };
  }

  // The welcome page's example answer quotes its passage from the database.
  async function showWelcome() {
    const preview = $("#previewPassage");
    if (preview && !preview.textContent) {
      try {
        preview.textContent = `"${(await verseText("Matthew 11:28")).text}"`;
      } catch {
        /* the example still reads without its quote */
      }
    }
  }

  // ---------------------------------------------------------------------
  // Shared pieces: cards, reading plans, the plan builder
  // ---------------------------------------------------------------------
  // A card with a small label (or a head row) followed by its body.
  function card(head, { warm } = {}, body = []) {
    return el("section", { class: `card fade-in${warm ? " warm" : ""}` }, [
      typeof head === "string" ? el("h2", { class: "kicker", text: head }) : head,
      ...body,
    ]);
  }
  function cardHead(label, aside) {
    return el("div", { class: "card-head" }, [el("h2", { class: "kicker", text: label }), aside]);
  }

  async function openSession(id, then) {
    try {
      const full = await api(`/me/sessions/${id}`);
      app().loadConversation(id, full.messages);
      if (then) setTimeout(() => app().submitQuery(then), 150);
    } catch (err) {
      toast(err.message, { tone: "error" });
    }
  }

  async function startWholeBiblePlan(button, onDone) {
    if (button) button.disabled = true;
    try {
      await api("/plan", { method: "POST", body: { start_date: localToday(), days: 365, translation: translation() } });
      toast("Your one-year plan starts today.");
      onDone();
    } catch (err) {
      if (button) button.disabled = false;
      toast(err.message, { tone: "error" });
    }
  }

  // The box where someone tells Aquila what they'd like to read, at the top
  // of Reading plans in the Bible (#bible/plans).
  // Plan with Aquila, kept to one line like the home's ask box: a small head
  // (with the whole-Bible plan as a link at its end) and the box. The ideas
  // show under it only while the box has focus and nothing typed yet.
  function planBuilder({ onBuilt }) {
    const id = "planRequest";
    const input = el("input", { id, type: "text", maxlength: "500", autocomplete: "off", enterkeyhint: "go", placeholder: "What would you like to read?" });
    const msg = formMessage();
    const build = el("button", { class: "btn btn-ember", type: "submit", text: "Shape" });
    const whole = el("button", { class: "linkish plan-ask-whole", type: "button", text: "Whole Bible in a year" });
    whole.onclick = () => startWholeBiblePlan(whole, onBuilt);

    const pick = (idea) => { input.value = idea; input.focus(); form.classList.add("has-text"); };
    const form = el("form", { class: "plan-ask" }, [
      el("div", { class: "plan-ask-head" }, [titleInfo(el("h2", { class: "plan-ask-title", text: "Plan with Aquila" }), PLAN_ABOUT), whole]),
      el("label", { class: "sr", for: id, text: "What would you like to read?" }),
      el("div", { class: "ask-box" }, [input, build]),
      el("div", { class: "plan-ideas" }, [
        el("span", { text: "Try" }),
        ...PLAN_IDEAS.map((idea) => el("button", { type: "button", text: idea, onmousedown: (e) => e.preventDefault(), onclick: () => pick(idea) })),
      ]),
      msg.node,
    ]);
    input.addEventListener("input", () => form.classList.toggle("has-text", Boolean(input.value.trim())));

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const request = input.value.trim();
      if (request.length < 3) return msg.say("Tell Aquila a little about what you'd like to read.", true);
      msg.say("");
      build.disabled = true;
      build.textContent = "Shaping...";
      try {
        const plan = await api("/me/plans/build", { method: "POST", body: { request, today: localToday(), translation: translation() } });
        toast(`"${plan.title}" starts today.`);
        onBuilt(plan);
      } catch (err) {
        msg.say(err.message, true);
        build.disabled = false;
        build.textContent = "Shape";
      }
    });
    return form;
  }

  // One reading plan: where it stands today, today's chapters, and its
  // actions. The home screen's Today list has its own one-line version
  // (planRow).
  function planItem(plan, { onChange }) {
    const bar = el("span", { style: `width:${Math.max(plan.progress_pct, 1)}%` });
    const progressText = el("span");
    const doneBtn = el("button", { type: "button" });
    const paint = (p) => {
      doneBtn.className = p.done_today ? "btn btn-sm btn-ghost" : "btn btn-sm btn-ember";
      doneBtn.innerHTML = p.done_today ? `${ICON.check}<span>Read today</span>` : "<span>Mark as read</span>";
      bar.style.width = `${Math.max(p.progress_pct, 1)}%`;
      progressText.textContent = `${p.completed} of ${p.days} days read`;
    };
    paint(plan);
    doneBtn.addEventListener("click", async () => {
      const next = !plan.done_today;
      try {
        plan = { ...plan, ...(await api(`/me/plans/${plan.id}/progress`, { method: "POST", body: { day: plan.day, done: next, today: localToday() } })) };
        paint(plan);
        if (next) toast(`Day ${plan.day} read. ${plan.completed} of ${plan.days} done.`);
      } catch (err) {
        toast(err.message, { tone: "error" });
      }
    });

    const refs = compactRefs(plan.refs);
    const body = [
      plan.overview ? el("p", { class: "overview", text: plan.overview }) : null,
      el("div", { class: "bar", role: "progressbar", "aria-label": `${plan.title} progress`, "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(plan.progress_pct) }, bar),
      el("div", { class: "progress-line" }, [progressText, el("span", { text: `Day ${plan.day} of ${plan.days}` })]),
      el("div", { class: "refs" }, [
        el("span", { class: "kicker", text: "Today" }),
        // Each opens the chapter in the Bible ("John 3-4" opens at John 3).
        ...refs.map((r) => el("a", { class: "chapter", href: `#${window.Reader.href(r)}`, text: r, title: `Read ${r} in the Bible` })),
      ]),
      el("div", { class: "card-actions-row" }, [
        doneBtn,
        el("button", {
          class: "act", type: "button", html: `${ICON.download}<span>PDF</span>`,
          onclick: () => downloadFile(`/plan/${plan.id}/pdf`, `${plan.title}.pdf`).catch((err) => toast(err.message, { tone: "error" })),
        }),
        el("button", {
          class: "act danger", type: "button", text: "Delete",
          onclick: async () => {
            if (!confirm(`Delete "${plan.title}"? Your progress in it goes too.`)) return;
            try {
              await api(`/me/plans/${plan.id}`, { method: "DELETE" });
              onChange();
            } catch (err) {
              toast(err.message, { tone: "error" });
            }
          },
        }),
      ]),
    ];
    return el("article", { class: "card plan-item" }, [el("h3", { class: "section-title", text: plan.title }), ...body]);
  }

  // ---------------------------------------------------------------------
  // Home
  // ---------------------------------------------------------------------
  // Read top to bottom: what's happening now (a church live, Amens), the ask
  // box, today's verse, then Today (the few things the person keeps day by
  // day), with where they left off beside it. Every part is drawn
  // only when it has something to say, so a quiet day is a short page.
  // app/hearth.py gathers it all in one request.
  const HOME_HABITS = 3;

  function plural(n, one, many = `${one}s`) {
    return `${n} ${n === 1 ? one : many}`;
  }
  function clip(text, n) {
    return text.length > n ? `${text.slice(0, n - 1).trimEnd()}...` : text;
  }

  // One line that reads like a notification: an icon (with an optional count),
  // a title and a detail, opening `href`. Amens (web/refuge.js) and a church
  // going live (web/church.js) both use it, so the two look alike.
  function homeNote({ href, icon, count = 0, title, detail, live = false }) {
    return el("a", { class: `home-note fade-in${live ? " is-live" : ""}`, href, "aria-label": detail ? `${title}, ${detail}` : title }, [
      el("span", { class: "home-note-icon", "aria-hidden": "true" }, [
        el("span", { html: icon }),
        count ? el("span", { class: "home-note-count", text: count > 9 ? "9+" : String(count) }) : null,
      ]),
      el("span", { class: "home-note-text" }, [el("strong", { text: title }), detail ? el("small", { text: detail }) : null]),
      el("span", { class: "home-note-go", "aria-hidden": "true", html: ICON.forward }),
    ]);
  }

  // The streak as a few quiet words after the date ("· 2 days"), so it adds
  // no row or pill of its own. A tap shows the week, a dot per day lit for
  // each day they came in. Nothing shows before the first day.
  function emberChip(e) {
    if (!e.streak) return null;
    const label = e.streak > 1 ? `${e.streak} days in a row` : e.streak === 1 ? "Day one" : "One dot for every day you come in";
    const dayClass = (d) => `${d.lit ? " lit" : ""}${d.today ? " today" : ""}`;
    const wrap = el("span", { class: "ember-wrap" });
    const week = el("div", { class: "ember-week", role: "group", "aria-label": "This week", hidden: true }, [
      el("p", { text: label }),
      el("div", { class: "ember-days" }, e.week.map((d) => el("span", { class: `ember-day${dayClass(d)}` }, [
        el("span", { class: "ember-dot" }),
        el("small", { text: d.label }),
      ]))),
    ]);
    const chip = el("button", {
      class: "ember-chip", type: "button", title: label, "aria-expanded": "false", "aria-label": `${label}. Show this week`,
    }, [el("i", { "aria-hidden": "true" }), plural(e.streak, "day")]);
    const close = (ev) => {
      if (ev && wrap.contains(ev.target)) return;
      week.hidden = true;
      chip.setAttribute("aria-expanded", "false");
      document.removeEventListener("click", close, true);
    };
    chip.addEventListener("click", () => {
      if (!week.hidden) return close();
      week.hidden = false;
      chip.setAttribute("aria-expanded", "true");
      document.addEventListener("click", close, true);
    });
    wrap.append(chip, week);
    return wrap;
  }

  // The verse, its reference (a link into the reader), one way to reflect
  // on it, and everything else behind "⋯".
  function verseCard(v) {
    return el("section", { class: "card warm home-verse fade-in" }, [
      el("h2", { class: "kicker ember", text: "Verse for today" }),
      el("p", { class: "scripture-lg", text: `"${v.text}"` }),
      el("div", { class: "home-verse-foot" }, [
        el("a", { class: "verse-ref", href: `#${window.Reader.href(v.ref)}`, text: `${v.ref} · ${v.translation}` }),
        el("button", { class: "text-act", type: "button", text: "Reflect", onclick: () => app().submitQuery(`Help me reflect on ${v.ref}.`) }),
        moreMenu(`More for ${v.ref}`, [
          { label: "Keep in journal", onClick: () => openJournal({ passage_ref: v.ref, verse_text: v.text }) },
          { label: "Save", onClick: () => window.Saved.verse(v.ref, v.translation) },
          { label: "See connections", onClick: () => window.Graph.open([`${v.book} ${v.chapter}:${v.verse}`]) },
          { label: "Share", onClick: () => shareCard(v) },
        ]),
      ]),
    ]);
  }

  // One row of Today. A row with `done` (true or false) has a circle that
  // ticks it through `onTick(next)`, which resolves false when it couldn't;
  // a row without just opens `href` or runs `onOpen`.
  function todayRow({ icon, title, detail, href, onOpen, done = null, onTick, tickLabel }) {
    const text = [el("strong", { text: title }), detail ? el("small", { text: detail }) : null];
    const body = href
      ? el("a", { class: "today-body", href }, text)
      : el("button", { class: "today-body", type: "button", onclick: onOpen }, text);
    const row = el("li", { class: `today-item${done ? " is-done" : ""}` });
    if (done === null) {
      row.append(el("span", { class: "today-mark", "aria-hidden": "true", html: icon }), body, el("span", { class: "home-note-go", "aria-hidden": "true", html: ICON.forward }));
      return row;
    }
    const tick = el("button", { class: "today-tick", type: "button", "aria-label": tickLabel || title, "aria-pressed": String(done), html: ICON.check });
    tick.addEventListener("click", async () => {
      const next = tick.getAttribute("aria-pressed") !== "true";
      const paint = (on) => {
        tick.setAttribute("aria-pressed", String(on));
        row.classList.toggle("is-done", on);
        row.dispatchEvent(new CustomEvent("today:tick", { bubbles: true }));
      };
      paint(next);
      tick.disabled = true;
      if ((await onTick(next)) === false) paint(!next);
      tick.disabled = false;
    });
    row.append(tick, body);
    return row;
  }

  // Runs a tick's request, toasting the error and resolving false on failure.
  async function tickRequest(path, body) {
    try {
      return await api(path, { method: "POST", body: { today: localToday(), ...body } });
    } catch (err) {
      toast(err.message, { tone: "error" });
      return false;
    }
  }

  function planRow(plan) {
    if (!plan) return todayRow({ icon: ICON.book, title: "Start a reading plan", href: "#bible/plans" });
    const refs = compactRefs(plan.refs);
    return todayRow({
      title: refs.join(", ") || plan.title,
      detail: `${plan.title} · Day ${plan.day} of ${plan.days}`,
      href: refs.length ? `#${window.Reader.href(plan.refs[0])}` : "#bible/plans",
      done: !!plan.done_today,
      tickLabel: `Mark day ${plan.day} of ${plan.title} as read`,
      onTick: async (done) => {
        const result = await tickRequest(`/me/plans/${plan.id}/progress`, { day: plan.day, done });
        if (result && done) toast(`Day ${plan.day} read. ${result.completed} of ${result.days} done.`);
        return !!result;
      },
    });
  }

  // `summary` is app/prayers.py::prayer_summary plus `prayed_today`, which is
  // null until the prayer-practice migration has run (then there's no tick).
  function prayRow(summary) {
    const detail = summary.open ? `${plural(summary.open, "open request")}` : "Your prayer list";
    if (summary.prayed_today === null || summary.prayed_today === undefined) {
      return todayRow({ icon: ICON.heart, title: "Pray", detail, href: "#prayers" });
    }
    return todayRow({
      title: "Pray", detail, href: "#prayers", done: summary.prayed_today, tickLabel: "I prayed today",
      onTick: async (prayed) => {
        const ok = !!(await tickRequest("/me/prayers/log", { prayed }));
        if (ok && prayed) toast("Amen.");
        return ok;
      },
    });
  }

  // A habit from Pebbles, counted for the week ("3 of 5 this week"), never as a streak.
  function habitRow(habit) {
    const detail = (done) => `${done} of ${habit.per_week} this week`;
    let weekDone = habit.week_done;
    const row = todayRow({
      title: habit.title, detail: detail(weekDone), href: "#pebbles", done: !!habit.tended_today, tickLabel: `${habit.title}: done today`,
      onTick: async (tended) => {
        const ok = !!(await tickRequest(`/me/refuge/seeds/${habit.id}/tend`, { tended }));
        if (ok) {
          weekDone += tended ? 1 : -1;
          row.querySelector("small").textContent = detail(weekDone);
        }
        return ok;
      },
    });
    return row;
  }

  function todayCard(data) {
    const habits = (data.pebbles || []).filter((s) => s.kind === "habit").slice(0, HOME_HABITS);
    const rows = [
      planRow(data.plan),
      data.prayers ? prayRow(data.prayers) : null,
      ...habits.map(habitRow),
    ].filter(Boolean);
    const tally = el("span", { class: "card-aside" });
    const list = el("ul", { class: "today-items" }, rows);
    const count = () => {
      const ticks = $$(".today-tick", list);
      const done = ticks.filter((t) => t.getAttribute("aria-pressed") === "true").length;
      // A tally only once there's more than one thing to tick.
      tally.textContent = ticks.length < 2 ? "" : done === ticks.length ? "All done" : `${done} of ${ticks.length}`;
      tally.classList.toggle("is-done", !!ticks.length && done === ticks.length);
    };
    list.addEventListener("today:tick", count);
    count();
    return card(cardHead("Today", tally), {}, [list]);
  }

  // ---------------------------------------------------------------------
  // Where to start: a short guide for a new account
  // ---------------------------------------------------------------------
  // Shown for someone's first three weeks until they close it or have been
  // to every place. A place ticks off from what the home already knows
  // (a conversation, a plan, a prayer) or, where it can't know, once it's
  // been opened from here. Both memories live on this device only.
  const START_CLOSED = "adullumStartClosed";
  const START_TRIED = "adullumStartTried";
  const START_DAYS = 21;
  const START_ICON = {
    plan: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="5" width="16" height="15" rx="2"/><path d="M8 3v4M16 3v4M4 10h16M9 14l2 2 4-4"/></svg>',
    refuge: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 20h18M5 20V11a7 7 0 0 1 14 0v9M10 20v-5a2 2 0 0 1 4 0v5"/></svg>',
    church: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 2v4M10 4h4M6 21V11l6-5 6 5v10M3 21h18M10 21v-4h4v4"/></svg>',
  };

  function readStore(key, fallback) {
    try {
      return JSON.parse(localStorage.getItem(key)) ?? fallback;
    } catch {
      return fallback;
    }
  }
  function writeStore(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* a private window keeps the guide open, which is harmless */
    }
  }

  function startCard(data) {
    if (readStore(START_CLOSED, false)) return null;
    const joined = data.profile && data.profile.joined ? new Date(data.profile.joined) : null;
    if (joined && Date.now() - joined.getTime() > START_DAYS * 864e5) return null;

    const tried = new Set(readStore(START_TRIED, []));
    const places = [
      { key: "ask", name: "Ask Aquila", icon: ICON.chat, href: "#aquila", done: !!data.last_session },
      { key: "bible", name: "Read the Bible", icon: ICON.book, href: "#bible" },
      { key: "plan", name: "Start a reading plan", icon: START_ICON.plan, href: "#bible/plans", done: !!data.plan },
      { key: "pray", name: "Keep a prayer list", icon: ICON.heart, href: "#prayers", done: !!(data.prayers && data.prayers.total) },
      { key: "refuge", name: "Rest in Refuge", icon: START_ICON.refuge, href: "#refuge" },
      { key: "church", name: "Add your church", icon: START_ICON.church, href: "#church/add" },
    ].map((p) => ({ ...p, done: p.done || tried.has(p.key) }));
    const done = places.filter((p) => p.done).length;
    if (done === places.length) return null;

    const node = el("section", { class: "card home-start fade-in", "aria-label": "Where to start" });
    const close = el("button", {
      class: "icon-act", type: "button", "aria-label": "Close the guide", html: ICON.close,
      onclick: () => {
        writeStore(START_CLOSED, true);
        node.remove();
        toast("Everything here is in the menu whenever you want it.", { tone: "info" });
      },
    });
    node.append(
      el("div", { class: "card-head" }, [
        titleInfo(el("h2", { class: "start-title", text: "Where would you like to start?" }),
          "A few places to begin. Each one ticks off once you've been, and you can close this whenever you like."),
        el("span", { class: "start-aside" }, [el("span", { class: "card-aside", text: `${done} of ${places.length}` }), close]),
      ]),
      el("div", { class: "start-grid" }, places.map((p) =>
        el("a", {
          class: `start-place${p.done ? " is-done" : ""}`, href: p.href,
          onclick: () => { tried.add(p.key); writeStore(START_TRIED, [...tried]); },
        }, [
          el("span", { class: "start-icon", html: p.done ? ICON.check : p.icon }),
          el("span", { class: "start-name", text: p.name }),
          p.done ? el("span", { class: "sr", text: "(done)" }) : null,
        ])
      ))
    );
    return node;
  }

  function continueCard(s) {
    if (!s) return null;
    const meta = [when(s.updated_at), s.refs.slice(0, 2).join(", ")].filter(Boolean).join(" · ");
    return card("Pick up where you left off", {}, [
      el("button", { class: "resume", type: "button", onclick: () => openSession(s.id) }, [
        el("span", { class: "today-mark", "aria-hidden": "true", html: ICON.chat }),
        el("span", { class: "today-body" }, [el("strong", { text: s.title || "Your last conversation" }), el("small", { text: meta })]),
        el("span", { class: "home-note-go", "aria-hidden": "true", html: ICON.forward }),
      ]),
      s.followup ? el("button", { class: "resume-next", type: "button", title: s.followup, onclick: () => openSession(s.id, s.followup) }, [
        el("span", { class: "faint", text: "Next " }), s.followup,
      ]) : null,
    ]);
  }

  // A journal entry from a while back. The person's own words, so Inter,
  // not the serif kept for Scripture.
  function revisitCard(r) {
    const where = r.passage_ref || r.question || "a passage";
    return card(cardHead("From your journal", el("span", { class: "card-aside", text: agoPhrase(r.created_at) })), {}, [
      el("p", { class: "revisit-quote", text: `"${clip(r.reflection, 140)}"` }),
      el("p", { class: "faint home-quiet", text: where }),
      el("button", {
        class: "text-act", type: "button", text: "Return to it with Aquila",
        onclick: () => app().submitQuery(`I'd like to come back to ${where}. Last time I wrote: "${r.reflection.slice(0, 300)}"`),
      }),
    ]);
  }

  function setGreeting() {
    const name = displayName();
    $("#greet").textContent = `Good ${partOfDay()}${name ? `, ${name}` : ""}`;
  }

  async function showHome() {
    setGreeting();
    $("#dayLine").textContent = new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
    const main = $("#homeMain");
    const side = $("#homeSide");
    const notes = $("#homeNotes");
    if (!main.children.length) main.append(el("div", { class: "empty", text: "Opening your cave..." }));
    const tiles = $("#homeTiles");
    tiles.replaceChildren(window.Declare.homeLine());

    // The verse is public and cached for the day, so it loads alongside the
    // home request rather than after it.
    const versePromise = verseOfTheDay().catch(() => null);
    let data;
    try {
      data = await api(`/me/home?today=${localToday()}`);
    } catch (err) {
      main.replaceChildren(el("div", { class: "empty" }, [el("strong", { text: "Your cave isn't open yet" }), err.message]));
      side.replaceChildren();
      return;
    }
    // /me may still be loading on a fresh visit, so the home payload's profile
    // fills in the name rather than waiting for it.
    if (data.profile) profile = { ...(profile || {}), ...data.profile };
    setGreeting();
    updateChrome();
    $("#homeEmbers").replaceChildren(...[data.embers ? emberChip(data.embers) : null].filter(Boolean));

    // Amens sits beside Declare. It's null until the Refuge migration has run,
    // and homeCard returns null itself when there's nothing to tell, which
    // leaves Declare the whole row. A church going live gets the full-width
    // line above once its check returns; nothing else about churches shows
    // here (web/church.js).
    tiles.querySelectorAll(".home-tile.is-amens").forEach((old) => old.remove());
    const amens = data.amens ? window.Refuge.homeCard(data.amens) : null;
    if (amens) tiles.prepend(el("div", { class: "home-tile is-amens" }, amens));
    notes.replaceChildren();
    window.Church.homeLive().then((live) => {
      if (live && notes.isConnected) notes.replaceChildren(live);
    }).catch(() => {});

    $("#homeStart").replaceChildren(...[startCard(data)].filter(Boolean));

    const v = await versePromise;
    $("#homeVerse").replaceChildren(...(v ? [verseCard(v)] : []));
    main.replaceChildren(todayCard(data));
    // The halfway check-in on a reflection's plan leads the side while it
    // lasts (two weeks from the middle of the stretch, app/reflections.py).
    side.replaceChildren(...[
      data.reflection ? window.Reflections.homeCard(data.reflection) : null,
      continueCard(data.last_session),
      data.revisit ? revisitCard(data.revisit) : null,
      window.Support.homeCard(),
    ].filter(Boolean));
  }

  // ---------------------------------------------------------------------
  // Past conversations: the Ask rail on wide screens, a sheet on phones
  // ---------------------------------------------------------------------
  // One past conversation: tap to open, and a small button beside it to
  // rename or delete it. `onChanged` redraws whichever list it sits in.
  function conversationButton(s, onOpen, onChanged) {
    const open = el("button", { class: "rail-item", type: "button", "aria-current": String(s.id === (app() && app().getSessionId())), onclick: onOpen }, [
      el("span", { text: s.title || "Untitled" }),
      el("small", { text: when(s.updated_at || s.created_at) }),
    ]);
    const more = el("button", { class: "rail-more", type: "button", "aria-label": `Rename or delete "${s.title || "Untitled"}"`, html: ICON_MORE, onclick: () => manageConversation(s, onChanged) });
    return el("div", { class: "rail-row" }, [open, more]);
  }

  const ICON_MORE = '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="19" cy="12" r="1.8"/></svg>';

  function manageConversation(s, onChanged) {
    const title = el("input", { class: "field", maxlength: "120", "aria-label": "Name" });
    title.value = s.title || "";
    const msg = formMessage();
    const save = el("button", { class: "btn btn-ember btn-sm", type: "submit", text: "Save" });
    const remove = el("button", { class: "btn btn-ghost btn-sm danger-text", type: "button", text: "Delete" });
    const form = el("form", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "manageConvTitle" }, [
      el("h3", { id: "manageConvTitle", text: "This conversation" }),
      el("label", { class: "field-wrap" }, ["Name", title]),
      msg.node,
      el("div", { class: "sheet-actions" }, [remove, el("span", { style: "flex:1" }), el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Cancel", onclick: () => close() }), save]),
    ]);
    const close = overlay(form);
    const changed = () => {
      refreshRail();
      if (onChanged) onChanged();
    };
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!title.value.trim()) return msg.say("Give it a name.", true);
      save.disabled = true;
      try {
        await api(`/me/sessions/${s.id}`, { method: "PATCH", body: { title: title.value.trim() } });
        close();
        toast("Renamed.");
        changed();
      } catch (err) {
        msg.say(err.message, true);
        save.disabled = false;
      }
    });
    remove.onclick = async () => {
      if (!confirm("Delete this conversation? This can't be undone.")) return;
      try {
        await api(`/me/sessions/${s.id}`, { method: "DELETE" });
        close();
        toast("Deleted.");
        // Deleting the conversation on screen starts a fresh one.
        if (app() && app().getSessionId() === s.id) app().newConversation();
        changed();
      } catch (err) {
        msg.say(err.message, true);
      }
    };
  }

  let railTimer = null;
  function refreshRail() {
    if (!signedIn()) return;
    clearTimeout(railTimer);
    // The conversation is saved just after the answer finishes streaming, so a
    // brand new one appears in the list a moment later.
    railTimer = setTimeout(async () => {
      const list = $("#railList");
      if (!list) return;
      try {
        const rows = await api("/me/sessions");
        list.replaceChildren(
          ...(rows.length
            ? rows.slice(0, 30).map((s) => conversationButton(s, () => openSession(s.id)))
            : [el("p", { class: "faint", style: "padding:4px 10px;font-size:14px", text: "Your conversations will appear here." })])
        );
      } catch {
        /* the rail is a convenience */
      }
    }, 1200);
  }

  async function openConversations() {
    const list = el("div", { class: "conv-list" }, el("p", { class: "faint", text: "Opening..." }));
    const sheet = el("div", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "convTitle" }, [
      el("div", { class: "row-between" }, [
        el("h3", { id: "convTitle", text: "Conversations" }),
        el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "New", onclick: () => { close(); app().newConversation(); } }),
      ]),
      list,
    ]);
    const close = overlay(sheet);
    const fill = async () => {
      try {
        const rows = await api("/me/sessions");
        list.replaceChildren(
          ...(rows.length
            ? rows.slice(0, 30).map((s) => conversationButton(s, () => { close(); openSession(s.id); }, fill))
            : [el("p", { class: "faint", text: "Your conversations will appear here." })])
        );
      } catch (err) {
        list.replaceChildren(el("p", { class: "form-msg bad", text: err.message }));
      }
    };
    fill();
  }

  // ---------------------------------------------------------------------
  // Journal sheet: save an answer, a verse, or a free-written entry
  // ---------------------------------------------------------------------
  // An entry's tags as the person sees them. Older entries may also carry a
  // "season" from before tags replaced it; it shows as one more tag.
  function entryTags(e) {
    const tags = [...(e.tags || [])];
    if (e.mood && !tags.includes(e.mood)) tags.push(e.mood);
    return tags;
  }

  function openJournal(item = {}, onSaved) {
    if (!signedIn()) {
      toast("Create a free account to keep a journal.", { tone: "info" });
      app().go("join");
      return;
    }
    const reflection = el("textarea", { id: "journalReflection", placeholder: "What is this stirring in you? A sentence is plenty." });
    const passage = el("input", { id: "journalPassage", placeholder: "Psalm 23, or leave blank" });
    const tags = el("input", { id: "journalTags", placeholder: "prayer, family, small group" });
    const msg = formMessage();
    const save = el("button", { class: "btn btn-ember btn-sm", type: "submit", text: "Save" });
    const freeWrite = !item.passage_ref && !item.question;

    const preview = freeWrite
      ? el("label", { class: "field-wrap" }, ["Passage (optional)", passage])
      : el("div", { class: "journal-preview" }, item.passage_ref
          ? [el("strong", { text: item.passage_ref }), document.createTextNode(item.verse_text || "")]
          : [el("strong", { text: item.question || "" }), document.createTextNode((item.answer || "").replace(/^#+\s*/gm, "").slice(0, 400))]);

    const formEl = el("form", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "journalTitle" }, [
      sheetTitle("journalTitle", freeWrite ? "New journal entry" : "Save to your journal", "Only you can see this. Aquila may bring it up gently next time you talk."),
      preview,
      el("label", { class: "field-wrap" }, ["Your reflection", reflection]),
      el("label", { class: "field-wrap" }, ["Tags (separate with commas)", tags]),
      msg.node,
      el("div", { class: "sheet-actions" }, [el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Cancel", onclick: () => close() }), save]),
    ]);
    const close = overlay(formEl);

    formEl.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (freeWrite && !reflection.value.trim()) return msg.say("Write a line or two first.", true);
      save.disabled = true;
      try {
        const first = (item.citations || [])[0];
        const entry = await api("/me/journal", {
          method: "POST",
          body: {
            question: item.question || null,
            answer: item.answer || null,
            passage_ref: item.passage_ref || passage.value.trim() || (first ? `${first.book} ${first.chapter}:${first.verse}` : null),
            verse_text: item.verse_text || null,
            citations: item.citations || [],
            reflection: reflection.value.trim(),
            tags: tags.value.split(",").map((t) => t.trim()).filter(Boolean),
            session_id: item.question ? app().getSessionId() : null,
          },
        });
        close();
        toast("Saved to your journal.", { action: { label: "Open", href: "#journal" } });
        if (onSaved) onSaved(entry);
      } catch (err) {
        msg.say(err.message, true);
        save.disabled = false;
      }
    });
  }

  // ---------------------------------------------------------------------
  // Under each answer
  // ---------------------------------------------------------------------
  function plainAnswer(text) {
    return text.replace(/^#{1,6}\s*(.+)$/gm, "$1.").replace(/\*\*(.+?)\*\*/g, "$1");
  }

  let speaking = null;
  function listen(btn, text) {
    if (!("speechSynthesis" in window)) return toast("Your browser can't read aloud.", { tone: "info" });
    if (speaking === btn) {
      speechSynthesis.cancel();
      return;
    }
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(plainAnswer(text));
    u.rate = 0.97;
    const label = btn.querySelector("span");
    // The button may show only its icon (under an answer), so its state is
    // also in its name and colour, not just the word.
    const show = (playing) => {
      label.textContent = playing ? "Stop" : "Listen";
      btn.setAttribute("aria-label", playing ? "Stop reading" : "Listen");
      btn.title = playing ? "Stop reading" : "Listen";
      btn.classList.toggle("is-playing", playing);
    };
    u.onend = u.onerror = () => {
      if (speaking === btn) speaking = null;
      show(false);
    };
    speaking = btn;
    show(true);
    speechSynthesis.speak(u);
  }

  function decorateAnswer(msg, data) {
    if (!msg || msg.querySelector(".answer-actions") || !data.answer) return;
    const refs = (data.citations || []).map((c) => `${c.book} ${c.chapter}:${c.verse}`);
    // One tap saves the answer to Saved in the Bible (web/saved.js); a second
    // takes it back out.
    const saveBtn = el("button", { class: "act", type: "button", title: "Save", "aria-label": "Save", html: `${ICON.bookmark}<span>Save</span>` });
    let savedId = null;
    const paintSaved = () => {
      saveBtn.classList.toggle("is-done", !!savedId);
      saveBtn.innerHTML = savedId ? `${ICON.check}<span>Saved</span>` : `${ICON.bookmark}<span>Save</span>`;
      saveBtn.setAttribute("aria-pressed", String(!!savedId));
    };
    saveBtn.onclick = async () => {
      saveBtn.disabled = true;
      if (savedId) {
        if (await window.Saved.remove(savedId)) savedId = null;
      } else {
        const item = await window.Saved.answer({ question: data.query, answer: data.answer, citations: data.citations || [] });
        if (item) savedId = item.id;
      }
      paintSaved();
      saveBtn.disabled = false;
    };
    const listenBtn = el("button", { class: "act act-icon", type: "button", title: "Listen", "aria-label": "Listen", html: `${ICON.speaker}<span>Listen</span>` });
    listenBtn.onclick = () => listen(listenBtn, data.answer);
    // One quiet line of actions: the Bible first, since that's where an answer
    // should lead. How a verse links to others lives in Connections alone.
    const row = el("div", { class: "answer-actions" }, [
      refs.length ? el("a", { class: "act", href: `#${window.Reader.href(refs[0])}`, title: `Open ${refs[0]} in the Bible`, html: `${ICON.book}<span>Bible</span>` }) : null,
      refs.length ? el("button", { class: "act", type: "button", html: `${ICON.graph}<span>Connections</span>`, onclick: () => window.Graph.open(refs.slice(0, 4)) }) : null,
      saveBtn,
      listenBtn,
      refs.length
        ? el("button", {
            class: "act act-icon", type: "button", title: "Share", "aria-label": "Share", html: `${ICON.share}<span>Share</span>`,
            onclick: async () => {
              try {
                shareCard(await verseText(refs[0]));
              } catch {
                toast("Couldn't make the card. Try again in a moment.", { tone: "error" });
              }
            },
          })
        : null,
    ]);
    const cites = msg.querySelector(".cites");
    (cites || msg).after(row);
  }

  function markMemory(msg) {
    if (!msg || msg.querySelector(".memory-mark")) return;
    const mark = el("a", {
      class: "memory-mark", href: "#remembers",
      title: "Aquila drew on what she remembers about you. See or change it in Settings.",
      html: `${ICON.memory}<span>Aquila remembered something you shared</span>`,
    });
    msg.querySelector(".stages").after(mark);
  }

  // A verse as an image to keep or send: drawn on a canvas in the current
  // theme's colours, shared through the device's share sheet where there is
  // one, downloaded otherwise.
  function wrapLines(ctx, text, maxWidth) {
    const words = text.split(/\s+/);
    const lines = [];
    let line = "";
    for (const w of words) {
      const test = line ? `${line} ${w}` : w;
      if (ctx.measureText(test).width > maxWidth && line) {
        lines.push(line);
        line = w;
      } else line = test;
    }
    if (line) lines.push(line);
    return lines;
  }
  async function shareCard({ ref, text, translation: tr }) {
    try {
      await document.fonts.ready;
    } catch {
      /* draw with whatever is loaded */
    }
    const css = getComputedStyle(document.documentElement);
    const token = (n) => css.getPropertyValue(n).trim();
    const W = 1080;
    const H = 1350;
    const c = document.createElement("canvas");
    c.width = W;
    c.height = H;
    const ctx = c.getContext("2d");
    ctx.fillStyle = token("--ground");
    ctx.fillRect(0, 0, W, H);

    let size = 64;
    let lines;
    do {
      ctx.font = `400 ${size}px "Source Serif 4", Georgia, serif`;
      lines = wrapLines(ctx, `"${text}"`, W - 200);
      size -= 4;
    } while (lines.length * size * 1.3 > H - 520 && size > 30);
    const lineH = (size + 4) * 1.4;
    let y = (H - lines.length * lineH) / 2;
    ctx.fillStyle = token("--text");
    ctx.textBaseline = "top";
    for (const l of lines) {
      ctx.fillText(l, 100, y);
      y += lineH;
    }
    ctx.font = `600 36px "Inter", system-ui, sans-serif`;
    ctx.fillStyle = token("--ember");
    ctx.fillText(`${ref} · ${tr}`, 100, y + 30);

    ctx.strokeStyle = token("--ember");
    ctx.lineWidth = 6;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(100, H - 100);
    ctx.bezierCurveTo(100, H - 190, 125, H - 220, 140, H - 220);
    ctx.bezierCurveTo(155, H - 220, 180, H - 190, 180, H - 100);
    ctx.stroke();
    ctx.font = `600 38px "Inter", system-ui, sans-serif`;
    ctx.fillStyle = token("--text");
    ctx.fillText("Adullum", 205, H - 150);

    const blob = await new Promise((resolve) => c.toBlob(resolve, "image/png"));
    const file = new File([blob], `${ref.replace(/[^\w]+/g, "-")}.png`, { type: "image/png" });
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      try {
        await navigator.share({ files: [file], title: ref });
      } catch {
        /* cancelled */
      }
      return;
    }
    const a = el("a", { href: URL.createObjectURL(blob), download: file.name });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    toast("Card saved to your downloads.");
  }

  // ---------------------------------------------------------------------
  // The cave: Journal, Refuge and Prayers, side by side as tabs (sermon notes
  // live in the Church tab, web/church.js). Past
  // conversations live with Aquila (the rail, or the Conversations sheet on a
  // phone), where they can be opened, renamed and deleted; notes, highlights,
  // saved things and reading plans live in the Bible (#bible/notes,
  // #bible/saved, #bible/plans).
  // ---------------------------------------------------------------------
  // Hash routes that open a tab directly, and the header button each tab shows.
  // #amens opens Refuge already inside the Amens room.
  // #reflection/<id> opens a reflection inside the Journal tab (web/reflections.js).
  const CAVE_ROUTES = { journal: "journal", prayers: "prayers", refuge: "refuge", amens: "refuge", pebbles: "refuge", reflection: "journal" };
  const CAVE_ACTIONS = {
    journal: ["New entry", () => newEntryMenu()],
    prayers: ["New", () => newPrayerMenu()],
    // Refuge has no header button: its rooms are its own ways in.
  };
  let caveTab = "journal";
  let tagFilter = null;

  // `route` is the hash that opened the cave, passed on so a tab can open
  // somewhere inside itself (Refuge's #amens).
  async function showCave(tab, route) {
    caveTab = tab || caveTab;
    $$("[data-cave-tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.caveTab === caveTab)));
    // A reflection open in the Journal tab has its own way back, so the
    // header button steps aside while it's open. Any other way out of it
    // (a tab, another page) saves what's waiting and closes it.
    const reflectionId = route === "reflection" ? location.hash.split("/")[1] : null;
    if (!reflectionId) {
      window.Reflections.hide();
      if (location.hash.startsWith("#reflection/")) history.replaceState(null, "", `#${caveTab}`);
    }
    const action = CAVE_ACTIONS[caveTab];
    $("#caveAction").hidden = !action || !!reflectionId;
    // A plus before the label: both open a small menu of new things.
    if (action) {
      $("#caveAction").textContent = action[0];
      $("#caveAction").insertAdjacentHTML("afterbegin", '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>');
    }
    // Leaving Refuge settles the page back and lets an unkept talk vanish.
    if (caveTab !== "refuge") window.Refuge.hide();
    const panel = $("#cavePanel");
    panel.replaceChildren(el("div", { class: "empty", text: "Opening..." }));
    try {
      await {
        journal: (p) => (reflectionId ? window.Reflections.show(p, reflectionId) : renderJournal(p)),
        prayers: (p) => window.Prayers.renderTab(p),
        refuge: (p) => window.Refuge.renderTab(p, route),
      }[caveTab](panel);
    } catch (err) {
      panel.replaceChildren(el("div", { class: "empty" }, [el("strong", { text: "Couldn't open this" }), err.message]));
    }
  }

  // The Journal's filter value that shows reflections instead of entries.
  // Tags are always lower case (app/cave.py::_clean_tags), so it can't clash.
  const REFLECTIONS_FILTER = "@Reflections";

  // "New entry" offers a plain entry or a reflection.
  function newEntryMenu() {
    headerMenu("New entry", [
      { title: "Journal entry", sub: "Write about today", onPick: () => openJournal({}, () => showCave("journal")) },
      { title: "Reflection", sub: "Look back and look ahead with God", onPick: () => window.Reflections.openStart() },
    ]);
  }

  // The Prayers tab's "New" offers a prayer for the list, or a quick
  // declaration for something right now (web/declare.js).
  function newPrayerMenu() {
    headerMenu("New", [
      { title: "Prayer", about: "Keep it on your list. Pray or declare over it any day.", onPick: () => window.Prayers.openSheet({}, () => showCave("prayers")) },
      { title: "Declare", about: "For something right now. Nothing is kept unless you tap Keep, and then it joins your prayer list.", onPick: () => window.Declare.open({ from: "quick" }) },
      { title: "Fast", about: "Set aside days to fast and pray, and count them here. Only you can see it.", onPick: () => window.Prayers.startFast(() => showCave("prayers")) },
    ]);
  }

  // A small menu of choices under the cave's header button. Each choice has
  // a short line under it (`sub`) or its explanation behind an info button
  // (`about`). It closes on a pick, Escape, a scroll, or a click elsewhere.
  function headerMenu(label, choices) {
    const button = $("#caveAction");
    if (button.getAttribute("aria-expanded") === "true") return;
    const choice = ({ title, sub, about, onPick }) => {
      const pick = el("button", {
        class: "more-item new-entry-item", type: "button", role: "menuitem",
        onclick: () => { close(); onPick(); },
      }, [el("strong", { text: title }), sub ? el("span", { text: sub }) : null]);
      return about ? el("div", { class: "new-entry-row" }, [pick, info(about, { label: `About ${title}` })]) : pick;
    };
    const menu = el("div", { class: "more-menu new-entry-menu", role: "menu", "aria-label": label }, choices.map(choice));
    const at = button.getBoundingClientRect();
    menu.style.top = `${at.bottom + 6}px`;
    menu.style.right = `${Math.max(12, window.innerWidth - at.right)}px`;
    document.body.append(menu);
    button.setAttribute("aria-expanded", "true");
    menu.querySelector("button").focus();

    function close() {
      menu.remove();
      button.setAttribute("aria-expanded", "false");
      document.removeEventListener("click", onOutside, true);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    }
    function onOutside(e) {
      if (!menu.contains(e.target)) close();
    }
    function onKey(e) {
      if (e.key === "Escape") {
        close();
        button.focus();
      }
    }
    // Wait a tick, so the click that opened the menu doesn't also close it.
    setTimeout(() => {
      document.addEventListener("click", onOutside, true);
      document.addEventListener("keydown", onKey);
      window.addEventListener("scroll", close, true);
      window.addEventListener("resize", close);
    });
  }

  async function renderJournal(panel) {
    // Reflections come back empty until their migration has run.
    const [entries, reflections] = await Promise.all([api("/me/journal"), window.Reflections.list()]);
    if (!entries.length && !reflections.length) {
      panel.replaceChildren(el("div", { class: "empty" }, [
        el("strong", { text: "Nothing in your journal yet" }),
        "Write about a verse or an answer you saved, about today, or look back on a stretch of time with God.",
        el("div", { class: "empty-actions" }, [
          el("button", { class: "btn btn-ember btn-sm", type: "button", text: "Write an entry", onclick: () => openJournal({}, () => showCave("journal")) }),
          el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Start a reflection", onclick: () => window.Reflections.openStart() }),
        ]),
      ]));
      return;
    }
    // Filter by the tags actually in use, most used first, or to reflections.
    // Filtering happens here rather than on the server: a journal is at most
    // a hundred entries.
    const counts = new Map();
    entries.forEach((e) => entryTags(e).forEach((t) => counts.set(t, (counts.get(t) || 0) + 1)));
    const used = [...counts.keys()].sort((a, b) => counts.get(b) - counts.get(a) || a.localeCompare(b));
    if (tagFilter === REFLECTIONS_FILTER ? !reflections.length : tagFilter && !counts.has(tagFilter)) tagFilter = null;
    const options = [["", "All entries"], ...(reflections.length ? [[REFLECTIONS_FILTER, "Reflections"]] : []), ...used.map((t) => [t, `#${t}`])];
    const filter = options.length > 1
      ? filterSelect("Filter the journal", options, tagFilter || "", (value) => {
          tagFilter = value || null;
          showCave("journal");
        })
      : null;

    if (tagFilter === REFLECTIONS_FILTER) {
      const cards = [
        ...reflections.filter((r) => r.current).map(window.Reflections.planCard),
        ...reflections.filter((r) => !r.current).map(window.Reflections.rowCard),
      ];
      panel.replaceChildren(
        listBar(`${reflections.length} ${reflections.length === 1 ? "reflection" : "reflections"}`, filter),
        el("div", { class: "entries" }, cards)
      );
      return;
    }
    const shown = tagFilter ? entries.filter((e) => entryTags(e).includes(tagFilter)) : entries;
    // The plan someone is living in, and reflections still in progress, sit
    // above the entries when the whole journal is showing.
    const pinned = tagFilter ? [] : window.Reflections.pinned(reflections);
    panel.replaceChildren(
      listBar(`${shown.length} ${shown.length === 1 ? "entry" : "entries"}`, filter),
      pinned.length ? el("div", { class: "entries journal-pinned" }, pinned) : null,
      el("div", { class: "entries" }, shown.map(journalCard))
    );
  }

  // A round icon button for an entry's less wordy actions.
  function iconAct(icon, label, onclick) {
    return el("button", { class: "icon-act", type: "button", "aria-label": label, title: label, html: icon, onclick });
  }

  // An entry: what it's about, the person's reflection, then one row of
  // actions. The likely next step stays in words; Connections and Edit are
  // icons; Share and Delete wait in the "⋯" menu, so Delete is never one slip away.
  function journalCard(e) {
    const node = el("article", { class: "entry fade-in" });
    const meta = el("div", { class: "entry-meta" }, [el("span", { text: when(e.created_at) })]);
    for (const t of entryTags(e)) meta.append(el("span", { class: "tag", text: `#${t}` }));
    const refl = el("p", { class: "refl", text: e.reflection || "No reflection yet. Tap the pencil to add one." });
    const editBtn = iconAct(ICON.edit, "Edit");
    editBtn.onclick = () => {
      const ta = el("textarea", { "aria-label": "Your reflection" });
      ta.value = e.reflection || "";
      refl.replaceWith(ta);
      ta.focus();
      editBtn.innerHTML = ICON.check;
      editBtn.setAttribute("aria-label", "Save");
      editBtn.title = "Save";
      editBtn.classList.add("is-on");
      editBtn.onclick = async () => {
        try {
          node.replaceWith(journalCard(await api(`/me/journal/${e.id}`, { method: "PATCH", body: { reflection: ta.value.trim() } })));
        } catch (err) {
          toast(err.message, { tone: "error" });
        }
      };
    };
    const refs = (e.citations || []).map((c) => `${c.book} ${c.chapter}:${c.verse}`);
    if (!refs.length && e.passage_ref) refs.push(e.passage_ref);
    const textAct = (icon, label, onclick) => el("button", { class: "text-act", type: "button", html: icon, onclick }, [label]);
    const actions = el("div", { class: "entry-actions" }, [
      e.question ? textAct(ICON.chat, "Ask again", () => app().submitQuery(e.question)) : null,
      el("div", { class: "entry-icons" }, [
        refs.length ? iconAct(ICON.graph, "See connections", () => window.Graph.open(refs.slice(0, 4))) : null,
        editBtn,
        moreMenu("More for this entry", [
          e.passage_ref && e.verse_text
            ? { label: "Share as an image", onClick: () => shareCard({ ref: e.passage_ref, text: e.verse_text, translation: ((e.citations || [])[0] || {}).translation || translation() }) }
            : null,
          {
            label: "Delete", danger: true,
            onClick: async () => {
              if (!confirm("Delete this journal entry? This can't be undone.")) return;
              try {
                await api(`/me/journal/${e.id}`, { method: "DELETE" });
                node.remove();
              } catch (err) {
                toast(err.message, { tone: "error" });
              }
            },
          },
        ]),
      ]),
    ]);
    node.append(meta, el("h3", { text: e.passage_ref || e.question || "A moment kept" }));
    if (e.verse_text) node.append(el("p", { class: "verse", text: e.verse_text }));
    node.append(refl, actions);
    return node;
  }

  // Reading plans: the builder, then every plan with today's reading. Drawn
  // into the Bible's "Reading plans" page by web/reader.js, which passes
  // `rerender` so a change redraws just this panel.
  async function renderPlans(panel, rerender) {
    const rows = await api(`/me/plans?today=${localToday()}`);
    panel.replaceChildren(
      planBuilder({ onBuilt: rerender }),
      rows.length
        ? el("div", { class: "plan-list" }, [el("h2", { class: "section-title", text: "Your plans" }), ...rows.map((p) => planItem(p, { onChange: rerender }))])
        : el("p", { class: "muted", style: "margin-top:20px", text: "No plans yet. Shape one with Aquila above, or read the whole Bible in a year." })
    );
  }

  // ---------------------------------------------------------------------
  // Settings: profile, theme, and what Aquila remembers
  // ---------------------------------------------------------------------
  // Drawn afresh each time Settings opens, since whether the supporter themes
  // are unlocked can change between visits.
  function renderThemeOptions() {
    const box = $("#themeOptions");
    const current = document.documentElement.dataset.theme;
    const unlocked = isFriend();
    box.replaceChildren(
      ...Object.entries(THEME_NAMES).map(([key, name]) => {
        const locked = SUPPORTER_THEMES.has(key) && !unlocked;
        return el("button", {
          class: `theme-option${locked ? " locked" : ""}`, type: "button", "data-set-theme": key, "aria-pressed": String(key === current),
          title: locked ? "A thank-you for friends of the cave" : name,
        }, [
          el("span", { class: "swatch", "data-swatch": key, "aria-hidden": "true" }),
          name,
          SUPPORTER_THEMES.has(key) ? el("span", { class: "theme-friend", html: ICON.heart, "aria-label": "Supporter theme" }) : null,
        ]);
      })
    );
  }

  // Where each kind of memory came from, as shown under it in Settings.
  const MEMORY_SOURCES = { note: "from a conversation", journal: "from your journal", prayer: "from your prayer list" };

  async function renderMemories(panel) {
    panel.replaceChildren(el("p", { class: "faint", text: "Opening..." }));
    let rows;
    try {
      rows = await api("/me/memories");
    } catch (err) {
      panel.replaceChildren(el("p", { class: "form-msg bad", text: err.message }));
      return;
    }
    const toggle = el("input", { type: "checkbox", id: "memoryToggle" });
    toggle.checked = !profile || profile.memory_enabled !== false;
    toggle.onchange = async () => {
      try {
        const p = await api("/me", { method: "PATCH", body: { memory_enabled: toggle.checked } });
        profile = { ...profile, ...p };
        toast(toggle.checked ? "Aquila will remember." : "Aquila won't keep new notes, or use old ones.");
      } catch (err) {
        toggle.checked = !toggle.checked;
        toast(err.message, { tone: "error" });
      }
    };
    const list = rows.length
      ? el("ul", { class: "memory-list" }, rows.map((m) => {
          const item = el("li", {}, [
            el("div", {}, [
              el("p", { text: m.content }),
              el("small", { text: `${when(m.created_at)} · ${MEMORY_SOURCES[m.kind] || MEMORY_SOURCES.note}` }),
            ]),
          ]);
          item.append(el("button", {
            class: "act danger", type: "button", text: "Forget",
            onclick: async () => {
              try {
                await api(`/me/memories/${m.id}`, { method: "DELETE" });
                item.remove();
              } catch (err) {
                toast(err.message, { tone: "error" });
              }
            },
          }));
          return item;
        }))
      : el("p", { class: "muted", text: "Nothing yet. As you share what you're studying or walking through, Aquila keeps a few short notes here." });
    panel.replaceChildren(
      el("label", { class: "switch", for: "memoryToggle" }, [toggle, "Let Aquila remember me"]),
      list,
      rows.length
        ? el("div", { class: "row", style: "margin-top:16px" }, [el("button", {
            class: "btn btn-ghost btn-sm", type: "button", text: "Forget everything",
            onclick: async () => {
              if (!confirm("Let Aquila forget everything she has noted about you? Your journal stays.")) return;
              try {
                await api("/me/memories", { method: "DELETE" });
                renderMemories(panel);
              } catch (err) {
                toast(err.message, { tone: "error" });
              }
            },
          })])
        : null
    );
  }

  async function showSettings(route) {
    if (!profile) await loadProfile();
    $("#settingsEmail").textContent = email() ? `Signed in as ${email()}` : "";
    $("#settingsName").value = displayName();
    renderThemeOptions();
    window.Support.renderSettings();
    renderMemories($("#memoryPanel"));
    if (route === "remembers") setTimeout(() => $("#remembers").scrollIntoView({ behavior: "smooth", block: "start" }), 120);
  }

  function wireSettings() {
    $("#nameForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const name = $("#settingsName").value.trim();
      if (!name) return toast("Add a name first.", { tone: "info" });
      try {
        const p = await api("/me", { method: "PATCH", body: { display_name: name } });
        profile = { ...profile, ...p };
        updateChrome();
        toast("Saved.");
      } catch (err) {
        toast(err.message, { tone: "error" });
      }
    });
    $$("[data-sign-out]").forEach((b) => b.addEventListener("click", signOut));
    $("#exportData").addEventListener("click", exportData);
    $("#closeAccount").addEventListener("click", closeAccount);
  }

  // Saves a file from the server. It goes through fetch rather than a plain
  // link because the request needs the sign-in header.
  async function downloadFile(path, name) {
    const resp = await fetch(`${apiBase()}${path}`, { headers: await authHeaders() });
    if (!resp.ok) throw new Error(`The download didn't work (${resp.status}).`);
    const url = URL.createObjectURL(await resp.blob());
    const a = el("a", { href: url, download: name });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }

  // Everything the person keeps, as one zip (app/account.py).
  async function exportData(e) {
    const button = e.currentTarget;
    button.disabled = true;
    toast("Gathering everything. This can take a moment.", { tone: "info" });
    try {
      await downloadFile("/me/export", `Adullum export ${localToday()}.zip`);
    } catch (err) {
      toast(err.message, { tone: "error" });
    } finally {
      button.disabled = false;
    }
  }

  // Closing an account removes everything in it for good, so the person
  // types their email to confirm, and the sheet says plainly what goes.
  function closeAccount() {
    const typed = el("input", { class: "field", type: "email", autocomplete: "off", "aria-label": "Your email" });
    const msg = formMessage();
    const confirmBtn = el("button", { class: "btn btn-ghost btn-sm danger-text", type: "submit", text: "Delete my account" });
    const form = el("form", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "closeAccountTitle" }, [
      el("h3", { id: "closeAccountTitle", text: "Delete your account?" }),
      el("p", { text: "This removes your conversations, journal, prayers, notes, Refuge, sermon notes and everything else you keep here, and anything you shared on the Amens wall. It can't be undone." }),
      el("p", { class: "muted", text: "You may want to download your data first." }),
      el("label", { class: "field-wrap" }, [`Type ${email()} to confirm`, typed]),
      msg.node,
      el("div", { class: "sheet-actions" }, [el("span", { style: "flex:1" }), el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Cancel", onclick: () => close() }), confirmBtn]),
    ]);
    const close = overlay(form);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (typed.value.trim().toLowerCase() !== (email() || "").toLowerCase()) return msg.say("That isn't your email address.", true);
      confirmBtn.disabled = true;
      try {
        await api("/me", { method: "DELETE", body: { confirm: typed.value.trim() } });
        close();
        writeSession(null);
        profile = null;
        lastName = "";
        updateChrome();
        app().go("welcome");
        toast("Your account and everything in it have been deleted.");
      } catch (err) {
        msg.say(err.message, true);
        confirmBtn.disabled = false;
      }
    });
  }

  // ---------------------------------------------------------------------
  // Signed out
  // ---------------------------------------------------------------------
  async function showSignedOut() {
    $("#farewellName").textContent = lastName ? `Rest well, ${lastName}.` : "Rest well.";
    const box = $("#farewellVerse");
    if (!box.dataset.loaded) {
      try {
        const v = await verseText("Psalm 4:8");
        box.querySelector("[data-text]").textContent = `"${v.text}"`;
        box.querySelector("[data-ref]").textContent = `Psalm 4:8 · ${v.translation}`;
        box.hidden = false;
        box.dataset.loaded = "1";
      } catch {
        /* the page reads fine without it */
      }
    }
  }

  // ---------------------------------------------------------------------
  // Called by index.html's router each time the view changes
  // ---------------------------------------------------------------------
  function onView(view, route) {
    if (view !== "cave") { window.Refuge.hide(); window.Sermons.hide(); window.Reflections.hide(); }
    if (view === "welcome") showWelcome();
    else if (view === "signin") showSignin(route);
    else if (view === "home") showHome();
    else if (view === "aquila") refreshRail();
    else if (view === "cave") showCave(CAVE_ROUTES[route], route);
    else if (view === "settings") showSettings(route);
    else if (view === "signedout") showSignedOut();
    else if (view === "desk") window.Refuge.renderDesk();
    else if (view === "sermon") window.Sermons.renderShared();
    else if (view === "support") window.Support.show();
  }

  window.Cave = {
    authHeaders,
    api,
    el,
    overlay,
    info,
    titleInfo,
    sheetTitle,
    formMessage,
    listBar,
    filterSelect,
    moreMenu,
    iconAct,
    weekDots,
    localDate,
    when,
    agoPhrase,
    localToday,
    card,
    cardHead,
    homeNote,
    showCave,
    renderPlans,
    signedIn,
    signOut,
    account,
    supporterSince,
    isFriend,
    onView,
    openJournal,
    openConversations,
    decorateAnswer,
    markMemory,
    refreshRail,
    shareCard,
    toast,
    verseText,
  };

  consumeRedirect();
  document.addEventListener("DOMContentLoaded", () => {
    upgradeInfo();
    setTheme(document.documentElement.dataset.theme);
    wireAuth();
    wireSettings();
    $$("[data-cave-tab]").forEach((b) => b.addEventListener("click", () => showCave(b.dataset.caveTab)));
    $("#caveAction").addEventListener("click", () => CAVE_ACTIONS[caveTab] && CAVE_ACTIONS[caveTab][1]());
    if (signedIn()) loadProfile();
    else updateChrome();
  });
})();
