// The cave's Prayers tab: praying, fasting and the prayer list, plus the
// small prayer card on the home screen.
//
// The top of the tab is two cards side by side (stacked on a phone):
//   This week   seven days, lit on any day the person prayed, and an
//               "I prayed today" button (app/prayers.py::prayer_week).
//   Fasting     a fast underway, with which day it is, or a way to start one
//               (app/fasting.py). Finished fasts are kept, with a reflection.
// Below them, the prayer list: each request is open until it's marked
// answered, and can be marked "Prayed today", which also lights the day.
//
// Loaded after web/cave.js, whose helpers (el, overlay, api, toast, card,
// moreMenu, weekDots) it borrows through window.Cave at call time.
(function () {
  const svg = (path, width = "1.8") => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
  const ICON = {
    check: svg('<path d="M5 12.5l4.5 4.5L19 7.5"/>', "2.2"),
    circle: svg('<circle cx="12" cy="12" r="7.5"/>'),
    aquila: svg('<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/>'),
    book: svg('<path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M4 21V5M9 7h6"/>'),
    declare: svg('<path d="M3 11v2M7 8v8M11 5v14M15 8v8M19 10v4"/>'),
  };

  const cave = () => window.Cave;
  const app = () => window.AdullumApp;
  const el = (...args) => cave().el(...args);
  const api = (...args) => cave().api(...args);
  const toast = (text) => cave().toast(text);

  // Which half of the list the tab is showing: "open" or "answered".
  let showing = "open";

  function shortDate(iso) {
    return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  }
  // A local date ("2026-11-05") as "Thu, Nov 5".
  function dayDate(iso) {
    return cave().localDate(iso).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  }
  function clip(text, n) {
    return text.length > n ? `${text.slice(0, n - 3)}...` : text;
  }
  function plural(n, one, many) {
    return `${n} ${n === 1 ? one : many}`;
  }

  // Asks Aquila to pray alongside the person. "pray" mode answers with a few
  // verses, a prayer for the request and encouragement to keep praying, not a
  // study (app/agent/nodes.py::pray_with). A linked passage goes first so
  // retrieval (app/retrieval.py::parse_reference) starts from it.
  function prayWithAquila(body, passageRef) {
    const ask = `Would you pray with me about this? ${body}`;
    app().submitQuery(passageRef ? `On ${passageRef}: ${ask}` : ask, { mode: "pray" });
  }

  // A sheet's Cancel and save buttons, the same in every sheet here.
  function sheetActions(close, save) {
    return el("div", { class: "sheet-actions" }, [el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Cancel", onclick: () => close() }), save]);
  }

  // ---------------------------------------------------------------------
  // Prayer sheets
  // ---------------------------------------------------------------------
  // Add a prayer, or edit one when `existing` is given.
  function openSheet({ existing } = {}, onSaved) {
    if (!cave().signedIn()) {
      toast("Create a free account to keep a prayer list.");
      app().go("join");
      return;
    }
    const body = el("textarea", { id: "prayerBody", maxlength: "2000", placeholder: "Someone or something you're bringing to God" });
    const passage = el("input", { id: "prayerPassage", maxlength: "120", placeholder: "Philippians 4:6, or leave blank" });
    body.value = existing ? existing.body : "";
    passage.value = (existing && existing.passage_ref) || "";
    const msg = cave().formMessage();
    const save = el("button", { class: "btn btn-ember btn-sm", type: "submit", text: existing ? "Save changes" : "Add to my list" });
    const form = el("form", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "prayerTitle" }, [
      cave().sheetTitle("prayerTitle", existing ? "Edit prayer" : "A new prayer", "Only you can see your prayer list. If Aquila's memory is on, she'll keep it in mind when you talk."),
      el("label", { class: "field-wrap" }, ["What you're praying for", body]),
      el("label", { class: "field-wrap" }, ["A verse to hold onto (optional)", passage]),
      msg.node,
    ]);
    const close = cave().overlay(form);
    form.append(sheetActions(close, save));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const text = body.value.trim();
      if (!text) return msg.say("Write a few words about what you're praying for.", true);
      save.disabled = true;
      try {
        const payload = { body: text, passage_ref: passage.value.trim() || null };
        const prayer = existing
          ? await api(`/me/prayers/${existing.id}`, { method: "PATCH", body: payload })
          : await api("/me/prayers", { method: "POST", body: payload });
        close();
        toast(existing ? "Saved." : "Added to your prayer list.");
        if (onSaved) onSaved(prayer);
      } catch (err) {
        msg.say(err.message, true);
        save.disabled = false;
      }
    });
  }

  function openAnsweredSheet(p, onSaved) {
    const note = el("textarea", { id: "prayerAnswer", maxlength: "2000", placeholder: "What happened? A sentence is plenty, or leave it blank." });
    const msg = cave().formMessage();
    const save = el("button", { class: "btn btn-ember btn-sm", type: "submit", text: "Mark answered" });
    const form = el("form", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "answeredTitle" }, [
      el("h3", { id: "answeredTitle", text: "Answered" }),
      el("div", { class: "journal-preview" }, [el("strong", { text: `Praying since ${shortDate(p.created_at)}` }), document.createTextNode(p.body)]),
      el("label", { class: "field-wrap" }, ["How was it answered?", note]),
      msg.node,
    ]);
    const close = cave().overlay(form);
    form.append(sheetActions(close, save));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      save.disabled = true;
      try {
        await api(`/me/prayers/${p.id}`, { method: "PATCH", body: { status: "answered", answer_note: note.value.trim() || null } });
        close();
        toast("Marked answered. Thanks be to God.");
        if (onSaved) onSaved();
      } catch (err) {
        msg.say(err.message, true);
        save.disabled = false;
      }
    });
  }

  // ---------------------------------------------------------------------
  // This week of prayer
  // ---------------------------------------------------------------------
  // Marks a day prayed, or takes it back: for one request when `prayerId` is
  // given, otherwise just "I prayed today". Returns false when it couldn't.
  async function logPrayed({ prayerId = null, prayed }) {
    try {
      await api("/me/prayers/log", { method: "POST", body: { today: cave().localToday(), prayer_id: prayerId, prayed } });
      return true;
    } catch (err) {
      toast(err.message);
      return false;
    }
  }

  function weekCard(week, onChange) {
    const days = week.days_this_week;
    const prayed = week.prayed_today;
    const button = el("button", {
      class: `btn btn-sm ${prayed ? "btn-ghost is-done" : "btn-ember"}`,
      type: "button",
      "aria-pressed": String(prayed),
      html: `${prayed ? ICON.check : ICON.circle}<span>${prayed ? "Prayed today" : "I prayed today"}</span>`,
      onclick: async () => {
        button.disabled = true;
        if (await logPrayed({ prayed: !prayed })) {
          if (!prayed) toast("Amen.");
          onChange();
        } else {
          button.disabled = false;
        }
      },
    });
    return el("section", { class: "card practice-card fade-in" }, [
      cave().cardHead("This week", el("span", { class: "faint practice-aside", text: days ? `Prayed ${plural(days, "day", "days")}` : "A new week" })),
      cave().weekDots(week.week, { label: "Days you prayed this week" }),
      el("div", { class: "practice-foot" }, [
        el("p", { class: "faint", text: "Praying for something on your list counts too." }),
        button,
      ]),
    ]);
  }

  // ---------------------------------------------------------------------
  // Fasting
  // ---------------------------------------------------------------------
  const FAST_KINDS = {
    full: { short: "Water only", label: "Water-only fast", hint: "Water only, for the days you set." },
    daniel: { short: "Daniel", label: "Daniel fast", hint: "Vegetables and water, as Daniel asked for (Daniel 1:12)." },
    meal: { short: "A meal", label: "Skipping a meal", hint: "Giving up a meal, or meals, and praying in that time.", detail: "Which meal?", placeholder: "Lunch" },
    other: { short: "Other", label: "Setting something down", hint: "Something else given up for a while, to make room for God.", detail: "What are you setting down?", placeholder: "Social media" },
  };

  function fastTitle(f) {
    const label = FAST_KINDS[f.kind].label;
    return f.detail ? `${label} · ${f.detail}` : label;
  }

  function fastWhen(f) {
    const p = f.progress;
    if (f.status === "finished") return `${dayDate(f.starts_on)} to ${dayDate(f.finished_on)} · ${plural(p.day, "day", "days")}`;
    if (p.starts_in) return `Starts ${p.starts_in === 1 ? "tomorrow" : dayDate(f.starts_on)} · ${plural(p.of, "day", "days")}`;
    if (p.of === 1) return "Today";
    return p.last_day_reached ? `Day ${p.day} of ${p.of} · the last day` : `Day ${p.day} of ${p.of} · until ${dayDate(p.ends_on)}`;
  }

  // Start a fast, or edit `existing`.
  function fastSheet(existing, onSaved) {
    let kind = (existing && existing.kind) || "full";
    const detail = el("input", { class: "field", maxlength: "80" });
    const days = el("input", { class: "field", type: "number", min: "1", max: "40", inputmode: "numeric" });
    const starts = el("input", { class: "field", type: "date" });
    const intention = el("textarea", { class: "field", maxlength: "1000", rows: "2", placeholder: "Wisdom about the job, my brother's health..." });
    const passage = el("input", { class: "field", maxlength: "120", placeholder: "Isaiah 58:6, or leave blank" });
    detail.value = (existing && existing.detail) || "";
    days.value = existing ? existing.days : 1;
    starts.value = cave().localToday();
    intention.value = (existing && existing.intention) || "";
    passage.value = (existing && existing.passage_ref) || "";

    const hint = el("p", { class: "seg-hint" });
    const detailLabel = el("span");
    const detailWrap = el("label", { class: "field-wrap" }, [detailLabel, detail]);
    const kinds = Object.entries(FAST_KINDS).map(([key, k]) =>
      el("button", { type: "button", "aria-pressed": String(key === kind), text: k.short, onclick: () => { kind = key; paint(); } })
    );
    function paint() {
      kinds.forEach((b, i) => b.setAttribute("aria-pressed", String(Object.keys(FAST_KINDS)[i] === kind)));
      const k = FAST_KINDS[kind];
      hint.textContent = k.hint;
      detailWrap.hidden = !k.detail;
      detailLabel.textContent = k.detail || "";
      detail.placeholder = k.placeholder || "";
    }
    paint();

    const quickDays = el("div", { class: "quick-picks", role: "group", "aria-label": "Common lengths" }, [1, 3, 7, 21, 40].map((n) =>
      el("button", { type: "button", text: plural(n, "day", "days"), onclick: () => { days.value = n; } })
    ));
    const msg = cave().formMessage();
    const save = el("button", { class: "btn btn-ember btn-sm", type: "submit", text: existing ? "Save" : "Start fast" });
    const form = el("form", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "fastTitle" }, [
      cave().sheetTitle("fastTitle", existing ? "Edit fast" : "Start a fast", "Only you can see this. Fast as you're able, whether that's a meal, a day or longer."),
      // Health comes first, so this one stays on the sheet rather than behind the info button.
      el("p", { class: "sheet-lede", text: "Check with a doctor before a long fast." }),
      el("div", { class: "seg seg-sheet", role: "group", "aria-label": "Kind of fast" }, kinds),
      hint,
      detailWrap,
      el("div", { class: "field-row" }, [
        el("label", { class: "field-wrap" }, ["How many days", days]),
        existing ? null : el("label", { class: "field-wrap" }, ["Starting", starts]),
      ].filter(Boolean)),
      quickDays,
      el("label", { class: "field-wrap" }, ["What are you fasting and praying for? (optional)", intention]),
      el("label", { class: "field-wrap" }, ["A verse to hold onto (optional)", passage]),
      msg.node,
    ]);
    const close = cave().overlay(form);
    form.append(sheetActions(close, save));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const n = Number(days.value);
      if (!Number.isInteger(n) || n < 1 || n > 40) return msg.say("A fast here is from 1 to 40 days.", true);
      save.disabled = true;
      const body = {
        kind,
        detail: FAST_KINDS[kind].detail ? detail.value.trim() || null : null,
        days: n,
        intention: intention.value.trim() || null,
        passage_ref: passage.value.trim() || null,
        today: cave().localToday(),
      };
      try {
        if (existing) await api(`/me/fasts/${existing.id}`, { method: "PATCH", body });
        else await api("/me/fasts", { method: "POST", body: { ...body, starts_on: starts.value || null } });
        close();
        toast(existing ? "Saved." : "Your fast has begun. The Lord be with you.");
        onSaved();
      } catch (err) {
        msg.say(err.message, true);
        save.disabled = false;
      }
    });
  }

  function finishFastSheet(f, onSaved) {
    const reflection = el("textarea", { class: "field", maxlength: "2000", rows: "3", placeholder: "What did you notice? What did God show you? Or leave it blank." });
    const msg = cave().formMessage();
    const save = el("button", { class: "btn btn-ember btn-sm", type: "submit", text: "Finish fast" });
    const form = el("form", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "finishFastTitle" }, [
      el("h3", { id: "finishFastTitle", text: "Finish your fast" }),
      el("div", { class: "journal-preview" }, [el("strong", { text: `${fastTitle(f)} · ${fastWhen(f)}` }), document.createTextNode(f.intention || "")]),
      el("label", { class: "field-wrap" }, ["Remember it (optional)", reflection]),
      msg.node,
    ]);
    const close = cave().overlay(form);
    form.append(sheetActions(close, save));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      save.disabled = true;
      try {
        await api(`/me/fasts/${f.id}`, { method: "PATCH", body: { status: "finished", reflection: reflection.value.trim() || null, today: cave().localToday() } });
        close();
        toast("Well done. Break your fast gently.");
        onSaved();
      } catch (err) {
        msg.say(err.message, true);
        save.disabled = false;
      }
    });
  }

  async function deleteFast(f, onChange) {
    if (!confirm("Delete this fast? This can't be undone.")) return;
    try {
      await api(`/me/fasts/${f.id}`, { method: "DELETE" });
      onChange();
    } catch (err) {
      toast(err.message);
    }
  }

  function pastFastsSheet(past, onChange) {
    const close = cave().overlay(el("div", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "pastFastsTitle" }, [
      el("h3", { id: "pastFastsTitle", text: "Past fasts" }),
      el("div", { class: "past-list" }, past.map((f) => el("div", { class: "past-item" }, [
        el("div", { class: "past-head" }, [
          el("strong", { text: fastTitle(f) }),
          cave().moreMenu(`More for ${fastTitle(f)}`, [{ label: "Delete", danger: true, onClick: () => { close(); deleteFast(f, onChange); } }]),
        ]),
        el("span", { class: "faint", text: fastWhen(f) }),
        f.intention ? el("p", { text: f.intention }) : null,
        f.reflection ? el("div", { class: "answer-note" }, [el("strong", { text: "What you noticed" }), el("p", { text: f.reflection })]) : null,
      ].filter(Boolean)))),
      el("div", { class: "sheet-actions" }, el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Close", onclick: () => close() })),
    ]));
  }

  function fastCard(fasts, onChange) {
    const start = () => fastSheet(null, onChange);
    const pastLink = fasts.past.length
      ? el("button", { class: "linkish practice-link", type: "button", text: `Past fasts (${fasts.past.length})`, onclick: () => pastFastsSheet(fasts.past, onChange) })
      : null;

    if (!fasts.active.length) {
      return el("section", { class: "card practice-card fade-in" }, [
        cave().cardHead("Fasting", null),
        el("p", { class: "muted practice-lede", text: "Set aside a time to fast and pray, and keep track of the days here." }),
        el("div", { class: "practice-foot" }, [pastLink || el("span"), el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Start a fast", onclick: start })]),
      ]);
    }

    const rows = fasts.active.map((f) => {
      const p = f.progress;
      const finish = el("button", {
        class: `btn btn-sm ${p.last_day_reached ? "btn-ember" : "btn-ghost"}`,
        type: "button", text: "Finish", onclick: () => finishFastSheet(f, onChange),
      });
      const pray = el("button", {
        class: "act", type: "button", html: `${ICON.aquila}<span>Pray with Aquila</span>`,
        onclick: () => prayWithAquila(`I'm fasting${f.intention ? ` and praying for this: ${f.intention}` : " and want to pray"}.`, f.passage_ref),
      });
      return el("div", { class: "fast" }, [
        el("div", { class: "fast-head" }, [
          el("div", { class: "fast-title" }, [el("strong", { text: fastTitle(f) }), el("span", { class: "faint", text: fastWhen(f) })]),
          cave().moreMenu(`More for ${fastTitle(f)}`, [
            { label: "Edit", onClick: () => fastSheet(f, onChange) },
            { label: "Start another fast", onClick: start },
            { label: "Delete", danger: true, onClick: () => deleteFast(f, onChange) },
          ]),
        ]),
        el("div", { class: "bar", role: "progressbar", "aria-label": "Days of the fast", "aria-valuemin": "0", "aria-valuemax": String(p.of), "aria-valuenow": String(p.day) },
          el("span", { style: `width:${Math.round(p.fraction * 100)}%` })),
        f.intention ? el("p", { class: "fast-intention", text: f.intention }) : null,
        el("div", { class: "practice-foot" }, [pray, finish]),
      ].filter(Boolean));
    });
    return el("section", { class: "card practice-card is-fasting fade-in" }, [
      cave().cardHead("Fasting", pastLink),
      ...rows,
    ]);
  }

  // ---------------------------------------------------------------------
  // The prayer list
  // ---------------------------------------------------------------------
  function prayerCard(p, prayedFor, rerender) {
    const answered = p.status === "answered";
    const node = el("article", { class: `entry prayer-card${answered ? " is-answered" : ""} fade-in` });
    const remove = {
      label: "Delete", danger: true, onClick: async () => {
        if (!confirm("Delete this prayer? This can't be undone.")) return;
        try {
          await api(`/me/prayers/${p.id}`, { method: "DELETE" });
          rerender();
        } catch (err) {
          toast(err.message);
        }
      },
    };
    const menu = cave().moreMenu("More for this prayer", answered
      ? [{
          label: "Reopen", onClick: async () => {
            try {
              await api(`/me/prayers/${p.id}`, { method: "PATCH", body: { status: "open" } });
              rerender();
            } catch (err) {
              toast(err.message);
            }
          },
        }, remove]
      : [{ label: "Edit", onClick: () => openSheet({ existing: p }, rerender) }, remove]);

    const week = prayedFor || { today: false, this_week: 0 };
    // One line of running text, so on a narrow card it wraps like a sentence
    // rather than dropping the count onto a line of its own.
    const since = el("span", { class: "entry-since", text: `Praying since ${shortDate(p.created_at)}` });
    if (week.this_week) since.append(" · ", el("span", { class: "prayed-count", text: `prayed ${plural(week.this_week, "day", "days")} this week` }));
    const meta = el("div", { class: "entry-meta" }, [
      answered ? el("span", { class: "badge answered", html: `${ICON.check}<span>Answered ${shortDate(p.answered_at)}</span>` }) : since,
      menu,
    ]);

    let footer;
    if (answered) {
      footer = null;
    } else {
      const prayed = el("button", {
        class: `act${week.today ? " is-done" : ""}`,
        type: "button",
        "aria-pressed": String(week.today),
        html: `${week.today ? ICON.check : ICON.circle}<span>${week.today ? "Prayed today" : "Prayed"}</span>`,
        onclick: async () => {
          prayed.disabled = true;
          if (await logPrayed({ prayerId: p.id, prayed: !week.today })) rerender();
          else prayed.disabled = false;
        },
      });
      footer = el("div", { class: "entry-actions" }, [
        prayed,
        // On a phone this shows its icon alone (.act-collapse), so it keeps
        // its name in aria-label and title.
        el("button", {
          class: "act act-collapse", type: "button", "aria-label": "Pray with Aquila", title: "Pray with Aquila",
          html: `${ICON.aquila}<span>Pray with Aquila</span>`, onclick: () => prayWithAquila(p.body, p.passage_ref),
        }),
        // Scripture spoken aloud over this request (web/declare.js); opens its
        // kept declaration when it has one.
        el("button", {
          class: "act", type: "button",
          html: `${ICON.declare}<span>Declare over</span>`, onclick: () => window.Declare.open({ from: "prayer", prayer: { id: p.id, body: p.body } }),
        }),
        // Quiet on purpose, at the end of the row: there when it's time,
        // without pressing the question every time the list is opened.
        el("button", { class: "act-quiet", type: "button", html: `${ICON.check}<span>Answered</span>`, onclick: () => openAnsweredSheet(p, rerender) }),
      ]);
    }

    // Optional parts are null; filtered out because DOM append would print them.
    node.append(...[
      meta,
      el("p", { class: "prayer-body", text: p.body }),
      p.passage_ref
        ? el("a", { class: "pill prayer-passage", href: `#${window.Reader.href(p.passage_ref)}`, html: ICON.book }, el("span", { text: p.passage_ref }))
        : null,
      answered && p.answer_note
        ? el("div", { class: "answer-note" }, [el("strong", { text: "How it was answered" }), el("p", { text: p.answer_note })])
        : null,
      footer,
    ].filter(Boolean));
    return node;
  }

  // ---------------------------------------------------------------------
  // The tab
  // ---------------------------------------------------------------------
  async function renderTab(panel) {
    const rerender = () => renderTab(panel);
    const today = cave().localToday();
    // The week and fasting read tables from a later migration than the list,
    // so each fails on its own and the list still shows.
    const [rows, week, fasts] = await Promise.all([
      api("/me/prayers"),
      api(`/me/prayers/week?today=${today}`).catch((err) => ({ error: err })),
      api(`/me/fasts?today=${today}`).catch((err) => ({ error: err })),
    ]);

    let practice;
    if (week.error && fasts.error) {
      practice = el("p", { class: "setup-note", text: week.error.message });
    } else {
      practice = el("div", { class: "practice-grid" }, [
        week.error ? null : weekCard(week, rerender),
        fasts.error ? null : fastCard(fasts, rerender),
      ].filter(Boolean));
    }
    const prayedFor = (week && week.by_prayer) || {};

    if (!rows.length) {
      panel.replaceChildren(practice, el("div", { class: "empty" }, [
        el("strong", { text: "Your prayer list is empty" }),
        "Keep what you're praying for here. Mark the days you pray for it, and when it's answered, look back on how God has been faithful.",
        el("div", {}, el("button", { class: "btn btn-ember btn-sm", type: "button", text: "Add a prayer", onclick: () => openSheet({}, rerender) })),
      ]));
      return;
    }

    const open = rows.filter((p) => p.status === "open");
    const answered = rows
      .filter((p) => p.status === "answered")
      .sort((a, b) => (b.answered_at || "").localeCompare(a.answered_at || ""));
    const list = showing === "answered" ? answered : open;
    const bar = cave().listBar(
      showing === "answered" ? `${answered.length} answered` : `${open.length} open`,
      cave().filterSelect("Which prayers to show", [
        ["open", `Open (${open.length})`],
        ["answered", `Answered (${answered.length})`],
      ], showing, (value) => { showing = value; rerender(); })
    );
    const empty = showing === "answered"
      ? "Nothing marked answered yet. When a prayer is answered, mark it on the Open list."
      : "No open prayers right now.";
    panel.replaceChildren(
      practice,
      el("h2", { class: "section-title prayer-list-title", text: "Prayer list" }),
      bar,
      list.length
        ? el("div", { class: "entries prayer-list" }, list.map((p) => prayerCard(p, prayedFor[p.id], rerender)))
        : el("p", { class: "muted", text: empty })
    );
  }

  window.Prayers = { renderTab, openSheet };
})();
