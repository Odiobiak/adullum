// Reflections: a guided time with God over a month, a quarter, a year or a
// season the person names (app/reflections.py).
//
//   Starting one   "Reflection" under the Journal's New entry opens a sheet:
//                  pick the length of time and the stretch it looks back on.
//   The reflection #reflection/<id>, drawn inside the Journal tab, in three
//                  stages. Look back: the numbers they choose to count, their
//                  goals, each area of life with how it went. Lay down. Look
//                  ahead, mirroring look back: numbers to aim for, and for each
//                  area where they'd like it to be and what they'd like to see.
//                  It saves as they write, so it can take a few evenings.
//   Kept           its look ahead is the plan for the stretch ahead: pinned at
//                  the top of the Journal while it runs (planCard), a goal can
//                  go to Pebbles, the home screen shows a halfway check-in
//                  (homeCard), and the next reflection opens with "What you
//                  set out" beside what happened.
//
// Private to the person; nothing here feeds Aquila's memory. A verse is kept as
// a reference and its text is always read from the database.
//
// Loaded after web/cave.js, whose helpers it borrows through window.Cave at
// call time. Reached as window.Reflections.
(function () {
  const cave = () => window.Cave;
  const app = () => window.AdullumApp;
  const el = (...args) => cave().el(...args);
  const api = (...args) => cave().api(...args);
  const toast = (...args) => cave().toast(...args);

  const SPANS = [["month", "Month"], ["quarter", "Quarter"], ["year", "Year"], ["season", "Season"]];
  // How a question names the stretch being looked back on.
  const SPAN_WORDS = { month: "this month", quarter: "these three months", year: "this year", season: "this season" };
  const RATINGS = [["hard", "Hard"], ["mixed", "Mixed"], ["steady", "Steady"], ["thriving", "Thriving"]];
  const RATING_NAME = Object.fromEntries(RATINGS);
  // Areas of life offered to begin with; the person can name their own.
  const AREAS = ["Spiritual", "Family", "Social", "Health", "Work", "Money", "Church", "Rest"];
  const KINDS = [["habit", "Habit"], ["number", "A number"], ["date", "By a date"], ["hope", "A hope"]];
  const PER_WEEK = ["once a week", "twice a week", "3 days a week", "4 days a week", "5 days a week", "6 days a week", "every day"];
  const GOAL_STATUS = { on_the_way: "On the way", reached: "Reached", not_this_time: "Not this time" };
  const STAGES = [["back", "Look back"], ["lay", "Lay down"], ["ahead", "Look ahead"]];
  // What the name field suggests for each length of time. A reflection
  // without a name is called by its dates.
  const NAME_HINTS = { month: "A month of rest", quarter: "Back to basics", year: "A year of new beginnings", season: "My first year in a new city" };
  const TITLE_LENGTH = 80;
  const STONES_VERSE = "1 Samuel 7:12";
  const SAVE_DELAY = 900;
  // The halfway check-ins someone has put away, by reflection id, on this device.
  const CHECK_IN_KEY = "adullumCheckInsPutAway";

  // What Adullum counts for the person (from their cave, or from Pebbles)
  // carries the cave's own arch; a reflection itself, a sun on the horizon.
  const CAVE_MARK = '<svg class="refl-mark" viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" aria-hidden="true"><path d="M4 28C4 15 9 5 16 5s12 10 12 23M12.5 28c0-4.5 1.6-7.5 3.5-7.5s3.5 3 3.5 7.5"/></svg>';
  const HORIZON = '<svg class="refl-mark" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M3 18h18M6.5 18a5.5 5.5 0 0 1 11 0M12 5v3M5.6 9.1l1.8 1.8M18.4 9.1l-1.8 1.8"/></svg>';
  const ICON_SUMMARY = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>';
  const ICON_CHEVRON = '<svg class="refl-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>';

  // ---------------------------------------------------------------------
  // Small helpers
  // ---------------------------------------------------------------------
  // 12 -> "12", 2.5 -> "2.5", 3000 -> "3,000"
  function num(value) {
    return Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  function parseNum(text) {
    const value = Number(String(text).replace(/,/g, "").trim());
    return text !== "" && Number.isFinite(value) && value > 0 ? value : null;
  }
  function sameName(a, b) {
    return a.trim().toLowerCase() === b.trim().toLowerCase();
  }
  function xButton(label, onclick) {
    return el("button", { class: "refl-x", type: "button", "aria-label": label, title: label, text: "×", onclick });
  }
  function bar(fraction) {
    return el("div", { class: "refl-bar", "aria-hidden": "true" }, el("i", { style: `width:${Math.round(Math.min(Math.max(fraction, 0), 1) * 100)}%` }));
  }
  function seg(label, options, selected, onPick) {
    return el("div", { class: "seg refl-seg", role: "group", "aria-label": label }, options.map(([value, text]) =>
      el("button", { type: "button", "aria-pressed": String(value === selected), text, onclick: () => onPick(value === selected ? null : value) })
    ));
  }
  function textField(label, value, onInput, { long = false, placeholder = "" } = {}) {
    const input = el(long ? "textarea" : "input", { placeholder });
    input.value = value || "";
    input.addEventListener("input", () => onInput(input.value));
    return el("label", { class: "refl-field" }, [el("span", { text: label }), input]);
  }
  function blockTitle(text, about) {
    return cave().titleInfo(el("h3", { class: "refl-block-title", text }), about);
  }

  // ---------------------------------------------------------------------
  // Starting one
  // ---------------------------------------------------------------------
  function openStart() {
    if (!cave().signedIn()) {
      toast("Create a free account to keep a journal.", { tone: "info" });
      app().go("join");
      return;
    }
    let span = "year";
    let shift = 0;
    let asked = 0; // the latest preview asked for; older answers are ignored

    // A season starts out as the last six months, to change as they like.
    const from = el("input", { type: "date", "aria-label": "Season starts" });
    const to = el("input", { type: "date", "aria-label": "Season ends" });
    const sixMonthsAgo = new Date();
    sixMonthsAgo.setDate(1);
    sixMonthsAgo.setMonth(sixMonthsAgo.getMonth() - 6);
    from.value = `${sixMonthsAgo.getFullYear()}-${String(sixMonthsAgo.getMonth() + 1).padStart(2, "0")}-01`;
    to.value = cave().localToday();
    const back = el("strong", { text: "..." });
    const ahead = el("strong", { text: "..." });
    const earlier = el("button", { class: "refl-step", type: "button", "aria-label": "Earlier", text: "‹", onclick: () => { shift -= 1; refresh(); } });
    const later = el("button", { class: "refl-step", type: "button", "aria-label": "Later", text: "›", onclick: () => { shift += 1; refresh(); } });
    const spanRow = el("div", { class: "refl-span" }, [
      earlier,
      el("div", { class: "refl-span-box" }, [el("small", { text: "Looking back on" }), back]),
      el("span", { class: "refl-span-arrow", "aria-hidden": "true", text: "→" }),
      el("div", { class: "refl-span-box" }, [el("small", { text: "Looking ahead to" }), ahead]),
      later,
    ]);
    const seasonDates = el("div", { class: "refl-dates", hidden: true }, [
      el("label", {}, ["From", from]),
      el("label", {}, ["To", to]),
    ]);
    const lastWord = el("p", { class: "refl-last", hidden: true });
    const name = el("input", { id: "reflName", maxlength: String(TITLE_LENGTH), autocomplete: "off" });
    const nameField = el("label", { class: "field-wrap refl-name-field" }, ["Name it (optional)", name]);
    const spans = el("div", { class: "seg seg-sheet", role: "group", "aria-label": "Length of time" });
    const msg = cave().formMessage();
    const begin = el("button", { class: "btn btn-ember btn-sm", type: "submit", text: "Begin" });
    const form = el("form", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "reflStartTitle" }, [
      cave().sheetTitle("reflStartTitle", "What are you reflecting on?", "A reflection looks back over a stretch of time with God, and ahead to the next. Every question is optional, and it saves as you go."),
      spans, spanRow, seasonDates, nameField, lastWord, msg.node,
      el("div", { class: "sheet-actions" }, [el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Cancel", onclick: () => close() }), begin]),
    ]);
    const close = cave().overlay(form);

    function query() {
      const q = new URLSearchParams({ span, today: cave().localToday(), shift: String(shift) });
      if (span === "season") q.set("starts_on", from.value), q.set("ends_on", to.value);
      return q;
    }
    async function refresh() {
      spans.replaceChildren(...SPANS.map(([value, label]) =>
        el("button", { type: "button", "aria-pressed": String(value === span), text: label, onclick: () => { span = value; shift = 0; refresh(); } })
      ));
      seasonDates.hidden = span !== "season";
      name.placeholder = NAME_HINTS[span];
      earlier.hidden = later.hidden = span === "season";
      if (span === "season" && !(from.value && to.value)) {
        back.textContent = ahead.textContent = "Choose the dates";
        return;
      }
      const mine = ++asked;
      try {
        const p = await api(`/me/reflections/period?${query()}`);
        if (mine !== asked) return;
        back.textContent = p.label;
        ahead.textContent = p.ahead_label;
        lastWord.hidden = !p.last_word;
        lastWord.textContent = p.last_word ? `Last time you chose "${p.last_word}".` : "";
        msg.say("");
        begin.disabled = false;
      } catch (err) {
        if (mine !== asked) return;
        msg.say(err.message, true);
        begin.disabled = true;
      }
    }
    from.addEventListener("change", refresh);
    to.addEventListener("change", refresh);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      begin.disabled = true;
      try {
        const body = { span, title: name.value.trim() || null, today: cave().localToday(), shift };
        if (span === "season") Object.assign(body, { starts_on: from.value, ends_on: to.value });
        const r = await api("/me/reflections", { method: "POST", body });
        close();
        app().go(`reflection/${r.id}`);
      } catch (err) {
        msg.say(err.message, true);
        begin.disabled = false;
      }
    });
    refresh();
  }

  // ---------------------------------------------------------------------
  // A reflection, open in the Journal tab
  // ---------------------------------------------------------------------
  // The open reflection: the server's row plus what the page needs to keep
  // drawing it. Null when none is open.
  let open = null;

  // Fills in anything an older or brand-new reflection doesn't have yet, so
  // the drawing code can assume every list and field is there.
  function settle(r) {
    r.title = r.title || "";
    r.look_back = { numbers: [], goals: [], areas: [], saw_god: "", taught: "", ...(r.look_back || {}) };
    r.lay_down = { grateful: "", lay_down: "", forgive: "", ...(r.lay_down || {}) };
    r.look_ahead = { word: "", verse_ref: "", numbers: [], areas: [], asking: "", leading: "", ...(r.look_ahead || {}) };
    r.look_ahead.verse_ref = r.look_ahead.verse_ref || "";
    // Cave numbers always show what the cave holds now.
    for (const n of r.look_back.numbers) {
      if (n.key && r.summary.counts[n.key] !== undefined) n.value = String(r.summary.counts[n.key]);
    }
    return r;
  }

  async function show(panel, id) {
    await flush();
    panel.replaceChildren(el("div", { class: "empty", text: "Opening your reflection..." }));
    let r;
    try {
      r = settle(await api(`/me/reflections/${id}?today=${cave().localToday()}`));
    } catch (err) {
      panel.replaceChildren(el("div", { class: "empty" }, [
        el("strong", { text: "Couldn't open this reflection" }), err.message,
        el("div", {}, el("a", { class: "btn btn-ghost btn-sm", href: "#journal", text: "Back to your journal" })),
      ]));
      return;
    }
    open = { r, panel, stage: "back", timer: null, dirty: false, saving: null, summaryOpen: false, status: null, prayAsking: false, startPlan: false };
    draw();
  }

  // Leaving the reflection (another tab, another page) saves what's waiting.
  function hide() {
    flush();
    open = null;
  }

  // ----- saving -----
  function touch() {
    if (!open) return;
    open.dirty = true;
    setStatus("Saving...");
    clearTimeout(open.timer);
    open.timer = setTimeout(save, SAVE_DELAY);
  }

  async function save() {
    if (!open || !open.dirty) return;
    const { r } = open;
    const current = open;
    current.dirty = false;
    clearTimeout(current.timer);
    const request = api(`/me/reflections/${r.id}`, {
      method: "PUT",
      body: { title: r.title, look_back: r.look_back, lay_down: r.lay_down, look_ahead: r.look_ahead },
    });
    current.saving = request;
    try {
      const res = await request;
      if (open !== current) return;
      setStatus(res.verse_error ? "Saved. Check the verse." : "Saved");
      showVerse(res.verse_error ? null : res.verse_ref, res.verse_error);
    } catch (err) {
      if (open !== current) return;
      current.dirty = true;
      setStatus(`Not saved yet: ${err.message}`, true);
    } finally {
      if (current.saving === request) current.saving = null;
    }
  }

  // Saves now if anything is waiting, and waits for any save under way.
  async function flush() {
    if (!open) return;
    if (open.dirty) await save();
    else if (open.saving) await open.saving.catch(() => {});
  }

  function setStatus(text, bad) {
    if (!open || !open.status) return;
    open.status.textContent = text;
    open.status.classList.toggle("bad", !!bad);
  }

  // ----- the frame: back link, title, stages, footer -----
  function draw() {
    const { r, panel } = open;
    open.status = el("span", { class: "refl-status", role: "status", text: r.status === "kept" ? "Kept" : "Draft, saved as you go" });
    const menu = cave().moreMenu("More for this reflection", [{ label: "Delete this reflection", danger: true, onClick: remove }]);
    const stageTabs = el("div", { class: "seg refl-stages", role: "tablist", "aria-label": "Stages" }, STAGES.map(([key, label]) =>
      el("button", { type: "button", role: "tab", "aria-selected": String(key === open.stage), text: label, onclick: () => goTo(key) })
    ));
    const body = el("div", { class: "refl-body" }, { back: lookBack, lay: layDown, ahead: lookAhead }[open.stage]());
    panel.replaceChildren(
      el("div", { class: "refl-top" }, [
        el("a", { class: "refl-backlink", href: "#journal", text: "‹ Journal" }),
        open.status,
        menu,
      ]),
      el("header", { class: "refl-head" }, [
        el("p", { class: "kicker ember refl-kicker", html: HORIZON }, ["Reflection"]),
        nameInput(),
        el("p", { class: "refl-dates-line", text: `${r.label} into ${r.ahead_label}` }),
      ]),
      stageTabs,
      body,
      footer()
    );
  }

  // The reflection's name as a heading that can be typed into. Left blank,
  // the dates under it are what it's called.
  function nameInput() {
    const { r } = open;
    const input = el("input", {
      class: "refl-title", value: r.title, maxlength: String(TITLE_LENGTH), placeholder: "Name this reflection",
      "aria-label": "The name of this reflection", autocomplete: "off",
    });
    input.addEventListener("input", () => { r.title = input.value; touch(); });
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") input.blur(); });
    return input;
  }

  function goTo(stage) {
    open.stage = stage;
    draw();
    open.panel.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function footer() {
    const at = STAGES.findIndex(([key]) => key === open.stage);
    const back = at > 0 ? el("button", { class: "linkish", type: "button", text: "Back", onclick: () => goTo(STAGES[at - 1][0]) }) : el("span");
    const next = at < STAGES.length - 1
      ? el("button", { class: "btn btn-ember", type: "button", text: "Next", onclick: () => goTo(STAGES[at + 1][0]) })
      : el("button", { class: "btn btn-ember", type: "button", text: open.r.status === "kept" ? "Save changes" : "Keep this reflection", onclick: (e) => keep(e.currentTarget) });
    return el("div", { class: "refl-foot" }, [back, next]);
  }

  // Redraws the open stage after a change to its shape (something added,
  // removed or switched), keeping the page where it was.
  function redraw(focusSelector) {
    const y = window.scrollY;
    draw();
    window.scrollTo({ top: y });
    if (focusSelector) {
      const target = open.panel.querySelector(focusSelector);
      if (target) target.focus();
    }
  }

  async function remove() {
    if (!confirm("Delete this reflection? Pebbles it started stay in Refuge. This can't be undone.")) return;
    const { r } = open;
    clearTimeout(open.timer);
    open = null;
    try {
      await api(`/me/reflections/${r.id}`, { method: "DELETE" });
      toast("Reflection deleted.");
    } catch (err) {
      toast(err.message, { tone: "error" });
    }
    app().go("journal");
  }

  async function keep(button) {
    button.disabled = true;
    const { r } = open;
    try {
      open.dirty = true;
      await flush();
      if (!open || open.dirty) throw new Error("Your reflection didn't save. Check your connection and try again.");
      const kept = await api(`/me/reflections/${r.id}/keep`, { method: "POST", body: { today: cave().localToday() } });
      if (open && open.prayAsking && r.look_ahead.asking.trim()) {
        await api("/me/prayers", { method: "POST", body: { body: r.look_ahead.asking.trim() } }).catch((err) => toast(err.message, { tone: "error" }));
      }
      const goPlan = open && open.startPlan;
      open = null;
      toast(kept.planted ? `Kept. ${kept.planted === 1 ? "One goal is" : `${kept.planted} goals are`} in Pebbles now.` : "Kept. It's pinned in your journal.",
          kept.planted ? { action: { label: "Pebbles", href: "#pebbles" } } : {});
      app().go(goPlan ? "bible/plans" : "journal");
    } catch (err) {
      toast(err.message, { tone: "error" });
      button.disabled = false;
    }
  }

  // ---------------------------------------------------------------------
  // Look back
  // ---------------------------------------------------------------------
  function lookBack() {
    const { r } = open;
    const lb = r.look_back;
    const words = SPAN_WORDS[r.span];
    return [
      el("h3", { class: "refl-stage-title", text: `Looking back on ${r.label}` }),
      summaryBlock(),
      areasBlock("back"),
      textField(`Where did you see God ${words}?`, lb.saw_god, (v) => { lb.saw_god = v; touch(); }, { long: true, placeholder: "A moment, a person, a verse that met you" }),
      r.span === "month" ? null : textField("What did He teach you?", lb.taught, (v) => { lb.taught = v; touch(); }, { long: true, placeholder: "Something you know now that you didn't before" }),
    ];
  }

  // The summary, folded into one line until it's opened.
  function summaryBlock() {
    const { r } = open;
    const line = el("span");
    const updateLine = () => {
      line.textContent = r.look_back.numbers.filter((n) => n.label && n.value !== "").slice(0, 3).map((n) => `${n.value} ${n.label}`).join(", ") || "Tap to choose what you count";
    };
    updateLine();
    const details = el("details", { class: "refl-summary" }, [
      el("summary", {}, [
        el("span", { class: "refl-summary-badge", html: ICON_SUMMARY }),
        el("span", { class: "refl-summary-title" }, [el("strong", { text: `Your ${r.label} at a glance` }), line]),
        el("span", { html: ICON_CHEVRON }),
      ]),
      el("div", { class: "refl-summary-body" }, [
        r.set_out ? setOutPanel(r.set_out) : null,
        countTiles(updateLine),
        goalsPanel(),
        passagesPanel(),
        stonesPanel(),
        el("p", { class: "refl-note", text: "Only you see this. Taking something out here leaves it as it is everywhere else." }),
      ]),
    ]);
    details.open = open.summaryOpen;
    details.addEventListener("toggle", () => { if (open) open.summaryOpen = details.open; });
    return details;
  }

  // "What you set out": last time's plan for this stretch, beside what happened.
  function setOutPanel(so) {
    const ratings = Object.fromEntries(open.r.look_back.areas.map((a) => [a.name.toLowerCase(), a.rating]));
    const rows = [];
    for (const n of so.numbers || []) {
      if (!n.target) continue;
      const reached = n.done !== null && n.done >= n.target;
      rows.push(reviewRow(n.label, n.done === null ? `aimed for ${num(n.target)}` : reached ? `${num(n.done)} of ${num(n.target)}, reached` : `aimed for ${num(n.target)}, made ${num(n.done)}`,
        n.done === null ? null : n.done / n.target, reached));
    }
    for (const g of so.goals || []) {
      if (g.weeks) rows.push(reviewRow(g.text, `kept ${g.kept} of ${g.weeks} weeks`, g.kept / g.weeks, false, g.area));
      else if (g.status === "reached") rows.push(reviewRow(g.text, "Reached", 1, true, g.area));
      else if (g.measure) rows.push(reviewRow(g.text, g.progress, g.measure.fraction, false, g.area));
      else rows.push(reviewRow(g.text, g.status ? GOAL_STATUS[g.status] : "a hope", null, false, g.area));
    }
    for (const a of so.areas || []) {
      const now = ratings[(a.name || "").toLowerCase()];
      rows.push(reviewRow(a.name, now ? `hoped for ${RATING_NAME[a.aim]}, now ${RATING_NAME[now]}` : `hoped for ${RATING_NAME[a.aim]}`, null, now && a.aim === now));
    }
    return el("section", { class: "refl-panel" }, [
      el("h4", { text: `What you set out for ${so.label}` }),
      so.word ? el("p", { class: "refl-note", text: `Your word was "${so.word}".` }) : null,
      rows.length ? el("ul", { class: "refl-review" }, rows) : el("p", { class: "refl-note", text: "You didn't set anything to aim for last time." }),
    ]);
  }

  function reviewRow(label, result, fraction, met, area) {
    return el("li", {}, [
      el("div", { class: "refl-review-top" }, [
        el("span", {}, [label, area ? el("span", { class: "refl-area-tag", text: ` · ${area}` }) : null]),
        el("small", { class: met ? "met" : "", text: result }),
      ]),
      fraction === null || fraction === undefined ? null : bar(fraction),
    ]);
  }

  // "What you count": cave numbers (with the cave mark) and the person's own.
  function countTiles(updateLine) {
    const { r } = open;
    const numbers = r.look_back.numbers;
    const tiles = numbers.map((n) => {
      if (n.key) {
        return el("div", { class: "refl-tile" }, [
          el("strong", { text: n.value }),
          el("span", { html: CAVE_MARK }, [n.label]),
          xButton(`Take out ${n.label}`, () => { numbers.splice(numbers.indexOf(n), 1); touch(); redraw(); }),
        ]);
      }
      const value = el("input", { class: "refl-tile-num", value: n.value, "aria-label": "Number", placeholder: "0" });
      const label = el("input", { class: "refl-tile-label", value: n.label, "aria-label": "What it counts", placeholder: "what you counted" });
      value.addEventListener("input", () => { n.value = value.value.trim(); updateLine(); touch(); });
      label.addEventListener("input", () => { n.label = label.value; updateLine(); touch(); });
      return el("div", { class: "refl-tile" }, [value, label, xButton(`Remove ${n.label || "this number"}`, () => { numbers.splice(numbers.indexOf(n), 1); touch(); redraw(); })]);
    });
    const add = el("button", {
      class: "refl-tile refl-tile-add", type: "button", text: "+ Add a number",
      onclick: () => { numbers.push({ key: null, label: "", value: "" }); touch(); redraw(".refl-tile:nth-last-child(2) .refl-tile-num"); },
    });
    const missing = Object.keys(r.cave_counts).filter((key) => !numbers.some((n) => n.key === key));
    return el("section", { class: "refl-group" }, [
      el("div", { class: "refl-group-head" }, [el("h4", { text: "What you count" }), el("small", { html: `${CAVE_MARK}<span>from your cave, the rest are yours</span>` })]),
      el("div", { class: "refl-tiles" }, [...tiles, add]),
      missing.length ? el("div", { class: "refl-chips" }, missing.map((key) => el("button", {
        class: "chip-btn", type: "button", text: `+ ${r.cave_counts[key]}`,
        onclick: () => { numbers.push({ key, label: r.cave_counts[key], value: String(r.summary.counts[key] ?? 0) }); touch(); redraw(); },
      }))) : null,
    ]);
  }

  // Goals: Pebbles goals (counted there) and goals kept somewhere else.
  function goalsPanel() {
    const { r } = open;
    const goals = r.look_back.goals;
    const rows = goals.map((g) => {
      let status;
      if (g.seed_id) {
        status = el("span", { class: `refl-status-pill ${g.status || ""}`, text: g.status === "on_the_way" && g.progress ? g.progress : GOAL_STATUS[g.status] || "On the way" });
      } else {
        status = el("button", {
          class: `refl-status-pill ${g.status || ""}`, type: "button", title: "Tap to change", text: GOAL_STATUS[g.status] || "On the way",
          onclick: () => {
            const order = Object.keys(GOAL_STATUS);
            g.status = order[(order.indexOf(g.status) + 1) % order.length];
            touch();
            redraw();
          },
        });
      }
      return el("li", {}, [
        el("span", { class: "refl-goal-name", html: g.seed_id ? CAVE_MARK : "" }, [g.title]),
        status,
        xButton(`Take out ${g.title}`, () => { goals.splice(goals.indexOf(g), 1); touch(); redraw(); }),
      ]);
    });
    const input = el("input", { class: "refl-add-goal", placeholder: "A goal you kept somewhere else", "aria-label": "Add a goal", maxlength: "200" });
    const form = el("form", { class: "refl-add" }, [input, el("button", { class: "btn btn-ghost btn-sm", type: "submit", text: "Add" })]);
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const title = input.value.trim();
      if (!title) return;
      goals.push({ seed_id: null, title, status: "on_the_way", progress: null });
      touch();
      redraw(".refl-add-goal");
    });
    const missing = (r.summary.goals || []).filter((g) => !goals.some((x) => x.seed_id === g.seed_id));
    return el("section", { class: "refl-panel" }, [
      el("div", { class: "refl-group-head" }, [el("h4", { text: "Goals" }), el("small", { html: `${CAVE_MARK}<span>from Pebbles</span>` })]),
      rows.length ? el("ul", { class: "refl-goals" }, rows) : null,
      missing.length ? el("div", { class: "refl-chips" }, missing.map((g) => el("button", {
        class: "chip-btn", type: "button", text: `+ ${g.title}`,
        onclick: () => { goals.push({ ...g }); touch(); redraw(); },
      }))) : null,
      form,
    ]);
  }

  function passagesPanel() {
    const passages = open.r.summary.passages || [];
    if (!passages.length) return null;
    return el("section", { class: "refl-panel" }, [
      el("h4", { text: "Passages you kept coming back to" }),
      el("div", { class: "refl-chips" }, passages.map((ref) => el("a", { class: "badge refl-passage", href: window.Reader.href(ref), text: ref }))),
    ]);
  }

  // Answered prayers, under 1 Samuel 7:12 (its text read from the database).
  function stonesPanel() {
    const stones = open.r.summary.stones || [];
    if (!stones.length) return null;
    const verse = el("blockquote", { class: "refl-stones-verse", hidden: true }, [el("p", { class: "scripture" }), el("footer", { class: "refl-ref" })]);
    cave().verseText(STONES_VERSE).then((v) => {
      verse.querySelector("p").textContent = `"${v.text}"`;
      verse.querySelector("footer").textContent = `${STONES_VERSE} · ${v.translation}`;
      verse.hidden = false;
    }).catch(() => {});
    return el("section", { class: "refl-panel" }, [
      el("h4", { text: "Stones of help, prayers He answered" }),
      verse,
      el("ul", { class: "refl-stones" }, stones.map((s) => el("li", {}, [
        el("span", { text: s.text }),
        el("small", { text: new Date(s.answered_at).toLocaleDateString(undefined, { month: "short", day: "numeric" }) }),
      ]))),
    ]);
  }

  // ---------------------------------------------------------------------
  // Areas of life, in look back and look ahead alike
  // ---------------------------------------------------------------------
  function areaNames() {
    const { look_back: lb, look_ahead: la } = open.r;
    const names = [...AREAS];
    for (const a of [...lb.areas, ...la.areas]) if (!names.some((n) => sameName(n, a.name))) names.push(a.name);
    return names;
  }

  function areasBlock(side) {
    const { r } = open;
    const list = side === "back" ? r.look_back.areas : r.look_ahead.areas;
    const has = (name) => list.find((a) => sameName(a.name, name));
    const fresh = (name) => (side === "back" ? { name, rating: null, note: "" } : { name, aim: null, goals: [] });

    const chips = el("div", { class: "refl-area-chips" }, [
      ...areaNames().map((name) => el("button", {
        type: "button", "aria-pressed": String(!!has(name)), text: name,
        onclick: () => {
          const area = has(name);
          if (area) {
            if (side === "ahead" && area.goals.length && !confirm(`Leave out ${name}? Its goals here go with it.`)) return;
            list.splice(list.indexOf(area), 1);
          } else {
            list.push(fresh(name));
          }
          touch();
          redraw();
        },
      })),
      el("button", { class: "refl-area-own", type: "button", text: "+ Your own", onclick: () => { ownForm.hidden = false; ownInput.focus(); } }),
    ]);
    const ownInput = el("input", { class: "refl-own-area", placeholder: "Name an area, like Marriage or Studies", "aria-label": "Your own area of life", maxlength: "40" });
    const ownForm = el("form", { class: "refl-add", hidden: true }, [ownInput, el("button", { class: "btn btn-ghost btn-sm", type: "submit", text: "Add" })]);
    ownForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const name = ownInput.value.trim();
      if (!name) return;
      if (!has(name)) list.push(fresh(areaNames().find((n) => sameName(n, name)) || name));
      touch();
      redraw();
    });

    const cards = list.map((a) => (side === "back" ? areaBackCard(a, list) : areaAheadCard(a, list)));
    return el("section", { class: "refl-group" }, [
      blockTitle("Areas of your life", side === "back"
        ? "Pick the parts of life you'd like to look at. For each, say how it went and what happened."
        : "For each area, say where you'd like it to be and what you'd like to see happen there. A goal can be tracked in Pebbles."),
      chips, ownForm,
      el("div", { class: "refl-area-cards" }, cards),
    ]);
  }

  function areaBackCard(a, list) {
    const note = el("input", { class: "refl-area-note", value: a.note || "", placeholder: "What happened here?", "aria-label": `What happened in ${a.name}`, maxlength: "500" });
    note.addEventListener("input", () => { a.note = note.value; touch(); });
    return el("section", { class: "refl-area" }, [
      el("header", {}, [el("strong", { text: a.name }), xButton(`Leave out ${a.name}`, () => { list.splice(list.indexOf(a), 1); touch(); redraw(); })]),
      seg(`How was ${a.name}?`, RATINGS, a.rating, (value) => { a.rating = value; touch(); redraw(); }),
      note,
    ]);
  }

  function areaAheadCard(a, list) {
    const before = open.r.look_back.areas.find((x) => sameName(x.name, a.name));
    const input = el("input", { class: "refl-goal-input", placeholder: `Something for ${a.name.toLowerCase()}`, "aria-label": `Something you'd like to see in ${a.name}`, maxlength: "200" });
    const form = el("form", { class: "refl-add" }, [input, el("button", { class: "btn btn-ghost btn-sm", type: "submit", text: "Add" })]);
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      a.goals.push({ text, kind: "habit", per_week: 1, target: null, unit: null, due_on: null, track: false, seed_id: null });
      touch();
      const at = list.indexOf(a) + 1;
      redraw(`.refl-area:nth-child(${at}) .refl-goal-input`);
    });
    return el("section", { class: "refl-area" }, [
      el("header", {}, [el("strong", { text: a.name }), xButton(`Leave out ${a.name}`, () => {
        if (a.goals.length && !confirm(`Leave out ${a.name}? Its goals here go with it.`)) return;
        list.splice(list.indexOf(a), 1);
        touch();
        redraw();
      })]),
      el("p", { class: "refl-sub", text: before && before.rating ? `Where you'd like it to be (now ${RATING_NAME[before.rating]})` : "Where you'd like it to be" }),
      seg(`Where you'd like ${a.name} to be`, RATINGS, a.aim, (value) => { a.aim = value; touch(); redraw(); }),
      el("p", { class: "refl-sub", text: "What you'd like to see" }),
      a.goals.length ? el("ul", { class: "refl-agoals" }, a.goals.map((g) => goalAheadRow(a, g))) : null,
      form,
    ]);
  }

  // One goal for the stretch ahead: what kind it is, its detail, and whether
  // it goes to Pebbles.
  function goalAheadRow(area, g) {
    const kind = el("select", { class: "refl-select", "aria-label": `What kind of goal is ${g.text}` }, KINDS.map(([value, label]) =>
      el("option", { value, text: label, selected: value === g.kind })
    ));
    kind.disabled = !!g.seed_id;
    kind.addEventListener("change", () => {
      g.kind = kind.value;
      if (g.kind === "habit" && !g.per_week) g.per_week = 1;
      if (g.kind === "hope") g.track = false;
      touch();
      redraw();
    });

    const details = [];
    if (g.kind === "habit") {
      const often = el("select", { class: "refl-select", "aria-label": "How often" }, PER_WEEK.map((label, i) =>
        el("option", { value: String(i + 1), text: label, selected: i + 1 === (g.per_week || 1) })
      ));
      often.disabled = !!g.seed_id;
      often.addEventListener("change", () => { g.per_week = Number(often.value); touch(); });
      details.push(often);
    } else if (g.kind === "number") {
      const target = el("input", { class: "refl-small-input", type: "number", min: "0", step: "any", value: g.target ?? "", placeholder: "How many", "aria-label": "Number to reach" });
      const unit = el("input", { class: "refl-small-input", value: g.unit || "", placeholder: "books, pounds", "aria-label": "Counted in", maxlength: "30" });
      target.disabled = unit.disabled = !!g.seed_id;
      target.addEventListener("input", () => { g.target = parseNum(target.value); touch(); });
      unit.addEventListener("input", () => { g.unit = unit.value.trim() || null; touch(); });
      details.push(target, unit);
    } else if (g.kind === "date") {
      const due = el("input", { class: "refl-small-input", type: "date", value: g.due_on || "", "aria-label": "Done by" });
      due.disabled = !!g.seed_id;
      due.addEventListener("change", () => { g.due_on = due.value || null; touch(); });
      details.push(due);
    }

    let track = null;
    if (g.seed_id) {
      track = el("span", { class: "refl-track on", text: "In Pebbles" });
    } else if (g.kind !== "hope") {
      track = el("button", {
        class: `refl-track${g.track ? " on" : ""}`, type: "button", "aria-pressed": String(!!g.track),
        text: g.track ? "Goes to Pebbles" : "Track in Pebbles",
        title: "When you keep this reflection, it becomes a pebble you can tend in Refuge.",
        onclick: () => { g.track = !g.track; touch(); redraw(); },
      });
    }
    return el("li", { class: "refl-agoal" }, [
      el("strong", { text: g.text }),
      xButton(`Remove ${g.text}`, () => { area.goals.splice(area.goals.indexOf(g), 1); touch(); redraw(); }),
      el("div", { class: "refl-agoal-tools" }, [kind, ...details, track]),
    ]);
  }

  // ---------------------------------------------------------------------
  // Lay down
  // ---------------------------------------------------------------------
  function layDown() {
    const { r } = open;
    const ld = r.lay_down;
    return [
      el("h3", { class: "refl-stage-title", text: "Give thanks, and lay things down" }),
      el("p", { class: "refl-lede", text: `Before you look ahead, set down what you don't need to carry into ${r.ahead_label}.` }),
      textField("What are you grateful for?", ld.grateful, (v) => { ld.grateful = v; touch(); }, { long: true, placeholder: "Big or small" }),
      textField("What do you need to lay down?", ld.lay_down, (v) => { ld.lay_down = v; touch(); }, { long: true, placeholder: "A worry, a regret, a weight you've been holding" }),
      r.span === "month" ? null : textField("Is there anyone to forgive, or to ask forgiveness from?", ld.forgive, (v) => { ld.forgive = v; touch(); }, { long: true, placeholder: "Only if it's on your heart" }),
    ];
  }

  // ---------------------------------------------------------------------
  // Look ahead
  // ---------------------------------------------------------------------
  // The verse under the verse field, read from the database once it's a
  // reference, or what's wrong with it when it isn't.
  function showVerse(ref, problem) {
    if (!open) return;
    const box = open.panel.querySelector(".refl-verse-text");
    if (!box) return;
    if (problem) {
      box.replaceChildren(el("span", { class: "refl-note bad", text: problem }));
      return;
    }
    if (!ref) return box.replaceChildren();
    if (box.dataset.ref === ref) return;
    box.dataset.ref = ref;
    cave().verseText(ref).then((v) => {
      box.replaceChildren(el("span", { class: "scripture", text: `"${v.text}"` }), el("span", { class: "refl-ref", text: ` ${ref} · ${v.translation}` }));
    }).catch(() => box.replaceChildren());
  }

  function lookAhead() {
    const { r } = open;
    const la = r.look_ahead;
    const word = el("input", { class: "refl-word-input", value: la.word, maxlength: "40", placeholder: "One word", "aria-label": `A word for ${r.ahead_label}` });
    word.addEventListener("input", () => { la.word = word.value.trim(); touch(); });
    const verse = el("input", { value: la.verse_ref, placeholder: "John 15:4", "aria-label": "A verse to carry", maxlength: "120" });
    verse.addEventListener("input", () => { la.verse_ref = verse.value; touch(); });
    const verseText = el("p", { class: "refl-verse-text" });
    setTimeout(() => showVerse(la.verse_ref), 0);

    const checks = el("div", { class: "refl-checks" }, [
      check("Add what I'm asking for to my prayer list", null, open.prayAsking, (on) => { open.prayAsking = on; }),
      check("Start a reading plan", "Shaped with Aquila, or the whole Bible in a year", open.startPlan, (on) => { open.startPlan = on; }),
    ]);
    return [
      el("h3", { class: "refl-stage-title", text: `Looking ahead to ${r.ahead_label}` }),
      el("p", { class: "refl-lede", text: "Ask God what He has for it, then set out what you'd like it to hold. This is what you'll look back on next time." }),
      el("label", { class: "refl-field refl-word" }, [el("span", { text: `A word for ${r.ahead_label}` }), word]),
      el("label", { class: "refl-field" }, [el("span", { text: "A verse to carry" }), verse]),
      verseText,
      aimTiles(),
      areasBlock("ahead"),
      textField("What are you asking God for?", la.asking, (v) => { la.asking = v; touch(); }, { long: true, placeholder: "Hopes, prayers, a vision for what's next" }),
      r.span === "month" ? null : textField("Where do you sense Him leading?", la.leading, (v) => { la.leading = v; touch(); }, { long: true, placeholder: "Even if it's only a nudge" }),
      checks,
    ];
  }

  function check(label, sub, on, onChange) {
    const box = el("input", { type: "checkbox" });
    box.checked = on;
    box.addEventListener("change", () => onChange(box.checked));
    return el("label", { class: "refl-check" }, [box, el("span", {}, [label, sub ? el("small", { text: sub }) : null])]);
  }

  // Numbers to aim for, mirroring "What you count", with last time beside each.
  function aimTiles() {
    const { r } = open;
    const numbers = r.look_ahead.numbers;
    const tiles = numbers.map((n) => {
      const target = el("input", { class: "refl-tile-num", type: "number", min: "0", step: "any", value: n.target ?? "", placeholder: "Aim", "aria-label": `Aim for ${n.label || "this number"}` });
      target.disabled = !!n.seed_id;
      target.addEventListener("input", () => { n.target = parseNum(target.value); touch(); });
      const last = n.key ? r.summary.aim_lasts[n.key] : n.last;
      let label;
      if (n.key) {
        label = el("span", { html: CAVE_MARK }, [n.label]);
      } else {
        label = el("input", { class: "refl-tile-label", value: n.label, placeholder: "what you'll count", "aria-label": "What it counts", maxlength: "60" });
        label.disabled = !!n.seed_id;
        label.addEventListener("input", () => { n.label = label.value; touch(); });
      }
      return el("div", { class: "refl-tile" }, [
        target, label,
        last !== undefined && last !== null && last !== "" ? el("small", { class: "refl-last-time", text: `last time ${last}` }) : null,
        n.seed_id ? el("small", { class: "refl-last-time", text: "In Pebbles" }) : null,
        xButton(`Remove ${n.label || "this number"}`, () => { numbers.splice(numbers.indexOf(n), 1); touch(); redraw(); }),
      ]);
    });
    const add = el("button", {
      class: "refl-tile refl-tile-add", type: "button", text: "+ Add a number",
      onclick: () => { numbers.push({ key: null, label: "", target: null, last: null, seed_id: null }); touch(); redraw(".refl-aims .refl-tile:nth-last-child(2) .refl-tile-num"); },
    });
    // Offer what was counted looking back: the cave's numbers and the person's own.
    const offers = [
      ...r.aimable.filter((key) => !numbers.some((n) => n.key === key)).map((key) => ({ key, label: r.cave_counts[key], last: null })),
      ...r.look_back.numbers.filter((n) => !n.key && n.label.trim() && !numbers.some((x) => !x.key && sameName(x.label, n.label))).map((n) => ({ key: null, label: n.label.trim(), last: n.value })),
    ];
    return el("section", { class: "refl-group refl-aims" }, [
      blockTitle("Numbers to aim for", "Set a number to reach. Those marked with the cave Adullum counts for you. Your own go to Pebbles when you keep this, so you can move them along as you go."),
      el("div", { class: "refl-tiles" }, [...tiles, add]),
      offers.length ? el("div", { class: "refl-chips" }, offers.map((o) => el("button", {
        class: "chip-btn", type: "button", text: `+ ${o.label}`,
        onclick: () => { numbers.push({ key: o.key, label: o.label, target: null, last: o.last, seed_id: null }); touch(); redraw(); },
      }))) : null,
    ]);
  }

  // ---------------------------------------------------------------------
  // In the Journal
  // ---------------------------------------------------------------------
  // Every reflection, or none until the migration has run.
  async function list() {
    try {
      return await api(`/me/reflections?today=${cave().localToday()}`);
    } catch {
      return [];
    }
  }

  // Asks Aquila to pray over the plan, in her prayer mode (app/agent/nodes.py::
  // pray_with). The verse goes first so she starts from it.
  function prayOver(r) {
    const la = r.look_ahead || {};
    const hopes = (la.areas || []).flatMap((a) => (a.goals || []).map((g) => g.text)).slice(0, 4);
    const parts = [`Would you pray with me over ${r.ahead_label}${r.title ? `, which I've called "${r.title}"` : ""}?`];
    if (la.word) parts.push(`The word I sense for it is "${la.word}".`);
    if (hopes.length) parts.push(`I'm hoping for: ${hopes.join("; ")}.`);
    if ((la.asking || "").trim()) parts.push(la.asking.trim());
    const ask = parts.join(" ");
    app().submitQuery(la.verse_ref ? `On ${la.verse_ref}: ${ask}` : ask, { mode: "pray" });
  }

  // How one goal stands, as a short line, from plan_progress.
  function goalStanding(p) {
    if (!p) return "";
    if (p.weeks) return `${p.kept} of ${p.weeks} weeks`;
    if (p.status === "reached") return "reached";
    if (p.progress) return p.progress;
    return "";
  }

  // The plan someone is living in: pinned at the top of the Journal.
  function planCard(r) {
    const la = r.look_ahead || {};
    const progress = r.progress || { numbers: [], goals: [] };
    const aims = (la.numbers || []).map((n, i) => {
      const done = (progress.numbers[i] || {}).done;
      return n.target ? el("span", { class: "refl-aim", text: done !== null && done !== undefined ? `${num(done)} of ${num(n.target)} ${n.label}` : `${num(n.target)} ${n.label}` }) : null;
    }).filter(Boolean);
    // plan_progress lists every area's goals in order, so they're read in step.
    let at = 0;
    const areas = (la.areas || []).filter((a) => a.aim || (a.goals || []).length).map((a) => el("div", { class: "refl-plan-area" }, [
      el("b", {}, [a.name, a.aim ? el("span", { text: ` · aiming for ${RATING_NAME[a.aim]}` }) : null]),
      (a.goals || []).length ? el("ul", {}, a.goals.map((g) => {
        const standing = goalStanding(progress.goals[at++]);
        return el("li", {}, [g.text, standing ? el("small", { text: ` · ${standing}` }) : null]);
      })) : null,
    ]));
    const verse = el("blockquote", { class: "refl-plan-verse", hidden: true }, [el("p", { class: "scripture" }), el("footer", { class: "refl-ref" })]);
    if (la.verse_ref) {
      cave().verseText(la.verse_ref).then((v) => {
        verse.querySelector("p").textContent = `"${v.text}"`;
        verse.querySelector("footer").textContent = `${la.verse_ref} · ${v.translation}`;
        verse.hidden = false;
      }).catch(() => {});
    }
    return el("article", { class: "card warm refl-plan fade-in" }, [
      el("p", { class: "kicker ember refl-kicker", html: HORIZON }, [`Reflection · ${r.label} into ${r.ahead_label}`]),
      r.title ? el("h3", { class: "refl-plan-title", text: r.title }) : null,
      la.word ? el("p", { class: "refl-plan-word", text: la.word }) : null,
      verse,
      aims.length ? el("div", { class: "refl-aims-row" }, aims) : null,
      ...areas,
      el("div", { class: "card-actions-row" }, [
        el("a", { class: "btn btn-ember btn-sm", href: `#reflection/${r.id}`, text: "Open" }),
        el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Pray it with Aquila", onclick: () => prayOver(r) }),
      ]),
    ]);
  }

  function called(r) {
    return r.title || `${r.label} into ${r.ahead_label}`;
  }

  // A reflection in the list: a draft to carry on, or one kept before.
  function rowCard(r) {
    const draft = r.status !== "kept";
    const word = (r.look_ahead || {}).word;
    const node = el("article", { class: "entry refl-entry fade-in" }, [
      el("div", { class: "entry-meta" }, [
        el("span", { class: "tag", html: `${HORIZON}<span>Reflection</span>` }),
        el("span", { text: cave().when(r.updated_at || r.created_at) }),
        draft ? el("span", { class: "badge plain", text: "In progress" }) : null,
      ]),
      el("h3", { text: called(r) }),
      r.title ? el("p", { class: "refl-dates-line", text: `${r.label} into ${r.ahead_label}` }) : null,
      word ? el("p", { class: "refl-entry-word", text: word }) : null,
      el("div", { class: "entry-actions" }, [
        el("a", { class: "text-act", href: `#reflection/${r.id}`, text: draft ? "Carry on" : "Open" }),
        el("div", { class: "entry-icons" }, cave().moreMenu("More for this reflection", [{
          label: "Delete", danger: true,
          onClick: async () => {
            if (!confirm("Delete this reflection? Pebbles it started stay in Refuge. This can't be undone.")) return;
            try {
              await api(`/me/reflections/${r.id}`, { method: "DELETE" });
              node.remove();
            } catch (err) {
              toast(err.message, { tone: "error" });
            }
          },
        }])),
      ]),
    ]);
    return node;
  }

  // What the Journal shows above the entries: the plan being lived in, and
  // any reflection still in progress.
  function pinned(reflections) {
    return [
      ...reflections.filter((r) => r.current).map(planCard),
      ...reflections.filter((r) => r.status !== "kept").map(rowCard),
    ];
  }

  // ---------------------------------------------------------------------
  // The home screen's halfway check-in
  // ---------------------------------------------------------------------
  function putAway() {
    try {
      return JSON.parse(localStorage.getItem(CHECK_IN_KEY) || "[]");
    } catch {
      return [];
    }
  }

  function homeCard(glance) {
    if (!glance || putAway().includes(glance.id)) return null;
    const p = glance.progress || { numbers: [], goals: [] };
    const lines = [
      ...p.numbers.filter((n) => n.target && n.done !== null).map((n) => ({ text: n.label, standing: `${num(n.done)} of ${num(n.target)}`, fraction: n.done / n.target })),
      ...p.goals.filter((g) => g.weeks || g.measure).map((g) => ({ text: g.text, standing: goalStanding(g), fraction: g.weeks ? g.kept / g.weeks : g.measure.fraction })),
    ].slice(0, 3);
    const node = cave().card(`Halfway through ${glance.ahead_label}`, { warm: true }, [
      glance.title ? el("p", { class: "refl-plan-title", text: glance.title }) : null,
      glance.word ? el("p", { class: "refl-plan-word small", text: glance.word }) : null,
      glance.verse_ref ? el("p", { class: "refl-ref", text: glance.verse_ref }) : null,
      lines.length ? el("ul", { class: "refl-review" }, lines.map((l) => el("li", {}, [
        el("div", { class: "refl-review-top" }, [el("span", { text: l.text }), el("small", { text: l.standing })]),
        bar(l.fraction),
      ]))) : null,
      el("div", { class: "card-actions-row" }, [
        el("a", { class: "btn btn-ember btn-sm", href: `#reflection/${glance.id}`, text: "Look at it" }),
        el("button", {
          class: "act", type: "button", text: "Not now",
          onclick: () => {
            try {
              localStorage.setItem(CHECK_IN_KEY, JSON.stringify([...putAway(), glance.id].slice(-20)));
            } catch {
              /* a private window: it shows again next visit */
            }
            node.remove();
          },
        }),
      ]),
    ]);
    return node;
  }

  window.Reflections = { openStart, show, hide, list, pinned, planCard, rowCard, homeCard };
})();
