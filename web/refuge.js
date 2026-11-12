// Refuge: the quiet room in the cave, for every kind of season. The cave's
// Refuge tab, its five rooms, and the admin desk.
//
// The rooms are drawn in place inside the tab rather than given their own
// hash routes, so Refuge is one history entry and Back never leads from one
// room into another. What each room keeps:
//   Write it out    nothing, unless "Keep it" is pressed (app/refuge.py)
//   Talk with Aquila  nothing, unless "Keep this talk" is pressed; otherwise
//                   the talk lives only in `talk` below and vanishes on leaving
//   Pebbles         goals and habits (app/refuge.py seeds); praying and
//                   fasting are tracked on the prayer list (web/prayers.js)
//   Be still        nothing on the server; choices and this week's count
//                   stay on the device
//   Amens           posts, amens and kind words (app/one_another.py)
// Nothing anyone writes, talks through or shares here appears on the home
// screen or in Aquila's memory. Home shows only the person's own active
// habits (web/cave.js::todayCard) and, through homeCard below,
// the wall's public side: this week's amens and how many posts wait for theirs.
// #amens and #pebbles open the cave straight into that room.
//
// Loaded after web/cave.js, whose helpers it borrows through window.Cave.
(function () {
  const cave = () => window.Cave;
  const app = () => window.AdullamApp;
  const el = (...args) => cave().el(...args);
  const api = (...args) => cave().api(...args);
  const toast = (...args) => cave().toast(...args);
  // Aquila's wing mark, shared with the rest of the app (AQUILA_MARK in index.html).
  const aquilaMark = () => (app() && app().aquilaMark) || "";
  // Her mark in its gradient circle, as she appears beside what she says.
  const aquilaAvatar = (extra = "") => el("span", { class: `avatar-a refuge-aq${extra}`, "aria-hidden": "true", html: aquilaMark() });

  const svg = (path) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
  const ICON = {
    clock: svg('<circle cx="12" cy="12" r="9"/><path d="M12 7.5V12l3 2"/>'),
    bell: svg('<path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z"/><path d="M10 20.5a2 2 0 0 0 4 0"/>'),
    lock: svg('<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>'),
    mic: svg('<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>'),
    pen: svg('<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>'),
    talk: svg('<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/>'),
    // Pebbles: a small cairn of three stones, like the stones of remembrance in Joshua 4.
    pebbles: svg('<ellipse cx="12" cy="18" rx="7.5" ry="3"/><ellipse cx="12" cy="12.2" rx="5.2" ry="2.6"/><ellipse cx="12" cy="7" rx="3.2" ry="2.1"/>'),
    still: svg('<path d="M3 12c3-3 6-3 9 0s6 3 9 0"/><path d="M3 17c3-3 6-3 9 0s6 3 9 0" opacity=".5"/><path d="M3 7c3-3 6-3 9 0s6 3 9 0" opacity=".5"/>'),
    // Amens: hands folded in prayer.
    together: svg('<path d="M12 4.5c-.9-1.6-2.9-1.4-3.3.3L7.2 11.5l-2.4 3.2a1.6 1.6 0 0 0 .2 2.1l3.4 3.2"/><path d="M12 4.5c.9-1.6 2.9-1.4 3.3.3l1.5 6.7 2.4 3.2a1.6 1.6 0 0 1-.2 2.1l-3.4 3.2"/><path d="M12 4.5V16"/><path d="M8.4 20l3.6-4 3.6 4"/>'),
    person: svg('<circle cx="12" cy="8" r="3.5"/><path d="M5 20a7 7 0 0 1 14 0"/>'),
    back: svg('<path d="M15 6l-6 6 6 6"/>'),
    forward: svg('<path d="M9 6l6 6-6 6"/>'),
    send: svg('<path d="M5 12h13M13 6l6 6-6 6"/>'),
    check: svg('<path d="M5 12.5l4.5 4.5L19 7.5"/>'),
    plus: svg('<path d="M12 5v14M5 12h14"/>'),
    // Hands pressed together, thumbs showing, for praying over a burden.
    pray: svg('<path d="M12 4.5V15"/><path d="M12 4.5c-.6-1.3-2.2-1.2-2.6.1L8 10v3.5l-4 5 2.5 2 5.5-5"/><path d="M12 4.5c.6-1.3 2.2-1.2 2.6.1L16 10v3.5l4 5-2.5 2-5.5-5"/><path d="M8 13.5l2-1.5M16 13.5l-2-1.5"/>'),
    // A speaker giving off sound, for Be still's soft tones.
    sound: svg('<path d="M4 9.5v5h3.5L12 18.5v-13L7.5 9.5z"/><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11"/>'),
    close: svg('<path d="M6 6l12 12M18 6L6 18"/>'),
    // A small sun, for rejoicing over good news.
    rejoice: svg('<circle cx="12" cy="12" r="3.2"/><path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M5.6 18.4l1.8-1.8M16.6 7.4l1.8-1.8"/>'),
  };

  // Real numbers, checked when this was written. The country is guessed from
  // the browser's language and can be changed; the choice stays on the device.
  const HELPLINES = {
    "United Kingdom": [["Samaritans", "Call 116 123, free, any time", "tel:116123"], ["Shout", "Text SHOUT to 85258, any time", "sms:85258"], ["Emergency", "Call 999 if you're in danger now", "tel:999"]],
    Ireland: [["Samaritans", "Call 116 123, free, any time", "tel:116123"], ["Text About It", "Text HELLO to 50808, any time", "sms:50808"], ["Emergency", "Call 112 or 999", "tel:112"]],
    "United States": [["988 Suicide & Crisis Lifeline", "Call or text 988, any time", "tel:988"], ["Crisis Text Line", "Text HOME to 741741", "sms:741741"], ["Emergency", "Call 911 if you're in danger now", "tel:911"]],
    Canada: [["9-8-8 Suicide Crisis Helpline", "Call or text 988, any time", "tel:988"], ["Emergency", "Call 911", "tel:911"]],
    Australia: [["Lifeline", "Call 13 11 14, any time", "tel:131114"], ["Emergency", "Call 000", "tel:000"]],
    "Somewhere else": [["Find a Helpline", "Free, confidential lines in over 130 countries", "https://findahelpline.com"]],
  };
  const REGION_COUNTRY = { GB: "United Kingdom", IE: "Ireland", US: "United States", CA: "Canada", AU: "Australia" };

  function country() {
    try {
      const saved = localStorage.getItem("adullum:helpline-country");
      if (saved && HELPLINES[saved]) return saved;
    } catch { /* private window */ }
    const region = (navigator.language || "").split("-")[1];
    return REGION_COUNTRY[(region || "").toUpperCase()] || "Somewhere else";
  }
  function setCountry(c) {
    try { localStorage.setItem("adullum:helpline-country", c); } catch { /* private window */ }
  }

  function linkLabel(href) {
    return href.startsWith("http") ? "Open" : href.startsWith("sms") ? "Text" : "Call";
  }
  function helplineRows(rowClass) {
    return HELPLINES[country()].map(([name, how, href]) => el("div", { class: rowClass }, [
      el("div", {}, [el("strong", { text: name }), el("span", { text: how })]),
      el("a", { class: "btn btn-ember btn-sm", href, target: href.startsWith("http") ? "_blank" : null, rel: "noopener", text: linkLabel(href) }),
    ]));
  }

  function shortDate(iso) {
    return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
  function translation() {
    const input = document.getElementById("translation");
    return (input && input.value.trim()) || "BSB";
  }
  function plural(n, one, many) {
    return `${n} ${n === 1 ? one : many}`;
  }

  // ---------------------------------------------------------------------
  // Being in Refuge: the settled page, and leaving
  // ---------------------------------------------------------------------
  let panel = null;
  let talk = null; // { messages, keptId } while a talk is open; null otherwise

  function enter(p) {
    panel = p;
    document.body.classList.add("in-refuge");
  }

  // Called by web/cave.js whenever another tab or view takes over. A talk that
  // wasn't kept vanishes here, as Refuge promises.
  function hide() {
    document.body.classList.remove("in-refuge");
    talk = null;
    stopStill();
    panel = null;
  }

  function show(...nodes) {
    if (!panel) return;
    stopStill();
    panel.replaceChildren(el("div", { class: "refuge" }, nodes.filter(Boolean)));
    // Moving between rooms from far down the page brings the new room into view.
    if (panel.getBoundingClientRect().top < 0) panel.scrollIntoView({ block: "start" });
  }

  // A room that couldn't load says so in place, with a way back.
  function failed(err) {
    show(el("div", { class: "empty" }, [
      el("strong", { text: "Couldn't open this" }),
      err.message,
      el("div", {}, el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Back to Refuge", onclick: () => threshold() })),
    ]));
  }

  // A room: the way back, its title, and what's in it. `about` explains the
  // room behind an info button beside the title rather than under it: a
  // string, or { text, more, moreLabel } when there's a fuller explanation.
  function room(title, about, ...rest) {
    const heading = el("h2", { text: title });
    const spec = typeof about === "string" ? { text: about } : about;
    return el("div", { class: "room fade-in" }, [
      el("div", {}, [
        el("button", { class: "back", type: "button", html: `${ICON.back}<span>Refuge</span>`, onclick: threshold }),
        el("div", { class: "room-head" }, spec ? cave().titleInfo(heading, spec.text, { more: spec.more, moreLabel: spec.moreLabel }) : heading),
      ]),
      ...rest,
    ]);
  }

  // ---------------------------------------------------------------------
  // The opening screen
  // ---------------------------------------------------------------------
  // `route` is the hash that opened the cave; #amens and #pebbles go straight
  // to that room (the home screen links to both).
  const ROOM_ROUTES = { amens: () => amensRoom(), pebbles: () => pebblesRoom() };
  async function renderTab(p, route) {
    enter(p);
    await (ROOM_ROUTES[route] || threshold)();
  }

  // What Refuge is, behind the info button beside "Private to you". Each
  // room explains itself the same way once it's open.
  const ABOUT_REFUGE = [
    "A quiet room for any season. Talk it through with Aquila, write it out, breathe and pray, carry small goals with God, or share with others without your name.",
    "Only you can see what you keep here, and Aquila won't bring any of it up anywhere else.",
  ];

  // A room's way in: its icon and name, nothing more. `badge` is a small
  // count in the corner, with `label` saying what it counts.
  function tile(icon, name, open, { wide = false, badge = null, label = null } = {}) {
    return el("button", { class: `refuge-tile${wide ? " is-wide" : ""}`, type: "button", "aria-label": label, onclick: open }, [
      el("span", { class: "tile-icon", html: icon }),
      el("span", { class: "tile-name", text: name }),
      badge ? el("span", { class: "tile-badge", "aria-hidden": "true", text: badge }) : null,
    ]);
  }

  async function threshold() {
    talk = null;
    let overview, seeds;
    try {
      [overview, seeds] = await Promise.all([
        api("/me/refuge"),
        api(`/me/refuge/seeds?today=${cave().localToday()}`).catch(() => []),
      ]);
    } catch (err) {
      // The first visit before the migration lands here with the setup message.
      if (panel) panel.replaceChildren(el("div", { class: "empty" }, [el("strong", { text: "Refuge isn't open yet" }), err.message]));
      return;
    }
    const back = carried(overview.carried);
    show(
      el("section", { class: "refuge-home fade-in" }, [
        el("div", { class: "refuge-bar" }, [
          el("span", { class: "refuge-private", html: `${ICON.lock}<span>Private to you</span>` }),
          cave().info(ABOUT_REFUGE, { label: "About Refuge" }),
        ]),
        el("div", { class: "refuge-rooms" }, [
          tile(aquilaMark() || ICON.talk, "Talk with Aquila", () => talkRoom(), { wide: true }),
          tile(ICON.pen, "Write it out", () => writeRoom()),
          tile(ICON.still, "Be still", stillRoom),
          tile(ICON.pebbles, "Pebbles", pebblesRoom),
          tile(ICON.together, "Amens", amensRoom, back ? { badge: back.count, label: `Amens. ${back.line}` } : {}),
        ]),
        // Kept in plain sight: reaching a person should never be hidden.
        el("button", { class: "refuge-help", type: "button", html: `${ICON.person}<span>Talk to a person</span>`, onclick: helpRoom }),
      ]),
      growingToday(seeds),
      keptList(overview)
    );
  }

  // What came back to the person's posts on the Amens wall: a count for the
  // Amens tile, and the same news as a sentence for screen readers.
  function carried(c) {
    const total = c ? (c.reactions || 0) + (c.kind_words || 0) : 0;
    if (!total) return null;
    const words = plural(c.kind_words, "kind word", "kind words");
    const line = c.reactions
      ? `${plural(c.reactions, "amen", "amens")}${c.kind_words ? ` and ${words}` : ""} came back to you.`
      : `${words} came back to you.`;
    return { count: total > 99 ? "99+" : String(total), line };
  }

  // Habits not yet done today, as chips: one tap marks a habit done.
  function growingToday(seeds) {
    const due = seeds.filter((s) => s.kind === "habit" && s.status === "growing" && !s.tended_today).slice(0, 3);
    if (!due.length) return null;
    return el("section", { class: "refuge-section fade-in" }, [
      el("h3", { class: "refuge-sub", text: "Today" }),
      el("div", { class: "today-chips" }, due.map((s) => {
        const chip = el("button", { class: "chip-btn today-chip", type: "button", "aria-label": `Mark ${s.title} done today`, text: s.title });
        chip.addEventListener("click", async () => {
          chip.disabled = true;
          try {
            await api(`/me/refuge/seeds/${s.id}/tend`, { method: "POST", body: { today: cave().localToday(), tended: true } });
            chip.classList.add("is-done");
            chip.setAttribute("aria-label", `${s.title}, done today`);
            chip.insertAdjacentHTML("afterbegin", ICON.check);
          } catch (err) {
            chip.disabled = false;
            toast(err.message, { tone: "error" });
          }
        });
        return chip;
      })),
    ]);
  }

  // What's been kept: writing and talks, blurred until tapped in case
  // someone is looking over a shoulder.
  function keptList(overview) {
    const items = [
      ...overview.writings.map((w) => ({ type: "writing", at: w.created_at, item: w })),
      ...overview.talks.map((t) => ({ type: "talk", at: t.updated_at, item: t })),
    ].sort((a, b) => b.at.localeCompare(a.at));
    if (!items.length) return null;
    return el("section", { class: "refuge-section fade-in" }, [
      cave().titleInfo(el("h3", { class: "refuge-sub", text: "Kept" }), "Only you can see these. Each stays blurred until you tap it, in case someone's looking over your shoulder."),
      el("div", { class: "kept-list" }, items.map(({ type, item }) => keptRow(type, item))),
    ]);
  }

  function keptRow(type, item) {
    const row = el("div", { class: "kept" });
    const text = el("p", { class: "kept-text", tabindex: "0", role: "button", "aria-label": "Show or hide", text: type === "talk" ? item.title : item.body });
    const toggle = () => row.classList.toggle("is-open");
    text.addEventListener("click", toggle);
    text.addEventListener("keydown", (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), toggle()));
    const actions = type === "talk"
      ? [
          el("button", { class: "act", type: "button", text: "Open", onclick: () => openKeptTalk(item.id) }),
          el("button", { class: "act danger", type: "button", text: "Erase", onclick: async () => {
            if (!confirm("Erase this talk? It can't be brought back.")) return;
            await removeKept(`/me/refuge/talks/${item.id}`, row, "Erased.");
          } }),
        ]
      : [el("button", { class: "act", type: "button", text: "Let it go", onclick: () => removeKept(`/me/refuge/writings/${item.id}`, row, "Let go. It's gone for good.") })];
    row.append(
      el("div", { class: "kept-main" }, [el("span", { class: "kept-kind", text: `${type === "talk" ? "Talk with Aquila" : SHAPES[item.shape].kept} · ${shortDate(item.created_at)}` }), text]),
      el("div", { class: "kept-actions" }, actions)
    );
    return row;
  }

  async function removeKept(path, row, message) {
    try {
      await api(path, { method: "DELETE" });
      row.classList.add("is-going");
      setTimeout(() => row.remove(), 400);
      toast(message);
    } catch (err) {
      toast(err.message, { tone: "error" });
    }
  }

  // ---------------------------------------------------------------------
  // Write it out
  // ---------------------------------------------------------------------
  const SHAPES = {
    blank: {
      label: "Blank page", kept: "Writing",
      lede: "Write to yourself, to God, or to no one at all.",
      release: { title: "It's gone.", line: "It was never saved anywhere. You don't have to carry it back out with you.", verse: "1 Peter 5:7" },
    },
    lament: {
      label: "When it hurts", kept: "Lament",
      lede: "Many psalms move this way: from what hurts, to what you're asking, to what you still trust. Go at your own pace.",
      steps: [["What hurts?", "Say it as plainly as you need to. God can take it."], ["What are you asking God for?", "Even if it's only to get through today."], ["What do you still hold onto, even a little?", "It's fine if this one is short."]],
      release: { title: "It's gone.", line: "It was never saved anywhere. You don't have to carry it back out with you.", verse: "1 Peter 5:7" },
    },
    thanks: {
      label: "When it's good", kept: "Thanks",
      lede: "Some psalms just stop to remember what God has done. This is one of those moments.",
      steps: [["What happened?", "Big or small."], ["Where did you see God in it?", "A person, a timing, a door that opened."], ["What do you want to remember?", "For the days that feel different."]],
      release: { title: "Offered up.", line: "It wasn't saved, but it was said, and that counts.", verse: "Psalm 107:1" },
    },
    dream: {
      label: "When you're hoping", kept: "Hope",
      lede: "Bring what you're hoping for to God, and think it through with Him.",
      steps: [["What are you hoping for?", "Say it without shrinking it."], ["What would you ask God about it?", "For it, for wisdom, for patience."], ["What could a first small step be?", "Something you could do this week."]],
      release: { title: "Placed in His hands.", line: "It wasn't saved. If you'd like to come back to it, make it a goal in Pebbles next time.", verse: "Proverbs 16:3" },
    },
  };

  function writeRoom(shape = "blank") {
    const spec = SHAPES[shape];
    const blank = el("textarea", { class: "refuge-page", placeholder: "Start anywhere. It isn't saved while you write.", "aria-label": "What you want to write" });
    const steps = (spec.steps || []).map(([q, hint]) => {
      const box = el("textarea", { class: "refuge-page refuge-page-sm", "aria-label": q });
      return { q, box, node: el("div", { class: "lament-step" }, [el("label", { text: q }), el("p", { class: "hint", text: hint }), box]) };
    });
    // Guided writing is kept with its prompts, so it still reads well later.
    const writing = () => spec.steps
      ? steps.filter((s) => s.box.value.trim()).map((s) => `${s.q}\n${s.box.value.trim()}`).join("\n\n")
      : blank.value.trim();

    const shapes = el("div", { class: "moods", role: "group", "aria-label": "How to write", style: "margin:0" }, Object.entries(SHAPES).map(([key, s]) =>
      el("button", { class: "mood", type: "button", style: "text-transform:none", "aria-pressed": String(key === shape), text: s.label, onclick: () => writeRoom(key) })
    ));

    const actions = [
      el("span", { class: "faint", text: "Nothing is saved unless you keep it." }),
      shape === "dream"
        ? el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Make it a goal", onclick: () => {
            // The hope becomes the goal, what they'd ask God is why it
            // matters, and the first small step is its first step.
            const hope = steps[0].box.value.trim();
            if (!hope) return toast("Write what you're hoping for first.", { tone: "info" });
            const firstStep = steps[2].box.value.trim();
            plantSheet({ kind: "goal", title: hope.slice(0, 200), note: steps[1].box.value.trim() || null, steps: firstStep ? [firstStep.slice(0, 200)] : [] }, pebblesRoom);
          } })
        : null,
      el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Keep it, only for me", onclick: async () => {
        const body = writing();
        if (!body) return toast("Write a little first.", { tone: "info" });
        try {
          await api("/me/refuge/writings", { method: "POST", body: { shape, body } });
          toast("Kept. Only you can open it.");
          threshold();
        } catch (err) {
          toast(err.message, { tone: "error" });
        }
      } }),
      el("button", { class: "btn btn-ember btn-sm", type: "button", text: "Let it go", onclick: () => {
        const body = writing();
        if (!body) return toast("Write a little first.", { tone: "info" });
        release(body, spec.release, shape);
      } }),
    ];

    show(room("Write it out", spec.lede, shapes, el("div", { class: "write-body" }, spec.steps ? steps.map((s) => s.node) : [blank]), el("div", { class: "release-row" }, actions)));
    (spec.steps ? steps[0].box : blank).focus();
  }

  // The words drift up and fade. Nothing was sent anywhere, so there is
  // nothing to delete; this is only the letting go.
  async function release(text, words, shape) {
    const box = el("div", { class: "releasing", "aria-hidden": "true" });
    text.split(/(\s+)/).slice(0, 400).forEach((w, i) => box.append(el("span", { text: w, style: `animation-delay:${(Math.random() * 0.9 + i * 0.01).toFixed(2)}s` })));
    show(el("p", { class: "muted", role: "status", text: "Letting it go..." }), box);
    const verse = cave().verseText(words.verse).catch(() => null);
    await new Promise((r) => setTimeout(r, 3200));
    const v = await verse;
    if (!panel) return;
    show(el("section", { class: "released fade-in" }, [
      el("h2", { text: words.title }),
      el("p", { class: "muted", text: words.line }),
      v ? el("p", { class: "scripture-lg", text: v.text }) : null,
      v ? el("p", { class: "verse-ref", text: `${words.verse} · ${v.translation}` }) : null,
      el("div", { class: "card-actions-row", style: "justify-content:center;margin-top:24px" }, [
        el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Write more", onclick: () => writeRoom(shape) }),
        el("button", { class: "btn btn-ember btn-sm", type: "button", text: "Back to Refuge", onclick: threshold }),
      ]),
    ]));
  }

  // ---------------------------------------------------------------------
  // Talk with Aquila
  // ---------------------------------------------------------------------
  const OPENING = "I'm here. Whatever you're carrying or hoping for, you can bring it. I'll listen first.";
  const STARTERS = [
    "I just need to vent",
    "Something good happened",
    "Help me plan what's next with God",
    "I'm carrying something heavy",
    "I'm scared",
  ];

  function aquilaBubble(text, extra) {
    return el("div", { class: "soft-aq" }, [
      aquilaAvatar(),
      el("div", { class: "words" }, [...text.split(/\n{2,}/).map((p) => el("p", { text: p })), extra || null]),
    ]);
  }

  function careCard() {
    return el("div", { class: "care-card" }, [
      ...helplineRows("care-line"),
      el("button", { class: "linkish", type: "button", style: "justify-self:start", text: "More people to talk to", onclick: helpRoom }),
    ]);
  }

  function messageNode(m) {
    if (m.role === "user") return el("div", { class: "msg-me", text: m.content });
    const links = (m.verses || []).map((v) => el("a", { class: "verse-ref", href: `#${window.Reader.href(`${v.book} ${v.chapter}:${v.verse}`)}`, text: `Read ${v.book} ${v.chapter}:${v.verse} in context` }));
    return aquilaBubble(m.content, m.care ? careCard() : links.length ? el("p", {}, links) : null);
  }

  // Only role and content go to the server; verses and care are for drawing.
  const wire = (messages) => messages.map(({ role, content }) => ({ role, content }));

  async function openKeptTalk(id) {
    try {
      const kept = await api(`/me/refuge/talks/${id}`);
      talk = { messages: kept.messages, keptId: kept.id };
      talkRoom();
    } catch (err) {
      toast(err.message, { tone: "error" });
    }
  }

  async function saveKept() {
    if (!talk || !talk.keptId) return;
    try {
      await api(`/me/refuge/talks/${talk.keptId}`, { method: "PUT", body: { messages: wire(talk.messages) } });
    } catch {
      toast("Couldn't keep the latest part of this talk.", { tone: "error" });
    }
  }

  function talkRoom(firstMessage) {
    if (!talk) talk = { messages: [{ role: "aquila", content: OPENING }], keptId: null };
    const list = el("div", { class: "soft-thread", "aria-live": "polite" }, talk.messages.map(messageNode));
    const box = el("textarea", { rows: "1", maxlength: "4000", placeholder: "Say as much or as little as you want", "aria-label": "Message to Aquila" });
    const sendBtn = el("button", { class: "iconbtn", type: "button", "aria-label": "Send", html: ICON.send });
    // The voice call lives only here. It's a call of its own over Cognigy, so
    // its warning comes first (index.html::openVoice) and nothing from it
    // joins this written talk.
    const voiceBtn = el("button", {
      class: "iconbtn soft-mic", type: "button", "aria-label": "Talk out loud", title: "Talk out loud", html: ICON.mic,
      onclick: () => app().openVoice(),
    });
    const starters = talk.messages.length === 1
      ? el("div", { class: "starters" }, STARTERS.map((s) => el("button", { class: "act", type: "button", text: s, onclick: () => send(s) })))
      : null;

    const keepBtn = el("button", { class: `act${talk.keptId ? " is-done" : ""}`, type: "button", text: talk.keptId ? "Kept" : "Keep this talk" });
    const status = el("p", { class: "refuge-promise", html: `${ICON.lock}<span></span>` });
    const say = () => {
      status.lastChild.textContent = talk.keptId
        ? "Kept, only for you. Nothing you say here goes into Aquila's memory."
        : "This talk vanishes when you leave, unless you keep it. Nothing here goes into Aquila's memory.";
    };
    say();
    keepBtn.onclick = async () => {
      if (talk.keptId) return;
      if (talk.messages.length < 2) return toast("Say something first, then you can keep it.", { tone: "info" });
      try {
        const kept = await api("/me/refuge/talks", { method: "POST", body: { messages: wire(talk.messages) } });
        talk.keptId = kept.id;
        keepBtn.textContent = "Kept";
        keepBtn.classList.add("is-done");
        say();
      } catch (err) {
        toast(err.message, { tone: "error" });
      }
    };
    const erase = el("button", { class: "act danger", type: "button", text: "Erase", onclick: async () => {
      if (talk.keptId) {
        if (!confirm("Erase this talk? It can't be brought back.")) return;
        try {
          await api(`/me/refuge/talks/${talk.keptId}`, { method: "DELETE" });
        } catch (err) {
          return toast(err.message, { tone: "error" });
        }
      }
      talk = null;
      toast("Erased.");
      talkRoom();
    } });

    let busy = false;
    async function send(text) {
      text = (text || "").trim();
      if (!text || busy || !talk) return;
      busy = true;
      sendBtn.disabled = true;
      if (starters) starters.remove();
      const mine = { role: "user", content: text };
      talk.messages.push(mine);
      list.append(messageNode(mine));
      box.value = "";
      // While she replies, her mark breathes slowly beside three soft dots.
      const wait = el("div", { class: "listening", role: "status", "aria-label": "Aquila is listening" }, [
        aquilaAvatar(" is-listening"),
        el("span", { class: "thinking", html: "<span></span><span></span><span></span>" }),
      ]);
      list.append(wait);
      wait.scrollIntoView({ behavior: "smooth", block: "nearest" });
      const current = talk;
      try {
        const res = await api("/me/refuge/talk", { method: "POST", body: { messages: wire(current.messages), translation: translation() } });
        if (talk !== current) return; // left or erased while she was replying
        const reply = { role: "aquila", content: res.reply, care: res.care, verses: res.verses };
        current.messages.push(reply);
        const node = messageNode(reply);
        wait.replaceWith(node);
        node.scrollIntoView({ behavior: "smooth", block: "nearest" });
        saveKept();
      } catch (err) {
        // A daily limit is said as it is; anything else can be sent again.
        const note = err.status === 429 ? err.message : `${err.message} Your words are still here; try sending again.`;
        wait.replaceWith(el("p", { class: `form-msg${err.status === 429 ? "" : " bad"}`, text: note }));
        current.messages.pop();
        box.value = text;
      } finally {
        busy = false;
        sendBtn.disabled = false;
      }
    }
    sendBtn.onclick = () => send(box.value);
    box.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        send(box.value);
      }
    });
    box.addEventListener("input", () => {
      box.style.height = "auto";
      box.style.height = `${Math.min(box.scrollHeight, 160)}px`;
    });

    show(room("Talk with Aquila", null,
      el("div", { class: "talk-bar" }, [status, el("div", { class: "talk-actions" }, [keepBtn, erase])]),
      list,
      starters,
      el("div", { class: "soft-composer" }, [box, voiceBtn, sendBtn])
    ));
    if (firstMessage) send(firstMessage);
    else box.focus();
  }

  // ---------------------------------------------------------------------
  // Pebbles (once "Grow"; app/refuge.py still says seeds): goals and habits.
  // A goal is reached by steps, by a number ("4 of 12 books") or simply
  // marked reached, optionally by a date. A habit is meant for some days a
  // week and shows this week as dots, counted ("3 of 5 this week"), never as
  // a streak. Praying and fasting are tracked on the prayer list instead.
  // ---------------------------------------------------------------------
  const PEBBLE = {
    goal: { name: "Goal", placeholder: "e.g. Read through the Gospels", reach: "Mark reached", reached: "Reached", talk: "a goal I'm working toward" },
    habit: { name: "Habit", placeholder: "e.g. Read a psalm before bed", reach: "It's part of me now", reached: "Part of me now", talk: "a habit I'm trying to build" },
  };
  // How a goal is tracked, chosen when it's set: steps, a number, or neither.
  const TRACK_BY = [["steps", "Steps"], ["number", "A number"], ["none", "Just done"]];
  const STATUS_LABEL = { growing: "Active", fulfilled: "Reached", set_aside: "Set aside" };
  let pebbleFilter = "growing";

  function amount(n) {
    return Number(n).toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  function perWeekLabel(n) {
    return n === 7 ? "Every day" : `${plural(n, "day", "days")} a week`;
  }
  // "Dec 31 · 12 days left", or that it's due or past, for an active goal.
  function dueLine(seed) {
    if (seed.due_in === null || seed.due_in === undefined || seed.status !== "growing") return null;
    const when = cave().localDate(seed.due_on).toLocaleDateString(undefined, { month: "short", day: "numeric" });
    if (seed.due_in < 0) return el("span", { class: "due is-late", text: `Was due ${when}` });
    if (seed.due_in === 0) return el("span", { class: "due is-soon", text: "Due today" });
    return el("span", { class: `due${seed.due_in <= 7 ? " is-soon" : ""}`, text: `${when} · ${plural(seed.due_in, "day", "days")} left` });
  }

  // A compact segmented choice inside a sheet; `onPick` gets the chosen key.
  function segChoice(label, options, selected, onPick) {
    const group = el("div", { class: "seg seg-sheet", role: "group", "aria-label": label });
    const paint = (key) => [...group.children].forEach((b, i) => b.setAttribute("aria-pressed", String(options[i][0] === key)));
    options.forEach(([key, text]) => group.append(el("button", { type: "button", text, onclick: () => { paint(key); onPick(key); } })));
    paint(selected);
    return group;
  }

  // Set a goal or start a habit, or edit `existing`. Something prefilled but
  // not yet saved (from Write it out) comes in as `existing` without an id.
  function plantSheet(existing, onSaved) {
    const editing = !!(existing && existing.id);
    let kind = (existing && existing.kind) || "goal";
    const existingSteps = ((existing && existing.steps) || []).map((s) => (typeof s === "string" ? { text: s, done: false } : s));
    let trackBy = existing && existing.target ? "number" : existingSteps.length || !editing ? "steps" : "none";

    const title = el("input", { class: "field", maxlength: "200" });
    const stepsBox = el("textarea", { class: "field", rows: "4", placeholder: "One step per line" });
    const target = el("input", { class: "field", type: "number", min: "0", step: "any", inputmode: "decimal", placeholder: "12" });
    const unit = el("input", { class: "field", maxlength: "30", placeholder: "books" });
    const due = el("input", { class: "field", type: "date" });
    const perWeek = el("select", { class: "field" }, [7, 6, 5, 4, 3, 2, 1].map((n) => el("option", { value: n, text: perWeekLabel(n) })));
    const note = el("textarea", { class: "field", maxlength: "2000", rows: "2", placeholder: "Why it matters to you" });
    const passage = el("input", { class: "field", maxlength: "120", placeholder: "Philippians 4:13, or leave blank" });
    title.value = (existing && existing.title) || "";
    stepsBox.value = existingSteps.map((s) => s.text).join("\n");
    target.value = (existing && existing.target) || "";
    unit.value = (existing && existing.unit) || "";
    due.value = (existing && existing.due_on) || "";
    perWeek.value = String((existing && existing.per_week) || 7);
    note.value = (existing && existing.note) || "";
    passage.value = (existing && existing.passage_ref) || "";

    const titleLabel = el("span");
    const stepsWrap = el("label", { class: "field-wrap" }, ["Steps", stepsBox]);
    const numberWrap = el("div", { class: "field-row" }, [
      el("label", { class: "field-wrap" }, ["Reach", target]),
      el("label", { class: "field-wrap" }, ["Of what", unit]),
    ]);
    const trackWrap = el("div", { class: "field-wrap" }, [
      el("span", { text: "Track it by" }),
      segChoice("Track it by", TRACK_BY, trackBy, (key) => { trackBy = key; paint(); }),
    ]);
    const dueWrap = el("label", { class: "field-wrap" }, ["By when (optional)", due]);
    const perWeekWrap = el("label", { class: "field-wrap" }, ["How often", perWeek]);
    // Why it matters and a verse are worth having but not worth the room up
    // front, so they fold away unless they already hold something.
    const more = el("details", { class: "more-fields", open: !!(note.value || passage.value) }, [
      el("summary", { text: "Why it matters, and a verse (optional)" }),
      el("label", { class: "field-wrap" }, ["Why it matters", note]),
      el("label", { class: "field-wrap" }, ["A verse to hold onto", passage]),
    ]);

    function paint() {
      const goal = kind === "goal";
      titleLabel.textContent = PEBBLE[kind].name;
      title.placeholder = PEBBLE[kind].placeholder;
      trackWrap.hidden = !goal;
      stepsWrap.hidden = !goal || trackBy !== "steps";
      numberWrap.hidden = !goal || trackBy !== "number";
      dueWrap.hidden = !goal;
      perWeekWrap.hidden = goal;
    }
    paint();

    const msg = cave().formMessage();
    const save = el("button", { class: "btn btn-ember btn-sm", type: "submit", text: editing ? "Save" : kind === "goal" ? "Set goal" : "Start habit" });
    const form = el("form", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "plantTitle" }, [
      cave().sheetTitle("plantTitle", editing ? `Edit ${PEBBLE[kind].name.toLowerCase()}` : "New pebble", "Only you can see your pebbles."),
      editing ? null : segChoice("Goal or habit", [["goal", "Goal"], ["habit", "Habit"]], kind, (key) => {
        kind = key;
        save.textContent = key === "goal" ? "Set goal" : "Start habit";
        paint();
      }),
      el("label", { class: "field-wrap" }, [titleLabel, title]),
      trackWrap,
      stepsWrap,
      numberWrap,
      dueWrap,
      perWeekWrap,
      more,
      msg.node,
      el("div", { class: "sheet-actions" }, [el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Cancel", onclick: () => close() }), save]),
    ]);
    const close = cave().overlay(form);

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!title.value.trim()) return msg.say("Give it a few words.", true);
      const body = { title: title.value.trim(), note: note.value.trim() || null, passage_ref: passage.value.trim() || null };
      if (kind === "goal") {
        const lines = trackBy === "steps" ? stepsBox.value.split("\n").map((s) => s.trim()).filter(Boolean) : [];
        const number = trackBy === "number" ? Number(target.value) : null;
        if (trackBy === "number" && !(number > 0)) return msg.say("Set the number you're aiming for.", true);
        // An edited goal keeps the steps already ticked.
        const done = new Set(existingSteps.filter((s) => s.done).map((s) => s.text));
        Object.assign(body, {
          steps: editing ? lines.map((text) => ({ text, done: done.has(text) })) : lines,
          target: number,
          unit: number ? unit.value.trim() || null : null,
          due_on: due.value || null,
        });
      } else {
        body.per_week = Number(perWeek.value);
      }
      save.disabled = true;
      try {
        if (editing) await api(`/me/refuge/seeds/${existing.id}`, { method: "PATCH", body });
        else await api("/me/refuge/seeds", { method: "POST", body: { kind, ...body } });
        close();
        toast(editing ? "Saved." : kind === "goal" ? "Goal set." : "Habit started.");
        if (onSaved) onSaved();
      } catch (err) {
        msg.say(err.message, true);
        save.disabled = false;
      }
    });
  }

  function fulfilSheet(seed, onSaved) {
    const spec = PEBBLE[seed.kind];
    const note = el("textarea", { class: "field", maxlength: "2000", rows: "3", placeholder: "How did you get there? A sentence is plenty, or leave it blank." });
    const msg = cave().formMessage();
    const save = el("button", { class: "btn btn-ember btn-sm", type: "submit", text: spec.reach });
    const form = el("form", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "fulfilTitle" }, [
      el("h3", { id: "fulfilTitle", text: spec.reach }),
      el("div", { class: "journal-preview" }, [el("strong", { text: `${spec.name} since ${shortDate(seed.created_at)}` }), document.createTextNode(seed.title)]),
      el("label", { class: "field-wrap" }, ["Remember how it came about", note]),
      msg.node,
      el("div", { class: "sheet-actions" }, [el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Cancel", onclick: () => close() }), save]),
    ]);
    const close = cave().overlay(form);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      save.disabled = true;
      try {
        await api(`/me/refuge/seeds/${seed.id}`, { method: "PATCH", body: { status: "fulfilled", outcome_note: note.value.trim() || null } });
        close();
        toast("Thanks be to God.");
        onSaved();
      } catch (err) {
        msg.say(err.message, true);
        save.disabled = false;
      }
    });
  }

  // Where a number goal stands now, typed in (for amounts that don't go up
  // by one at a time, like money saved).
  function amountSheet(seed, onSaved) {
    const input = el("input", { class: "field", type: "number", min: "0", step: "any", inputmode: "decimal" });
    input.value = seed.progress || 0;
    const msg = cave().formMessage();
    const save = el("button", { class: "btn btn-ember btn-sm", type: "submit", text: "Update" });
    const form = el("form", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "amountTitle" }, [
      el("h3", { id: "amountTitle", text: seed.title }),
      el("label", { class: "field-wrap" }, [`Where you are now, of ${amount(seed.target)}${seed.unit ? ` ${seed.unit}` : ""}`, input]),
      msg.node,
      el("div", { class: "sheet-actions" }, [el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Cancel", onclick: () => close() }), save]),
    ]);
    const close = cave().overlay(form);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const value = Number(input.value);
      if (!(value >= 0)) return msg.say("Enter a number, 0 or more.", true);
      save.disabled = true;
      try {
        await api(`/me/refuge/seeds/${seed.id}`, { method: "PATCH", body: { progress: value } });
        close();
        onSaved();
      } catch (err) {
        msg.say(err.message, true);
        save.disabled = false;
      }
    });
  }

  // The "⋯" menu every pebble has: the things done now and then.
  function pebbleMenu(seed, rerender, { withReach = true } = {}) {
    const patch = async (body) => {
      try {
        await api(`/me/refuge/seeds/${seed.id}`, { method: "PATCH", body });
        rerender();
      } catch (err) {
        toast(err.message, { tone: "error" });
      }
    };
    const remove = {
      label: "Delete", danger: true, onClick: async () => {
        if (!confirm("Delete this? Its history goes too.")) return;
        try {
          await api(`/me/refuge/seeds/${seed.id}`, { method: "DELETE" });
          rerender();
        } catch (err) {
          toast(err.message, { tone: "error" });
        }
      },
    };
    if (seed.status !== "growing") return cave().moreMenu(`More for ${seed.title}`, [{ label: "Make it active again", onClick: () => patch({ status: "growing" }) }, remove]);
    return cave().moreMenu(`More for ${seed.title}`, [
      {
        label: "Talk it over with Aquila", onClick: () => {
          talk = null;
          talkRoom(`I'd like to talk with you about ${PEBBLE[seed.kind].talk}: "${seed.title}".${seed.note ? ` ${seed.note}` : ""}`);
        },
      },
      { label: "Edit", onClick: () => plantSheet(seed, rerender) },
      withReach ? { label: PEBBLE[seed.kind].reach, onClick: () => fulfilSheet(seed, rerender) } : null,
      { label: "Set aside for now", onClick: () => patch({ status: "set_aside" }) },
      remove,
    ]);
  }

  // A habit as one row: a check for today, its name and this week's count,
  // and the week as dots (tap an earlier day to mark it).
  function habitRow(seed, rerender) {
    const active = seed.status === "growing";
    const mark = async (day, tended) => {
      try {
        await api(`/me/refuge/seeds/${seed.id}/tend`, { method: "POST", body: { today: cave().localToday(), day, tended } });
        rerender();
      } catch (err) {
        toast(err.message, { tone: "error" });
      }
    };
    const metWeek = seed.week_done >= seed.per_week;
    const sub = active
      ? `${seed.week_done} of ${seed.per_week} this week${metWeek ? " · well done" : ""}`
      : `${STATUS_LABEL[seed.status]}${seed.fulfilled_at ? ` ${shortDate(seed.fulfilled_at)}` : ""} · ${perWeekLabel(seed.per_week)}`;
    return el("div", { class: `habit-row${seed.tended_today ? " is-done" : ""}${active ? "" : " is-quiet"}` }, [
      active
        ? el("button", {
            class: "habit-check", type: "button", "aria-pressed": String(seed.tended_today),
            "aria-label": `Done today: ${seed.title}`, html: ICON.check,
            onclick: () => mark(cave().localToday(), !seed.tended_today),
          })
        : el("span", { class: "habit-check", "aria-hidden": "true", html: ICON.check }),
      el("div", { class: "habit-main" }, [
        el("strong", { text: seed.title }),
        el("span", { class: `habit-sub${metWeek && active ? " is-met" : ""}`, text: sub }),
      ]),
      active ? cave().weekDots(seed.week, { label: `${seed.title}, this week`, onToggle: (m) => mark(m.day, !m.done) }) : null,
      pebbleMenu(seed, rerender),
    ]);
  }

  // A goal as a card: how far along it is, and the one thing to do next.
  function goalCard(seed, rerender) {
    const active = seed.status === "growing";
    const m = seed.measure;
    const patch = async (body) => {
      try {
        await api(`/me/refuge/seeds/${seed.id}`, { method: "PATCH", body });
        rerender();
      } catch (err) {
        toast(err.message, { tone: "error" });
      }
    };
    const complete = m && m.fraction >= 1;
    // Once there's nothing left to count, reaching it is the next thing, so
    // it moves from the menu onto the card.
    const reachOnCard = active && (!m || complete);

    let progress = null;
    if (m) {
      const bar = el("div", { class: "bar", role: "progressbar", "aria-label": "Progress", "aria-valuemin": "0", "aria-valuemax": String(m.of), "aria-valuenow": String(m.done) },
        el("span", { style: `width:${Math.round(m.fraction * 100)}%` }));
      const count = m.by === "number"
        ? `${amount(m.done)} of ${amount(m.of)}${seed.unit ? ` ${seed.unit}` : ""}`
        : `${m.done} of ${plural(m.of, "step", "steps")}`;
      const controls = m.by === "number" && active
        ? el("div", { class: "stepper", role: "group", "aria-label": "Change progress" }, [
            el("button", { type: "button", "aria-label": "One less", text: "−", disabled: !(seed.progress > 0), onclick: () => patch({ progress: Math.max(0, Number(seed.progress) - 1) }) }),
            el("button", { type: "button", "aria-label": "One more", text: "+", onclick: () => patch({ progress: Number(seed.progress) + 1 }) }),
          ])
        : null;
      progress = el("div", { class: "goal-progress" }, [
        bar,
        el("div", { class: "goal-count" }, [
          m.by === "number" && active
            ? el("button", { class: "count-btn", type: "button", title: "Type where you are now", text: count, onclick: () => amountSheet(seed, rerender) })
            : el("span", { text: count }),
          controls,
        ]),
      ]);
    }

    const steps = m && m.by === "steps"
      ? el("div", { class: "steps" }, seed.steps.map((s, i) => el("label", { class: `step${s.done ? " done" : ""}` }, [
          el("input", { type: "checkbox", checked: s.done, disabled: !active, onchange: (e) => patch({ steps: seed.steps.map((x, j) => (j === i ? { ...x, done: e.target.checked } : x)) }) }),
          el("span", { text: s.text }),
        ])))
      : null;

    const status = active
      ? dueLine(seed)
      : el("span", { class: `badge ${seed.status === "fulfilled" ? "answered" : "plain"}`, html: seed.status === "fulfilled" ? `${ICON.check}<span>Reached ${shortDate(seed.fulfilled_at)}</span>` : "Set aside" });

    return el("article", { class: `entry goal-card${complete ? " is-complete" : ""}${seed.status === "fulfilled" ? " is-fulfilled" : ""}${seed.status === "set_aside" ? " is-aside" : ""} fade-in` }, [
      el("div", { class: "goal-head" }, [el("h3", { text: seed.title }), pebbleMenu(seed, rerender, { withReach: !reachOnCard })]),
      status ? el("div", { class: "entry-meta" }, status) : null,
      seed.note ? el("p", { class: "refl", text: seed.note }) : null,
      progress,
      steps,
      seed.passage_ref ? el("a", { class: "pill prayer-passage", href: `#${window.Reader.href(seed.passage_ref)}` }, el("span", { text: seed.passage_ref })) : null,
      seed.status === "fulfilled" && seed.outcome_note ? el("div", { class: "answer-note" }, [el("strong", { text: "How it came about" }), el("p", { text: seed.outcome_note })]) : null,
      reachOnCard
        ? el("div", { class: "entry-actions" }, el("button", {
            class: `btn btn-sm ${complete ? "btn-ember" : "btn-ghost"}`, type: "button",
            html: `${ICON.check}<span>${PEBBLE.goal.reach}</span>`, onclick: () => fulfilSheet(seed, rerender),
          }))
        : null,
    ].filter(Boolean));
  }

  // The room's shell is drawn once; `draw` refills only its body, so marking
  // a habit or ticking a step never jumps the page back to the top.
  async function pebblesRoom() {
    let seeds;
    try {
      seeds = await api(`/me/refuge/seeds?today=${cave().localToday()}`);
    } catch (err) {
      return failed(err);
    }
    const body = el("div", { class: "pebbles" });
    const refresh = async () => {
      try {
        seeds = await api(`/me/refuge/seeds?today=${cave().localToday()}`);
        draw();
      } catch (err) {
        toast(err.message, { tone: "error" });
      }
    };
    const newPebble = (kind) => plantSheet(kind ? { kind } : null, refresh);

    function draw() {
      const counts = { growing: 0, fulfilled: 0, set_aside: 0 };
      seeds.forEach((s) => counts[s.status]++);
      if (!counts[pebbleFilter]) pebbleFilter = "growing";
      const shown = seeds.filter((s) => s.status === pebbleFilter);
      const habits = shown.filter((s) => s.kind === "habit");
      const goals = shown.filter((s) => s.kind === "goal");

      const filter = cave().filterSelect("Which pebbles to show",
        Object.entries(STATUS_LABEL).filter(([key]) => key === "growing" || counts[key]).map(([key, label]) => [key, `${label} (${counts[key]})`]),
        pebbleFilter, (value) => { pebbleFilter = value; draw(); });
      const bar = el("div", { class: "list-bar" }, [
        filter,
        el("button", { class: "btn btn-ember btn-sm", type: "button", html: `${ICON.plus}<span>New</span>`, onclick: () => newPebble() }),
      ]);

      if (!shown.length) {
        body.replaceChildren(bar, el("div", { class: "empty pebbles-empty" }, [
          el("strong", { text: "Start with one small stone" }),
          "A goal for this season, or a habit you'd like to build. Pebbles keeps track, one day and one step at a time.",
          el("div", { class: "row pebbles-starts" }, [
            el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Set a goal", onclick: () => newPebble("goal") }),
            el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Start a habit", onclick: () => newPebble("habit") }),
          ]),
        ]));
        return;
      }

      const doneToday = habits.filter((h) => h.tended_today).length;
      body.replaceChildren(...[
        bar,
        habits.length ? el("section", { class: "pebble-section" }, [
          el("div", { class: "row-between" }, [
            el("h3", { class: "kicker", text: "Habits" }),
            pebbleFilter === "growing" ? el("span", { class: "faint pebble-tally", text: `${doneToday} of ${habits.length} done today` }) : null,
          ]),
          el("div", { class: "habit-list" }, habits.map((s) => habitRow(s, refresh))),
        ]) : null,
        goals.length ? el("section", { class: "pebble-section" }, [
          el("h3", { class: "kicker", text: "Goals" }),
          el("div", { class: "entries goal-list" }, goals.map((s) => goalCard(s, refresh))),
        ]) : null,
      ].filter(Boolean));
    }

    draw();
    show(room("Pebbles", "Goals you're working toward and habits you're building, carried with God one small stone at a time.", body));
  }

  // ---------------------------------------------------------------------
  // Be still
  // ---------------------------------------------------------------------
  // A guided pause with God. The person picks a rhythm, a length and, if
  // they like, a breath prayer: a line of Scripture prayed in two halves,
  // the first on the breath in and the second on the breath out. Then the
  // page gives way to a full-screen session: a light that fills and empties
  // with the breath, a ring that fills as the minutes pass, and the words.
  // Afterwards it asks how they are, and points somewhere useful if the
  // answer is "still heavy".
  //
  // Nothing here reaches the server. The choices and a count of this week's
  // quiet moments are kept on this device only (localStorage), and the page
  // works the same without them.
  //
  // The breath prayers' words are never typed here. Each is a reference
  // whose text is read from the database in the reader's translation and
  // cut in two by breathHalves, so the words always match the Bible open.

  const RHYTHMS = {
    calm: { name: "Calm", line: "In for 4, hold for 2, out for 6. A longer breath out helps the body settle.", phases: [["in", 4], ["hold", 2], ["out", 6]] },
    even: { name: "Even", line: "In for 5, out for 5. Slow and steady, about six breaths a minute.", phases: [["in", 5], ["out", 5]] },
    box: { name: "Box", line: "In, hold, out, hold, for 4 each. Good for a racing mind.", phases: [["in", 4], ["hold", 4], ["out", 4], ["rest", 4]] },
    sleep: { name: "Deep rest", line: "In for 4, hold for 7, out for 8. Unhurried, for winding down at night.", phases: [["in", 4], ["hold", 7], ["out", 8]] },
  };
  const PHASE_WORDS = { in: "Breathe in", hold: "Hold", out: "Breathe out", rest: "Rest" };
  const LENGTHS = [1, 3, 5, 10];
  const SETTLE_SECONDS = 3; // "Settle in" before the first breath
  const RECORD_AFTER = 20; // seconds of breathing before a pause counts this week

  // `words` is how many words of the verse to gather before cutting it in
  // two, tuned so each half is one comfortable breath in every translation.
  const BREATH_PRAYERS = [
    { id: "still", theme: "Be still", ref: "Psalm 46:10", words: 6 },
    { id: "shepherd", theme: "My shepherd", ref: "Psalm 23:1", words: 6 },
    { id: "afraid", theme: "When I'm afraid", ref: "Psalm 56:3", words: 6 },
    { id: "rest", theme: "Rest in God", ref: "Psalm 62:1", words: 10 },
    { id: "peace", theme: "His peace", ref: "John 14:27", words: 8 },
    { id: "hands", theme: "Letting go", ref: "Psalm 31:5", words: 10 },
    { id: "fight", theme: "He fights for me", ref: "Exodus 14:14", words: 8 },
    { id: "help", theme: "My help", ref: "Psalm 121:2", words: 8 },
  ];
  const NO_PRAYER = "none";

  // Words that start a natural second half when a line has no comma to cut at.
  const BREATH_JOINS = new Set(["and", "that", "for", "because", "but", "so"]);

  // Cuts a verse into the two halves of a breath prayer. A psalm's heading
  // ("A Psalm of David.") and quotation marks are dropped first. Clauses are
  // gathered until there are `target` words, then cut at the clause break
  // nearest the middle; a single clause is cut before a joining word near
  // the middle ("Be still and know / that I am God"), or else in half.
  function breathHalves(text, ref, target) {
    let clean = text.replace(/[“”"]/g, "").replace(/(^|\s)‘|’(?=\s|$)/g, "$1").trim();
    if (/^Psalm /.test(ref)) {
      const withoutHeading = clean.replace(/^.*?\b(?:Psalm|Song|Maskil|Miktam)\b[^.]*\.\s+/, "");
      if (withoutHeading) clean = withoutHeading;
    }
    const wordCount = (s) => s.split(/\s+/).length;
    const clauses = clean.split(/\s*[,;:.!?]+\s*/).filter(Boolean);
    const picked = [];
    let total = 0;
    for (const clause of clauses) {
      picked.push(clause);
      total += wordCount(clause);
      if (total >= target) break;
    }
    if (picked.length > 1) {
      let cut = 1;
      let bestGap = Infinity;
      let run = 0;
      for (let i = 1; i < picked.length; i++) {
        run += wordCount(picked[i - 1]);
        const gap = Math.abs(run - total / 2);
        if (gap < bestGap) [cut, bestGap] = [i, gap];
      }
      return { text: clean, in: picked.slice(0, cut).join(", "), out: picked.slice(cut).join(", ") };
    }
    const words = picked[0].split(/\s+/);
    let cut = Math.ceil(words.length / 2);
    let bestGap = Infinity;
    words.forEach((word, i) => {
      if (i < 2 || i > words.length - 2 || !BREATH_JOINS.has(word.toLowerCase())) return;
      const gap = Math.abs(i - words.length / 2);
      if (gap < bestGap) [cut, bestGap] = [i, gap];
    });
    return { text: clean, in: words.slice(0, cut).join(" "), out: words.slice(cut).join(" ") };
  }

  // Each verse is read once per translation and remembered for the visit.
  const breathCache = new Map();
  function prayerLines(prayer) {
    const key = `${prayer.ref}|${translation()}`;
    if (!breathCache.has(key)) {
      const loading = cave().verseText(prayer.ref).then((v) => ({ ...breathHalves(v.text, prayer.ref, prayer.words), translation: v.translation }));
      loading.catch(() => breathCache.delete(key)); // try again next time
      breathCache.set(key, loading);
    }
    return breathCache.get(key);
  }

  // This device only: wrapped, because storage can be blocked or throw.
  const STILL_PREFS_KEY = "adullumStill";
  const STILL_LOG_KEY = "adullumStillLog";
  function readLocal(key, fallback) {
    try {
      return JSON.parse(localStorage.getItem(key)) || fallback;
    } catch {
      return fallback;
    }
  }
  function writeLocal(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* fine without it */
    }
  }
  function stillPrefs() {
    const saved = readLocal(STILL_PREFS_KEY, {});
    return {
      rhythm: RHYTHMS[saved.rhythm] ? saved.rhythm : "calm",
      minutes: LENGTHS.includes(saved.minutes) ? saved.minutes : 3,
      prayer: saved.prayer === NO_PRAYER || BREATH_PRAYERS.some((p) => p.id === saved.prayer) ? saved.prayer : "still",
      tones: saved.tones === true,
    };
  }

  // A local day as YYYY-MM-DD, `back` days before today.
  function dayKey(back = 0) {
    const d = new Date(`${cave().localToday()}T12:00:00`);
    d.setDate(d.getDate() - back);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }
  // The log is { "2026-11-06": [times, seconds] }, kept for two weeks.
  function recordStill(seconds) {
    const log = readLocal(STILL_LOG_KEY, {});
    const today = dayKey();
    const [times, total] = log[today] || [0, 0];
    log[today] = [times + 1, total + Math.round(seconds)];
    const oldest = dayKey(13);
    for (const day of Object.keys(log)) if (day < oldest) delete log[day];
    writeLocal(STILL_LOG_KEY, log);
  }
  function weekTally() {
    const log = readLocal(STILL_LOG_KEY, {});
    let times = 0;
    let seconds = 0;
    for (let back = 0; back < 7; back++) {
      const [t, s] = log[dayKey(back)] || [0, 0];
      times += t;
      seconds += s;
    }
    return { times, minutes: Math.max(1, Math.round(seconds / 60)) };
  }

  function clock(seconds) {
    const s = Math.max(0, Math.ceil(seconds));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }

  // A soft bell as the breath turns: higher going in, lower going out, and
  // a gentle pair at the end. Made in the browser, so there's no file to load.
  let stillAudio = null;
  function chime(kind) {
    try {
      stillAudio = stillAudio || new (window.AudioContext || window.webkitAudioContext)();
      const notes = kind === "end" ? [396, 528] : [kind === "in" ? 528 : 396];
      notes.forEach((freq, i) => {
        const at = stillAudio.currentTime + i * 0.35;
        const osc = stillAudio.createOscillator();
        const gain = stillAudio.createGain();
        osc.type = "sine";
        osc.frequency.value = freq;
        gain.gain.setValueAtTime(0.0001, at);
        gain.gain.exponentialRampToValueAtTime(0.06, at + 0.04);
        gain.gain.exponentialRampToValueAtTime(0.0001, at + 2.4);
        osc.connect(gain).connect(stillAudio.destination);
        osc.start(at);
        osc.stop(at + 2.5);
      });
    } catch {
      /* no sound is fine */
    }
  }

  // The running session, if any: its timer, its full-screen node, and what
  // it listens to. stopStill takes all of it down, and runs whenever the
  // room changes or the person leaves Refuge.
  let still = null;
  function stopStill() {
    if (!still) return;
    clearInterval(still.timer);
    document.removeEventListener("keydown", still.onKey);
    document.removeEventListener("visibilitychange", still.onVisible);
    if (still.wake) still.wake.release().catch(() => {});
    still.node.remove();
    document.body.classList.remove("still-open");
    still = null;
  }

  // Asks the phone not to dim its screen mid-breath. It's let go whenever
  // the page is hidden, so it's asked for again on coming back.
  function keepScreenOn() {
    if (!still || still.done || !navigator.wakeLock) return;
    navigator.wakeLock.request("screen").then((lock) => {
      if (still && !still.done) still.wake = lock;
      else lock.release().catch(() => {});
    }).catch(() => {});
  }

  function stillRoom() {
    const prefs = stillPrefs();
    const save = () => writeLocal(STILL_PREFS_KEY, prefs);

    const summary = el("small");
    const orb = el("button", { class: "still-orb", type: "button", onclick: () => beginStill(prefs) }, [
      el("span", { class: "still-orb-light", "aria-hidden": "true" }),
      el("span", { class: "still-orb-text" }, [el("strong", { text: "Begin" }), summary]),
    ]);
    const paintSummary = () => {
      summary.textContent = `${prefs.minutes} min · ${RHYTHMS[prefs.rhythm].name}`;
      orb.setAttribute("aria-label", `Begin, ${summary.textContent}`);
    };

    // Pray as you breathe: the chips, and the two halves of the chosen verse.
    const preview = el("div", { class: "still-preview", "aria-live": "polite" });
    async function showPrayer() {
      const prayer = BREATH_PRAYERS.find((p) => p.id === prefs.prayer);
      if (!prayer) {
        preview.replaceChildren(el("p", { class: "still-hint", text: "No words this time. Just breathe with the light, and let God be near." }));
        return;
      }
      preview.replaceChildren(el("p", { class: "still-hint", text: "Finding the verse…" }));
      try {
        const lines = await prayerLines(prayer);
        if (prefs.prayer !== prayer.id) return; // another was picked meanwhile
        preview.replaceChildren(
          el("p", { class: "still-line" }, [el("span", { class: "still-cue", text: "In" }), el("span", { class: "scripture", text: lines.in })]),
          el("p", { class: "still-line" }, [el("span", { class: "still-cue", text: "Out" }), el("span", { class: "scripture", text: lines.out })]),
          el("p", { class: "verse-ref", text: `${prayer.ref} · ${lines.translation}` })
        );
      } catch {
        preview.replaceChildren(el("p", { class: "still-hint", text: "Couldn't find this verse just now. You can still breathe with the light." }));
      }
    }
    const prayerChips = el("div", { class: "moods", role: "group", "aria-label": "Pray as you breathe" },
      [...BREATH_PRAYERS.map((p) => [p.id, p.theme]), [NO_PRAYER, "Just breathe"]].map(([id, label]) => el("button", {
        class: "mood", type: "button", "aria-pressed": String(prefs.prayer === id), text: label,
        onclick: (e) => {
          prefs.prayer = id;
          save();
          prayerChips.querySelectorAll(".mood").forEach((b) => b.setAttribute("aria-pressed", String(b === e.currentTarget)));
          showPrayer();
        },
      })));

    // A row of choices that behaves like the sign-in switch.
    function segment(label, options, current, onPick) {
      const group = el("div", { class: "seg", role: "group", "aria-label": label }, options.map(([value, text]) => el("button", {
        type: "button", "aria-pressed": String(value === current), text,
        onclick: (e) => {
          group.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === e.currentTarget)));
          onPick(value);
        },
      })));
      return group;
    }
    const rhythmLine = el("p", { class: "still-hint", text: RHYTHMS[prefs.rhythm].line });
    const rhythms = segment("Rhythm", Object.entries(RHYTHMS).map(([key, r]) => [key, r.name]), prefs.rhythm, (key) => {
      prefs.rhythm = key;
      rhythmLine.textContent = RHYTHMS[key].line;
      save();
      paintSummary();
    });
    const lengths = segment("Length", LENGTHS.map((m) => [m, `${m} min`]), prefs.minutes, (m) => {
      prefs.minutes = m;
      save();
      paintSummary();
    });
    const tones = el("input", { type: "checkbox", checked: prefs.tones });
    tones.addEventListener("change", () => {
      prefs.tones = tones.checked;
      save();
      if (tones.checked) chime("in"); // a taste of it, and it unlocks sound on iPhones
    });

    const tally = weekTally();
    paintSummary();
    show(el("div", { class: "fade-in" }, [
      el("button", { class: "back", type: "button", html: `${ICON.back}<span>Refuge</span>`, onclick: threshold }),
      el("section", { class: "still" }, [
        cave().titleInfo(el("h2", { text: "Be still" }), "A few quiet minutes with God. Breathe with the light, and if you'd like, pray a line of Scripture as you do."),
        orb,
        el("p", { class: "still-hint", text: "Tap the light when you're ready. Find somewhere you can sit for a moment." }),
        el("div", { class: "card still-options" }, [
          el("div", { class: "still-field" }, [el("p", { class: "still-label", text: "Pray as you breathe" }), prayerChips, preview]),
          el("div", { class: "still-field" }, [el("p", { class: "still-label", text: "Rhythm" }), rhythms, rhythmLine]),
          el("div", { class: "still-field" }, [el("p", { class: "still-label", text: "Length" }), lengths]),
          el("label", { class: "switch still-switch" }, [tones, "Soft tones as the breath turns, so you can close your eyes"]),
        ]),
        el("p", { class: "still-tally", text: tally.times
          ? `This week: ${plural(tally.times, "quiet moment", "quiet moments")}, ${plural(tally.minutes, "minute", "minutes")}. Kept on this device only.`
          : "Nothing here leaves your device." }),
      ]),
    ]));
    showPrayer();
  }

  // What follows "How are you now?", and where each answer can lead.
  const STILL_AFTER = {
    calmer: { label: "Calmer", reply: "Carry this quiet with you into the rest of your day.", go: ["again", "refuge"] },
    same: { label: "About the same", reply: "That's alright. Showing up is enough, and God was here with you either way.", go: ["again", "write"] },
    heavy: { label: "Still heavy", reply: "Thank you for being honest. You don't have to carry it alone.", go: ["talk", "write", "person"] },
  };

  async function beginStill(prefs) {
    stopStill();
    const rhythm = RHYTHMS[prefs.rhythm];
    const cycle = rhythm.phases.reduce((sum, [, secs]) => sum + secs, 0);
    const total = Math.ceil((prefs.minutes * 60) / cycle) * cycle; // end on a whole breath
    const prayer = BREATH_PRAYERS.find((p) => p.id === prefs.prayer);
    const lines = prayer ? await prayerLines(prayer).catch(() => null) : null;

    // The stage: a progress ring around the light, the breath's word inside.
    const RADIUS = 146;
    const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
    const stage = el("div", { class: "still-stage", html: `<svg class="still-ring" viewBox="0 0 300 300" aria-hidden="true"><circle class="still-ring-track" cx="150" cy="150" r="${RADIUS}"/><circle class="still-ring-fill" cx="150" cy="150" r="${RADIUS}" stroke-dasharray="${CIRCUMFERENCE}" stroke-dashoffset="${CIRCUMFERENCE}"/></svg>` });
    const ringFill = stage.querySelector(".still-ring-fill");
    const light = el("div", { class: "still-light", "aria-hidden": "true" });
    const phaseWord = el("p", { class: "still-phase", "aria-live": "polite", text: "Settle in" });
    const count = el("p", { class: "still-count", "aria-hidden": "true" });
    stage.append(light, el("div", { class: "still-center" }, [phaseWord, count]));
    const words = el("p", { class: "still-words scripture" });
    const timeLeft = el("span", { class: "still-left", text: clock(total) });
    const pause = el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Pause", onclick: () => togglePause() });
    const end = el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "End", onclick: () => finish(false) });
    const tones = el("button", { class: "still-icon-btn", type: "button", "aria-pressed": String(prefs.tones), "aria-label": "Soft tones", title: "Soft tones", html: ICON.sound });
    tones.onclick = () => {
      prefs.tones = !prefs.tones;
      tones.setAttribute("aria-pressed", String(prefs.tones));
      writeLocal(STILL_PREFS_KEY, prefs);
    };
    const body = el("div", { class: "still-body" }, [stage, words, el("div", { class: "still-controls" }, [timeLeft, pause, end])]);
    const node = el("div", { class: "still-session", role: "dialog", "aria-modal": "true", "aria-label": "Be still", tabindex: "-1" }, [
      el("div", { class: "still-top" }, [
        el("span", { class: "still-ref", text: prayer && lines ? `${prayer.ref} · ${lines.translation}` : `${rhythm.name} · ${prefs.minutes} min` }),
        el("span", { class: "still-top-actions" }, [tones, el("button", { class: "still-icon-btn", type: "button", "aria-label": "Close", title: "Close", html: ICON.close, onclick: () => finish(false) })]),
      ]),
      body,
    ]);

    // Time runs from the clock, not from counting ticks, so a slow tick never
    // stretches a breath. Paused time is set aside.
    const startedAt = performance.now();
    let pausedAt = null;
    let pausedFor = 0;
    let lastPhase = null;
    const elapsed = () => ((pausedAt ?? performance.now()) - startedAt - pausedFor) / 1000 - SETTLE_SECONDS;

    function showWords(text) {
      if (words.textContent === text && words.classList.contains("is-shown")) return;
      words.classList.remove("is-shown");
      setTimeout(() => {
        words.textContent = text;
        words.classList.add("is-shown");
      }, 300);
    }

    // A new part of the breath: the light grows on the way in, rests on a
    // hold, and shrinks on the way out, over exactly the seconds left in it.
    function enterPhase(kind, secondsLeft) {
      phaseWord.textContent = PHASE_WORDS[kind];
      node.dataset.phase = kind;
      const moving = kind === "in" || kind === "out";
      light.style.transitionDuration = `${moving ? secondsLeft : 0.6}s`;
      light.style.transform = kind === "in" || kind === "hold" ? "scale(1)" : "scale(0.55)";
      if (lines) showWords(kind === "in" || kind === "hold" ? lines.in : lines.out);
      if (prefs.tones && moving) chime(kind);
    }

    function tick() {
      if (pausedAt !== null || still.done) return;
      const t = elapsed();
      if (t < 0) {
        count.textContent = String(Math.ceil(-t));
        return;
      }
      if (t >= total) return finish(true);
      const within = t % cycle;
      let start = 0;
      let index = 0;
      while (within >= start + rhythm.phases[index][1]) start += rhythm.phases[index++][1];
      const [kind, secs] = rhythm.phases[index];
      const secondsLeft = secs - (within - start);
      const phaseId = `${Math.floor(t / cycle)}:${index}`;
      if (phaseId !== lastPhase) {
        lastPhase = phaseId;
        enterPhase(kind, secondsLeft);
      }
      count.textContent = String(Math.ceil(secondsLeft));
      timeLeft.textContent = `${clock(total - t)} left`;
      ringFill.style.strokeDashoffset = String(CIRCUMFERENCE * (1 - t / total));
    }

    function togglePause() {
      if (still.done) return;
      if (pausedAt === null) {
        pausedAt = performance.now();
        // Hold the light where it is, mid-breath.
        const now = getComputedStyle(light).transform;
        light.style.transitionDuration = "0s";
        light.style.transform = now;
        phaseWord.textContent = "Paused";
        count.textContent = "";
        pause.textContent = "Resume";
        node.classList.add("is-paused");
      } else {
        pausedFor += performance.now() - pausedAt;
        pausedAt = null;
        lastPhase = null; // pick the breath up again from where it was
        pause.textContent = "Pause";
        node.classList.remove("is-paused");
        if (elapsed() < 0) phaseWord.textContent = "Settle in";
        tick();
      }
    }

    // Ending on time, or early. A pause of any length counts this week once
    // it's had a few breaths; closing after the check-in just goes back.
    function finish(completed) {
      if (still.done) {
        stopStill();
        stillRoom();
        return;
      }
      const breathed = Math.max(0, Math.min(elapsed(), total));
      still.done = true;
      clearInterval(still.timer);
      if (still.wake) still.wake.release().catch(() => {});
      still.wake = null;
      if (breathed >= RECORD_AFTER) recordStill(breathed);
      if (!completed && breathed < RECORD_AFTER) {
        stopStill();
        stillRoom();
        return;
      }
      if (prefs.tones) chime("end");
      showAfter(breathed);
    }

    function showAfter(seconds) {
      tones.hidden = true;
      const reply = el("div", { class: "still-reply", "aria-live": "polite" });
      const actions = {
        again: () => el("button", { class: "btn btn-ember btn-sm", type: "button", text: "Another round", onclick: () => beginStill(prefs) }),
        refuge: () => el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Back to Refuge", onclick: threshold }),
        write: () => el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Write it out", onclick: () => writeRoom() }),
        talk: () => el("button", { class: "btn btn-ember btn-sm", type: "button", text: "Talk with Aquila", onclick: () => talkRoom() }),
        person: () => el("button", { class: "linkish", type: "button", text: "Need a person?", onclick: helpRoom }),
      };
      const feelings = el("div", { class: "moods still-feel", role: "group", "aria-label": "How are you now?" },
        Object.entries(STILL_AFTER).map(([key, after]) => el("button", {
          class: "mood", type: "button", "aria-pressed": "false", text: after.label,
          onclick: (e) => {
            feelings.querySelectorAll(".mood").forEach((b) => b.setAttribute("aria-pressed", String(b === e.currentTarget)));
            reply.replaceChildren(el("p", { text: after.reply }), el("div", { class: "still-actions" }, after.go.map((go) => actions[go]())));
          },
        })));
      const minutes = Math.max(1, Math.round(seconds / 60));
      body.replaceChildren(el("div", { class: "still-after fade-in" }, [
        el("div", { class: "still-orb-light still-after-light", "aria-hidden": "true" }),
        el("h2", { text: "Rest here a moment" }),
        el("p", { class: "muted", text: `${plural(minutes, "quiet minute", "quiet minutes")} with God.` }),
        lines ? el("blockquote", { class: "still-verse" }, [
          el("p", { class: "scripture", text: lines.text }),
          el("p", { class: "verse-ref", text: `${prayer.ref} · ${lines.translation}` }),
        ]) : null,
        el("p", { class: "still-ask", text: "How are you now?" }),
        feelings,
        reply,
      ]));
    }

    still = {
      node,
      done: false,
      wake: null,
      timer: null,
      // Space pauses and Escape closes, unless a button has the key.
      onKey: (e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          finish(false);
        } else if (e.key === " " && !e.target.closest("button, input, textarea, a")) {
          e.preventDefault();
          togglePause();
        }
      },
      onVisible: () => {
        if (document.visibilityState === "visible") keepScreenOn();
      },
    };
    document.body.append(node);
    document.body.classList.add("still-open");
    document.addEventListener("keydown", still.onKey);
    document.addEventListener("visibilitychange", still.onVisible);
    keepScreenOn();
    node.focus();
    count.textContent = String(SETTLE_SECONDS);
    still.timer = setInterval(tick, 200);
  }

  // ---------------------------------------------------------------------
  // Amens (app/one_another.py; it was "One another" at first)
  // ---------------------------------------------------------------------
  // Saying amen is the wall's one reaction, counted once per person by the
  // server (app/one_another.py), but it reads as what it means on each kind
  // of post. On a burden you say a prayer, and once you have, the button
  // turns to "Amen", agreeing with it; on good news you rejoice, and it
  // turns to "Amen" the same way. Each kind has its words for the button,
  // the line under a post ("You and 4 others prayed for this"), the count
  // on a bubble, and what the person who shared it sees.
  const REACTIONS = {
    burden: {
      icon: ICON.pray,
      action: "Say a prayer",
      verb: "Pray",
      hint: "Pray for them in your own words, then tap to say amen.",
      short: (n) => plural(n, "prayer", "prayers"),
      others: (n) => (n ? `${plural(n, "person has", "people have")} prayed for this` : "Be the first to pray for this"),
      withYou: (n) => (n > 1 ? `You and ${plural(n - 1, "other", "others")} prayed for this` : "You prayed for this"),
      forMine: (n) => (n ? `${plural(n, "person", "people")} prayed for you` : "No prayers yet"),
    },
    rejoice: {
      icon: ICON.rejoice,
      action: "Rejoice with them",
      verb: "Rejoice",
      hint: "Thank God with them, then tap to say amen.",
      short: (n) => `${n} rejoicing`,
      others: (n) => (n ? `${plural(n, "person is", "people are")} rejoicing` : "Be the first to rejoice with them"),
      withYou: (n) => (n > 1 ? `You and ${plural(n - 1, "other", "others")} are rejoicing` : "You're rejoicing with them"),
      forMine: (n) => (n ? `${plural(n, "person", "people")} rejoiced with you` : "No amens yet"),
    },
  };

  // A few anonymous faces for the people who said amen: never who they are,
  // just a sense that real people are here. Three at most.
  function amenFaces(n) {
    return el("span", { class: "amen-faces", "aria-hidden": "true" },
      Array.from({ length: Math.min(n, 3) }, (_, i) => el("span", { class: `amen-face amen-face-${i + 1}` })));
  }
  // The share box's prompts. Closed, it's one short line; open, the fuller
  // invitation stands in for a description under the room's title.
  const SHARE_TEASER = "Share a burden or a joy, anonymously";
  const SHARE_PROMPT = "Share your burdens or joys anonymously. Let people pray and rejoice with you, and send a few kind words.";
  // `choose` names the kind in the share box, on the admin desk and at the top
  // of each bubble, as the ask it is: the same words as the buttons others
  // answer with ("Say a prayer", "Rejoice with them").
  const POST_KINDS = {
    burden: { choose: "Pray for me", who: "Someone asked for prayer", mineWho: "Your prayer request" },
    rejoice: { choose: "Rejoice with me", who: "Someone has good news", mineWho: "Your good news" },
    // A prayer request its writer marked answered: good news for a few days.
    answered: { choose: "Answered", who: "God answered a prayer", mineWho: "Your answered prayer" },
  };
  // How a post on the wall reads: an answered prayer as good news.
  const shownKind = (post) => (post.answered ? "rejoice" : post.kind);
  const kindSpec = (post) => POST_KINDS[post.answered ? "answered" : post.kind];
  const MINE_STATUS = {
    waiting: ["Waiting for approval", "plain"], shared: ["On the wall", "answered"],
    ended: ["Off the wall", "plain"], not_shared: ["Not shared", "plain"],
  };

  // How long a post stays on the wall (app/one_another.py::LIFETIME_DAYS),
  // as "How Amens works" and the info buttons put it. Keep in step.
  const HOW_LONG = "A prayer request stays on the wall for two weeks, and you can keep it up two weeks more at a time, up to two months. Good news stays a week. Mark a prayer answered and it stays five more days as good news, so everyone who prayed can see. Your own copy never goes away.";

  // A kind word as the writer sees it, with how many people sent it.
  function kindWordNode(w) {
    const times = w.count > 1 ? el("span", { class: "encouragement-count", text: `×${w.count}` }) : null;
    return el("div", { class: "encouragement" }, w.ref
      ? [el("span", { class: "scripture", text: w.text }), " ", el("span", { class: "verse-ref", text: `${w.ref} · ${w.translation}` }), times]
      : [w.text, times]);
  }
  // How many kind words came back to one of the person's own posts.
  const kindWordCount = (post) => post.kind_word_count ?? post.kind_words.reduce((n, w) => n + (w.count || 1), 0);

  async function kindWordsSheet(post, onSent) {
    let choices;
    try {
      choices = await api(`/me/refuge/kind-words?kind=${shownKind(post)}&translation=${encodeURIComponent(translation())}`);
    } catch (err) {
      return toast(err.message, { tone: "error" });
    }
    const msg = cave().formMessage();
    const options = choices.map((w, i) => el("label", { class: "choice" }, [
      el("input", { type: "radio", name: "kindWord", value: w.id, checked: i === 0 }),
      el("span", {}, w.ref ? [el("span", { class: "scripture", style: "font-size:16px", text: w.text }), el("br"), el("span", { class: "verse-ref", text: w.ref })] : w.text),
    ]));
    const send = el("button", { class: "btn btn-ember btn-sm", type: "submit", text: "Send" });
    const form = el("form", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "kindTitle" }, [
      cave().sheetTitle("kindTitle", "Send a few kind words", "They'll see the one you choose, but never who sent it, and they can't write back."),
      el("div", { class: "choice-list" }, options),
      msg.node,
      el("div", { class: "sheet-actions" }, [el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Cancel", onclick: () => close() }), send]),
    ]);
    const close = cave().overlay(form);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const picked = form.querySelector("input[name=kindWord]:checked");
      if (!picked) return msg.say("Choose one.", true);
      send.disabled = true;
      try {
        await api(`/me/refuge/posts/${post.id}/kind-words`, { method: "POST", body: { choice: picked.value } });
        close();
        toast("Sent. You may never know what it meant to them.");
        onSent();
      } catch (err) {
        msg.say(err.message, true);
        send.disabled = false;
      }
    });
  }

  // Why a post is reported; the keys match app/one_another.py::REPORT_CATEGORIES.
  // "danger" goes to the top of the admin desk and alerts the people there.
  const REPORT_REASONS = [
    ["danger", "Someone may be in danger"],
    ["identifies", "It names or could identify someone"],
    ["unkind", "It's hurtful or hateful"],
    ["spam", "It's spam or selling something"],
    ["other", "Something else"],
  ];
  const REPORT_LABEL = Object.fromEntries(REPORT_REASONS);

  function reportSheet(post, onReported) {
    const category = el("select", { class: "field", required: true }, [
      el("option", { value: "", text: "Choose one", disabled: true, selected: true }),
      ...REPORT_REASONS.map(([value, text]) => el("option", { value, text })),
    ]);
    const danger = el("p", { class: "desk-note", hidden: true, text: "If you know someone is in danger right now, call your local emergency number. We'll look at this first." });
    category.addEventListener("change", () => { danger.hidden = category.value !== "danger"; });
    const reason = el("textarea", { class: "field", maxlength: "300", rows: "3", placeholder: "Anything else we should know? Optional." });
    const msg = cave().formMessage();
    const send = el("button", { class: "btn btn-ember btn-sm", type: "submit", text: "Report" });
    const form = el("form", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "reportTitle" }, [
      cave().sheetTitle("reportTitle", "Report this", "It comes off the wall straight away, and a person looks at it again."),
      el("label", { class: "field-wrap" }, ["Why", category]),
      danger,
      el("label", { class: "field-wrap" }, ["Details", reason]),
      msg.node,
      el("div", { class: "sheet-actions" }, [el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Cancel", onclick: () => close() }), send]),
    ]);
    const close = cave().overlay(form);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      send.disabled = true;
      try {
        await api(`/me/refuge/posts/${post.id}/report`, { method: "POST", body: { category: category.value, reason: reason.value.trim() || null } });
        close();
        toast("Thank you. A person will look at it.");
        onReported();
      } catch (err) {
        msg.say(err.message, true);
        send.disabled = false;
      }
    });
  }

  // A post with its actions. `onChange` hears about an amen or kind words,
  // so the bubble it was opened from can show them too.
  function wallCard(post, rerender, onChange) {
    const spec = kindSpec(post);
    const r = REACTIONS[shownKind(post)];
    const people = el("span");
    const tally = el("p", { class: "amen-people", "aria-live": "polite" });
    const react = el("button", { class: "amen-btn", type: "button" });
    const paint = () => {
      const n = post.reactions || 0;
      tally.replaceChildren(amenFaces(n), people);
      people.textContent = post.reacted ? r.withYou(n) : r.others(n);
      react.classList.toggle("is-done", !!post.reacted);
      react.disabled = !!post.reacted;
      react.title = post.reacted ? "" : r.hint;
      react.innerHTML = post.reacted ? `${ICON.check}<span>Amen</span>` : `${r.icon}<span>${r.action}</span>`;
    };
    paint();
    react.onclick = async () => {
      react.disabled = true;
      try {
        const res = await api(`/me/refuge/posts/${post.id}/react`, { method: "POST" });
        post.reacted = true;
        post.reactions = res.reactions;
        paint();
        react.classList.add("is-saying"); // the one-off glow as it turns to Amen
        if (onChange) onChange("amen");
      } catch (err) {
        react.disabled = false;
        toast(err.message, { tone: "error" });
      }
    };
    const words = el("button", { class: `act${post.sent_kind_word ? " is-done" : ""}`, type: "button", disabled: post.sent_kind_word, text: post.sent_kind_word ? "Kind words sent" : "Send kind words" });
    words.onclick = () => kindWordsSheet(post, () => {
      words.classList.add("is-done");
      words.disabled = true;
      words.textContent = "Kind words sent";
      post.sent_kind_word = true;
      if (onChange) onChange("words");
    });
    return el("article", { class: `burden burden-${shownKind(post)} fade-in` }, [
      el("p", { class: "burden-who", text: spec.who }),
      el("p", { class: "burden-text", text: post.body }),
      post.answered && post.answer_note ? el("p", { class: "answered-note" }, [el("strong", { text: "How: " }), post.answer_note]) : null,
      tally,
      el("div", { class: "burden-actions" }, [
        react, words,
        el("button", { class: "report", type: "button", text: "Report", onclick: () => reportSheet(post, rerender) }),
      ]),
    ]);
  }

  // On the wall, each post is a bubble. Its size follows the post's length,
  // it drifts on its own rhythm (staggered by `index`), and tapping it opens
  // the whole post with its actions. Saying amen makes the bubble pulse.
  function bubbleSize(text) {
    return text.length <= 70 ? "s" : text.length <= 170 ? "m" : "l";
  }

  function bubble(post, index, rerender) {
    const spec = kindSpec(post);
    const count = el("span", { class: "bubble-count" });
    const node = el("button", {
      class: `bubble bubble-${shownKind(post)} bubble-${bubbleSize(post.body)}${post.answered ? " is-answered" : ""}`,
      type: "button",
      style: `--drift-delay:${-((index * 1.7) % 7).toFixed(1)}s;--drift-time:${6 + (index % 4)}s`,
      "aria-label": `${spec.who}: ${post.body}`,
    }, [
      el("span", { class: "bubble-who", text: spec.choose }),
      el("span", { class: "bubble-text", text: post.body }),
      count,
    ]);
    const r = REACTIONS[shownKind(post)];
    const paint = () => {
      const n = post.reactions || 0;
      count.innerHTML = `${post.reacted ? ICON.check : r.icon}<span></span>`;
      count.lastChild.textContent = post.reacted ? (n > 1 ? `Amen · ${r.short(n)}` : "Amen") : (n ? r.short(n) : r.verb);
      node.classList.toggle("is-amened", !!post.reacted);
    };
    paint();
    node.onclick = () => openBubble(post, rerender, (what) => {
      paint();
      if (what !== "amen") return;
      node.classList.remove("is-popping");
      void node.offsetWidth; // restart the pulse if it ran before
      node.classList.add("is-popping");
    });
    return node;
  }

  function openBubble(post, rerender, onChange) {
    const close = cave().overlay(el("div", { class: "sheet bubble-sheet", role: "dialog", "aria-modal": "true", "aria-label": kindSpec(post).who }, [
      // A report takes the post off the wall, so the wall is drawn again.
      wallCard(post, () => { close(); rerender(); }, onChange),
      el("div", { class: "sheet-actions" }, el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Close", onclick: () => close() })),
    ]));
  }

  // What this person has shared, as small bubbles in one row that scrolls
  // sideways, so it never pushes the wall down the page. Each shows what came
  // back once it's on the wall (or that it wasn't shared), and tapping it
  // opens the whole post, the kind words and "Take it down". Posts still
  // waiting for approval sit apart, in waitingZone.
  const MINE_BUBBLE_STATUS = { waiting: "Waiting", ended: "Off the wall", not_shared: "Not shared" };

  // One of this person's own posts, opened in a sheet.
  function openMine(post, rerender) {
    const close = cave().overlay(el("div", { class: "sheet bubble-sheet", role: "dialog", "aria-modal": "true", "aria-label": POST_KINDS[post.kind].mineWho }, [
      // Taking it down redraws the room, so the sheet goes first.
      mineCard(post, () => { close(); rerender(); }),
      el("div", { class: "sheet-actions" }, el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Close", onclick: () => close() })),
    ]));
  }

  // Posts waiting for a person to approve them, just under the share box.
  // Folded, it's one slim line, like a notification ("2 waiting for
  // approval", with a dot per post in its colour), so it never pushes the
  // wall down however many are waiting. Opened, it's a compact list: a dot
  // for the kind, the words, and when. Tapping a post opens it, where it can
  // still be taken down. Whether it's open survives the room redrawing.
  let waitingOpen = false;

  function waitingZone(posts, rerender) {
    const n = posts.length;
    const zone = el("details", { class: "waiting fade-in" }, [
      el("summary", { class: "waiting-bar" }, [
        el("span", { class: "waiting-icon", html: ICON.clock }),
        el("span", { class: "waiting-label" }, [
          el("strong", { text: String(n) }),
          ` ${n === 1 ? "post" : "posts"} waiting for approval`,
        ]),
        el("span", { class: "waiting-dots", "aria-hidden": "true" },
          posts.slice(0, 5).map((post) => el("span", { class: `waiting-dot waiting-dot-${post.kind}` }))),
        el("span", { class: "waiting-chevron", "aria-hidden": "true", html: ICON.forward }),
      ]),
      el("div", { class: "waiting-body" }, [
        el("p", { class: "waiting-note", text: "The automatic check wasn't sure about these, so a person looks first, usually within a day. Then they move to \"What you've shared\"." }),
        el("ul", { class: "waiting-list" }, posts.map((post) => el("li", {}, el("button", {
          class: "waiting-item", type: "button", "aria-label": `${POST_KINDS[post.kind].choose}, waiting for approval: ${post.body}`,
          onclick: () => openMine(post, rerender),
        }, [
          el("span", { class: `waiting-dot waiting-dot-${post.kind}`, title: POST_KINDS[post.kind].choose }),
          el("span", { class: "waiting-text", text: post.body }),
          el("span", { class: "waiting-when", text: shortDate(post.created_at) }),
        ])))),
      ]),
    ]);
    zone.open = waitingOpen;
    zone.addEventListener("toggle", () => { waitingOpen = zone.open; });
    return zone;
  }

  function mineBubble(post, index, rerender) {
    const r = REACTIONS[post.kind];
    const n = post.reactions || 0;
    const words = kindWordCount(post);
    // Its amens show whether it's on the wall or has left it.
    const shared = post.status === "shared" || post.status === "ended";
    // On the wall it reads like the wall's own bubbles; before that, its status.
    const who = post.answered ? POST_KINDS.answered.choose : post.status === "shared" ? POST_KINDS[post.kind].choose : MINE_BUBBLE_STATUS[post.status];
    const count = el("span", { class: "bubble-count" });
    if (shared) {
      count.innerHTML = `${r.icon}<span></span>${words ? `${ICON.talk}<span></span>` : ""}`;
      const [amens, kind] = count.querySelectorAll("span");
      amens.textContent = n ? String(n) : "None yet";
      if (kind) kind.textContent = String(words);
    }
    const label = shared
      ? `${r.forMine(n)}${words ? `, ${plural(words, "kind word", "kind words")}` : ""}. ${post.body}`
      : `${who}. ${post.body}`;
    const node = el("button", {
      class: `bubble bubble-mine bubble-${post.kind} is-${post.status.replace("_", "-")}${n ? " has-amens" : ""}`,
      type: "button",
      style: `--drift-delay:${-((index * 1.3) % 6).toFixed(1)}s;--drift-time:${7 + (index % 3)}s`,
      "aria-label": label,
    }, [
      el("span", { class: "bubble-who", text: who }),
      el("span", { class: "bubble-text", text: post.body }),
      shared ? count : null,
    ]);
    node.onclick = () => openMine(post, rerender);
    return node;
  }

  // How long one of the writer's own posts has on the wall.
  function wallTime(post) {
    if (post.status === "ended") return "It's left the wall. It stays here for you, with everything that came back.";
    if (post.status !== "shared") return null;
    if (post.days_left <= 0) return "On the wall until later today.";
    return `On the wall for ${plural(post.days_left, "more day", "more days")}.`;
  }

  // "Keep it up": a prayer request two weeks more on the wall.
  async function keepUp(post, rerender) {
    try {
      await api(`/me/refuge/posts/${post.id}/keep-up`, { method: "POST" });
      toast("It's on the wall for two more weeks.");
      rerender();
    } catch (err) {
      toast(err.message, { tone: "error" });
    }
  }

  // "God answered": a line on how, then good news on the wall for five days.
  function answeredSheet(post, rerender) {
    const note = el("textarea", { maxlength: "280", rows: "3", placeholder: "Mum's surgery went well. Thank you for praying." });
    const msg = cave().formMessage();
    const save = el("button", { class: "btn btn-ember btn-sm", type: "submit", text: "Share the answer" });
    const form = el("form", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "answeredTitle" }, [
      cave().sheetTitle("answeredTitle", "God answered", "It stays on the wall five more days as good news, so everyone who prayed can see. Without your name, as always."),
      el("label", { class: "field-wrap" }, ["How (optional)", note]),
      msg.node,
      el("div", { class: "sheet-actions" }, [el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Cancel", onclick: () => close() }), save]),
    ]);
    const close = cave().overlay(form);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      save.disabled = true;
      try {
        await api(`/me/refuge/posts/${post.id}/answered`, { method: "POST", body: { note: note.value.trim() || null } });
        close();
        toast("Thank God. Everyone who prayed will see it.");
        rerender();
      } catch (err) {
        msg.say(err.message, true);
        save.disabled = false;
      }
    });
  }

  function mineCard(post, rerender) {
    const spec = post.answered ? POST_KINDS.answered : POST_KINDS[post.kind];
    const r = REACTIONS[post.kind];
    const [statusText, statusClass] = post.answered ? ["Answered", "answered"] : MINE_STATUS[post.status];
    const n = post.reactions || 0;
    const words = kindWordCount(post);
    const cameBack = post.status === "shared" || post.status === "ended";
    const canAnswer = post.kind === "burden" && !post.answered && post.status !== "not_shared";
    return el("article", { class: "burden is-mine fade-in" }, [
      el("div", { class: "entry-meta" }, [el("span", { class: `badge ${statusClass}`, text: statusText }), el("span", { text: `${spec.mineWho} · ${shortDate(post.created_at)}` })]),
      el("p", { class: "burden-text", text: post.body }),
      post.answered && post.answer_note ? el("p", { class: "answered-note" }, [el("strong", { text: "How: " }), post.answer_note]) : null,
      // What came back to them: the amens as people, and the kind words.
      cameBack ? el("div", { class: `amen-summary${n ? " has-amens" : ""}` }, [
        el("span", { class: "amen-summary-icon", html: r.icon }),
        el("div", { class: "amen-summary-text" }, [
          el("strong", { text: r.forMine(n) }),
          el("span", { text: words ? `${n ? "and " : ""}${plural(words, "kind word", "kind words")} sent to you` : n ? "Each one is someone who stopped for you." : "It's on the wall, and people will see it." }),
        ]),
        n ? amenFaces(n) : null,
      ]) : null,
      cameBack ? el("p", { class: "mine-time" }, [wallTime(post), " ", cave().info(HOW_LONG, { label: "How long a post stays" })]) : null,
      post.status === "waiting" ? el("p", { class: "faint", style: "font-size:14px", text: "A person is looking at this before it's shared. It'll appear on the wall once they have." }) : null,
      post.status === "not_shared" ? el("p", { class: "faint", style: "font-size:14px", text: "This one wasn't shared on the wall. It's still here for you, and you can take it down." }) : null,
      post.kind_words.length ? el("div", { class: "encouragements" }, post.kind_words.map(kindWordNode)) : null,
      el("div", { class: "burden-actions" }, [
        post.can_keep_up ? el("button", { class: "btn btn-ember btn-sm", type: "button", text: post.status === "ended" ? "Put it back up" : "Keep it up 2 more weeks", onclick: () => keepUp(post, rerender) }) : null,
        canAnswer ? el("button", { class: "act", type: "button", html: `${ICON.check}<span>God answered</span>`, onclick: () => answeredSheet(post, rerender) }) : null,
        el("button", { class: "act danger", type: "button", text: "Take it down", onclick: async () => {
          if (!confirm("Take this down? It comes off the wall for everyone, and you won't see it here again.")) return;
          try {
            await api(`/me/refuge/posts/${post.id}`, { method: "DELETE" });
            rerender();
          } catch (err) {
            toast(err.message, { tone: "error" });
          }
        } }),
      ]),
    ].filter(Boolean));
  }

  // A quiet line under the share box when one of the person's prayer
  // requests is about to leave the wall, or just has: keep it up?
  function keepUpNudge(mine, rerender) {
    const post = mine.find((p) => p.can_keep_up);
    if (!post) return null;
    const when = post.status === "ended" ? "has left the wall" : post.days_left <= 0 ? "leaves the wall today" : `leaves the wall in ${plural(post.days_left, "day", "days")}`;
    return el("div", { class: "keep-up-nudge fade-in" }, [
      el("span", { class: "keep-up-icon", html: ICON.clock }),
      el("span", { class: "keep-up-text" }, [el("strong", { text: `Your prayer request ${when}.` }), el("small", { text: post.body })]),
      el("span", { class: "keep-up-actions" }, [
        el("button", { class: "btn btn-ember btn-sm", type: "button", text: post.status === "ended" ? "Put it back up" : "Keep it up", onclick: () => keepUp(post, rerender) }),
        el("button", { class: "linkish", type: "button", text: "God answered", onclick: () => answeredSheet(post, rerender) }),
      ]),
    ]);
  }

  // The share box, as a compact composer: one line until it's tapped, then
  // the two kinds, the fine print and the share button open beneath it. It
  // grows with what's written and folds away again once something is shared.
  const SHARE_MAX = 280;

  function shareBox(rerender) {
    let kind = "burden";
    const box = el("textarea", { class: "amens-composer-text", rows: "1", maxlength: String(SHARE_MAX), placeholder: SHARE_TEASER, "aria-label": "What you want to share" });
    const count = el("span", { class: "amens-composer-count", text: String(SHARE_MAX) });
    const fit = () => {
      box.style.height = "auto";
      box.style.height = `${box.scrollHeight}px`;
    };
    // Only the two kinds someone can share; "answered" comes later, from the post.
    const kinds = el("div", { class: "seg amens-composer-kinds", role: "group", "aria-label": "What you're sharing" }, ["burden", "rejoice"].map((key) => {
      const spec = POST_KINDS[key];
      const b = el("button", { type: "button", "aria-pressed": String(key === kind) }, [
        el("span", { html: REACTIONS[key].icon }),
        el("span", { text: spec.choose }),
      ]);
      b.onclick = () => {
        kind = key;
        kinds.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
        box.focus();
      };
      return b;
    }));
    const msg = cave().formMessage();
    const care = el("div", { hidden: true });
    const send = el("button", { class: "btn btn-ember btn-sm", type: "button", text: "Share" });

    const composer = el("section", { class: "amens-composer" });
    const open = () => {
      if (composer.classList.contains("is-open")) return;
      composer.classList.add("is-open");
      box.placeholder = SHARE_PROMPT;
      fit();
    };
    const fold = () => {
      composer.classList.remove("is-open");
      box.placeholder = SHARE_TEASER;
      box.style.height = "";
    };
    box.addEventListener("focus", open);
    box.addEventListener("input", () => {
      count.textContent = String(SHARE_MAX - box.value.length);
      count.classList.toggle("is-low", SHARE_MAX - box.value.length <= 20);
      fit();
    });

    send.onclick = async () => {
      const body = box.value.trim();
      if (!body) return msg.say("Write a little first.", true);
      send.disabled = true;
      msg.say("");
      try {
        const res = await api("/me/refuge/posts", { method: "POST", body: { kind, body } });
        if (res.outcome === "care") {
          // Not posted. What they wrote matters too much for a wall.
          care.hidden = false;
          care.replaceChildren(el("div", { class: "care-panel" }, [
            el("p", { text: "Thank you for trusting us with this. It sounds like you may not be safe right now, and you deserve a real person with you, not a wall. These are free and there for exactly this." }),
            el("div", { class: "care-card" }, helplineRows("care-line")),
            el("div", { class: "card-actions-row" }, [
              el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Talk with Aquila", onclick: () => { talk = null; talkRoom(body); } }),
              el("button", { class: "linkish", type: "button", text: "More people to talk to", onclick: helpRoom }),
            ]),
          ]));
          return;
        }
        box.value = "";
        count.textContent = String(SHARE_MAX);
        fold();
        toast(res.outcome === "shared"
          ? "It's on the wall. People can pray and rejoice with you now."
          : "Thank you. A person will look at it first, then people can pray and rejoice with you.");
        rerender();
      } catch (err) {
        msg.say(err.message, true);
      } finally {
        send.disabled = false;
      }
    };

    composer.append(
      el("div", { class: "amens-composer-row" }, [el("span", { class: "amens-composer-icon", html: ICON.pen }), box]),
      el("div", { class: "amens-composer-more" }, [
        el("div", { class: "amens-composer-bar" }, [kinds, el("span", { class: "amens-composer-send" }, [count, send])]),
        msg.node,
        el("p", { class: "amens-composer-note", text: "Shared without your name. It's checked as it goes up, and you can take it down any time." }),
      ]),
      care
    );
    return composer;
  }

  // "How Amens works", opened from the info button beside the room's title.
  const HOW_AMENS_WORKS = [
    ["Share anonymously", "Choose \"Pray for me\" for something you're carrying, or \"Rejoice with me\" for good news. Share as much or as little as you like. Names and places are up to you, but links and contact details can't be posted."],
    ["Checked as it goes up", "Every post is checked as it's shared. Most go on the wall straight away; anything the check isn't sure of waits for a person to look at it first. A report sends a post to a person to look at, and usually takes it down while they do. Nobody, not even the people who check, is shown who wrote it."],
    ["Everyone gets prayed for", "There are no followers. Each person's wall shows posts they haven't prayed for first, starting with those fewest people have seen, so every request gets carried, not just the newest."],
    ["Others stand with you", "People can pray or rejoice with you, and send a few kind words: a verse or a short blessing. They can't write back, and you never see who they are."],
    ["How long it stays", HOW_LONG],
    ["See what came back", "Your posts sit under \"What you've shared\" with how many prayed or rejoiced, and any kind words. If you allow notifications, you get one quiet note in the evening when people prayed for you. You can take a post down any time."],
    ["If you're not safe", "If what you write sounds like you might be in danger, it isn't posted. You're shown people you can talk to right away instead."],
  ];

  function howAmensWorks() {
    const close = cave().overlay(el("div", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "amensHowTitle" }, [
      el("h3", { id: "amensHowTitle", text: "How Amens works" }),
      el("p", { class: "sheet-lede", text: "A quiet wall where people carry each other's burdens and share each other's joy." }),
      el("ol", { class: "how-steps" }, HOW_AMENS_WORKS.map(([title, text]) =>
        el("li", {}, [el("strong", { text: title }), el("span", { text })]))),
      el("div", { class: "sheet-actions" }, el("button", { class: "btn btn-ember btn-sm", type: "button", text: "Got it", onclick: () => close() })),
    ]));
  }

  // The evening note: one quiet notification when people prayed for or
  // rejoiced with what this person shared (app/one_another.py::run_digest).
  // On by default; it needs this device to allow notifications, so a small
  // "Allow on this device" shows when it's on and the device hasn't yet.
  function digestSwitch(on) {
    const box = el("input", { type: "checkbox", role: "switch" });
    box.checked = on;
    const notify = window.Notify;
    const allow = el("button", {
      class: "linkish digest-allow", type: "button", text: "Allow on this device",
      onclick: async () => { if (await notify.enable()) paint(); },
    });
    const paint = () => {
      allow.hidden = !(box.checked && notify && notify.supported() && Notification.permission !== "granted");
    };
    box.addEventListener("change", async () => {
      try {
        await api("/me", { method: "PATCH", body: { amens_digest: box.checked } });
        paint();
      } catch (err) {
        box.checked = !box.checked;
        toast(err.message, { tone: "error" });
      }
    });
    paint();
    return el("div", { class: "digest-row" }, [
      el("span", { class: "digest-icon", html: ICON.bell }),
      el("label", { class: "digest-label" }, [box, el("span", { text: "An evening note when people pray for you" })]),
      cave().info("Once a day, in your evening, a single notification says how many prayed or rejoiced with you and how many kind words came. Never who.", { label: "About the evening note" }),
      allow,
    ]);
  }

  async function amensRoom() {
    let data;
    try {
      data = await api(`/me/refuge/wall?translation=${encodeURIComponent(translation())}`);
    } catch (err) {
      return failed(err);
    }
    const rerender = () => amensRoom();
    // The wall comes a page at a time (app/one_another.py::wall). "Show more"
    // adds the next page's bubbles, skipping any already showing, since
    // amens said meanwhile can move a post between pages.
    const bubbles = el("div", { class: "bubble-wall" }, data.posts.map((p, i) => bubble(p, i, rerender)));
    const shown = new Set(data.posts.map((p) => p.id));
    let page = 0;
    const more = data.has_more ? el("button", {
      class: "btn btn-ghost btn-sm wall-more", type: "button", text: "Show more",
      onclick: async () => {
        more.disabled = true;
        try {
          const next = await api(`/me/refuge/wall?translation=${encodeURIComponent(translation())}&page=${page + 1}`);
          page = next.page;
          const fresh = next.posts.filter((p) => !shown.has(p.id));
          fresh.forEach((p) => shown.add(p.id));
          const at = bubbles.children.length;
          bubbles.append(...fresh.map((p, i) => bubble(p, at + i, rerender)));
          if (next.has_more) more.disabled = false;
          else more.remove();
        } catch (err) {
          more.disabled = false;
          toast(err.message, { tone: "error" });
        }
      },
    }) : null;
    // Waiting posts get their own zone; the rest are what's been through review.
    const waiting = data.mine.filter((p) => p.status === "waiting");
    const reviewed = data.mine.filter((p) => p.status !== "waiting");
    show(room("Amens", {
        text: [
          "Share a burden or a joy without your name. Others can pray or rejoice with you, and send a few kind words.",
          "Prayer requests stay two weeks (you can keep them up longer), good news a week.",
        ],
        more: howAmensWorks,
        moreLabel: "How Amens works",
      },
      shareBox(rerender),
      keepUpNudge(data.mine, rerender),
      waiting.length ? waitingZone(waiting, rerender) : null,
      reviewed.length ? el("section", { class: "wall-section" }, [
        el("p", { class: "kicker", text: "What you've shared" }),
        el("div", { class: "mine-row" }, reviewed.map((p, i) => mineBubble(p, i, rerender))),
        typeof data.digest === "boolean" ? digestSwitch(data.digest) : null,
      ]) : null,
      el("section", { class: "wall-section" }, [
        el("p", { class: "kicker", text: "On the wall" }),
        ...(data.posts.length
          ? [
              bubbles,
              more,
              el("p", { class: "bubble-hint", text: "Tap a bubble to read it, pray or rejoice with them, or send a few kind words." }),
            ]
          : [el("p", { class: "muted", text: "Nothing on the wall right now. When someone shares, it'll appear here for you to carry with them." })]),
      ])
    ));
  }

  // ---------------------------------------------------------------------
  // The Amens notice on the home screen (web/cave.js::showHome)
  // ---------------------------------------------------------------------
  // `glance` is app/one_another.py::amens_glance: this week's amens across the
  // whole wall and how many posts by other people have gone up since this
  // person last opened the wall that they haven't said amen to. Nothing this
  // person shared ever shows here.
  //
  // It reads like a notification rather than a card: one line, a count on
  // the icon, and the whole thing opens the wall. On a week with nothing
  // waiting and no amens said there is nothing to tell, so it stays away.
  function homeCard(glance) {
    const { waiting, this_week: thisWeek } = glance;
    if (!waiting && !thisWeek) return null;

    const title = waiting ? `${plural(waiting, "new post", "new posts")} on Amens` : "All caught up on Amens";
    const detail = thisWeek ? `${plural(thisWeek, "amen", "amens")} this week` : "Open the wall";

    return cave().homeNote({ href: "#amens", icon: ICON.together, count: waiting, title, detail });
  }

  // ---------------------------------------------------------------------
  // Someone to talk to
  // ---------------------------------------------------------------------
  function helpRoom() {
    const pick = el("select", { class: "field", style: "margin:0;max-width:240px", "aria-label": "Where you are" },
      Object.keys(HELPLINES).map((c) => el("option", { value: c, text: c, selected: c === country() })));
    pick.addEventListener("change", () => { setCountry(pick.value); helpRoom(); });
    const counsellors = [
      ["Association of Christians in Counselling (UK)", "Search for a counsellor who shares your faith.", "https://www.acc-uk.org"],
      ["American Association of Christian Counselors (US)", "A directory of Christian counsellors.", "https://www.aacc.net"],
      ["Psychology Today", "Most countries. Filter by faith to find Christian therapists.", "https://www.psychologytoday.com"],
    ].map(([name, how, href]) => el("div", { class: "help-line" }, [
      el("div", {}, [el("strong", { text: name }), el("span", { text: how })]),
      el("a", { class: "act", href, target: "_blank", rel: "noopener", text: "Visit" }),
    ]));
    const words = "Hi. I'm going through something and I'd like to talk to someone. Is there a pastor I could speak with?";

    show(room("Someone to talk to", "Aquila can listen, but some things need a person who can sit with you. These are real people.",
      el("section", { class: "card help-card urgent" }, [
        el("div", { class: "row-between", style: "flex-wrap:wrap;gap:10px" }, [el("h3", { class: "section-title", style: "margin:0", text: "If you're not safe right now" }), pick]),
        el("div", {}, helplineRows("help-line")),
      ]),
      el("section", { class: "card help-card" }, [
        el("div", {}, [el("h3", { class: "section-title", text: "A Christian counsellor" }), el("p", { class: "muted", style: "font-size:15px", text: "For grief, anxiety, marriage, addiction, or anything you'd rather work through with someone trained, over a few weeks." })]),
        el("div", {}, counsellors),
      ]),
      el("section", { class: "card help-card" }, [
        el("div", {}, [el("h3", { class: "section-title", text: "A church near you" }), el("p", { class: "muted", style: "font-size:15px", text: "Most churches are glad to talk with someone, member or not. Your location goes to the map, never to us." })]),
        el("div", {}, el("a", { class: "btn btn-ember btn-sm", href: "https://www.google.com/maps/search/church+near+me", target: "_blank", rel: "noopener", text: "Find churches near me" })),
        el("p", { class: "kicker", style: "margin:6px 0 0", text: "Not sure what to say? You could start with this" }),
        el("p", { class: "say-this", text: words }),
        el("div", {}, el("button", { class: "act", type: "button", text: "Copy", onclick: () => {
          if (navigator.clipboard) navigator.clipboard.writeText(words).then(() => toast("Copied.")).catch(() => toast("Couldn't copy.", { tone: "error" }));
        } })),
      ])
    ));
  }

  // ---------------------------------------------------------------------
  // The admin desk (#desk), for the people in ADMIN_EMAILS (app/desk.py).
  // Numbers across the top, then three tabs: To review (flagged by the
  // check, reported or held, urgent first), On the wall (each post's time
  // there) and History (the audit trail). Never who wrote or reported a post.
  // ---------------------------------------------------------------------
  const KIND_NAME = { burden: "Prayer request", rejoice: "Good news" };
  const QUEUE_STATUS = { pending: "Flagged by the check", reported: "Reported", held: "Held" };
  const STATUS_NOW = { pending: "waiting", reported: "reported", held: "held", approved: "approved", removed: "removed" };
  const DESK_TABS = [["review", "To review"], ["live", "On the wall"], ["log", "History"]];
  const DESK_FILTERS = {
    review: [["all", "Everything"], ["urgent", "Urgent"], ["pending", "Flagged by the check"], ["reported", "Reported"], ["held", "Held"]],
    live: [["all", "Everything on the wall"], ["ending", "Ending in 2 days"], ["burden", "Prayer requests"], ["rejoice", "Good news"], ["answered", "Answered prayers"], ["kept_up", "Kept up"]],
    log: [["all", "Every entry"], ["approve", "Approved or put back"], ["remove", "Removed"], ["hold", "Held"], ["report", "Reports"]],
  };
  // How an entry on the trail reads.
  const TRAIL_WORDS = {
    approve: (e) => ({ reported: "Put back after a report", held: "Put back after a hold", removed: "Restored" }[e.from_status] || "Approved"),
    remove: () => "Removed",
    hold: () => "Held off the wall",
    report: (e) => (e.from_status !== "approved" ? "Reported again" : e.to_status === "reported" ? "Reported, taken off the wall" : "Reported, left up for the desk"),
  };
  const desk = { tab: "review", show: { review: "all", live: "all", log: "all" } };

  const stamp = (iso) => new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  const clip = (text, n) => (text.length > n ? `${text.slice(0, n - 1).trimEnd()}...` : text);
  const times = (n) => (n === 1 ? "once" : n === 2 ? "twice" : `${n} times`);

  function openDesk(tab, show) {
    desk.tab = tab;
    if (show) desk.show[tab] = show;
    renderDesk();
  }

  async function decide(post, action, note) {
    await api(`/admin/refuge/${post.id}`, { method: "POST", body: { action, note: note || null } });
    toast({ approve: "On the wall.", remove: "Removed.", hold: "Held off the wall." }[action]);
  }

  // Removing or holding asks for an optional note for the trail; approving is one tap.
  function decideSheet(post, action, done) {
    const [title, about, verb] = {
      remove: ["Remove this post", "It leaves the wall for good. Its writer sees it as not shared, never why.", "Remove"],
      hold: ["Hold it off the wall", "It comes off the wall now and waits under To review until you put it back or remove it. Its writer sees it as waiting.", "Hold"],
    }[action];
    const note = el("textarea", { class: "field", maxlength: "300", rows: "2", placeholder: "Optional. Only the desk sees this." });
    const msg = cave().formMessage();
    const send = el("button", { class: "btn btn-ember btn-sm", type: "submit", text: verb });
    const form = el("form", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "deskDecideTitle" }, [
      cave().sheetTitle("deskDecideTitle", title, about),
      el("label", { class: "field-wrap" }, ["Note for the record", note]),
      msg.node,
      el("div", { class: "sheet-actions" }, [el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Cancel", onclick: () => close() }), send]),
    ]);
    const close = cave().overlay(form);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      send.disabled = true;
      try {
        await decide(post, action, note.value.trim());
        close();
        done();
      } catch (err) {
        msg.say(err.message, true);
        send.disabled = false;
      }
    });
  }

  function deskStats(s) {
    const tile = (n, label, tab, show, tone) => el("button", {
      class: `desk-stat${tone && n ? ` ${tone}` : ""}`, type: "button", onclick: () => openDesk(tab, show),
    }, [el("strong", { text: String(n) }), el("span", { text: label })]);
    return el("div", { class: "desk-stats" }, [
      tile(s.to_review, "To review", "review", "all"),
      tile(s.urgent, "Urgent", "review", "urgent", "urgent"),
      tile(s.reported, "Reported", "review", "reported"),
      tile(s.on_wall, "On the wall", "live", "all"),
      tile(s.ending_soon, "Ending in 2 days", "live", "ending"),
      tile(s.decided_week, "Decisions this week", "log", "all"),
    ]);
  }

  // A post's life so far, oldest first, folded away until it's wanted.
  function timeline(p) {
    const items = [["Shared", p.created_at]];
    // A post approved on the desk has that on the trail; otherwise it went up by itself.
    if (p.approved_at && !p.history.some((e) => e.action === "approve" && e.from_status === "pending")) items.push(["Went up", p.approved_at]);
    p.history.forEach((e) => items.push([`${TRAIL_WORDS[e.action](e)}${e.actor_email ? ` by ${e.actor_email}` : ""}`, e.created_at, e.note]));
    items.sort((a, b) => new Date(a[1]) - new Date(b[1]));
    return el("details", { class: "desk-trail" }, [
      el("summary", { text: `History (${items.length})` }),
      el("ol", {}, items.map(([what, at, note]) => el("li", {}, [
        el("span", { text: what }), el("time", { datetime: at, text: stamp(at) }), note ? el("p", { text: note }) : null,
      ].filter(Boolean)))),
    ]);
  }

  function reportsBlock(p) {
    if (!p.reports.length) return null;
    return el("div", { class: "desk-reports" }, [
      el("strong", { text: `Reported ${times(p.reports.length)}` }),
      ...p.reports.map((r) => el("p", { text: `${REPORT_LABEL[r.category] || REPORT_LABEL.other}${r.reason ? `: ${r.reason}` : ""} (${cave().when(r.created_at)})` })),
    ]);
  }

  function reviewCard(p, rerender) {
    const check = p.auto_check || {};
    const flagged = check.flagged || [];
    const notes = [
      check.error ? "The automatic check didn't run. Read this one closely." : null,
      flagged.length ? `The automatic check noticed: ${flagged.join(", ")}.` : null,
      p.status === "pending" && !check.error && !flagged.length ? "Nothing was flagged. It's here because every post waits for the desk at the moment." : null,
      p.still_up ? "Still on the wall. Whoever reported it had already taken down as many posts as one person can in a day." : null,
      p.put_back ? `Put back ${times(p.put_back)} before, and back again.` : null,
    ].filter(Boolean);
    const approve = el("button", {
      class: "btn btn-ember btn-sm", type: "button", text: p.status === "pending" ? "Approve" : p.still_up ? "Keep it up" : "Put it back",
      onclick: async () => {
        approve.disabled = true;
        try {
          await decide(p, "approve");
          rerender();
        } catch (err) {
          toast(err.message, { tone: "error" });
          approve.disabled = false;
        }
      },
    });
    return el("article", { class: `burden desk-card fade-in${p.urgent ? " is-urgent" : ""}` }, [
      el("div", { class: "entry-meta" }, [
        p.urgent ? el("span", { class: "badge urgent", text: "Urgent" }) : null,
        el("span", { class: "badge plain", text: p.still_up ? "Reported, still up" : QUEUE_STATUS[p.status] }),
        el("span", { text: `${KIND_NAME[p.kind]}, shared ${cave().when(p.created_at).toLowerCase()}` }),
      ].filter(Boolean)),
      el("p", { class: "burden-text", text: p.body }),
      ...notes.map((n) => el("p", { class: "desk-note", text: n })),
      reportsBlock(p),
      timeline(p),
      el("div", { class: "burden-actions" }, [
        approve,
        p.still_up ? el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Hold while I look", onclick: () => decideSheet(p, "hold", rerender) }) : null,
        el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Remove", onclick: () => decideSheet(p, "remove", rerender) }),
      ].filter(Boolean)),
    ].filter(Boolean));
  }

  function liveCard(p, rerender) {
    const ending = p.days_left <= 2;
    const facts = [
      plural(p.amen_count || 0, "amen", "amens"),
      p.kind_word_count ? plural(p.kind_word_count, "kind word", "kind words") : null,
      p.kept_up ? `kept up ${times(p.kept_up)}` : null,
      `up since ${new Date(p.approved_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}`,
    ].filter(Boolean).join(" · ");
    return el("article", { class: "burden desk-card fade-in" }, [
      el("div", { class: "entry-meta" }, [
        el("span", { class: `badge ${ending ? "" : "plain"}`, text: p.days_left <= 1 ? "Last day" : `${p.days_left} days left` }),
        el("span", { class: "badge plain", text: p.answered ? "Answered prayer" : KIND_NAME[p.kind] }),
        el("span", { text: facts }),
      ]),
      el("p", { class: "burden-text", text: p.body }),
      p.answer_note ? el("p", { class: "desk-note", text: `How it was answered: ${p.answer_note}` }) : null,
      p.reports.length ? el("p", { class: "desk-note", text: `Reported ${times(p.reports.length)} before${p.put_back ? `, put back ${times(p.put_back)}` : ""}.` }) : null,
      timeline(p),
      el("div", { class: "burden-actions" }, [
        el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Hold while I look", onclick: () => decideSheet(p, "hold", rerender) }),
        el("button", { class: "btn btn-ghost btn-sm danger-text", type: "button", text: "Remove", onclick: () => decideSheet(p, "remove", rerender) }),
      ]),
    ].filter(Boolean));
  }

  function logRow(e) {
    const post = e.post;
    return el("li", { class: "desk-log-row" }, [
      el("div", { class: "desk-log-head" }, [
        el("strong", { text: TRAIL_WORDS[e.action](e) }),
        el("span", { class: "faint", text: `${e.actor_email || "From the wall"} · ${stamp(e.created_at)}` }),
      ]),
      e.note ? el("p", { class: "desk-log-note", text: e.note }) : null,
      el("p", { class: "desk-log-post", text: post ? `${KIND_NAME[post.kind]}, now ${STATUS_NOW[post.status]}: "${clip(post.body, 140)}"` : "Its writer has since deleted this post." }),
    ].filter(Boolean));
  }

  // A list that comes a page at a time from the server, with "Show more".
  async function pagedList(path, key, draw, { tag = "div", cls = "desk-list", empty }) {
    let data = await api(`${path}&page=0`);
    const list = el(tag, { class: cls }, data[key].map(draw));
    const more = el("button", {
      class: "btn btn-ghost btn-sm desk-more", type: "button", text: "Show more", hidden: !data.has_more,
      onclick: async () => {
        more.disabled = true;
        try {
          data = await api(`${path}&page=${data.page + 1}`);
          list.append(...data[key].map(draw));
          more.hidden = !data.has_more;
        } catch (err) {
          toast(err.message, { tone: "error" });
        }
        more.disabled = false;
      },
    });
    const count = `${data[key].length}${data.has_more ? "+" : ""}`;
    return { count, nodes: data[key].length ? [list, more] : [el("p", { class: "faint", text: empty })] };
  }

  async function deskTab(data, rerender) {
    const show = desk.show[desk.tab];
    if (desk.tab === "review") {
      const matches = (p) => (show === "urgent" ? p.urgent : show === "reported" ? p.status === "reported" || p.still_up : p.status === show);
      const rows = data.queue.filter((p) => show === "all" || matches(p));
      return {
        count: plural(rows.length, "post", "posts"),
        nodes: rows.length ? [el("div", { class: "desk-list" }, rows.map((p) => reviewCard(p, rerender)))] : [el("p", { class: "faint", text: "Nothing waiting here." })],
      };
    }
    if (desk.tab === "live") {
      const page = await pagedList(`/admin/refuge/live?show=${show}`, "posts", (p) => liveCard(p, rerender), { empty: "Nothing on the wall here right now." });
      return { count: `${page.count} on the wall, soonest to leave first`, nodes: page.nodes };
    }
    const page = await pagedList(`/admin/refuge/log?action=${show}`, "entries", logRow, { tag: "ol", cls: "desk-log", empty: "Nothing on the trail yet." });
    return { count: `${page.count} entries, newest first`, nodes: page.nodes };
  }

  async function renderDesk() {
    const box = document.getElementById("deskPanel");
    if (!box) return;
    // Redrawing after a decision keeps the page in place until the new one is ready.
    if (!box.firstChild) box.replaceChildren(el("div", { class: "empty", text: "Opening..." }));
    try {
      const data = await api("/admin/refuge");
      const tab = await deskTab(data, renderDesk);
      const tabs = el("div", { class: "seg desk-tabs", role: "tablist", "aria-label": "Admin desk" }, DESK_TABS.map(([key, label]) => el("button", {
        type: "button", role: "tab", "aria-selected": String(desk.tab === key), onclick: () => openDesk(key),
        text: key === "review" && data.stats.to_review ? `${label} (${data.stats.to_review})` : label,
      })));
      const filter = cave().filterSelect("Show", DESK_FILTERS[desk.tab], desk.show[desk.tab], (value) => openDesk(desk.tab, value));
      box.replaceChildren(el("div", { class: "refuge desk" }, [deskStats(data.stats), tabs, cave().listBar(tab.count, filter), ...tab.nodes]));
    } catch (err) {
      box.replaceChildren(el("div", { class: "empty" }, [el("strong", { text: "Couldn't open the desk" }), err.message]));
    }
  }

  // helplineRows is shared with Declare (web/declare.js), which shows them instead of words when a situation sounds unsafe.
  window.Refuge = { renderTab, hide, renderDesk, homeCard, helplineRows };
})();
