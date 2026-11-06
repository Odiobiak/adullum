// Refuge: the quiet room in the cave, for every kind of season. The cave's
// Refuge tab, its five rooms, the Leave quickly button, and the admin desk.
//
// The rooms are drawn in place inside the tab rather than given their own
// hash routes, so Leave quickly (or Escape) can replace the one history entry
// and Back never leads back in. What each room keeps:
//   Write it out    nothing, unless "Keep it" is pressed (app/refuge.py)
//   Talk with Aquila  nothing, unless "Keep this talk" is pressed; otherwise
//                   the talk lives only in `talk` below and vanishes on leaving
//   Grow            hopes, goals, habits and prayers (app/refuge.py seeds)
//   Be still        nothing at all
//   Amens           posts, amens and kind words (app/one_another.py)
// Nothing anyone keeps or shares here appears on the home screen or in
// Aquila's memory. The home's Amens notice (homeCard below) shows only the
// wall's public side: this week's amens and how many posts wait for theirs.
// #amens opens the cave straight into the Amens room.
//
// Loaded after web/cave.js, whose helpers it borrows through window.Cave.
(function () {
  const cave = () => window.Cave;
  const app = () => window.AdullumApp;
  const el = (...args) => cave().el(...args);
  const api = (...args) => cave().api(...args);
  const toast = (text) => cave().toast(text);
  // Aquila's wing mark, shared with the rest of the app (AQUILA_MARK in index.html).
  const aquilaMark = () => (app() && app().aquilaMark) || "";
  // Her mark in its gradient circle, as she appears beside what she says.
  const aquilaAvatar = (extra = "") => el("span", { class: `avatar-a refuge-aq${extra}`, "aria-hidden": "true", html: aquilaMark() });

  const svg = (path) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
  const ICON = {
    lock: svg('<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>'),
    pen: svg('<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>'),
    talk: svg('<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/>'),
    grow: svg('<path d="M12 21v-9"/><path d="M12 12c0-4 3-7 8-7 0 5-3 7-8 7z"/><path d="M12 14c0-3-2.5-5.5-7-5.5 0 4 2.5 5.5 7 5.5z"/>'),
    still: svg('<path d="M3 12c3-3 6-3 9 0s6 3 9 0"/><path d="M3 17c3-3 6-3 9 0s6 3 9 0" opacity=".5"/><path d="M3 7c3-3 6-3 9 0s6 3 9 0" opacity=".5"/>'),
    together: svg('<path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/>'),
    person: svg('<circle cx="12" cy="8" r="3.5"/><path d="M5 20a7 7 0 0 1 14 0"/>'),
    back: svg('<path d="M15 6l-6 6 6 6"/>'),
    forward: svg('<path d="M9 6l6 6-6 6"/>'),
    send: svg('<path d="M5 12h13M13 6l6 6-6 6"/>'),
    check: svg('<path d="M5 12.5l4.5 4.5L19 7.5"/>'),
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
  // Being in Refuge: the settled page, Leave quickly, and leaving
  // ---------------------------------------------------------------------
  let panel = null;
  let talk = null; // { messages, keptId } while a talk is open; null otherwise

  const exitButton = el("button", { class: "quick-exit", type: "button", title: "Go straight to a plain screen. Back won't return here." }, [
    "Leave quickly ", el("kbd", { text: "Esc" }),
  ]);
  exitButton.addEventListener("click", leaveQuickly);

  function enter(p) {
    panel = p;
    document.body.classList.add("in-refuge");
    if (!exitButton.isConnected) document.body.append(exitButton);
  }

  // Called by web/cave.js whenever another tab or view takes over. A talk that
  // wasn't kept vanishes here, as Refuge promises.
  function hide() {
    document.body.classList.remove("in-refuge");
    exitButton.remove();
    talk = null;
    stopStill();
    panel = null;
  }

  function leaveQuickly() {
    document.querySelectorAll(".sheet-overlay").forEach((o) => o.remove());
    if (panel) panel.replaceChildren();
    hide();
    location.replace("#home");
  }

  // Escape leaves, unless a sheet or the account menu is open (Escape closes those first).
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || !panel) return;
    const menu = document.getElementById("menu");
    if (document.querySelector(".sheet-overlay") || (menu && !menu.hidden)) return;
    leaveQuickly();
  });

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

  function room(title, lede, ...rest) {
    return el("div", { class: "room fade-in" }, [
      el("div", {}, [
        el("button", { class: "back", type: "button", html: `${ICON.back}<span>Refuge</span>`, onclick: threshold }),
        el("div", { class: "room-head" }, el("div", {}, [el("h2", { text: title }), lede ? el("p", { class: "muted", text: lede }) : null])),
      ]),
      ...rest,
    ]);
  }

  // ---------------------------------------------------------------------
  // The opening screen
  // ---------------------------------------------------------------------
  // `route` is the hash that opened the cave; #amens goes straight to the wall.
  async function renderTab(p, route) {
    enter(p);
    await (route === "amens" ? amensRoom() : threshold());
  }

  function door(icon, title, line, open) {
    return el("button", { class: "refuge-door", type: "button", onclick: open }, [
      el("span", { class: "door-icon", html: icon }),
      el("span", {}, [el("strong", { text: title }), el("span", { class: "line", text: line })]),
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
    show(
      el("section", { class: "refuge-threshold fade-in" }, [
        el("p", { class: "refuge-promise", html: `${ICON.lock}<span>Only you can see this. Aquila won't bring any of it up anywhere else.</span>` }),
        el("h2", { class: "refuge-q", text: "What's on your heart today?" }),
        el("div", { class: "refuge-doors" }, [
          door(ICON.pen, "Write it out", "Whatever you're carrying or hoping for. Keep it, or let it go.", () => writeRoom()),
          door(aquilaMark() || ICON.talk, "Talk with Aquila", "Hurting, hoping or planning. She'll listen first.", () => talkRoom()),
          door(ICON.grow, "Grow", "Hopes, goals, habits and prayers to grow into with God.", growRoom),
          door(ICON.together, "Amens", "Share without your name. Others say amen with you.", amensRoom),
          door(ICON.still, "Be still", "One quiet minute, when words won't come.", stillRoom),
        ]),
        el("button", { class: "refuge-help-link", type: "button", html: `${ICON.person}<span>Need a person? Someone to talk to, a Christian counsellor, or a church nearby</span>`, onclick: helpRoom }),
      ]),
      carriedNote(overview.carried),
      growingToday(seeds),
      keptList(overview)
    );
  }

  function carriedNote(c) {
    if (!c) return null;
    const words = plural(c.kind_words, "kind word", "kind words");
    const line = c.reactions
      ? `${plural(c.reactions, "amen", "amens")}${c.kind_words ? ` and ${words}` : ""} came back to you.`
      : `${words} came back to you.`;
    return el("div", { class: "carried-note fade-in" }, [
      el("span", { html: ICON.together }),
      el("span", { text: line }),
      el("button", { class: "act", type: "button", text: "See", onclick: amensRoom }),
    ]);
  }

  // Habits and prayers not yet tended today, so they can be done from here.
  function growingToday(seeds) {
    const due = seeds.filter((s) => s.status === "growing" && s.rhythm && !s.tended_today).slice(0, 3);
    if (!due.length) return null;
    return el("section", { class: "fade-in" }, [
      el("p", { class: "kicker", text: "For today" }),
      el("div", { class: "today-list" }, due.map((s) => {
        const row = el("div", { class: "today-row" }, [
          el("span", { class: `badge ${s.kind === "prayer" ? "" : "plain"}`, text: KIND_LABEL[s.kind] }),
          el("span", { class: "today-title", text: s.title }),
        ]);
        row.append(el("button", { class: "act", type: "button", text: s.kind === "prayer" ? "Prayed today" : "Done today", onclick: async () => {
          try {
            await api(`/me/refuge/seeds/${s.id}/tend`, { method: "POST", body: { today: cave().localToday(), tended: true } });
            row.classList.add("is-done");
            row.lastChild.replaceWith(el("span", { class: "today-done", html: `${ICON.check}<span>Done</span>` }));
          } catch (err) {
            toast(err.message);
          }
        } }));
        return row;
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
    return el("section", { class: "fade-in" }, [
      el("p", { class: "kicker", text: "Kept here, only for you" }),
      el("p", { class: "faint", style: "font-size:13px;margin:-6px 0 10px", text: "Tap to read." }),
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
      toast(err.message);
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
      release: { title: "Placed in His hands.", line: "It wasn't saved. If you'd like to come back to it, plant it in Grow next time.", verse: "Proverbs 16:3" },
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
        ? el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Plant it in Grow", onclick: () => {
            const hope = steps[0].box.value.trim();
            if (!hope) return toast("Write what you're hoping for first.");
            plantSheet({ kind: "hope", title: hope.slice(0, 200), note: [steps[1].box.value.trim(), steps[2].box.value.trim()].filter(Boolean).join("\n\n") }, growRoom);
          } })
        : null,
      el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Keep it, only for me", onclick: async () => {
        const body = writing();
        if (!body) return toast("Write a little first.");
        try {
          await api("/me/refuge/writings", { method: "POST", body: { shape, body } });
          toast("Kept. Only you can open it.");
          threshold();
        } catch (err) {
          toast(err.message);
        }
      } }),
      el("button", { class: "btn btn-ember btn-sm", type: "button", text: "Let it go", onclick: () => {
        const body = writing();
        if (!body) return toast("Write a little first.");
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
      toast(err.message);
    }
  }

  async function saveKept() {
    if (!talk || !talk.keptId) return;
    try {
      await api(`/me/refuge/talks/${talk.keptId}`, { method: "PUT", body: { messages: wire(talk.messages) } });
    } catch {
      toast("Couldn't keep the latest part of this talk.");
    }
  }

  function talkRoom(firstMessage) {
    if (!talk) talk = { messages: [{ role: "aquila", content: OPENING }], keptId: null };
    const list = el("div", { class: "soft-thread", "aria-live": "polite" }, talk.messages.map(messageNode));
    const box = el("textarea", { rows: "1", maxlength: "4000", placeholder: "Say as much or as little as you want", "aria-label": "Message to Aquila" });
    const sendBtn = el("button", { class: "iconbtn", type: "button", "aria-label": "Send", html: ICON.send });
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
      if (talk.messages.length < 2) return toast("Say something first, then you can keep it.");
      try {
        const kept = await api("/me/refuge/talks", { method: "POST", body: { messages: wire(talk.messages) } });
        talk.keptId = kept.id;
        keepBtn.textContent = "Kept";
        keepBtn.classList.add("is-done");
        say();
      } catch (err) {
        toast(err.message);
      }
    };
    const erase = el("button", { class: "act danger", type: "button", text: "Erase", onclick: async () => {
      if (talk.keptId) {
        if (!confirm("Erase this talk? It can't be brought back.")) return;
        try {
          await api(`/me/refuge/talks/${talk.keptId}`, { method: "DELETE" });
        } catch (err) {
          return toast(err.message);
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
        wait.replaceWith(el("p", { class: "form-msg bad", text: `${err.message} Your words are still here; try sending again.` }));
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
      el("div", { class: "soft-composer" }, [box, sendBtn])
    ));
    if (firstMessage) send(firstMessage);
    else box.focus();
  }

  // ---------------------------------------------------------------------
  // Grow: hopes, goals, habits and prayers
  // ---------------------------------------------------------------------
  const KIND_LABEL = { hope: "Hope", goal: "Goal", habit: "Habit", prayer: "Prayer" };
  const KINDS = {
    hope: { line: "Something you're trusting God for.", placeholder: "What are you hoping for?", note: "What would it mean to you?", fulfil: "It came to pass", fulfilled: "Came to pass", talk: "something I'm hoping for" },
    goal: { line: "Something to work toward, step by step.", placeholder: "What do you want to reach?", note: "Why does it matter?", fulfil: "Reached it", fulfilled: "Reached", talk: "a goal I'm working toward" },
    habit: { line: "A rhythm to build, day by day.", placeholder: "e.g. Read a psalm before bed", note: "What do you hope it grows in you?", fulfil: "It's part of me now", fulfilled: "Rooted", talk: "a habit I'm trying to build" },
    prayer: { line: "Something to keep praying, day by day.", placeholder: "e.g. Patience with my children", note: "Who or what is it for?", fulfil: "Answered", fulfilled: "Answered", talk: "something I keep praying about" },
  };
  let growFilter = "growing";

  // Plant something new, or edit `existing`.
  function plantSheet(existing, onSaved) {
    const editing = existing && existing.id;
    let kind = (existing && existing.kind) || "hope";
    const title = el("input", { class: "field", maxlength: "200" });
    const note = el("textarea", { class: "field", maxlength: "2000", rows: "3" });
    const passage = el("input", { class: "field", maxlength: "120", placeholder: "Jeremiah 29:11, or leave blank" });
    const stepsBox = el("textarea", { class: "field", rows: "4", placeholder: "One step per line" });
    title.value = (existing && existing.title) || "";
    note.value = (existing && existing.note) || "";
    passage.value = (existing && existing.passage_ref) || "";
    stepsBox.value = ((existing && existing.steps) || []).map((s) => (typeof s === "string" ? s : s.text)).join("\n");
    const stepsWrap = el("label", { class: "field-wrap" }, ["Steps (optional)", stepsBox]);
    const titleLabel = el("span");
    const noteLabel = el("span");
    const msg = cave().formMessage();

    const kindButtons = Object.keys(KINDS).map((k) => el("button", { class: "kind-choice", type: "button", "aria-pressed": String(k === kind), onclick: () => { kind = k; paint(); } }, [
      el("strong", { text: KIND_LABEL[k] }), el("span", { text: KINDS[k].line }),
    ]));
    function paint() {
      kindButtons.forEach((b, i) => b.setAttribute("aria-pressed", String(Object.keys(KINDS)[i] === kind)));
      titleLabel.textContent = KIND_LABEL[kind];
      title.placeholder = KINDS[kind].placeholder;
      noteLabel.textContent = `${KINDS[kind].note} (optional)`;
      // Steps belong to goals; an existing seed keeps its kind.
      stepsWrap.hidden = kind !== "goal";
    }
    paint();

    const save = el("button", { class: "btn btn-ember btn-sm", type: "submit", text: editing ? "Save" : "Plant it" });
    const form = el("form", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "plantTitle" }, [
      el("h3", { id: "plantTitle", text: editing ? "Edit" : "Plant something" }),
      el("p", { class: "sheet-lede", text: "Only you can see what you're growing." }),
      editing ? null : el("div", { class: "kind-choices" }, kindButtons),
      el("label", { class: "field-wrap" }, [titleLabel, title]),
      el("label", { class: "field-wrap" }, [noteLabel, note]),
      stepsWrap,
      el("label", { class: "field-wrap" }, ["A verse to hold onto (optional)", passage]),
      msg.node,
      el("div", { class: "sheet-actions" }, [el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Cancel", onclick: () => close() }), save]),
    ]);
    const close = cave().overlay(form);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!title.value.trim()) return msg.say("Give it a few words.", true);
      save.disabled = true;
      const lines = stepsBox.value.split("\n").map((s) => s.trim()).filter(Boolean);
      try {
        if (editing) {
          const done = new Set((existing.steps || []).filter((s) => s.done).map((s) => s.text));
          await api(`/me/refuge/seeds/${existing.id}`, { method: "PATCH", body: {
            title: title.value.trim(), note: note.value.trim() || null, passage_ref: passage.value.trim() || null,
            ...(kind === "goal" ? { steps: lines.map((text) => ({ text, done: done.has(text) })) } : {}),
          } });
        } else {
          await api("/me/refuge/seeds", { method: "POST", body: {
            kind, title: title.value.trim(), note: note.value.trim() || null, passage_ref: passage.value.trim() || null, steps: kind === "goal" ? lines : [],
          } });
        }
        close();
        toast(editing ? "Saved." : "Planted.");
        if (onSaved) onSaved();
      } catch (err) {
        msg.say(err.message, true);
        save.disabled = false;
      }
    });
  }

  function fulfilSheet(seed, onSaved) {
    const note = el("textarea", { class: "field", maxlength: "2000", rows: "3", placeholder: "How did it happen? A sentence is plenty, or leave it blank." });
    const msg = cave().formMessage();
    const save = el("button", { class: "btn btn-ember btn-sm", type: "submit", text: KINDS[seed.kind].fulfil });
    const form = el("form", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "fulfilTitle" }, [
      el("h3", { id: "fulfilTitle", text: KINDS[seed.kind].fulfil }),
      el("div", { class: "journal-preview" }, [el("strong", { text: `${KIND_LABEL[seed.kind]} since ${shortDate(seed.created_at)}` }), document.createTextNode(seed.title)]),
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

  function rhythmDots(seed) {
    const today = new Date();
    return el("div", { class: "rhythm", "aria-label": `Tended ${seed.rhythm.filter(Boolean).length} of the last 7 days` }, seed.rhythm.map((on, i) => {
      const d = new Date(today);
      d.setDate(today.getDate() - (seed.rhythm.length - 1 - i));
      return el("span", { class: `rhythm-day${on ? " on" : ""}`, title: d.toLocaleDateString(undefined, { weekday: "long" }) }, el("i"));
    }));
  }

  function seedCard(seed, rerender) {
    const growing = seed.status === "growing";
    const node = el("article", { class: `entry seed-card seed-${seed.kind}${seed.status === "fulfilled" ? " is-fulfilled" : ""}${seed.status === "set_aside" ? " is-aside" : ""} fade-in` });
    const patch = async (body) => {
      try {
        await api(`/me/refuge/seeds/${seed.id}`, { method: "PATCH", body });
        rerender();
      } catch (err) {
        toast(err.message);
      }
    };
    const meta = el("div", { class: "entry-meta" }, [
      el("span", { class: `badge ${seed.kind === "hope" || seed.kind === "prayer" ? "" : "plain"}`, text: KIND_LABEL[seed.kind] }),
      seed.status === "fulfilled"
        ? el("span", { class: "badge answered", html: `${ICON.check}<span>${KINDS[seed.kind].fulfilled} ${shortDate(seed.fulfilled_at)}</span>` })
        : el("span", { text: seed.status === "set_aside" ? "Set aside" : `Since ${shortDate(seed.created_at)}` }),
    ]);

    let steps = null;
    if (seed.kind === "goal" && seed.steps.length) {
      const done = seed.steps.filter((s) => s.done).length;
      steps = el("div", { class: "steps" }, [
        el("p", { class: "faint", style: "font-size:13px", text: `${done} of ${seed.steps.length} steps` }),
        ...seed.steps.map((s, i) => el("label", { class: `step${s.done ? " done" : ""}` }, [
          el("input", { type: "checkbox", checked: s.done, disabled: !growing, onchange: (e) => {
            const next = seed.steps.map((x, j) => (j === i ? { ...x, done: e.target.checked } : x));
            patch({ steps: next });
          } }),
          el("span", { text: s.text }),
        ])),
      ]);
    }

    let tend = null;
    if (seed.rhythm && growing) {
      const label = seed.kind === "prayer" ? "Prayed today" : "Done today";
      const btn = el("button", { class: `act${seed.tended_today ? " is-done" : ""}`, type: "button", html: `${ICON.check}<span>${label}</span>` });
      btn.onclick = async () => {
        const tended = !btn.classList.contains("is-done");
        try {
          await api(`/me/refuge/seeds/${seed.id}/tend`, { method: "POST", body: { today: cave().localToday(), tended } });
          rerender();
        } catch (err) {
          toast(err.message);
        }
      };
      tend = el("div", { class: "tend-row" }, [rhythmDots(seed), btn]);
    }

    const act = (label, onclick, extra = "") => el("button", { class: `act${extra}`, type: "button", text: label, onclick });
    const remove = act("Delete", async () => {
      if (!confirm("Delete this? Its history goes too.")) return;
      try {
        await api(`/me/refuge/seeds/${seed.id}`, { method: "DELETE" });
        rerender();
      } catch (err) {
        toast(err.message);
      }
    }, " danger");
    const actions = growing
      ? [
          act("Talk it over with Aquila", () => {
            talk = null;
            const note = seed.note ? ` ${seed.note}` : "";
            talkRoom(`I'd like to talk with you about ${KINDS[seed.kind].talk}: "${seed.title}".${note}`);
          }),
          act(KINDS[seed.kind].fulfil, () => fulfilSheet(seed, rerender)),
          act("Edit", () => plantSheet(seed, rerender)),
          act("Set aside", () => patch({ status: "set_aside" })),
          remove,
        ]
      : [act("Grow again", () => patch({ status: "growing" })), remove];

    node.append(...[
      meta,
      el("h3", { text: seed.title }),
      seed.note ? el("p", { class: "refl", text: seed.note }) : null,
      seed.passage_ref ? el("a", { class: "pill prayer-passage", href: `#${window.Reader.href(seed.passage_ref)}` }, el("span", { text: seed.passage_ref })) : null,
      steps,
      tend,
      seed.status === "fulfilled" && seed.outcome_note ? el("div", { class: "answer-note" }, [el("strong", { text: "How it came about" }), el("p", { text: seed.outcome_note })]) : null,
      el("div", { class: "entry-actions" }, actions),
    ].filter(Boolean));
    return node;
  }

  async function growRoom() {
    let seeds;
    try {
      seeds = await api(`/me/refuge/seeds?today=${cave().localToday()}`);
    } catch (err) {
      return failed(err);
    }
    const rerender = () => growRoom();
    const groups = { growing: [], fulfilled: [], set_aside: [] };
    seeds.forEach((s) => groups[s.status].push(s));
    const filter = el("div", { class: "moods", role: "group", "aria-label": "Which to show", style: "margin:0" }, [
      ["growing", `Growing (${groups.growing.length})`],
      ["fulfilled", `Came to pass (${groups.fulfilled.length})`],
      ["set_aside", `Set aside (${groups.set_aside.length})`],
    ].filter(([key], i) => i === 0 || groups[key].length).map(([key, label]) =>
      el("button", { class: "mood", type: "button", style: "text-transform:none", "aria-pressed": String(key === growFilter), text: label, onclick: () => { growFilter = key; rerender(); } })
    ));
    if (!groups[growFilter].length && growFilter !== "growing") growFilter = "growing";
    const list = groups[growFilter];
    const plant = el("button", { class: "btn btn-ember btn-sm", type: "button", text: "Plant something", onclick: () => plantSheet(null, rerender) });
    show(room("Grow", "Hopes you're holding, goals you're working toward, habits and prayers you're building. Bring them to God one day at a time.",
      el("div", { class: "row-between", style: "flex-wrap:wrap;gap:10px" }, [filter, plant]),
      list.length
        ? el("div", { class: "entries seed-list" }, list.map((s) => seedCard(s, rerender)))
        : el("div", { class: "empty" }, [
            el("strong", { text: "Nothing planted yet" }),
            "A hope you're trusting God for, a goal for this season, a habit you'd like to build, or a prayer to keep praying. Start with one.",
          ])
    ));
  }

  // ---------------------------------------------------------------------
  // Be still
  // ---------------------------------------------------------------------
  let stillTimer = null;
  function stopStill() {
    clearInterval(stillTimer);
    stillTimer = null;
  }

  function stillRoom() {
    const word = el("b", { text: "Ready when you are" });
    const circle = el("div", { class: "breath", "aria-hidden": "true" }, word);
    const timer = el("p", { class: "timer", role: "timer", text: "1:00" });
    const verse = el("p", { class: "scripture-lg" });
    const ref = el("p", { class: "verse-ref" });
    const start = el("button", { class: "btn btn-ember btn-sm", type: "button", text: "Begin" });
    start.onclick = () => {
      stopStill();
      start.hidden = true;
      circle.classList.add("is-on");
      let left = 60;
      let beat = 0;
      word.textContent = "Breathe in";
      timer.textContent = "1:00";
      stillTimer = setInterval(() => {
        left -= 1;
        beat = (beat + 1) % 10;
        word.textContent = beat < 4 ? "Breathe in" : beat < 6 ? "Hold" : "Breathe out";
        timer.textContent = `0:${String(left).padStart(2, "0")}`;
        if (left <= 0) {
          stopStill();
          circle.classList.remove("is-on");
          word.textContent = "Rest here";
          timer.textContent = "";
          start.textContent = "One more minute";
          start.hidden = false;
        }
      }, 1000);
    };
    show(el("div", { class: "fade-in" }, [
      el("button", { class: "back", type: "button", html: `${ICON.back}<span>Refuge</span>`, onclick: threshold }),
      el("section", { class: "still" }, [
        el("h2", { text: "Be still" }),
        el("p", { class: "muted", text: "Breathe with the light. In for four, hold for two, out for four." }),
        circle, verse, ref, timer,
        el("div", { style: "margin-top:16px" }, start),
      ]),
    ]));
    cave().verseText("Psalm 46:10").then((v) => {
      verse.textContent = v.text;
      ref.textContent = `Psalm 46:10 · ${v.translation}`;
    }).catch(() => {});
  }

  // ---------------------------------------------------------------------
  // Amens (app/one_another.py; it was "One another" at first)
  // ---------------------------------------------------------------------
  // Saying amen is the wall's one reaction. `hint` says what it means on each
  // kind of post, since the button itself just says "Say amen".
  const amenCount = (n) => plural(n, "amen", "amens");
  const amenSaid = (n) => (n > 1 ? `Amen, with ${plural(n - 1, "other", "others")}` : "Amen");
  const POST_KINDS = {
    burden: { choose: "Carrying something", who: "Someone is carrying this", mineWho: "You're carrying this", hint: "Say amen once you've prayed for this", placeholder: "What are you carrying? No names, places or links." },
    rejoice: { choose: "Something good", who: "Someone has good news", mineWho: "Your good news", hint: "Say amen to rejoice with them", placeholder: "What's the good news? No names, places or links." },
  };
  const MINE_STATUS = { waiting: ["Waiting to be read", "plain"], shared: ["Shared", "answered"], not_shared: ["Not shared", "plain"] };

  function kindWordNode(w) {
    return el("div", { class: "encouragement" }, w.ref
      ? [el("span", { class: "scripture", text: w.text }), " ", el("span", { class: "verse-ref", text: `${w.ref} · ${w.translation}` })]
      : w.text);
  }

  async function kindWordsSheet(post, onSent) {
    let choices;
    try {
      choices = await api(`/me/refuge/kind-words?kind=${post.kind}&translation=${encodeURIComponent(translation())}`);
    } catch (err) {
      return toast(err.message);
    }
    const msg = cave().formMessage();
    const options = choices.map((w, i) => el("label", { class: "choice" }, [
      el("input", { type: "radio", name: "kindWord", value: w.id, checked: i === 0 }),
      el("span", {}, w.ref ? [el("span", { class: "scripture", style: "font-size:16px", text: w.text }), el("br"), el("span", { class: "verse-ref", text: w.ref })] : w.text),
    ]));
    const send = el("button", { class: "btn btn-ember btn-sm", type: "submit", text: "Send" });
    const form = el("form", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "kindTitle" }, [
      el("h3", { id: "kindTitle", text: "Send a few kind words" }),
      el("p", { class: "sheet-lede", text: "Choose one. They'll see it, but never who sent it, and they can't write back." }),
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

  function reportSheet(post, onReported) {
    const reason = el("textarea", { class: "field", maxlength: "300", rows: "3", placeholder: "What's wrong with it? Optional." });
    const msg = cave().formMessage();
    const send = el("button", { class: "btn btn-ember btn-sm", type: "submit", text: "Report" });
    const form = el("form", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "reportTitle" }, [
      el("h3", { id: "reportTitle", text: "Report this" }),
      el("p", { class: "sheet-lede", text: "It comes off the wall straight away, and a person looks at it again." }),
      el("label", { class: "field-wrap" }, ["Reason", reason]),
      msg.node,
      el("div", { class: "sheet-actions" }, [el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Cancel", onclick: () => close() }), send]),
    ]);
    const close = cave().overlay(form);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      send.disabled = true;
      try {
        await api(`/me/refuge/posts/${post.id}/report`, { method: "POST", body: { reason: reason.value.trim() || null } });
        close();
        toast("Thank you. A person will look at it.");
        onReported();
      } catch (err) {
        msg.say(err.message, true);
        send.disabled = false;
      }
    });
  }

  function wallCard(post, rerender) {
    const spec = POST_KINDS[post.kind];
    const react = el("button", { class: `act${post.reacted ? " is-done" : ""}`, type: "button", title: spec.hint, disabled: post.reacted, text: post.reacted ? amenSaid(post.reactions) : "Say amen" });
    react.onclick = async () => {
      try {
        const res = await api(`/me/refuge/posts/${post.id}/react`, { method: "POST" });
        react.classList.add("is-done");
        react.disabled = true;
        react.textContent = amenSaid(res.reactions);
      } catch (err) {
        toast(err.message);
      }
    };
    const words = el("button", { class: `act${post.sent_kind_word ? " is-done" : ""}`, type: "button", disabled: post.sent_kind_word, text: post.sent_kind_word ? "Kind words sent" : "Send kind words" });
    words.onclick = () => kindWordsSheet(post, () => { words.classList.add("is-done"); words.disabled = true; words.textContent = "Kind words sent"; });
    return el("article", { class: `burden burden-${post.kind} fade-in` }, [
      el("p", { class: "burden-who", text: spec.who }),
      el("p", { class: "burden-text", text: post.body }),
      el("div", { class: "burden-actions" }, [
        react, words,
        el("button", { class: "report", type: "button", text: "Report", onclick: () => reportSheet(post, rerender) }),
      ]),
    ]);
  }

  function mineCard(post, rerender) {
    const spec = POST_KINDS[post.kind];
    const [statusText, statusClass] = MINE_STATUS[post.status];
    return el("article", { class: "burden is-mine fade-in" }, [
      el("div", { class: "entry-meta" }, [el("span", { class: `badge ${statusClass}`, text: statusText }), el("span", { text: `${spec.mineWho} · ${shortDate(post.created_at)}` })]),
      el("p", { class: "burden-text", text: post.body }),
      post.status === "shared" ? el("div", { class: "carried-count" }, [
        el("span", { text: amenCount(post.reactions) }),
        el("span", { text: plural(post.kind_words.length, "kind word", "kind words") }),
      ]) : null,
      post.status === "waiting" ? el("p", { class: "faint", style: "font-size:14px", text: "This is approved before it's shared. It'll appear on the wall once it is." }) : null,
      post.status === "not_shared" ? el("p", { class: "faint", style: "font-size:14px", text: "This one wasn't shared on the wall. It's still here for you, and you can take it down." }) : null,
      post.kind_words.length ? el("div", { class: "encouragements" }, post.kind_words.map(kindWordNode)) : null,
      el("div", { class: "burden-actions" }, el("button", { class: "act danger", type: "button", text: "Take it down", onclick: async () => {
        if (!confirm("Take this down? It comes off the wall for everyone.")) return;
        try {
          await api(`/me/refuge/posts/${post.id}`, { method: "DELETE" });
          rerender();
        } catch (err) {
          toast(err.message);
        }
      } })),
    ].filter(Boolean));
  }

  function shareBox(rerender) {
    let kind = "burden";
    const box = el("textarea", { class: "field", maxlength: "280", placeholder: POST_KINDS.burden.placeholder, "aria-label": "What you want to share" });
    const count = el("span", { text: "280 left" });
    box.addEventListener("input", () => { count.textContent = `${280 - box.value.length} left`; });
    const kinds = el("div", { class: "moods", role: "group", "aria-label": "What you're sharing", style: "margin:0 0 12px" }, Object.entries(POST_KINDS).map(([key, spec]) => {
      const b = el("button", { class: "mood", type: "button", style: "text-transform:none", "aria-pressed": String(key === kind), text: spec.choose });
      b.onclick = () => {
        kind = key;
        box.placeholder = spec.placeholder;
        kinds.querySelectorAll(".mood").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      };
      return b;
    }));
    const msg = cave().formMessage();
    const care = el("div", { hidden: true });
    const send = el("button", { class: "btn btn-ember btn-sm", type: "button", text: "Share anonymously" });
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
        count.textContent = "280 left";
        toast("Thank you. Once it's approved, others can say amen with you.");
        rerender();
      } catch (err) {
        msg.say(err.message, true);
      } finally {
        send.disabled = false;
      }
    };
    return el("section", { class: "card share-box" }, [
      el("h3", { class: "section-title", text: "Share something" }),
      kinds, box, msg.node,
      el("div", { class: "share-foot" }, [
        el("span", { text: "This is approved before it's shared. You can take it down any time." }),
        el("span", { class: "share-send" }, [count, send]),
      ]),
      care,
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
    show(room("Amens", "Share what you're carrying or something good, anonymously. People say amen, praying or rejoicing with you, and can send a few kind words.",
      shareBox(rerender),
      data.mine.length ? el("section", { class: "wall-section" }, [el("p", { class: "kicker", text: "What you've shared" }), ...data.mine.map((p) => mineCard(p, rerender))]) : null,
      el("section", { class: "wall-section" }, [
        el("p", { class: "kicker", text: "On the wall" }),
        ...(data.posts.length
          ? data.posts.map((p) => wallCard(p, rerender))
          : [el("p", { class: "muted", text: "Nothing on the wall right now. When someone shares, it'll appear here for you to carry with them." })]),
      ])
    ));
  }

  // ---------------------------------------------------------------------
  // The Amens notice on the home screen (web/cave.js::showHome)
  // ---------------------------------------------------------------------
  // `glance` is app/one_another.py::amens_glance: this week's amens across the
  // whole wall and how many posts by other people still wait for this
  // person's amen. Nothing this person shared ever shows here.
  //
  // It reads like a notification rather than a card: one line, a count on
  // the icon, and the whole thing opens the wall. On a week with nothing
  // waiting and no amens said there is nothing to tell, so it stays away.
  function homeCard(glance) {
    const { waiting, this_week: thisWeek } = glance;
    if (!waiting && !thisWeek) return null;

    const title = waiting ? `${plural(waiting, "post", "posts")} waiting for your amen` : "You're all caught up on Amens";
    const detail = thisWeek ? `${plural(thisWeek, "amen", "amens")} this week` : "Open the wall";

    return el("a", { class: "amens-note fade-in", href: "#amens", "aria-label": `Amens: ${title}, ${detail}` }, [
      el("span", { class: "amens-note-icon", "aria-hidden": "true" }, [
        el("span", { html: ICON.together }),
        waiting ? el("span", { class: "amens-note-count", text: waiting > 9 ? "9+" : String(waiting) }) : null,
      ]),
      el("span", { class: "amens-note-text" }, [
        el("strong", { text: title }),
        el("small", { text: detail }),
      ]),
      el("span", { class: "amens-note-go", "aria-hidden": "true", html: ICON.forward }),
    ]);
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
          if (navigator.clipboard) navigator.clipboard.writeText(words).then(() => toast("Copied.")).catch(() => toast("Couldn't copy."));
        } })),
      ])
    ));
  }

  // ---------------------------------------------------------------------
  // The admin desk (#desk), for the people in ADMIN_EMAILS
  // ---------------------------------------------------------------------
  function deskCard(post, rerender) {
    const check = post.auto_check || {};
    const notes = [
      check.error ? "The automatic check didn't run. Read this one closely." : null,
      check.flagged && check.flagged.length ? `The automatic check noticed: ${check.flagged.join(", ")}.` : null,
    ].filter(Boolean);
    const decide = (action) => async () => {
      try {
        await api(`/admin/refuge/${post.id}`, { method: "POST", body: { action } });
        toast(action === "approve" ? "On the wall." : "Removed.");
        rerender();
      } catch (err) {
        toast(err.message);
      }
    };
    return el("article", { class: "burden desk-card fade-in" }, [
      el("div", { class: "entry-meta" }, [el("span", { class: "badge plain", text: POST_KINDS[post.kind].choose }), el("span", { text: cave().when(post.created_at) })]),
      el("p", { class: "burden-text", text: post.body }),
      ...notes.map((n) => el("p", { class: "desk-note", text: n })),
      post.reports.length ? el("div", { class: "desk-reports" }, [
        el("strong", { text: plural(post.reports.length, "report", "reports") }),
        ...post.reports.map((r) => el("p", { text: r.reason || "No reason given." })),
      ]) : null,
      el("div", { class: "burden-actions" }, [
        el("button", { class: "btn btn-ember btn-sm", type: "button", text: post.status === "reported" ? "Put it back" : "Approve", onclick: decide("approve") }),
        el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Remove", onclick: decide("remove") }),
      ]),
    ].filter(Boolean));
  }

  async function renderDesk() {
    const box = document.getElementById("deskPanel");
    if (!box) return;
    box.replaceChildren(el("div", { class: "empty", text: "Opening..." }));
    try {
      const data = await api("/admin/refuge");
      const rerender = () => renderDesk();
      const section = (title, lede, rows) => el("section", { class: "wall-section" }, [
        el("h2", { class: "section-title", text: `${title} (${rows.length})` }),
        el("p", { class: "muted", style: "font-size:15px;margin-bottom:12px", text: lede }),
        ...(rows.length ? rows.map((p) => deskCard(p, rerender)) : [el("p", { class: "faint", text: "Nothing here." })]),
      ]);
      box.replaceChildren(el("div", { class: "refuge" }, [
        section("Waiting to be read", "These passed the automatic check. Approve what's kind and safe to share; remove anything that names someone, could identify the writer, or doesn't belong.", data.pending),
        section("Reported", "Taken off the wall because someone reported them. Put back what's fine; remove the rest.", data.reported),
      ]));
    } catch (err) {
      box.replaceChildren(el("div", { class: "empty" }, [el("strong", { text: "Couldn't open the desk" }), err.message]));
    }
  }

  window.Refuge = { renderTab, hide, renderDesk, homeCard };
})();
