// Welcome: a short walk through the five tabs for a new account.
// It opens once over the home screen (cave.js::showHome calls maybeShow) and
// takes a step per tab in the nav's own order, lighting that tab in the top
// bar (the tab bar on a phone) as it goes. Each step pairs a small drawing of
// the tab with numbered notes on what's in it. The last step, "Make it yours",
// picks the translation and theme and brings chosen places to the front of
// the home's start list (cave.js::startCard).
//
// Seen or skipped is kept on the profile (profiles.welcomed_at, through
// PATCH /me) and on this device, so it never opens twice. "Take the tour
// again" in Settings and under the start list opens it whenever wanted.
// No verse text appears here: examples are references and made-up names.
//
// Loaded after web/cave.js, whose helpers it borrows through window.Cave.
(function () {
  const cave = () => window.Cave;
  const SEEN = "adullumWelcomed"; // this device has seen the tour
  const FIRST = "adullumStartFirst"; // start-list places picked in the last step
  const NEW_DAYS = 7; // only an account this new is welcomed (before the migration runs)

  const svg = (d, w = 1.8) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
  const ICON = {
    chat: svg('<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/>', 1.9),
    book: svg('<path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M4 21V5M9 7h6"/>'),
    plan: svg('<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M8 3v4M16 3v4M4 10h16M9 14l2 2 4-4"/>'),
    heart: svg('<path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/>'),
    refuge: svg('<path d="M3 20h18M5 20V11a7 7 0 0 1 14 0v9M10 20v-5a2 2 0 0 1 4 0v5"/>'),
    church: svg('<path d="M12 2v4M10 4h4M6 21V11l6-5 6 5v10M3 21h18M10 21v-4h4v4"/>'),
    speak: svg('<path d="M11 5L6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/>'),
    pen: svg('<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16z"/>'),
    still: svg('<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3.5"/>'),
    pebbles: svg('<ellipse cx="8" cy="16" rx="4.5" ry="3"/><ellipse cx="16.5" cy="10" rx="3.5" ry="2.5"/>'),
    links: svg('<circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="8" r="2.5"/><circle cx="10" cy="18" r="2.5"/><path d="M8.3 7l7.3.7M7 8.3l2.2 7.4M16.4 10l-4.8 6"/>'),
    save: svg('<path d="M6 3h12v18l-6-4-6 4z"/>'),
    share: svg('<path d="M12 3v12M7 8l5-5 5 5"/><path d="M5 13v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6"/>'),
    lock: svg('<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>', 2),
    person: svg('<circle cx="12" cy="8" r="3.5"/><path d="M5 20a7 7 0 0 1 14 0"/>', 2),
    check: svg('<path d="M5 12.5l4.5 4.5L19 7.5"/>', 2.4),
    back: svg('<path d="M15 6l-6 6 6 6"/>', 1.9),
    next: svg('<path d="M9 6l6 6-6 6"/>', 1.9),
    arch: '<svg viewBox="0 0 132 110" fill="none" aria-hidden="true"><path d="M6 106C6 52 32 8 66 8s60 44 60 98" stroke="currentColor" stroke-width="10" stroke-linecap="round"/><path d="M44 106c0-22 10-38 22-38s22 16 22 38" stroke="currentColor" stroke-width="10" stroke-linecap="round"/></svg>',
  };

  // The five tabs, in the nav's order, with the tab bar's icons (index.html).
  const TABS = [
    { key: "home", name: "Home", says: "Your day", icon: svg('<path d="M4 21V10.5L12 4l8 6.5V21"/><path d="M10 21v-6h4v6"/>', 1.9) },
    { key: "cave", name: "Cave", says: "Private rooms", icon: svg('<path d="M3 21C3 11 7 4 12 4s9 7 9 17"/><path d="M9 21c0-3.5 1.3-6 3-6s3 2.5 3 6"/>', 1.9) },
    { key: "aquila", name: "Aquila", says: "Ask anything", icon: ICON.chat },
    { key: "bible", name: "Bible", says: "Read and keep", icon: svg('<path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M4 21V5M9 7h6"/>', 1.9) },
    { key: "church", name: "Church", says: "Sermons, live", icon: svg('<path d="M12 2.5v5M10 4.5h4"/><path d="M5 21V11.5l7-4.5 7 4.5V21"/><path d="M10 21v-4a2 2 0 0 1 4 0v4"/>', 1.9) },
  ];

  // Each answer to "What brings you here?" and the start-list places it brings forward.
  const WANTS = [
    { key: "study", name: "Understand the Bible better", icon: ICON.chat, places: ["ask", "plan"] },
    { key: "daily", name: "Read every day", icon: ICON.book, places: ["plan", "bible"] },
    { key: "pray", name: "Pray more steadily", icon: ICON.heart, places: ["pray"] },
    { key: "rest", name: "A quiet place for a hard season", icon: ICON.refuge, places: ["refuge"] },
    { key: "church", name: "Keep up with my church", icon: ICON.church, places: ["church"] },
  ];
  const LOOKS = { dawn: "Dawn", lily: "Lily", olive: "Olive Grove", twilight: "Twilight", hearth: "Hearth" };

  // Small helpers for the drawings: a numbered ring, a line of placeholder text.
  const mark = (n) => `<span class="wl-mark">${n}</span>`;
  const bars = (...widths) => `<span class="wl-bars">${widths.map((w) => `<i style="width:${w}%"></i>`).join("")}</span>`;
  const parts = (items) => `<ol class="wl-parts">${items.map(([b, t], i) => `<li><span class="wl-num">${i + 1}</span><span><b>${b}</b> ${t}</span></li>`).join("")}</ol>`;
  const tip = (icon, text, privacy = false) => `<p class="wl-tip${privacy ? " is-private" : ""}">${icon}<span>${text}</span></p>`;
  const kicker = (key) => {
    const t = TABS.find((x) => x.key === key);
    return `<span class="wl-kicker">${t.icon}${t.name} tab</span>`;
  };

  // One step per tab. `art` is the small drawing, `copy` the words beside it.
  const STEPS = [
    {
      art: `<div class="wl-device">
          <div class="wl-device-bar"><span class="wl-device-logo">${ICON.arch}Adullam</span><span class="wl-device-me" data-initial></span></div>
          <div class="wl-device-body">
            <div class="wl-mini-hero"><span class="wl-sub" data-today></span><strong data-greeting></strong><span class="wl-mini-ask">Ask Aquila anything<i></i></span></div>
            <div class="wl-mini"><span class="wl-sub">Verse for today · Psalm 23:1</span>${bars(92, 58)}</div>
            <div class="wl-row2">
              <div class="wl-mini"><span class="wl-line">${ICON.heart}Amens</span><span class="wl-sub">3 to pray for</span></div>
              <div class="wl-mini"><span class="wl-line">${ICON.speak}Declare</span><span class="wl-sub">Words for today</span></div>
            </div>
          </div>
          <div class="wl-device-tabs">${TABS.map((t) => `<span>${t.icon}${t.name}</span>`).join("")}</div>
        </div>`,
      copy: `<span class="wl-kicker">Welcome</span>
        <h2 data-welcome-title></h2>
        <p class="wl-lead">Adullam is a quiet place to study Scripture, pray and rest. Everything lives in five tabs. Here's a quick walk through each, about a minute in all.</p>
        <div class="wl-tabmap">${TABS.map((t) => `<button type="button" data-jump="${t.key}">${t.icon}<span>${t.name}</span><small>${t.says}</small></button>`).join("")}</div>`,
      welcome: true,
    },
    {
      tab: "home",
      art: `<div class="wl-mini-hero">${mark(1)}<strong>Good evening</strong><span class="wl-mini-ask">Ask Aquila anything<i></i></span></div>
        <div class="wl-mini">${mark(2)}<span class="wl-sub">Verse for today</span>${bars(92, 60)}</div>
        <div class="wl-mini">${mark(3)}<span class="wl-title">Today</span>
          <span class="wl-ticks"><span class="done">Read John 4</span><span>Pray for Mum's recovery</span><span>Walk and pray · 2 of 3 this week</span></span></div>
        <div class="wl-row2">
          <div class="wl-mini">${mark(4)}<span class="wl-line">${ICON.heart}3 waiting for your amen</span></div>
          <div class="wl-mini"><span class="wl-line">${ICON.speak}Declare</span></div>
        </div>`,
      copy: `${kicker("home")}<h2>Your day, at a glance</h2>
        <p class="wl-lead">Home is where you land each time. It gathers what's yours for today.</p>
        ${parts([
          ["The ask box.", "Type a question and Aquila answers it in her tab."],
          ["Verse for today.", 'Sit with it, or save it from the "⋯" beside it.'],
          ["Today.", "Your plan's reading, a prayer to pray and your habits, each a tick."],
          ["Amens and Declare.", "Prayers others asked for, and words for what you're facing."],
        ])}
        ${tip(ICON.person, "Your initials at the top right open the menu, with Settings, your theme and Support.")}`,
    },
    {
      tab: "cave",
      art: `<div class="wl-seg"><span class="on">Refuge${mark(1)}</span><span>Journal${mark(2)}</span><span>Prayers${mark(3)}</span></div>
        <div class="wl-tiles">
          <div class="wl-tile wide"><span class="wl-tile-icon">${ICON.chat}</span>Talk with Aquila</div>
          <div class="wl-tile"><span class="wl-tile-icon">${ICON.pen}</span>Write it out</div>
          <div class="wl-tile"><span class="wl-tile-icon">${ICON.still}</span>Be still</div>
          <div class="wl-tile"><span class="wl-tile-icon">${ICON.pebbles}</span>Pebbles</div>
          <div class="wl-tile">${mark(4)}<span class="wl-tile-icon">${ICON.heart}</span>Amens</div>
        </div>`,
      copy: `${kicker("cave")}<h2>Your private place</h2>
        <p class="wl-lead">The cave has three tabs of its own across the top.</p>
        ${parts([
          ["Refuge.", "Talk things through with Aquila, write it out, be still, or set small goals in Pebbles."],
          ["Journal.", "Write and tag entries, and look back on a month or a year with a reflection."],
          ["Prayers.", "Your prayer list, the days you prayed and any fast. Declare is in its New menu."],
          ["Amens.", "Inside Refuge. Ask for prayer without your name, and pray for others."],
        ])}
        ${tip(ICON.lock, "Your cave is private. Your journal and prayer list are for you alone, and a Refuge talk is gone when you leave unless you keep it.", true)}`,
    },
    {
      tab: "aquila",
      art: `<div class="wl-chat">
          <div class="wl-rail">${mark(1)}<b>Today</b><span class="on">Feet washing</span><span>Ruth and Naomi</span><b>This week</b><span>Psalm 23</span></div>
          <div class="wl-chat-main">
            <div class="wl-bubble">Why did Jesus wash the disciples' feet?</div>
            <div class="wl-mini">${mark(2)}<h4>The passage</h4>${bars(95, 70)}<h4>Context</h4>${bars(88)}<h4>To think about</h4>${bars(80)}</div>
            <div class="wl-mini">${mark(3)}<span class="wl-refs"><span>John 13:1-17</span><span>Luke 22:24-27</span></span>
              <span class="wl-icons">${ICON.book}${ICON.links}${ICON.save}${ICON.speak}${ICON.share}</span></div>
            <div class="wl-mini">${mark(4)}<span class="wl-sub">Keep going</span>${bars(75)}</div>
          </div>
        </div>`,
      copy: `${kicker("aquila")}<h2>Ask anything about the Bible</h2>
        <p class="wl-lead">Aquila answers from Scripture, with chapter and verse for what she says.</p>
        ${parts([
          ["Conversations.", "Every past talk, kept down the side to reopen, rename or delete. On a phone, tap Conversations."],
          ["The answer.", "Drawn from the Bible itself: what the passage says, its context, then things to think about. Nothing is made up, and nothing is stated as fact unless Scripture says it."],
          ["Under each answer.", "Tap a reference, or open the Bible, Connections, Save, Listen or Share."],
          ["Keep going.", "Two questions to follow on with."],
        ])}
        ${tip(ICON.chat, 'Ask in your own words, like "What was happening when Paul wrote Philippians?"')}`,
    },
    {
      tab: "bible",
      art: `<div class="wl-doors">
          <div class="wl-door">${mark(1)}${ICON.book}<strong>Bible</strong><small>Carry on at John 4</small></div>
          <div class="wl-door">${mark(2)}${ICON.plan}<strong>Reading plans</strong><small>1 to read today</small></div>
          <div class="wl-door">${mark(3)}${ICON.pen}<strong>My notes</strong><small>12 notes and highlights</small></div>
          <div class="wl-door">${mark(4)}${ICON.links}<strong>Connections</strong><small>Where a verse leads</small></div>
        </div>
        <div class="wl-verse-bar"><span>Highlight</span><span>Note</span><span>Save</span><span>Connections</span></div>`,
      copy: `${kicker("bible")}<h2>Read, and keep what speaks to you</h2>
        <p class="wl-lead">The Bible tab opens on its front page, with a door to each part.</p>
        ${parts([
          ["Bible.", "Public-domain translations, opening where you left off."],
          ["Reading plans.", "Follow one, or shape your own with Aquila."],
          ["My notes.", "Your notes and highlights, beside the verse in any translation."],
          ["Connections.", "Pick a verse and see the passages linked to it, by meaning and by classic cross-references. Tap a line to hear why they connect."],
        ])}
        ${tip(ICON.links, "Tap any verse to highlight it, write a note or save it. Saved keeps verses and Aquila's answers in one place.")}`,
    },
    {
      tab: "church",
      art: `<div class="wl-seg"><span>Churches</span><span class="on">Sermons</span><span>Listen</span></div>
        <div class="wl-mini is-warm">${mark(1)}<span class="wl-title">Hope that holds</span>
          <span class="wl-sub">Riverside Chapel · Pastor Ade · November 9</span>
          <h4>Held, not handled</h4>
          <span class="wl-ticks is-bullets"><span>God works in all of it</span><span>Nothing can separate us</span></span>
          <span class="wl-verse-block"><span>Romans 8:28-39</span><i></i><i style="width:70%"></i></span>
          <span class="wl-ticks"><span>Call Dad this week</span></span></div>
        <div class="wl-mini">${mark(2)}<span class="wl-sub">This week, from Sunday's sermon</span><span class="wl-ticks"><span class="done">Reread Romans 8</span><span>Carry a verse</span></span></div>
        <div class="wl-row2">
          <div class="wl-mini">${mark(3)}<span class="wl-church"><span class="wl-church-mark">${ICON.church}</span><span><strong>Riverside</strong><small>Sun 10:00</small></span><span class="wl-live">Live</span></span></div>
          <div class="wl-mini">${mark(4)}<span class="wl-church"><span class="wl-church-mark">${ICON.speak}</span><span><strong>Listen</strong><small>For the weary</small></span></span></div>
        </div>`,
      copy: `${kicker("church")}<h2>Your sermons in one place</h2>
        <p class="wl-lead">Faith isn't meant to be lived alone. At church you hear the Word preached and worship with others, and a sermon often says what you needed that week. This tab helps you keep it, and carry it past Sunday.</p>
        ${parts([
          ["Sermon notes.", "Take notes as you listen, with headings, verses, photos and to-dos, or draft them from the video."],
          ["This week.", "Small steps to carry Sunday's sermon through the days after."],
          ["Your churches.", "Paste your church's website for its times, its news, and a ping when it goes live."],
          ["Listen.", "Sermons from your churches and trusted podcasts, picked by how you're feeling."],
        ])}
        ${tip(ICON.lock, "The churches you add are kept for you alone, with no following and no directory.", true)}`,
    },
    {
      wide: true,
      copy: `<span class="wl-kicker">${ICON.check}Last step</span><h2>Make it yours</h2>
        <p class="wl-lead">Pick what fits and your home will start there. You can change any of this later in Settings.</p>`,
      form: true,
    },
  ];

  // ---------------------------------------------------------------------
  // Remembering it, on the device and on the profile
  // ---------------------------------------------------------------------
  function readLocal(key, fallback) {
    try {
      return JSON.parse(localStorage.getItem(key)) ?? fallback;
    } catch {
      return fallback;
    }
  }
  function writeLocal(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* a private window: the profile still remembers */
    }
  }

  // Kept per account, so a second person on a shared phone is still welcomed.
  const seenKey = () => `${SEEN}:${cave().account().id || ""}`;

  function markSeen() {
    writeLocal(seenKey(), true);
    if (cave().signedIn()) cave().api("/me", { method: "PATCH", body: { welcomed: true } }).catch(() => {});
  }

  // A new account that hasn't seen it, on the profile (profile.welcomed from
  // /me/home) or on this device. Before the migration welcomed is null, so
  // only an account made in the last week is welcomed then.
  function shouldShow(profile) {
    if (!profile || node || !cave().signedIn()) return false;
    if (profile.welcomed === true || readLocal(seenKey(), false)) return false;
    const joined = Date.parse(profile.joined || "");
    return profile.welcomed === false || Number.isNaN(joined) || Date.now() - joined < NEW_DAYS * 864e5;
  }

  // The start-list places picked in the last step, in the order they were brought forward.
  function startFirst() {
    const first = readLocal(FIRST, []);
    return Array.isArray(first) ? first : [];
  }

  // ---------------------------------------------------------------------
  // The tour
  // ---------------------------------------------------------------------
  let node = null; // the open tour, or null
  let step = 0;
  let picked = new Set();
  let returnFocus = null;

  const $ = (sel) => node.querySelector(sel);
  const $$ = (sel) => [...node.querySelectorAll(sel)];
  const navLinks = () => [...document.querySelectorAll("#topbar [data-nav], #tabbar [data-nav]")];
  const stepOf = (key) => STEPS.findIndex((s) => s.tab === key);

  function partOfDay() {
    const h = new Date().getHours();
    return h < 12 ? "morning" : h < 17 ? "afternoon" : "evening";
  }

  function panel(s, i) {
    const art = s.art ? `<div class="wl-art${s.welcome ? " is-welcome" : ""}" aria-hidden="true">${s.art}</div>` : "";
    return `<div class="wl-panel${s.wide ? " is-wide" : ""}" data-step="${i}" hidden>${art}<div class="wl-copy">${s.copy}</div>${s.form ? formHtml() : ""}</div>`;
  }

  // "Make it yours": what brings them here, the translation and the look.
  function formHtml() {
    return `<div class="wl-form">
      <div class="wl-field">
        <span class="wl-label" id="wlWants">What brings you here? <span class="wl-hint">Pick any</span></span>
        <div class="wl-wants" role="group" aria-labelledby="wlWants">${WANTS.map((w) =>
          `<button type="button" class="wl-want" data-want="${w.key}" aria-pressed="false"><span class="wl-want-icon">${w.icon}</span><span>${w.name}</span></button>`).join("")}</div>
      </div>
      <div class="wl-field">
        <label class="wl-field" data-translation-field><span class="wl-label">Read the Bible in</span><select class="field" data-welcome-translation></select></label>
        <div class="wl-field"><span class="wl-label" id="wlLooks">Choose a look</span>
          <div class="wl-looks" role="group" aria-labelledby="wlLooks">${Object.entries(LOOKS).map(([key, name]) =>
            `<button type="button" class="theme-option" data-set-theme="${key}" aria-pressed="false"><span class="swatch" data-swatch="${key}" aria-hidden="true"></span>${name}</button>`).join("")}</div>
        </div>
      </div>
    </div>`;
  }

  function build(name) {
    node = document.createElement("div");
    node.className = "welcome";
    node.innerHTML = `<section class="wl-card" role="dialog" aria-labelledby="wlTitle">
        <div class="wl-top"><div class="wl-steps" role="group" aria-label="Steps">${STEPS.map((_, i) =>
          `<button type="button" class="wl-dot" data-go="${i}" aria-label="Step ${i + 1}"></button>`).join("")}<span class="wl-count"></span></div>
          <button type="button" class="wl-skip" data-skip>Skip for now</button></div>
        ${STEPS.map(panel).join("")}
        <div class="wl-foot">
          <button type="button" class="btn btn-ghost" data-back>${ICON.back}Back</button>
          <span class="wl-keys">Arrow keys move, or tap a tab</span>
          <button type="button" class="btn btn-ember" data-next><span></span>${ICON.next}</button>
        </div>
      </section>`;

    // The person's own name and day on the welcome step.
    const title = $("[data-welcome-title]");
    title.id = "wlTitle";
    title.textContent = name ? `Welcome to Adullam, ${name}.` : "Welcome to Adullam.";
    $("[data-greeting]").textContent = `Good ${partOfDay()}${name ? `, ${name}` : ""}`;
    $("[data-initial]").textContent = (name || "A")[0].toUpperCase();
    $("[data-today]").textContent = new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });

    // Only the translations this server has loaded, as Settings lists them.
    const settings = document.getElementById("settingsTranslation");
    const select = $("[data-welcome-translation]");
    const options = settings ? [...settings.options] : [];
    if (options.length < 2) $("[data-translation-field]").hidden = true;
    select.replaceChildren(...options.map((o) => new Option(o.textContent, o.value)));
    select.value = window.Reader ? window.Reader.translation() : "BSB";
    select.addEventListener("change", () => window.Reader && window.Reader.setTranslation(select.value));

    const theme = document.documentElement.dataset.theme;
    $$("[data-set-theme]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.setTheme === theme)));

    node.addEventListener("click", (e) => {
      const t = e.target.closest("button");
      if (!t) return;
      if (t.dataset.go) go(+t.dataset.go);
      else if (t.dataset.jump) go(stepOf(t.dataset.jump));
      else if (t.hasAttribute("data-skip")) finish({ skipped: true });
      else if (t.hasAttribute("data-back")) go(step - 1);
      else if (t.hasAttribute("data-next")) step === STEPS.length - 1 ? finish() : go(step + 1);
      else if (t.dataset.want) {
        const on = !picked.has(t.dataset.want);
        on ? picked.add(t.dataset.want) : picked.delete(t.dataset.want);
        t.setAttribute("aria-pressed", String(on));
        t.firstChild.innerHTML = on ? ICON.check : WANTS.find((w) => w.key === t.dataset.want).icon;
      }
    });
  }

  function go(i) {
    step = Math.max(0, Math.min(STEPS.length - 1, i));
    $$("[data-step]").forEach((p) => { p.hidden = +p.dataset.step !== step; });
    $$(".wl-dot").forEach((d, n) => {
      d.classList.toggle("is-past", n < step);
      if (n === step) d.setAttribute("aria-current", "step");
      else d.removeAttribute("aria-current");
    });
    $(".wl-count").textContent = `${step + 1} of ${STEPS.length}`;
    $("[data-back]").hidden = step === 0;
    const upcoming = STEPS[step + 1] && TABS.find((t) => t.key === STEPS[step + 1].tab);
    $("[data-next] span").textContent = step === 0 ? "Show me around" : step === STEPS.length - 1 ? "Take me home" : upcoming ? `Next: ${upcoming.name}` : "Next: Make it yours";
    const tab = STEPS[step].tab;
    navLinks().forEach((a) => a.classList.toggle("is-lit", a.dataset.nav === tab));
    node.querySelector(".wl-card").scrollTop = 0;
    node.scrollTop = 0;
  }

  // While it's open the top bar and the tab bar belong to it: a tab jumps
  // to its step, and nothing else there leads away.
  function onBarClick(e) {
    if (!e.target.closest("#topbar, #tabbar")) return;
    e.preventDefault();
    e.stopPropagation();
    const link = e.target.closest("[data-nav]");
    if (link && stepOf(link.dataset.nav) >= 0) go(stepOf(link.dataset.nav));
  }

  function onKey(e) {
    if (e.target.closest("input, select, textarea")) return;
    if (e.key === "ArrowRight") go(step + 1);
    else if (e.key === "ArrowLeft") go(step - 1);
    else if (e.key === "Escape") finish({ skipped: true });
  }

  // Leaving by any other way (Back in the browser, a link) counts as seen.
  function onRoute() {
    finish({ skipped: true, quiet: true });
  }

  function open({ name = cave().displayName() } = {}) {
    if (node) return;
    returnFocus = document.activeElement;
    picked = new Set();
    build(name);
    document.body.append(node);
    document.body.classList.add("is-welcoming");
    document.addEventListener("click", onBarClick, true);
    document.addEventListener("keydown", onKey);
    window.addEventListener("hashchange", onRoute);
    go(0);
    $("[data-next]").focus({ preventScroll: true });
  }

  function finish({ skipped = false, quiet = false } = {}) {
    if (!node) return;
    markSeen();
    // Picks bring their places to the front of the start list; skipping keeps the last ones.
    if (!skipped && picked.size) {
      const first = [];
      WANTS.filter((w) => picked.has(w.key)).forEach((w) => w.places.forEach((p) => first.includes(p) || first.push(p)));
      writeLocal(FIRST, first);
    }
    document.removeEventListener("click", onBarClick, true);
    document.removeEventListener("keydown", onKey);
    window.removeEventListener("hashchange", onRoute);
    document.body.classList.remove("is-welcoming");
    navLinks().forEach((a) => a.classList.remove("is-lit"));
    node.remove();
    node = null;
    if (quiet) return;
    cave().redrawStart();
    if (skipped) cave().toast("The tour is in Settings whenever you want it.", { tone: "info" });
    if (returnFocus && returnFocus.isConnected) returnFocus.focus({ preventScroll: true });
  }

  function maybeShow(profile) {
    if (shouldShow(profile)) open({ name: profile.display_name || "" });
  }

  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-welcome-tour]")) open();
  });

  window.Welcome = { maybeShow, open, startFirst };
})();
