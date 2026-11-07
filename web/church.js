// The Church tab (#church): the churches a person has put in their own list,
// their sermon notes, and sermons to listen to, by season.
//
// Personal, never social: a church here is one the person added for
// themselves (app/churches.py). There's no following, no counts of who else
// goes, and Adullum never suggests a church.
//
// Routes, all inside the one view:
//   #church             your churches, each with its info icon for notices
//   #church/sermons     sermon notes (drawn by web/sermons.js); #sermons lands here
//   #church/listen      sermons for how you feel, from your churches and
//                       Adullum's catalog (app/listen.py)
//   #church/add         add a church from a link, or by hand
//   #church/c/<id>      one church: sermons, times, news, about
//   #church/live/<id>   a live stream with notes beside it
//   #church/week/<id>   the five small steps after a sermon
//
// Times: a church's gatherings are stored in its own time zone, and each is
// shown in the person's time too, worked out here with Intl.
//
// Loaded after web/cave.js and web/sermons.js, whose helpers it borrows at
// call time.
(function () {
  const cave = () => window.Cave;
  const el = (...args) => cave().el(...args);
  const api = (...args) => cave().api(...args);
  const toast = (text) => cave().toast(text);
  const $ = (sel) => document.querySelector(sel);

  const svg = (d, fill = "none") => `<svg viewBox="0 0 24 24" fill="${fill}" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
  const ICON = {
    plus: svg('<path d="M12 5v14M5 12h14"/>'),
    back: svg('<path d="M15 6l-6 6 6 6"/>'),
    next: svg('<path d="M9 6l6 6-6 6"/>'),
    info: svg('<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>'),
    play: svg('<path d="M8 5v14l11-7z"/>', "currentColor"),
    pen: svg('<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16z"/>'),
    out: svg('<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>'),
    close: svg('<path d="M6 6l12 12M18 6L6 18"/>'),
    check: svg('<path d="M5 12.5l4.5 4.5L19 7.5"/>'),
    link: svg('<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>'),
    mark: svg('<path d="M6 4h12v17l-6-4-6 4z"/>'),
    notes: svg('<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16z"/>'),
    bell: svg('<path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z"/><path d="M10 20.5a2 2 0 0 0 4 0"/>'),
  };

  const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  const MOODS = [["weary", "Weary"], ["anxious", "Anxious"], ["grateful", "Grateful"], ["grieving", "Grieving"], ["deciding", "Deciding"], ["joyful", "Joyful"]];
  const SECTIONS = [["", "Churches"], ["sermons", "Sermons"], ["listen", "Listen"]];

  let root = null;        // #churchPage while the view is open
  let churches = null;    // the list, once loaded
  let live = [];          // churches streaming right now
  let mood = "";          // Listen's season; empty is any season
  let sermonsReady = null;
  let showing = "";       // which part of the view is drawn

  const translation = () => ((document.getElementById("translation") || {}).value || "BSB").trim() || "BSB";

  // ---------------------------------------------------------------------
  // Time: a church's own time zone, and the person's
  // ---------------------------------------------------------------------
  const localZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  function validZone(zone) {
    if (!zone) return null;
    try {
      new Intl.DateTimeFormat("en-US", { timeZone: zone });
      return zone;
    } catch {
      return null;
    }
  }
  function zoneParts(zone, at = new Date()) {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: zone, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric", weekday: "short",
    }).formatToParts(at);
    const get = (type) => (parts.find((p) => p.type === type) || {}).value;
    return { y: +get("year"), m: +get("month"), d: +get("day"), h: +get("hour") % 24, min: +get("minute"), wd: DAYS.indexOf(get("weekday")) };
  }
  // How far `zone` is ahead of UTC at a moment, in milliseconds.
  function zoneOffset(zone, ms) {
    const p = zoneParts(zone, new Date(ms));
    return Date.UTC(p.y, p.m - 1, p.d, p.h, p.min) - Math.floor(ms / 60000) * 60000;
  }
  // The next time a weekly gathering starts, as a Date.
  function nextAt(gathering, zone) {
    zone = validZone(zone) || localZone;
    const now = zoneParts(zone);
    const [hh, mm] = gathering.time.split(":").map(Number);
    for (let ahead = 0; ahead <= 7; ahead++) {
      if ((now.wd + ahead) % 7 !== gathering.day) continue;
      if (ahead === 0 && (hh < now.h || (hh === now.h && mm <= now.min))) continue;
      const wall = Date.UTC(now.y, now.m - 1, now.d + ahead, hh, mm);
      let at = wall - zoneOffset(zone, wall);
      at = wall - zoneOffset(zone, at);
      return new Date(at);
    }
    return null;
  }
  function nextGathering(church) {
    let best = null;
    for (const g of church.gatherings || []) {
      const at = nextAt(g, church.time_zone);
      if (at && (!best || at < best.at)) best = { at, gathering: g };
    }
    return best;
  }
  const yourTime = (date) => date.toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" });
  function clockIn(zone) {
    return new Date().toLocaleTimeString(undefined, { timeZone: validZone(zone) || localZone, hour: "numeric", minute: "2-digit" });
  }
  function twelve(time) {
    const [h, m] = time.split(":").map(Number);
    return new Date(2000, 0, 1, h, m).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  }
  const sameZone = (church) => !validZone(church.time_zone) || validZone(church.time_zone) === localZone;
  const shortDate = (iso) => (iso ? new Date(`${iso.slice(0, 10)}T12:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "");

  // ---------------------------------------------------------------------
  // Small pieces
  // ---------------------------------------------------------------------
  const initials = (name) => (name || "?").split(/\s+/).filter((w) => /^[A-Za-z0-9]/.test(w)).slice(0, 2).map((w) => w[0].toUpperCase()).join("") || "?";
  function avatar(church, big = false) {
    const index = churches ? Math.max(0, churches.findIndex((c) => c.id === church.id)) : 0;
    return el("span", { class: `church-av church-av-${index % 4}${big ? " is-big" : ""}`, "aria-hidden": "true", text: initials(church.name) });
  }
  const liveFor = (id) => live.find((l) => l.church_id === id);
  const liveBadge = () => el("span", { class: "live-badge", text: "Live" });

  function sectionNav(current) {
    return el("nav", { class: "church-seg", "aria-label": "Church" }, SECTIONS.map(([key, label]) => el("a", {
      href: key ? `#church/${key}` : "#church", "aria-current": key === current ? "page" : null, text: label,
    })));
  }

  function head(current) {
    return el("div", { class: "church-top" }, [
      el("div", { class: "church-title-row" }, [
        el("h1", { class: "page-title", text: "Church" }),
        el("a", { class: "iconbtn church-add", href: "#church/add", "aria-label": "Add a church", title: "Add a church", html: ICON.plus }),
      ]),
      sectionNav(current),
    ]);
  }

  function backRow(href, label, ...actions) {
    return el("div", { class: "church-back-row" }, [
      el("a", { class: "act church-back", href, html: `${ICON.back}<span>${label}</span>` }),
      el("span", { class: "church-back-actions" }, actions.filter(Boolean)),
    ]);
  }

  // Draws the page, skipping parts that are null (a church that isn't live
  // has no live banner), which replaceChildren would print as "null".
  function fill(...nodes) {
    root.replaceChildren(...nodes.filter(Boolean));
  }

  function failed(err, what = "Couldn't open this") {
    return el("div", { class: "empty" }, [el("strong", { text: what }), err.message]);
  }

  async function loadChurches(force = false) {
    if (!churches || force) churches = await api("/me/churches");
    return churches;
  }
  async function loadLive() {
    try {
      live = await api("/me/churches/live");
    } catch {
      live = [];
    }
    return live;
  }

  // A calendar file for an event, so it can go in the person's own calendar.
  function calendarFile(event, church) {
    const stamp = new Date().toISOString().replace(/[-:]/g, "").slice(0, 15) + "Z";
    const day = event.date.replace(/-/g, "");
    const zone = validZone(church.time_zone);
    const start = event.time ? `DTSTART${zone ? `;TZID=${zone}` : ""}:${day}T${event.time.replace(":", "")}00` : `DTSTART;VALUE=DATE:${day}`;
    const text = (s) => String(s || "").replace(/[\\;,]/g, (c) => `\\${c}`).replace(/\n/g, "\\n");
    const ics = [
      "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Adullum//Church//EN", "BEGIN:VEVENT",
      `UID:${day}-${Math.random().toString(36).slice(2)}@adullum`, `DTSTAMP:${stamp}`, start,
      `SUMMARY:${text(event.title)}`, `LOCATION:${text(church.address || church.name)}`, "END:VEVENT", "END:VCALENDAR",
    ].join("\r\n");
    const link = el("a", { href: URL.createObjectURL(new Blob([ics], { type: "text/calendar" })), download: `${event.title.replace(/[^\w ]+/g, "").trim() || "event"}.ics` });
    document.body.append(link);
    link.click();
    setTimeout(() => { URL.revokeObjectURL(link.href); link.remove(); }, 1000);
  }

  // ---------------------------------------------------------------------
  // Reminders: a bell on each event and gathering. web/notify.js turns
  // notifications on for this device and app/reminders.py sends them.
  // ---------------------------------------------------------------------
  let reminders = new Map(); // key -> reminder, loaded with a church's page
  async function loadReminders() {
    reminders = new Map((await window.Notify.list()).map((r) => [r.key, r]));
  }
  const slug = (text) => (text || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60) || "event";
  const fullWhen = (date) => new Date(date).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  // A date and time on the wall in `zone`, as a Date.
  function wallToDate(isoDate, time, zone) {
    zone = validZone(zone) || localZone;
    const [y, m, d] = isoDate.split("-").map(Number);
    const [hh, mm] = time.split(":").map(Number);
    const wall = Date.UTC(y, m - 1, d, hh, mm);
    let at = wall - zoneOffset(zone, wall);
    at = wall - zoneOffset(zone, at);
    return new Date(at);
  }
  function dayBefore(isoDate) {
    const d = new Date(`${isoDate}T12:00:00Z`);
    d.setUTCDate(d.getUTCDate() - 1);
    return d.toISOString().slice(0, 10);
  }

  // A bell button with a small menu. `choices()` is asked each time it opens,
  // so the menu always matches what's set.
  function bell(label, choices) {
    const wrap = el("div", { class: "more church-bell" });
    const button = el("button", { class: "iconbtn church-row-act", type: "button", "aria-haspopup": "menu", "aria-expanded": "false", "aria-label": label, title: label, html: ICON.bell });
    let menu = null;
    const outside = (e) => { if (!wrap.contains(e.target)) close(); };
    const onKey = (e) => { if (e.key === "Escape") { close(); button.focus(); } };
    function close() {
      if (!menu) return;
      menu.remove();
      menu = null;
      button.setAttribute("aria-expanded", "false");
      document.removeEventListener("click", outside, true);
      document.removeEventListener("keydown", onKey);
    }
    button.onclick = () => {
      if (menu) return close();
      const { on, items } = choices();
      menu = el("div", { class: "more-menu church-bell-menu", role: "menu" }, [
        on ? el("p", { class: "church-bell-on", text: on }) : null,
        ...items.map((item) => el("button", {
          class: `more-item${item.danger ? " danger" : ""}`, type: "button", role: "menuitem", text: item.label,
          onclick: () => { close(); item.run(); },
        })),
      ]);
      wrap.append(menu);
      button.setAttribute("aria-expanded", "true");
      document.addEventListener("click", outside, true);
      document.addEventListener("keydown", onKey);
      const first = menu.querySelector("button");
      if (first) first.focus();
    };
    wrap.append(button);
    wrap.paint = (isOn) => {
      button.classList.toggle("is-on", isOn);
      button.setAttribute("aria-label", isOn ? `${label}: on` : label);
    };
    return wrap;
  }

  async function setReminder(button, reminder) {
    try {
      const saved = await window.Notify.remind(reminder);
      if (!saved) return;
      reminders.set(saved.key, saved);
      button.paint(true);
      toast(`Reminder set for ${fullWhen(saved.remind_at)}.`);
    } catch (err) {
      toast(err.message);
    }
  }
  async function turnOff(button, key) {
    try {
      await window.Notify.cancel(key);
      reminders.delete(key);
      button.paint(false);
      toast("Reminder off.");
    } catch (err) {
      toast(err.message);
    }
  }

  function eventBell(church, event) {
    const key = `event:${church.id}:${event.date}:${slug(event.title)}`;
    const start = event.time ? wallToDate(event.date, event.time, church.time_zone) : null;
    const options = start
      ? [["a day before", new Date(start.getTime() - 864e5)], ["an hour before", new Date(start.getTime() - 36e5)]]
      : [["the evening before", wallToDate(dayBefore(event.date), "18:00", church.time_zone)], ["that morning", wallToDate(event.date, "08:00", church.time_zone)]];
    const when = start ? yourTime(start) : shortDate(event.date);
    const button = bell(`Remind me about ${event.title}`, () => {
      const set = reminders.get(key);
      const items = set ? [{ label: "Turn off reminder", danger: true, run: () => turnOff(button, key) }]
        : options.filter(([, at]) => at > new Date()).map(([label, at]) => ({
            label: `Remind me ${label}`,
            run: () => setReminder(button, { key, title: event.title, body: `${church.name}, ${when}`, url: `#church/c/${church.id}`, remind_at: at.toISOString() }),
          }));
      items.push({ label: "Add to my calendar", run: () => calendarFile(event, church) });
      return { on: set ? `Reminder on: ${fullWhen(set.remind_at)}` : null, items };
    });
    button.paint(reminders.has(key));
    return button;
  }

  function gatheringBell(church, gathering) {
    const key = `gathering:${church.id}:${gathering.day}:${gathering.time.replace(":", "")}`;
    const label = gathering.label || "Gathering";
    const zone = validZone(church.time_zone) || localZone;
    const choice = (before, text, starts) => ({
      label: `Remind me ${text}, every week`,
      run: () => setReminder(button, {
        key, title: `${label}, ${church.name}`, body: starts, url: `#church/c/${church.id}`,
        repeat: { day: gathering.day, time: gathering.time, zone, before },
      }),
    });
    const button = bell(`Remind me before ${label}`, () => {
      const set = reminders.get(key);
      if (set) {
        const before = set.repeat && set.repeat.before === 60 ? "an hour" : "30 minutes";
        return { on: `Every week, ${before} before`, items: [{ label: "Turn off reminder", danger: true, run: () => turnOff(button, key) }] };
      }
      return { on: null, items: [choice(30, "30 minutes before", "Starts in 30 minutes."), choice(60, "an hour before", "Starts in an hour.")] };
    });
    button.paint(reminders.has(key));
    return button;
  }

  // ---------------------------------------------------------------------
  // The player: one video or episode, docked at the bottom while the
  // Church view is open
  // ---------------------------------------------------------------------
  let dock = null;
  function closePlayer() {
    if (dock) dock.remove();
    dock = null;
  }
  function play(item) {
    if (!item.video_id && !item.audio_url) {
      window.open(item.url, "_blank", "noopener");
      return;
    }
    closePlayer();
    const media = item.video_id
      ? el("iframe", {
          src: `https://www.youtube-nocookie.com/embed/${item.video_id}?autoplay=1&rel=0&modestbranding=1`,
          title: item.title, allow: "autoplay; encrypted-media; picture-in-picture; fullscreen", allowfullscreen: true,
          referrerpolicy: "strict-origin-when-cross-origin",
        })
      : el("audio", { src: item.audio_url, controls: true, autoplay: true });
    dock = el("div", { class: `church-player${item.video_id ? "" : " is-audio"}`, role: "region", "aria-label": "Now playing" }, [
      el("div", { class: "church-player-media" }, media),
      el("div", { class: "church-player-bar" }, [
        el("span", { class: "church-player-text" }, [el("strong", { text: item.title }), el("small", { text: item.church || "" })]),
        el("button", { class: "btn btn-ember btn-sm", type: "button", text: "Notes", onclick: () => fromLinkSheet({ url: item.url, churchId: item.church_id }) }),
        el("button", { class: "iconbtn", type: "button", "aria-label": "Close player", html: ICON.close, onclick: closePlayer }),
      ]),
    ]);
    document.body.append(dock);
  }

  function sermonRow(item, { showChurch = false } = {}) {
    const thumb = item.video_id
      ? el("img", {
          class: "church-thumb", src: `https://i.ytimg.com/vi/${item.video_id}/mqdefault.jpg`, alt: "", loading: "lazy",
          // A thumbnail that won't load becomes a plain tile, not a broken image.
          onerror: (e) => e.currentTarget.replaceWith(el("span", { class: "church-thumb is-audio", "aria-hidden": "true", html: ICON.play })),
        })
      : el("span", { class: "church-thumb is-audio", "aria-hidden": "true", html: ICON.play });
    const sub = [showChurch ? item.church : shortDate(item.published), (item.refs || [])[0]].filter(Boolean);
    return el("div", { class: "church-row" }, [
      el("button", { class: "church-row-main", type: "button", onclick: () => play(item), "aria-label": `Play ${item.title}` }, [
        thumb,
        el("span", { class: "church-row-text" }, [
          el("strong", { text: item.title }),
          el("small", {}, sub.map((s, i) => el("span", { class: i === sub.length - 1 && (item.refs || [])[0] === s ? "verse-ref" : null, text: (i ? " · " : "") + s }))),
        ]),
      ]),
      el("button", { class: "iconbtn church-row-act", type: "button", title: "Make notes", "aria-label": `Make notes on ${item.title}`, html: ICON.notes, onclick: () => fromLinkSheet({ url: item.url, churchId: item.church_id }) }),
    ]);
  }

  // ---------------------------------------------------------------------
  // Your churches
  // ---------------------------------------------------------------------
  async function showChurches() {
    fill(head(""), el("div", { class: "empty", text: "Opening..." }));
    let list;
    try {
      [list] = await Promise.all([loadChurches(true), loadLive()]);
    } catch (err) {
      fill(head(""), failed(err, "Church isn't open yet"));
      return;
    }
    if (!list.length) {
      fill(head(""), el("section", { class: "card church-empty fade-in" }, [
        el("h2", { class: "section-title", text: "Keep your churches close" }),
        el("p", { class: "muted", text: "Add the churches you belong to, near or far. See when they're live, their times in yours, and their sermons." }),
        el("a", { class: "btn btn-ember btn-sm", href: "#church/add", text: "Add a church" }),
      ]));
      return;
    }
    const weekCard = el("div");
    fill(head(""), el("div", { class: "church-list card fade-in" }, list.map(churchRow)), weekCard);
    thisWeekCard().then((card) => card && weekCard.replaceWith(card));
  }

  function churchRow(church) {
    const isLive = liveFor(church.id);
    const next = nextGathering(church);
    const notes = el("div", { class: "church-notes", hidden: true });
    const count = church.unseen ? el("span", { class: "church-info-count", text: String(church.unseen) }) : null;
    const info = el("button", {
      class: `church-info${church.unseen ? " has-new" : ""}`, type: "button", "aria-expanded": "false",
      "aria-label": church.unseen ? `${church.unseen} new from ${church.name}` : `Notes from ${church.name}`,
    }, [el("span", { html: ICON.info }), count]);
    info.onclick = () => {
      const open = notes.hidden;
      notes.hidden = !open;
      info.setAttribute("aria-expanded", String(open));
      info.classList.toggle("is-open", open);
      if (open && church.unseen) {
        church.unseen = 0;
        info.classList.remove("has-new");
        if (count) count.remove();
        info.setAttribute("aria-label", `Notes from ${church.name}`);
        api(`/me/churches/${church.id}/seen`, { method: "POST" }).catch(() => {});
      }
    };
    const soon = (church.events || []).slice(0, 2);
    notes.append(...(church.notices || []).map((n) => el("p", { class: "church-note" }, [el("span", { class: "church-note-when", text: n.date || "Note" }), el("span", { text: n.text })])),
      ...soon.map((e) => el("p", { class: "church-note" }, [el("span", { class: "church-note-when", text: shortDate(e.date) }), el("span", { text: e.title })])));
    if (!notes.children.length) notes.append(el("p", { class: "church-note muted", text: "Nothing new." }));
    return el("div", { class: "church-item" }, [
      el("div", { class: "church-item-row" }, [
        el("a", { class: "church-item-main", href: `#church/c/${church.id}` }, [
          avatar(church),
          el("span", { class: "church-row-text" }, [
            el("strong", { text: church.name }),
            el("small", { text: [church.city, validZone(church.time_zone) && !sameZone(church) ? clockIn(church.time_zone) : null].filter(Boolean).join(" · ") }),
          ]),
          isLive ? el("span", { class: "church-next is-live", text: "Live now" })
            : next ? el("span", { class: "church-next", text: yourTime(next.at) }) : null,
        ]),
        info,
      ]),
      notes,
    ]);
  }

  async function thisWeekCard() {
    let week;
    try {
      week = await api(`/me/church/week?today=${cave().localToday()}`);
    } catch {
      return null;
    }
    if (!week || !week.steps) return null;
    const done = week.steps.filter((s) => s.done).length;
    return el("a", { class: "church-week-card fade-in", href: `#church/week/${week.id}` }, [
      el("span", { class: "church-week-text" }, [
        el("span", { class: "church-week-top" }, [el("strong", { text: "This week" }), el("span", { text: `${done} of ${week.steps.length}` })]),
        el("strong", { class: "church-week-title", text: week.title || "Sunday's sermon" }),
        el("span", { class: "church-bars" }, week.steps.map((s) => el("span", { class: s.done ? "is-done" : null }))),
      ]),
      el("span", { class: "church-go", html: ICON.next }),
    ]);
  }

  // ---------------------------------------------------------------------
  // One church
  // ---------------------------------------------------------------------
  async function showChurch(id, tab = "sermons") {
    fill(el("div", { class: "empty", text: "Opening..." }));
    let church;
    try {
      [church] = await Promise.all([api(`/me/churches/${id}`), loadChurches().catch(() => null), live.length ? null : loadLive(), loadReminders()]);
    } catch (err) {
      fill(backRow("#church", "Church"), failed(err));
      return;
    }
    const isLive = liveFor(church.id);
    const body = el("div", { class: "church-body" });
    const tabs = [["sermons", "Sermons"], ["times", "Times"], ["news", "News"], ["about", "About"]];
    const tabBar = el("div", { class: "tabs church-tabs", role: "tablist", "aria-label": church.name });
    const draw = (key) => {
      tab = key;
      tabBar.replaceChildren(...tabs.map(([k, label]) => el("button", {
        type: "button", role: "tab", "aria-selected": String(k === key), onclick: () => draw(k),
      }, [label, k === "news" && church.unseen ? el("span", { class: "church-dot", "aria-label": "new" }) : null])));
      if (key === "news" && church.unseen) {
        church.unseen = 0;
        api(`/me/churches/${church.id}/seen`, { method: "POST" }).catch(() => {});
      }
      ({ sermons: churchSermons, times: churchTimes, news: churchNews, about: churchAbout })[key](church, body);
    };
    fill(
      backRow("#church", "Church",
        church.website ? el("a", { class: "iconbtn", href: church.website, target: "_blank", rel: "noopener", "aria-label": "Website", title: "Website", html: ICON.out }) : null,
        el("button", { class: "iconbtn", type: "button", "aria-label": "Edit", title: "Edit", html: ICON.pen, onclick: () => editSheet(church) })),
      el("div", { class: "church-hero" }, [
        avatar(church, true),
        el("div", {}, [
          el("h1", { class: "church-name", text: church.name }),
          el("p", { class: "muted church-where", text: [church.city, validZone(church.time_zone) ? `${clockIn(church.time_zone)} there` : null].filter(Boolean).join(" · ") }),
        ]),
      ]),
      isLive ? el("a", { class: "church-live-strip", href: `#church/live/${church.id}` }, [liveBadge(), el("span", { text: "Watch and take notes" }), el("span", { html: ICON.play })]) : null,
      tabBar,
      body,
    );
    draw(tab);
  }

  async function churchSermons(church, body) {
    if (!church.youtube_url && !church.podcast_url) {
      body.replaceChildren(el("div", { class: "empty church-quiet" }, [
        "Add their YouTube channel or podcast to see sermons here.",
        el("div", {}, el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Add a link", onclick: () => editSheet(church) })),
      ]));
      return;
    }
    body.replaceChildren(el("div", { class: "empty", text: "Finding sermons..." }));
    let items;
    try {
      items = await api(`/me/churches/${church.id}/sermons`);
    } catch (err) {
      body.replaceChildren(failed(err));
      return;
    }
    body.replaceChildren(items.length
      ? el("div", { class: "card church-list" }, items.map((i) => sermonRow(i)))
      : el("div", { class: "empty church-quiet", text: "No sermons found yet. A Spotify link can't be read; a YouTube channel or podcast feed can." }));
  }

  function churchTimes(church, body) {
    const rows = (church.gatherings || []).slice().sort((a, b) => a.day - b.day || a.time.localeCompare(b.time));
    if (!rows.length) {
      body.replaceChildren(el("div", { class: "empty church-quiet" }, ["No times yet.", el("div", {}, el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Add times", onclick: () => editSheet(church) }))]));
      return;
    }
    const other = !sameZone(church);
    body.replaceChildren(el("div", { class: "card church-list" }, rows.map((g) => {
      const at = nextAt(g, church.time_zone);
      return el("div", { class: "church-line" }, [
        el("span", { class: "church-row-text" }, [el("strong", { text: g.label || "Gathering" }), el("small", { text: `${DAYS[g.day]} ${twelve(g.time)}${other ? " there" : ""}` })]),
        other && at ? el("span", { class: "church-next", text: yourTime(at) }) : null,
        gatheringBell(church, g),
      ]);
    })));
  }

  function churchNews(church, body) {
    const notices = church.notices || [];
    const events = church.events || [];
    if (!notices.length && !events.length) {
      body.replaceChildren(el("div", { class: "empty church-quiet", text: church.source_url ? "Nothing new on their site." : "News comes from a church's website. Add it to see their notices and events." }));
      return;
    }
    body.replaceChildren(el("div", { class: "card church-list" }, [
      ...notices.map((n) => el("div", { class: "church-line church-notice" }, [el("span", { class: "church-notice-icon", html: ICON.info }), el("span", { text: n.text })])),
      ...events.map((e) => el("div", { class: "church-line" }, [
        el("span", { class: "church-date" }, [el("small", { text: new Date(`${e.date}T12:00:00`).toLocaleDateString(undefined, { month: "short" }) }), el("strong", { text: String(+e.date.slice(8, 10)) })]),
        el("span", { class: "church-row-text" }, [el("strong", { text: e.title }), el("small", { text: [DAY_NAMES[new Date(`${e.date}T12:00:00`).getDay()], e.time ? twelve(e.time) : null].filter(Boolean).join(" · ") })]),
        eventBell(church, e),
      ])),
    ]));
  }

  function churchAbout(church, body) {
    const row = (label, value) => (value ? el("div", { class: "church-about-row" }, [el("span", { text: label }), value]) : null);
    const link = (href, text) => el("a", { href, target: "_blank", rel: "noopener", text });
    const watch = [
      church.youtube_url ? link(church.youtube_url, "YouTube") : null,
      church.podcast_url ? link(church.podcast_url, "Podcast") : null,
      church.facebook_url ? link(church.facebook_url, "Facebook") : null,
    ].filter(Boolean);
    const alerts = el("input", { type: "checkbox", checked: church.live_alerts !== false });
    alerts.addEventListener("change", async () => {
      try {
        await api(`/me/churches/${church.id}`, { method: "PATCH", body: { live_alerts: alerts.checked } });
        church.live_alerts = alerts.checked;
        // Telling them means a notification, so ask this device too.
        if (alerts.checked) window.Notify.enable();
      } catch (err) {
        alerts.checked = !alerts.checked;
        toast(err.message);
      }
    });
    let source = null;
    if (church.source_url) {
      try {
        source = `${new URL(church.source_url).hostname.replace(/^www\./, "")}${church.checked_at ? `, checked ${shortDate(church.checked_at)}` : ""}`;
      } catch { /* leave it out */ }
    }
    body.replaceChildren(
      el("div", { class: "card church-list" }, [
        row("Address", church.address ? el("span", { text: church.address }) : null),
        row("Pastors", church.pastors ? el("span", { text: church.pastors }) : null),
        row("Watch", watch.length ? el("span", { class: "church-links" }, watch) : null),
        row("Details from", source ? el("span", { text: source }) : null),
        el("label", { class: "church-about-row church-toggle" }, [el("span", { text: "Tell me when it's live" }), alerts]),
        window.Notify.supported() && Notification.permission !== "granted" && church.live_alerts !== false
          ? el("div", { class: "church-about-row church-notify-row" }, [
              el("span", { text: "This device" }),
              el("button", { class: "linkish", type: "button", text: "Turn on notifications", onclick: async (e) => {
                if (await window.Notify.enable()) { e.currentTarget.replaceWith(el("span", { class: "muted", text: "Notifications are on" })); }
              } }),
            ])
          : null,
      ].filter(Boolean)),
      el("button", { class: "linkish church-remove", type: "button", text: "Remove from my churches", onclick: async () => {
        if (!confirm(`Remove ${church.name} from your churches? Your sermon notes stay.`)) return;
        try {
          await api(`/me/churches/${church.id}`, { method: "DELETE" });
          churches = null;
          location.hash = "church";
        } catch (err) {
          toast(err.message);
        }
      } }),
    );
  }

  // ---------------------------------------------------------------------
  // Adding and editing a church
  // ---------------------------------------------------------------------
  function zoneOptions(current) {
    const zones = (Intl.supportedValuesOf ? Intl.supportedValuesOf("timeZone") : [localZone]);
    const list = el("datalist", { id: "churchZones" }, zones.map((z) => el("option", { value: z })));
    return { list, value: current || localZone };
  }

  // The church form, used to review a draft from a link, to add by hand, and
  // to edit. `onSave` gets the cleaned values.
  function churchForm(initial, submitLabel, onSave) {
    const data = { gatherings: [], ...initial };
    const msg = cave().formMessage();
    const field = (label, input) => el("label", { class: "church-field" }, [el("span", { text: label }), input]);
    const name = el("input", { class: "field", required: true, maxlength: "120", value: data.name || "" });
    const city = el("input", { class: "field", maxlength: "120", value: data.city || "" });
    const zones = zoneOptions(data.time_zone);
    const zone = el("input", { class: "field", list: "churchZones", value: zones.value, autocomplete: "off", spellcheck: "false" });
    const website = el("input", { class: "field", type: "text", inputmode: "url", autocapitalize: "off", spellcheck: "false", placeholder: "https://", value: data.website || "" });
    const youtube = el("input", { class: "field", type: "text", inputmode: "url", autocapitalize: "off", spellcheck: "false", placeholder: "Channel link", value: data.youtube_url || "" });
    const podcast = el("input", { class: "field", type: "text", inputmode: "url", autocapitalize: "off", spellcheck: "false", placeholder: "Podcast feed or Apple Podcasts link", value: data.podcast_url || "" });

    const times = el("div", { class: "church-times" });
    const timeRow = (g = { label: "", day: 0, time: "10:00" }) => {
      const label = el("input", { class: "field", placeholder: "Sunday service", maxlength: "60", value: g.label || "", "aria-label": "What it is" });
      const day = el("select", { class: "field", "aria-label": "Day" }, DAY_NAMES.map((d, i) => el("option", { value: String(i), text: d, selected: i === g.day })));
      const time = el("input", { class: "field", type: "time", value: g.time, "aria-label": "Time", required: true });
      const row = el("div", { class: "church-time-row" }, [label, day, time,
        el("button", { class: "iconbtn", type: "button", "aria-label": "Remove this time", html: ICON.close, onclick: () => row.remove() })]);
      row.read = () => ({ label: label.value.trim(), day: +day.value, time: time.value });
      times.append(row);
    };
    (data.gatherings || []).forEach(timeRow);

    const found = [];
    if ((data.events || []).length) found.push(`${data.events.length} upcoming event${data.events.length === 1 ? "" : "s"}`);
    if ((data.notices || []).length) found.push(`${data.notices.length} notice${data.notices.length === 1 ? "" : "s"}`);

    const save = el("button", { class: "btn btn-ember", type: "submit", text: submitLabel });
    const form = el("form", { class: "church-form" }, [
      zones.list,
      field("Name", name),
      el("div", { class: "church-pair" }, [field("City", city), field("Time zone", zone)]),
      el("div", { class: "church-field" }, [
        el("span", { text: "Gatherings" }),
        times,
        el("button", { class: "act church-more-time", type: "button", html: `${ICON.plus}<span>Add a time</span>`, onclick: () => timeRow() }),
      ]),
      el("details", { class: "church-links-box", open: !!(data.youtube_url || data.podcast_url) }, [
        el("summary", { text: "Website, YouTube, podcast" }),
        field("Website", website), field("YouTube", youtube), field("Podcast", podcast),
      ]),
      found.length ? el("p", { class: "muted church-found", text: `Also found: ${found.join(" and ")}.` }) : null,
      msg.node,
      save,
    ]);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const tz = zone.value.trim();
      if (tz && !validZone(tz)) return msg.say("Pick a time zone from the list, like Africa/Lagos.", true);
      const values = {
        name: name.value.trim(),
        city: city.value.trim() || null,
        time_zone: tz || null,
        website: website.value.trim() || null,
        youtube_url: youtube.value.trim() || null,
        podcast_url: podcast.value.trim() || null,
        gatherings: [...times.children].map((r) => r.read()).filter((g) => g.time),
      };
      save.disabled = true;
      try {
        await onSave(values);
      } catch (err) {
        msg.say(err.message, true);
        save.disabled = false;
      }
    });
    return form;
  }

  function showAdd(mode = "link") {
    const pick = (key, label) => el("button", { type: "button", role: "tab", "aria-selected": String(mode === key), text: label, onclick: () => showAdd(key) });
    const body = el("div", { class: "church-add-body" });
    fill(
      backRow("#church", "Church"),
      el("h1", { class: "page-title church-add-title", text: "Add a church" }),
      el("div", { class: "tabs", role: "tablist", "aria-label": "How to add it" }, [pick("link", "Paste a link"), pick("manual", "Enter it myself")]),
      body,
    );
    if (mode === "manual") {
      body.append(el("div", { class: "card" }, churchForm({}, "Add to my churches", addChurch)));
      return;
    }
    const msg = cave().formMessage();
    const url = el("input", { class: "field", type: "text", inputmode: "url", autocapitalize: "off", spellcheck: "false", required: true, placeholder: "Website, YouTube channel or podcast", "aria-label": "Link" });
    const read = el("button", { class: "btn btn-ember", type: "submit", text: "Read it" });
    const form = el("form", { class: "card church-link-form" }, [url, msg.node, read]);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      read.disabled = true;
      read.textContent = "Reading the site...";
      try {
        const draft = await api(`/me/churches/read?today=${cave().localToday()}`, { method: "POST", body: { url: url.value.trim() } });
        body.replaceChildren(
          el("p", { class: "muted church-review-lede", text: "Here's what the site says. Correct anything that's off." }),
          el("div", { class: "card" }, churchForm(draft, "Add to my churches", (values) => addChurch({ ...draft, ...values }))),
        );
      } catch (err) {
        msg.say(err.message, true);
        read.disabled = false;
        read.textContent = "Read it";
      }
    });
    body.append(form);
    url.focus();
  }

  async function addChurch(values) {
    const church = await api("/me/churches", { method: "POST", body: values });
    churches = null;
    toast("Added to your churches.");
    location.hash = `church/c/${church.id}`;
  }

  function editSheet(church) {
    const sheet = el("div", { class: "sheet church-sheet", role: "dialog", "aria-modal": "true", "aria-label": `Edit ${church.name}` }, [
      el("div", { class: "church-sheet-head" }, [el("h3", { text: "Edit" }), el("button", { class: "iconbtn", type: "button", "aria-label": "Close", html: ICON.close, onclick: () => close() })]),
      churchForm(church, "Save", async (values) => {
        await api(`/me/churches/${church.id}`, { method: "PATCH", body: values });
        close();
        churches = null;
        showChurch(church.id);
      }),
    ]);
    const close = cave().overlay(sheet);
  }

  // ---------------------------------------------------------------------
  // Listen: sermons for how you feel, from the person's churches and from
  // Adullum's catalog of public sermon podcasts (app/listen.py). The season
  // and the source are two compact dropdowns on one line, and what Listen
  // is sits behind the info button, so the sermons get the room.
  // ---------------------------------------------------------------------
  const LISTEN_ABOUT = [
    "Sermons for how you feel, from your churches and from Adullum's catalog of public sermon podcasts across the Christian traditions.",
    "Adullum sorts each sermon into seasons with AI, so one can sit under more than one, and now and then one won't quite fit.",
  ];
  const CATALOG_ABOUT = "Chosen by Adullum from public sermon podcasts across the traditions and around the world: Catholic, Orthodox, Anglican, Presbyterian, Baptist and Pentecostal, from the UK, the US and Nigeria. Each is the preacher's or ministry's own feed.";
  // How many times a list still being sorted is looked at again, and how often.
  const LISTEN_RETRIES = 3;
  const LISTEN_RETRY_MS = 8000;

  let listenSource = "all";   // "all", "mine", "church:<id>", "catalog" or "catalog:<key>"
  let listenSources = null;   // { churches, catalog }, for the source dropdown
  let listenTimer = null;

  // The source dropdown: everywhere, then the person's churches, then the
  // catalog, each group with a way to choose all of it or one source.
  function sourceSelect(onPick) {
    const { churches = [], catalog = [] } = listenSources || {};
    const option = (value, text) => el("option", { value, text, selected: value === listenSource });
    const select = el("select", { class: "filter-select", "aria-label": "Where from" }, [
      option("all", "Everywhere"),
      churches.length ? el("optgroup", { label: "Your churches" }, [
        option("mine", "All your churches"),
        ...churches.map((c) => option(`church:${c.id}`, c.name)),
      ]) : null,
      el("optgroup", { label: "Adullum's catalog" }, [
        option("catalog", "The whole catalog"),
        ...catalog.map((c) => option(`catalog:${c.key}`, `${c.name} (${c.tradition})`)),
      ]),
    ].filter(Boolean));
    // A church removed since, or a source no longer offered, falls back to everywhere.
    if (select.value !== listenSource) listenSource = select.value = "all";
    select.addEventListener("change", () => onPick(select.value));
    return select;
  }

  async function showListen() {
    clearTimeout(listenTimer);
    const count = el("span", { class: "list-count" });
    const filters = el("div", { class: "church-listen-filters" });
    const list = el("div", { class: "church-listen-list" }, el("div", { class: "empty", text: "Finding sermons..." }));
    fill(
      head("listen"),
      el("div", { class: "church-listen-bar" }, [
        el("div", { class: "church-listen-count" }, [count, cave().info(LISTEN_ABOUT, { label: "About Listen" })]),
        filters,
      ]),
      list,
    );

    // The sources are read each time, so a church added or removed since shows
    // straight away, but alongside the sermons rather than before them.
    const sourcesReady = api("/me/listen/sources")
      .catch(() => listenSources || { churches: [], catalog: [] })
      .then((found) => { listenSources = found; });

    let tries = 0;
    async function load({ quietly = false } = {}) {
      clearTimeout(listenTimer);
      const asked = `${mood}|${listenSource}`;
      if (!quietly) {
        tries = 0;
        count.textContent = "";
        list.replaceChildren(el("div", { class: "empty", text: "Finding sermons..." }));
      }
      const query = new URLSearchParams({ source: listenSource });
      if (mood) query.set("mood", mood);
      let data;
      try {
        [data] = await Promise.all([api(`/me/listen?${query}`), sourcesReady]);
      } catch (err) {
        if (!quietly) list.replaceChildren(failed(err));
        return;
      }
      if (showing !== "listen" || asked !== `${mood}|${listenSource}`) return;
      drawList(data);
      // Sermons not yet sorted into seasons are sorted after the answer, so
      // look again a few times while the person is still here.
      if (data.pending && tries < LISTEN_RETRIES) {
        tries += 1;
        listenTimer = setTimeout(() => load({ quietly: true }), LISTEN_RETRY_MS);
      }
    }

    function drawList(data) {
      const total = data.mine.length + data.catalog.length;
      count.textContent = `${total} ${total === 1 ? "sermon" : "sermons"}`;
      const both = listenSource === "all";
      const wantsMine = both || listenSource === "mine" || listenSource.startsWith("church:");
      const wantsCatalog = both || listenSource.startsWith("catalog");
      const hasChurches = (listenSources.churches || []).length > 0;
      list.replaceChildren(...[
        wantsMine ? group(both ? "From your churches" : null, null, data.mine, hasChurches
          ? "Nothing for this in your churches' recent sermons yet."
          : el("p", { class: "church-listen-empty" }, ["Add your church to hear its sermons here too. ", el("a", { href: "#church/add", text: "Add a church" })])) : null,
        wantsCatalog ? group(both ? "From Adullum's catalog" : null, CATALOG_ABOUT, data.catalog, "Nothing for this in the catalog yet.") : null,
        data.pending ? el("p", { class: "church-listen-pending", text: "Still sorting some sermons into seasons. More will appear in a moment." }) : null,
      ].filter(Boolean));
    }

    // One group of sermons, under a small heading when both groups show.
    function group(title, about, items, empty) {
      let heading = null;
      if (title) {
        heading = el("h2", { class: "church-listen-head", text: title });
        if (about) heading = cave().titleInfo(heading, about);
      }
      const body = items.length
        ? el("div", { class: "card church-list" }, items.map((i) => sermonRow(i, { showChurch: true })))
        : typeof empty === "string" ? el("p", { class: "church-listen-empty", text: empty }) : empty;
      return el("section", { class: "church-listen-group fade-in" }, [heading, body]);
    }

    load();
    await sourcesReady;
    if (showing !== "listen") return;
    const before = listenSource;
    filters.replaceChildren(
      cave().filterSelect("How you feel", [["", "Any season"], ...MOODS], mood, (value) => { mood = value; load(); }),
      sourceSelect((value) => { listenSource = value; load(); }),
    );
    // A church removed since falls back to everywhere (sourceSelect); ask again for that.
    if (listenSource !== before) load();
  }

  // ---------------------------------------------------------------------
  // Sermon notes (web/sermons.js draws them)
  // ---------------------------------------------------------------------
  function showSermons() {
    const panel = el("div", { class: "church-sermons" });
    fill(
      head("sermons"),
      el("div", { class: "church-new-row" }, [
        el("button", { class: "btn btn-ghost btn-sm", type: "button", html: `${ICON.link}<span>From a link</span>`, onclick: () => fromLinkSheet({}) }),
        el("button", { class: "btn btn-ghost btn-sm", type: "button", html: `${ICON.plus}<span>Blank note</span>`, onclick: () => window.Sermons.newNote() }),
      ]),
      panel,
    );
    sermonsReady = window.Sermons.renderTab(panel);
    return sermonsReady;
  }

  // Opens the Sermons part of the tab, for web/sermons.js and the drafts here.
  async function openSermons() {
    if (showing !== "sermons" || !root) {
      sermonsReady = null;
      window.AdullumApp.go("church/sermons");
      for (let i = 0; i < 50 && !sermonsReady; i++) await new Promise((r) => setTimeout(r, 20));
    }
    await sermonsReady;
  }

  // Drafts a sermon note from a link and opens it.
  async function fromLinkSheet({ url = "", churchId = null }) {
    let mine = [];
    try {
      mine = await loadChurches();
    } catch { /* the church picker just stays empty */ }
    const msg = cave().formMessage();
    const input = el("input", { class: "field", type: "text", inputmode: "url", autocapitalize: "off", spellcheck: "false", required: true, placeholder: "YouTube or podcast link", value: url, "aria-label": "Sermon link" });
    const pick = el("select", { class: "field", "aria-label": "Church" }, [
      el("option", { value: "", text: "No church" }),
      ...mine.map((c) => el("option", { value: c.id, text: c.name, selected: c.id === churchId })),
    ]);
    const go = el("button", { class: "btn btn-ember btn-sm", type: "submit", text: "Draft my notes" });
    const steps = el("ol", { class: "church-steps", hidden: true }, ["Reading the captions", "Finding the passages", "Pulling out the main points", "Noting what to do this week"].map((t) => el("li", { text: t })));
    const form = el("form", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "fromLinkTitle" }, [
      el("h3", { id: "fromLinkTitle", text: "Notes from a sermon" }),
      el("p", { class: "sheet-lede", text: "Paste a link. Adullum drafts the note; you edit it." }),
      input,
      mine.length ? pick : null,
      steps,
      msg.node,
      el("div", { class: "sheet-actions" }, [el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Cancel", onclick: () => close() }), go]),
    ]);
    const close = cave().overlay(form);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      go.disabled = true;
      input.disabled = true;
      steps.hidden = false;
      let at = 0;
      const items = [...steps.children];
      items[0].classList.add("is-now");
      const ticker = setInterval(() => {
        if (at < items.length - 1) {
          items[at].classList.replace("is-now", "is-done");
          items[++at].classList.add("is-now");
        }
      }, 3500);
      try {
        const note = await api(`/me/sermons/from-link?today=${cave().localToday()}`, { method: "POST", body: { url: input.value.trim(), church_id: pick.value || null } });
        clearInterval(ticker);
        close();
        closePlayer();
        await openSermons();
        await window.Sermons.open(note.id);
        if (!note.from_transcript) toast("Drafted from the description, since the captions weren't available.");
      } catch (err) {
        clearInterval(ticker);
        steps.hidden = true;
        items.forEach((li) => li.classList.remove("is-now", "is-done"));
        msg.say(err.message, true);
        go.disabled = false;
        input.disabled = false;
      }
    });
    input.focus();
  }

  // ---------------------------------------------------------------------
  // Watching live, with notes beside it
  // ---------------------------------------------------------------------
  async function showLive(id) {
    closePlayer();
    fill(el("div", { class: "empty", text: "Opening..." }));
    let church;
    try {
      [church] = await Promise.all([api(`/me/churches/${id}`), loadLive()]);
    } catch (err) {
      fill(backRow("#church", "Church"), failed(err));
      return;
    }
    const stream = liveFor(church.id);
    if (!stream) {
      fill(backRow(`#church/c/${church.id}`, church.name), el("div", { class: "empty" }, [el("strong", { text: "Not live right now" }), "Their latest sermons are on their page."]));
      return;
    }
    const draftKey = `adullumLiveNote:${stream.video_id}`;
    let saved = "";
    try { saved = localStorage.getItem(draftKey) || ""; } catch { /* storage may be blocked */ }
    const notes = el("textarea", { class: "field church-live-notes", placeholder: "Write what you're hearing. Start a line with - for a bullet.", "aria-label": "Your notes" });
    notes.value = saved;
    notes.addEventListener("input", () => {
      try { localStorage.setItem(draftKey, notes.value); } catch { /* fine without it */ }
    });
    const mark = el("button", { class: "btn btn-ghost btn-sm", type: "button", html: `${ICON.mark}<span>Mark this moment</span>`, onclick: () => {
      const stamp = new Date().toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
      const before = notes.value && !notes.value.endsWith("\n") ? "\n" : "";
      notes.value += `${before}• ${stamp} `;
      notes.dispatchEvent(new Event("input"));
      notes.focus();
    } });
    const save = el("button", { class: "btn btn-ember btn-sm", type: "button", text: "Save to Sermons" });
    save.onclick = async () => {
      save.disabled = true;
      try {
        const note = await api("/me/sermons", { method: "POST", body: {
          title: `${church.name}, ${new Date().toLocaleDateString(undefined, { month: "short", day: "numeric" })}`,
          church: church.name,
          preached_on: cave().localToday(),
          blocks: [
            { id: Math.random().toString(36).slice(2, 12), type: "text", text: notes.value.trim() },
            { id: Math.random().toString(36).slice(2, 12), type: "link", url: `https://www.youtube.com/watch?v=${stream.video_id}`, label: "Watch again" },
          ],
        } });
        try { localStorage.removeItem(draftKey); } catch { /* fine */ }
        await openSermons();
        await window.Sermons.open(note.id);
      } catch (err) {
        toast(err.message);
        save.disabled = false;
      }
    };
    fill(
      backRow(`#church/c/${church.id}`, church.name),
      el("div", { class: "church-live" }, [
        el("div", { class: "church-live-video" }, el("iframe", {
          src: `https://www.youtube-nocookie.com/embed/${stream.video_id}?autoplay=1&rel=0&modestbranding=1`,
          title: `${church.name}, live`, allow: "autoplay; encrypted-media; picture-in-picture; fullscreen", allowfullscreen: true,
          referrerpolicy: "strict-origin-when-cross-origin",
        })),
        el("section", { class: "card church-live-side" }, [
          el("div", { class: "church-live-head" }, [liveBadge(), el("strong", { text: church.name })]),
          notes,
          el("div", { class: "church-live-actions" }, [mark, save]),
          el("p", { class: "muted church-live-hint", text: "Passages you write are linked to your Bible once it's saved." }),
        ]),
      ]),
    );
  }

  // ---------------------------------------------------------------------
  // The week after a sermon
  // ---------------------------------------------------------------------
  async function showWeek(id) {
    fill(el("div", { class: "empty", text: "Opening..." }));
    let week;
    try {
      week = await api(`/me/sermons/${id}/week`);
    } catch (err) {
      fill(backRow("#church", "Church"), failed(err));
      return;
    }
    const bars = el("span", { class: "church-bars" });
    const count = el("span");
    const paint = () => {
      bars.replaceChildren(...week.steps.map((s) => el("span", { class: s.done ? "is-done" : null })));
      count.textContent = `${week.steps.filter((s) => s.done).length} of ${week.steps.length}`;
    };
    paint();
    const preached = week.preached_on ? new Date(`${week.preached_on}T12:00:00`) : new Date();
    const today = cave().localToday();
    let openKey = (week.steps.find((s) => !s.done) || week.steps[0]).key;
    const list = el("div", { class: "church-steps-list" });

    const send = async (body) => {
      try {
        week = { ...week, ...(await api(`/me/sermons/${week.id}/week`, { method: "POST", body })) };
      } catch (err) {
        toast(err.message);
      }
    };
    const action = (step) => {
      if (step.key === "reread") return el("a", { class: "btn btn-ghost btn-sm", href: window.Reader.href(step.ref), text: `Open ${step.ref}` });
      if (step.key === "learn") return el("button", { class: "btn btn-ghost btn-sm", type: "button", text: `Save ${step.ref}`, onclick: async (e) => {
        const button = e.currentTarget;
        button.disabled = true;
        if (!(await window.Saved.verse(step.ref, translation()))) button.disabled = false;
      } });
      if (step.key === "question") {
        const box = el("textarea", { class: "field", rows: "3", maxlength: "2000", placeholder: "A line or two is enough.", "aria-label": "Your answer" });
        box.value = step.answer || "";
        box.addEventListener("change", () => send({ answer: box.value }));
        return box;
      }
      if (step.key === "pray") return el("a", { class: "btn btn-ghost btn-sm", href: "#prayers", text: "Open your prayers" });
      return null;
    };
    const draw = () => {
      list.replaceChildren(...week.steps.map((step) => {
        const day = new Date(preached);
        day.setDate(day.getDate() + step.offset);
        const isToday = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}` === today;
        const toggle = el("button", {
          class: `church-step-check${step.done ? " is-done" : ""}`, type: "button", "aria-pressed": String(step.done),
          "aria-label": step.done ? `Mark ${step.title} as not done` : `Mark ${step.title} as done`, html: ICON.check,
          onclick: async () => {
            step.done = !step.done;
            draw();
            paint();
            await send({ step: step.key, done: step.done });
            paint();
          },
        });
        const isOpen = openKey === step.key;
        const text = step.key === "reread" || step.key === "learn" ? step.ref : step.key === "pray" ? `Pray what you heard${step.ref ? ` from ${step.ref}` : ""} over someone who needs it.` : step.text;
        return el("div", { class: `church-step${isOpen ? " is-open" : ""}` }, [
          el("div", { class: "church-step-row" }, [
            toggle,
            el("button", { class: "church-step-title", type: "button", "aria-expanded": String(isOpen), onclick: () => { openKey = isOpen ? null : step.key; draw(); } }, [
              el("small", { class: isToday ? "is-today" : null, text: `${DAY_NAMES[day.getDay()]}${isToday ? " · today" : ""}` }),
              el("strong", { text: step.title }),
            ]),
          ]),
          isOpen ? el("div", { class: "church-step-body" }, [el("p", { text }), action(step)]) : null,
        ]);
      }));
    };
    draw();
    fill(
      backRow("#church", "Church"),
      el("section", { class: "church-week-head card warm" }, [
        el("small", { text: [week.church, shortDate(week.preached_on)].filter(Boolean).join(" · ") }),
        el("h1", { class: "church-name", text: week.title || "Sunday's sermon" }),
        week.passage_ref ? el("span", { class: "verse-ref", text: week.passage_ref }) : null,
        bars,
        count,
      ]),
      list,
    );
  }

  // ---------------------------------------------------------------------
  // Home: a card while one of the person's churches is live, and nothing
  // otherwise (web/cave.js::showHome puts it first)
  // ---------------------------------------------------------------------
  async function homeLive() {
    await loadLive();
    const showing = live.filter((l) => l.alerts !== false);
    if (!showing.length) return null;
    const first = showing[0];
    const more = showing.length - 1;
    return cave().homeNote({
      href: `#church/live/${first.church_id}`, icon: ICON.play, live: true,
      title: more ? `${first.name} and ${more} more are live` : `${first.name} is live`,
      detail: "Watch and take notes",
    });
  }

  // ---------------------------------------------------------------------
  // Called by index.html's router
  // ---------------------------------------------------------------------
  function show(param) {
    root = $("#churchPage");
    if (!root) return;
    const [part, id] = (param || "").split("/");
    const next = part === "c" || part === "live" || part === "week" ? `${part}/${id}` : part;
    if (showing === "sermons" && next !== "sermons") window.Sermons.hide();
    showing = next;
    if (part !== "listen" && part !== "c") closePlayer();
    if (part === "sermons") return showSermons();
    if (part === "listen") return showListen();
    if (part === "add") return showAdd();
    if (part === "c" && id) return showChurch(id);
    if (part === "live" && id) return showLive(id);
    if (part === "week" && id) return showWeek(id);
    return showChurches();
  }

  function hide() {
    clearTimeout(listenTimer);
    if (showing === "sermons") window.Sermons.hide();
    showing = "";
    closePlayer();
  }

  window.Church = { show, hide, homeLive, openSermons, nextAt };
})();
