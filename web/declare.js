// Declare: Scripture spoken aloud over something a person is facing
// (app/declare.py). One page, #declare, with three ways in:
//   home     the home screen's Declare line, for the person themselves
//   prayer   "Declare over" on a prayer, which opens its kept one if it has one
//   quick    "Declare" in the prayer list's New menu, for something right now
// A short form, then the words: an opening line, a few lines to say aloud,
// each with the verse it rests on (always read from the database), and Amen.
// "Speak it aloud" steps through them one at a time, full screen. Kept ones
// sit under the form, and #declare/<id> opens one.
//
// Loaded after web/cave.js, whose helpers it borrows through window.Cave.
(function () {
  const svg = (path) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
  const ICON = {
    declare: svg('<path d="M3 11v2M7 8v8M11 5v14M15 8v8M19 10v4"/>'),
    back: svg('<path d="M15 18l-6-6 6-6"/>'),
    speak: svg('<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>'),
    close: svg('<path d="M6 6l12 12M18 6L6 18"/>'),
  };

  const ABOUT = "Facing something, like an interview or an exam? Say what it is and declare Scripture over it, out loud. Every verse is shown word for word, read from the Bible.";

  // Quick starts: each fills the box with the start of a sentence to finish.
  const STARTERS = [
    ["An interview", "I have an interview "], ["An exam", "I have an exam "], ["Travel", "I'm travelling "],
    ["Health", "I'm waiting on "], ["Waiting", "I've been waiting a long time for "], ["A new start", "I'm starting "],
    ["Family", "My family "], ["A decision", "I have a decision to make about "],
  ];

  const cave = () => window.Cave;
  const el = (...args) => cave().el(...args);
  const api = (...args) => cave().api(...args);
  const toast = (...args) => cave().toast(...args);
  const page = () => document.getElementById("declarePage");
  // The one translation preference (index.html's hidden #translation).
  function translation() {
    const input = document.getElementById("translation");
    return (input && input.value.trim()) || "BSB";
  }

  let context = { from: "home" }; // how the page was opened, with the prayer when there is one
  let current = null; // the declaration on screen
  let closeAloud = () => {};

  // Opens the page from somewhere else in the app.
  function open(ctx = { from: "home" }) {
    context = ctx;
    current = null;
    if (location.hash === "#declare") show("");
    else location.hash = "declare";
  }

  async function show(sub) {
    if (sub) return showKept(sub);
    if (current) return renderWords();
    // A prayer that already has a kept declaration opens straight onto it.
    if (context.from === "prayer") {
      const kept = await api("/me/declarations").catch(() => []);
      const mine = kept.find((d) => d.prayer_id === context.prayer.id);
      if (mine) return showKept(mine.id);
    }
    renderForm();
  }

  function hide() {
    closeAloud();
  }

  // The home screen's one line, with the explanation behind its info button.
  // Declare's card on the home screen, beside Amens (cave.js::showHome), with
  // what Declare is behind its info button.
  function homeLine() {
    const note = cave().homeNote({ href: "#declare", icon: ICON.declare, title: "Declare", detail: "God's word over what you face" });
    note.addEventListener("click", () => { context = { from: "home" }; current = null; });
    return el("div", { class: "home-tile" }, [note, cave().info(ABOUT, { label: "About Declare" })]);
  }

  function backTo(label, onclick) {
    return el("button", { class: "back", type: "button", html: `${ICON.back}<span>${label}</span>`, onclick });
  }
  const leave = () => (location.hash = context.from === "home" ? "home" : "prayers");
  const leaveLabel = () => (context.from === "home" ? "Home" : "Prayers");

  function head(title, back) {
    return el("div", { class: "declare-head" }, [back, cave().titleInfo(el("h1", { class: "page-title", text: title }), ABOUT)]);
  }

  // ---------------------------------------------------------------------
  // The form
  // ---------------------------------------------------------------------
  function renderForm(prefill = "") {
    const prayer = context.from === "prayer" ? context.prayer : null;
    const msg = cave().formMessage();
    const situation = el("textarea", { class: "field", id: "declareSituation", rows: "3", maxlength: "600", placeholder: "An interview tomorrow, a hospital visit, a big decision..." });
    situation.value = prefill || (prayer ? prayer.body : "");
    const name = el("input", { class: "field", id: "declareName", maxlength: "40", autocomplete: "off", placeholder: "Their first name" });
    if (context.name) name.value = context.name;
    const submit = el("button", { class: "btn btn-ember btn-block", type: "submit", text: "Give me words" });

    const starters = el("div", { class: "declare-starters", role: "group", "aria-label": "Quick starts" }, STARTERS.map(([label, start]) =>
      el("button", { class: "chip-btn", type: "button", text: label, onclick: () => { situation.value = start; situation.focus(); situation.setSelectionRange(start.length, start.length); } })
    ));

    const form = el("form", { class: "declare-form" }, [
      prayer
        ? el("div", { class: "declare-from" }, [el("span", { class: "faint", text: "From your prayer" }), el("p", { text: prayer.body })])
        : el("label", { class: "field-wrap", for: "declareSituation" }, [context.from === "quick" ? "What are you declaring over?" : "What are you facing?", situation]),
      prayer ? null : starters,
      context.from === "home" ? null : el("label", { class: "field-wrap", for: "declareName" }, [
        "Who is it for?", name, el("span", { class: "field-hint", text: "Leave it blank if it's for you." }),
      ]),
      msg.node,
      submit,
      el("p", { class: "faint declare-note", text: "Every verse is shown word for word, in your translation." }),
    ]);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const text = (prayer ? prayer.body : situation.value).trim();
      if (!text) return msg.say("Say a few words about what you're facing.", true);
      submit.disabled = true;
      submit.textContent = "Finding words...";
      try {
        const who = name.value.trim() || null;
        const res = await api("/declare", { method: "POST", body: { situation: text, name: who, translation: translation() } });
        if (res.care) return renderCare();
        current = { ...res, situation: text, name: who };
        renderWords();
      } catch (err) {
        msg.say(err.message, true);
        submit.disabled = false;
        submit.textContent = "Give me words";
      }
    });

    const kept = el("div", { class: "declare-kept" });
    page().replaceChildren(head("Declare", backTo(leaveLabel(), leave)), form, kept);
    if (!prayer) situation.focus();
    if (context.from === "home") loadKept(kept);
  }

  // Kept declarations for oneself. Those kept with a prayer live with it.
  async function loadKept(node) {
    let rows;
    try {
      rows = (await api("/me/declarations")).filter((d) => !d.prayer_id);
    } catch {
      return; // not set up yet: Keep says what to run
    }
    if (!rows.length || !node.isConnected) return;
    node.replaceChildren(
      el("h2", { class: "section-title", text: "Kept" }),
      el("div", { class: "declare-kept-list" }, rows.map((d) =>
        el("a", { class: "declare-kept-item", href: `#declare/${d.id}` }, [
          el("strong", { text: d.title }), el("span", { class: "faint", text: cave().when(d.created_at) }),
        ])
      ))
    );
  }

  // A situation that sounds unsafe gets people, not words (app/care.py).
  function renderCare() {
    page().replaceChildren(
      head("Declare", backTo("Back", () => renderForm())),
      el("div", { class: "care-panel" }, [
        el("strong", { text: "That sounds like a lot to carry." }),
        el("p", { text: "You don't have to hold this alone. Please reach someone now. These are free, and there for exactly this." }),
        el("div", { class: "care-card" }, window.Refuge.helplineRows("care-line")),
        el("a", { class: "btn btn-ghost btn-sm", href: "#refuge", text: "Talk with Aquila in Refuge" }),
      ])
    );
  }

  // ---------------------------------------------------------------------
  // The words
  // ---------------------------------------------------------------------
  async function showKept(id) {
    page().replaceChildren(el("div", { class: "empty", text: "Opening..." }));
    try {
      const d = await api(`/me/declarations/${encodeURIComponent(id)}?translation=${encodeURIComponent(translation())}`);
      if (d.prayer_id && context.from !== "prayer") context = { from: "prayer", prayer: { id: d.prayer_id, body: d.situation } };
      if (!d.prayer_id && context.from !== "home") context = { from: "home" };
      current = d;
      renderWords();
    } catch (err) {
      page().replaceChildren(head("Declare", backTo(leaveLabel(), leave)), el("p", { class: "setup-note", text: err.message }));
    }
  }

  function renderWords() {
    const d = current;
    const back = d.id
      ? backTo(context.from === "home" ? "Declare" : "Prayers", () => { current = null; location.hash = context.from === "home" ? "declare" : "prayers"; })
      : backTo("Change it", () => { const s = d.situation; current = null; context.name = d.name; renderForm(s); });

    const words = el("article", { class: "card declare-words" }, [
      el("p", { class: "declare-opening", text: d.opening }),
      ...d.lines.map((line) => el("div", { class: "declare-line" }, [
        el("p", { class: "declare-say", text: line.say }),
        el("blockquote", { class: "declare-verse" }, [
          el("p", { class: "scripture", text: line.text }),
          el("a", { class: "declare-ref", href: `#${window.Reader.href(line.ref)}`, text: line.ref }),
        ]),
      ])),
      el("p", { class: "declare-opening declare-amen", text: "Amen." }),
    ]);

    const keepLabel = { home: "Keep", prayer: "Keep with this prayer", quick: "Keep as a prayer" }[context.from];
    const actions = el("div", { class: "declare-actions" }, [
      d.id ? null : el("button", { class: "btn btn-ghost btn-sm", type: "button", text: keepLabel, onclick: (e) => keep(e.currentTarget) }),
      el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Other words", onclick: (e) => again(e.currentTarget) }),
      d.id ? cave().moreMenu("More for this declaration", [{ label: "Delete", danger: true, onClick: remove }]) : null,
    ]);

    page().replaceChildren(
      head(d.title, back),
      el("button", { class: "btn btn-ember btn-block declare-speak", type: "button", html: `${ICON.speak}<span>Speak it aloud</span>`, onclick: () => speakAloud(d) }),
      words,
      actions,
      el("p", { class: "faint declare-note", text: `Shown in ${d.translation}. Change it in Settings.` })
    );
    window.scrollTo({ top: 0 });
  }

  async function keep(button) {
    const d = current;
    const from = context.from;
    button.disabled = true;
    try {
      const res = await api("/me/declarations", {
        method: "POST",
        body: {
          title: d.title, situation: d.situation, name: d.name, opening: d.opening,
          lines: d.lines.map(({ say, ref }) => ({ say, ref })),
          prayer_id: context.from === "prayer" ? context.prayer.id : null,
          as_prayer: context.from === "quick",
        },
      });
      current = { ...d, id: res.id, prayer_id: res.prayer_id };
      if (res.prayer_id) context = { from: "prayer", prayer: { id: res.prayer_id, body: d.situation } };
      // Its own address now, so Back and Delete lead somewhere sensible.
      history.replaceState(null, "", `#declare/${res.id}`);
      toast({ home: "Kept. It's under Declare.", prayer: "Kept with your prayer.", quick: "Kept on your prayer list." }[from]);
      renderWords();
    } catch (err) {
      toast(err.message, { tone: "error" });
      button.disabled = false;
    }
  }

  // Fresh words for the same situation. A kept one stays kept until the new
  // words are kept in its place.
  async function again(button) {
    const d = current;
    button.disabled = true;
    button.textContent = "Finding words...";
    try {
      const res = await api("/declare", { method: "POST", body: { situation: d.situation, name: d.name, translation: translation() } });
      if (res.care) return renderCare();
      current = { ...res, situation: d.situation, name: d.name };
      renderWords();
    } catch (err) {
      toast(err.message, { tone: "error" });
      button.disabled = false;
      button.textContent = "Other words";
    }
  }

  async function remove() {
    if (!confirm("Delete this declaration?")) return;
    try {
      await api(`/me/declarations/${current.id}`, { method: "DELETE" });
      toast("Deleted.");
      current = null;
      location.hash = context.from === "home" ? "declare" : "prayers";
    } catch (err) {
      toast(err.message, { tone: "error" });
    }
  }

  // ---------------------------------------------------------------------
  // Speak it aloud: one line at a time, full screen
  // ---------------------------------------------------------------------
  function speakAloud(d) {
    const steps = [{ say: d.opening }, ...d.lines, { say: "Amen." }];
    let at = 0;
    let wakeLock = null;
    const stage = el("div", { class: "aloud-stage", "aria-live": "polite" });
    const dots = el("div", { class: "aloud-dots", "aria-hidden": "true" }, steps.map(() => el("span")));
    const count = el("span", { class: "aloud-count" });
    const prev = el("button", { class: "iconbtn aloud-prev", type: "button", "aria-label": "Back", html: ICON.back, onclick: () => step(-1) });
    const next = el("button", { class: "btn btn-ember aloud-next", type: "button", onclick: () => step(1) });
    const wrap = el("div", { class: "aloud", role: "dialog", "aria-modal": "true", "aria-label": "Speak it aloud", tabindex: "-1" }, [
      el("div", { class: "aloud-top" }, [
        el("button", { class: "iconbtn", type: "button", "aria-label": "Close", html: ICON.close, onclick: () => close() }), dots, count,
      ]),
      stage,
      el("div", { class: "aloud-foot" }, [el("p", { class: "faint", text: "Say it out loud, then tap Next." }), el("div", { class: "aloud-buttons" }, [prev, next])]),
    ]);

    function draw() {
      const s = steps[at];
      stage.replaceChildren(...[
        el("p", { class: "aloud-say", text: s.say }),
        s.text ? el("p", { class: "scripture-lg", text: s.text }) : null,
        s.ref ? el("span", { class: "aloud-ref", text: s.ref }) : null,
      ].filter(Boolean));
      [...dots.children].forEach((dot, i) => dot.classList.toggle("is-on", i <= at));
      count.textContent = `${at + 1} of ${steps.length}`;
      prev.disabled = at === 0;
      next.textContent = at === steps.length - 1 ? "Done" : "Next";
    }
    function step(by) {
      if (at + by >= steps.length) return close();
      at = Math.max(0, at + by);
      draw();
    }
    function onKey(e) {
      if (e.key === "Escape") close();
      else if (e.key === "ArrowRight") step(1);
      else if (e.key === "ArrowLeft") step(-1);
    }
    function close() {
      wrap.remove();
      document.body.classList.remove("aloud-open");
      document.removeEventListener("keydown", onKey);
      if (wakeLock) wakeLock.release().catch(() => {});
      closeAloud = () => {};
    }

    closeAloud = close;
    document.body.append(wrap);
    document.body.classList.add("aloud-open");
    document.addEventListener("keydown", onKey);
    // Keeps the screen on while they're reading aloud, where it's allowed.
    if (navigator.wakeLock) navigator.wakeLock.request("screen").then((lock) => (wakeLock = lock)).catch(() => {});
    draw();
    wrap.focus();
  }

  window.Declare = { open, show, hide, homeLine };
})();
