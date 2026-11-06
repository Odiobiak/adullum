// The Bible reader: pick a book and chapter, read it in any translation that
// has been loaded, and tap verses to keep a note, highlight them, learn them by
// heart, ask Aquila about them, or follow them in Connections. Every note and
// highlight together is "My notes" (#bible/notes), and the verses being
// learned are "Memorize" (#bible/memorize, drawn by web/memorize.js). Both open
// from the reader bar through showMine below, so they live beside the text.
//
// This file also owns the translation preference. The hidden #translation
// input in index.html stays the one place every script reads it from (Aquila's
// answers, the verse of the day, Connections), so changing it here changes it
// everywhere. It is remembered on this device, and on the profile when signed in.
//
// Loaded after web/cave.js, whose helpers (el, overlay, api, toast) it borrows
// through window.Cave at call time.
(function () {
  const POS_KEY = "adullumReaderAt";
  const TR_KEY = "adullumTranslation";
  const ASK_VERSE = ["What does this mean?", "What's happening around this passage?", "How could I live this out today?"];
  const ASK_NOTE = ["What do you make of what I wrote?", "Does the rest of Scripture bear this out?", "Where else does the Bible speak to this?"];
  // Highlight colours, in picker order. The fills are theme tokens (--hl-*) in app.css.
  const HIGHLIGHT_COLORS = [["gold", "Gold"], ["green", "Green"], ["blue", "Blue"], ["rose", "Rose"]];

  const ICON = {
    note: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/></svg>',
    aquila: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/></svg>',
    graph: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="8" r="2.5"/><circle cx="10" cy="18" r="2.5"/><path d="M8.3 7l7.3.7M7 8.3l2.2 7.4M16.4 10l-4.8 6"/></svg>',
    copy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/></svg>',
    book: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M4 21V5M9 7h6"/></svg>',
    prev: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 5l-7 7 7 7"/></svg>',
    next: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 5l7 7-7 7"/></svg>',
    close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>',
    heart: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/></svg>',
    down: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>',
  };

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const cave = () => window.Cave;
  const app = () => window.AdullumApp;
  const el = (...args) => cave().el(...args);

  function apiBase() {
    const input = $("#apiBase");
    return ((input && input.value) || location.origin).trim().replace(/\/$/, "");
  }
  async function getJson(path) {
    const resp = await fetch(`${apiBase()}${path}`);
    let data = null;
    try {
      data = await resp.json();
    } catch {
      /* empty body */
    }
    if (!resp.ok) {
      const err = new Error((data && typeof data.detail === "string" && data.detail) || `Something went wrong (${resp.status}).`);
      err.status = resp.status;
      throw err;
    }
    return data;
  }
  function store(key, value) {
    try {
      if (value === null) localStorage.removeItem(key);
      else localStorage.setItem(key, value);
    } catch {
      /* storage blocked: remembered for this visit only */
    }
  }
  function recall(key) {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  }

  // ---------------------------------------------------------------------
  // Translations
  // ---------------------------------------------------------------------
  let translations = []; // [{code, name, about}], only the ones actually loaded
  let defaultTranslation = "BSB";
  let wanted = null; // a profile preference that arrived before the list did

  const input = $("#translation");
  const translation = () => (input && input.value.trim()) || defaultTranslation;
  // Applied straight away, before any other script asks, so the first verse
  // of the day is already in the translation this person reads.
  const saved = recall(TR_KEY);
  if (input && saved) input.value = saved;

  function nameOf(code) {
    const t = translations.find((x) => x.code === code);
    return t ? t.name : code;
  }

  function syncPickers() {
    for (const select of $$("select[data-translation-picker]")) {
      // The reader's own picker shows just the code (the full name sits above
      // the chapter title); Settings spells each one out.
      const short = select.dataset.translationPicker === "short";
      select.replaceChildren(...translations.map((t) => el("option", { value: t.code, text: short ? t.code : `${t.code} · ${t.name}`, title: t.name })));
      select.value = translation();
      select.disabled = translations.length < 2;
      select.title = translations.length < 2 ? "Only one translation is loaded so far" : "Translation";
    }
    const about = $("#settingsTranslationAbout");
    if (about) {
      const t = translations.find((x) => x.code === translation());
      about.textContent = t ? t.about : "";
    }
  }

  function setTranslation(code, { save = true } = {}) {
    if (!translations.some((t) => t.code === code)) return;
    const changed = code !== translation();
    if (input) input.value = code;
    store(TR_KEY, code);
    syncPickers();
    if (save && changed && cave().signedIn()) {
      cave().api("/me", { method: "PATCH", body: { preferred_translation: code } }).catch(() => {});
    }
    if (changed && current && !$("[data-view='bible']").hidden) load(current.book, current.chapter);
  }

  function applyPreferred(code) {
    if (!code) return;
    if (!translations.length) wanted = code;
    else if (translations.some((t) => t.code === code)) setTranslation(code, { save: false });
  }

  async function loadTranslations() {
    try {
      const data = await getJson("/bible/translations");
      defaultTranslation = data.default;
      translations = data.translations;
    } catch {
      translations = [{ code: defaultTranslation, name: defaultTranslation, about: "" }];
    }
    // A saved choice that isn't loaded on this server falls back quietly.
    if (!translations.some((t) => t.code === translation())) {
      if (input) input.value = defaultTranslation;
      store(TR_KEY, null);
    }
    if (wanted) applyPreferred(wanted);
    syncPickers();
  }

  // ---------------------------------------------------------------------
  // Books and places in the text
  // ---------------------------------------------------------------------
  let books = [];
  let booksReady = null;
  function ensureBooks() {
    if (!booksReady) {
      booksReady = getJson("/bible/books")
        .then((b) => (books = b))
        .catch((err) => {
          booksReady = null;
          throw err;
        });
    }
    return booksReady;
  }
  const keyOf = (name) => name.replace(/[\s.-]/g, "").toLowerCase();
  function findBook(name) {
    const k = keyOf(name || "");
    return books.find((b) => keyOf(b.name) === k) || null;
  }

  // "#bible/1-Samuel/3/5". Hyphens stand in for spaces so a link stays readable.
  function hashFor(book, chapter, verse) {
    return `bible/${encodeURIComponent(book.replace(/ /g, "-"))}/${chapter}${verse ? `/${verse}` : ""}`;
  }
  // "John 3:16" or "Song of Solomon 2:1-3" to its reader link, for other scripts.
  function href(ref) {
    const m = /^(.+?)\s+(\d+)(?::(\d+))?/.exec(ref || "");
    return m ? hashFor(m[1], Number(m[2]), m[3] ? Number(m[3]) : null) : "bible";
  }
  function refFor(book, chapter, start, end) {
    return `${book} ${chapter}:${start === end ? start : `${start}-${end}`}`;
  }

  // ---------------------------------------------------------------------
  // The chapter on screen
  // ---------------------------------------------------------------------
  let current = null; // the /bible/chapter payload
  let notes = []; // this chapter's notes
  let highlights = new Map(); // verse number -> colour, for this chapter
  let range = null; // {start, end} of the selected verses
  let loadToken = 0;
  let notesSignedIn = null; // whether this chapter's notes were fetched signed in

  // "hub" (the Bible tab's front page, #bible), "read" (a chapter), or one of
  // the person's own pages kept beside the text: "notes" (My notes,
  // #bible/notes) or "memorize" (#bible/memorize). The reader bar and page
  // swap between them; the open chapter stays loaded underneath, so going
  // back is instant.
  let mode = "read";
  function setMode(next) {
    mode = next;
    const reading = next === "read";
    // The front page is its own menu, so it has no use for the reader bar.
    $(".reader-bar").hidden = next === "hub";
    $("#readerPage").hidden = !reading;
    $("#readerMine").hidden = reading;
    $("#readerBack").hidden = reading;
    ["#readerPick", "#readerNotesLink", "#readerLearnLink", "#readerTranslation", ".reader-arrows"].forEach((s) => ($(s).hidden = !reading));
  }

  // Where "Bible" on the front page picks up: the chapter open now, else the
  // last one read on this device, else the very beginning.
  function lastPlace() {
    if (current) return { book: current.book, chapter: current.chapter, read: true };
    try {
      const saved = JSON.parse(recall(POS_KEY) || "null");
      if (saved && saved.book) return { book: saved.book, chapter: Number(saved.chapter) || 1, read: true };
    } catch {
      /* nothing saved */
    }
    return { book: "Genesis", chapter: 1, read: false };
  }

  async function show(param) {
    if (!param) return showHub();
    if (MINE[param]) return showMine(param);
    setMode("read");
    const parts = (param || "").split("/").filter(Boolean).map((p) => decodeURIComponent(p).replace(/-/g, " "));
    try {
      await ensureBooks();
    } catch (err) {
      return showProblem(err.message);
    }
    let book = findBook(parts[0]);
    let chapter = Number(parts[1]) || 1;
    const verse = Number(parts[2]) || null;
    if (!book) {
      const last = lastPlace();
      book = findBook(last.book) || books[0];
      chapter = last.chapter;
    }
    chapter = Math.min(Math.max(chapter, 1), book.chapters);
    // Coming back to the chapter already open (from Connections, say) only moves to the verse.
    if (current && current.book === book.name && current.chapter === chapter && current.translation === translation()) {
      if (verse) focusVerse(verse);
      if (notesSignedIn !== cave().signedIn()) loadPersonal(loadToken);
      return;
    }
    load(book.name, chapter, verse);
  }

  function showProblem(text, extra) {
    $("#readerText").replaceChildren(el("div", { class: "empty" }, [el("strong", { text: "Couldn't open this" }), text, extra || null]));
  }

  async function load(book, chapter, verse) {
    const token = ++loadToken;
    clearSelection();
    $("#readerPlace").textContent = `${book} ${chapter}`;
    $("#readerText").replaceChildren(el("div", { class: "empty", text: `Opening ${book} ${chapter}...` }));
    $("#readerNotes").replaceChildren();
    let data;
    try {
      const params = new URLSearchParams({ book, chapter: String(chapter), translation: translation() });
      data = await getJson(`/bible/chapter?${params}`);
    } catch (err) {
      if (token !== loadToken) return;
      const fallback = err.status === 404 && translation() !== defaultTranslation
        ? el("div", {}, el("button", { class: "btn btn-ghost btn-sm", type: "button", text: `Read in ${defaultTranslation} instead`, onclick: () => setTranslation(defaultTranslation) }))
        : null;
      return showProblem(err.message, fallback);
    }
    if (token !== loadToken) return;
    current = data;
    notes = [];
    highlights = new Map();
    store(POS_KEY, JSON.stringify({ book: data.book, chapter: data.chapter }));
    document.title = `${data.book} ${data.chapter}, Adullum`;
    renderChapter();
    if (verse) focusVerse(verse);
    else window.scrollTo({ top: 0 });
    loadPersonal(token);
  }

  function renderChapter() {
    const c = current;
    const poetry = c.genre === "poetry";
    const text = el("div", { class: `chapter-text${poetry ? " poetry" : ""}`, lang: "en" });
    for (const v of c.verses) {
      const span = el("span", { class: "v", "data-v": String(v.verse), tabindex: "0", role: "button", "aria-pressed": "false" }, [
        el("sup", { class: "vn", text: String(v.verse) }),
        document.createTextNode(`${v.text} `),
      ]);
      span.addEventListener("click", () => tapVerse(v.verse));
      span.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          tapVerse(v.verse);
        }
      });
      text.append(span);
    }
    const step = (target, dir) =>
      target
        ? el("a", { class: `btn btn-ghost btn-sm chapter-step ${dir}`, href: `#${hashFor(target.book, target.chapter)}`, html: dir === "prev" ? `${ICON.prev}<span></span>` : `<span></span>${ICON.next}` })
        : el("span");
    const prev = step(c.prev, "prev");
    const next = step(c.next, "next");
    if (c.prev) prev.querySelector("span").textContent = `${c.prev.book} ${c.prev.chapter}`;
    if (c.next) next.querySelector("span").textContent = `${c.next.book} ${c.next.chapter}`;

    $("#readerPlace").textContent = `${c.book} ${c.chapter}`;
    $("#readerPrev").hidden = !c.prev;
    $("#readerNext").hidden = !c.next;
    $("#readerText").replaceChildren(
      el("p", { class: "kicker", text: `${c.testament === "OT" ? "Old Testament" : "New Testament"} · ${nameOf(c.translation)}` }),
      el("h1", { class: "chapter-title", text: `${c.book} ${c.chapter}` }),
      text,
      el("nav", { class: "chapter-steps", "aria-label": "Chapters" }, [prev, next])
    );
  }

  function verseEl(n) {
    return $(`#readerText .v[data-v="${n}"]`);
  }

  function focusVerse(n) {
    const v = verseEl(n);
    if (!v) return;
    v.scrollIntoView({ behavior: "smooth", block: "center" });
    v.classList.add("is-focus");
    setTimeout(() => v.classList.remove("is-focus"), 2600);
  }

  // ---------------------------------------------------------------------
  // Selecting verses. A tap outside the selection stretches it to reach that
  // verse; a tap inside starts over from there; tapping a lone selected verse
  // lets it go.
  // ---------------------------------------------------------------------
  function tapVerse(n) {
    if (!range) range = { start: n, end: n };
    else if (n < range.start) range.start = n;
    else if (n > range.end) range.end = n;
    else if (range.start === range.end) range = null;
    else range = { start: n, end: n };
    paintSelection();
  }

  function clearSelection() {
    range = null;
    closeHighlightPicker();
    paintSelection();
  }

  function paintSelection() {
    $$("#readerText .v").forEach((s) => {
      const n = Number(s.dataset.v);
      const on = !!range && n >= range.start && n <= range.end;
      s.classList.toggle("is-selected", on);
      s.setAttribute("aria-pressed", String(on));
    });
    const bar = $("#verseBar");
    if (!range || !current) {
      bar.hidden = true;
      return;
    }
    $("#verseBarRef").textContent = refFor(current.book, current.chapter, range.start, range.end);
    bar.hidden = false;
  }

  function selection() {
    const c = current;
    const verses = c.verses.filter((v) => v.verse >= range.start && v.verse <= range.end);
    return {
      book: c.book,
      chapter: c.chapter,
      start: range.start,
      end: range.end,
      ref: refFor(c.book, c.chapter, range.start, range.end),
      text: verses.map((v) => v.text).join(" "),
      translation: c.translation,
    };
  }

  function wireBar() {
    $("#verseBarClose").addEventListener("click", clearSelection);
    $("#verseBarNote").addEventListener("click", () => openNoteSheet(selection()));
    $("#verseBarHighlight").addEventListener("click", toggleHighlightPicker);
    $("#verseBarLearn").addEventListener("click", async () => {
      const s = selection();
      if (await window.Memorize.add(s.ref, s.translation)) clearSelection();
    });
    $("#verseBarAsk").addEventListener("click", () => openAskSheet(selection()));
    $("#verseBarMap").addEventListener("click", () => {
      const s = selection();
      const refs = [];
      for (let n = s.start; n <= Math.min(s.end, s.start + 3); n++) refs.push(`${s.book} ${s.chapter}:${n}`);
      window.Graph.open(refs);
    });
    $("#verseBarCopy").addEventListener("click", async () => {
      const s = selection();
      try {
        await navigator.clipboard.writeText(`"${s.text}" ${s.ref} (${s.translation})`);
        cave().toast("Copied.");
      } catch {
        cave().toast("Your browser didn't allow copying.");
      }
    });
  }

  // ---------------------------------------------------------------------
  // The book and chapter picker
  // ---------------------------------------------------------------------
  function openPicker() {
    if (!books.length) return;
    const body = el("div", { class: "picker-body" });
    const sheet = el("div", { class: "sheet sheet-wide", role: "dialog", "aria-modal": "true", "aria-labelledby": "pickerTitle" }, [
      el("div", { class: "picker-head" }, [
        el("h3", { id: "pickerTitle", text: "Choose a book" }),
        el("button", { class: "iconbtn", type: "button", "aria-label": "Close", html: ICON.close, onclick: () => close() }),
      ]),
      body,
    ]);
    const close = cave().overlay(sheet);

    const goTo = (book, chapter) => {
      close();
      app().go(hashFor(book, chapter));
    };
    const chapters = (b) => {
      $("#pickerTitle").textContent = b.name;
      const grid = el("div", { class: "chapter-grid" });
      for (let n = 1; n <= b.chapters; n++) {
        const isHere = current && current.book === b.name && current.chapter === n;
        grid.append(el("button", { class: `chapter-num${isHere ? " is-here" : ""}`, type: "button", text: String(n), onclick: () => goTo(b.name, n) }));
      }
      body.replaceChildren(el("button", { class: "linkish", type: "button", text: "All books", onclick: booksView }), grid);
      grid.querySelector("button").focus();
    };
    function booksView() {
      $("#pickerTitle").textContent = "Choose a book";
      const group = (label, testament) =>
        el("section", { class: "book-group" }, [
          el("p", { class: "kicker", text: label }),
          el("div", { class: "book-grid" }, books.filter((b) => b.testament === testament).map((b) =>
            el("button", {
              class: `book-btn${current && current.book === b.name ? " is-here" : ""}`, type: "button", text: b.name,
              onclick: () => (b.chapters === 1 ? goTo(b.name, 1) : chapters(b)),
            })
          )),
        ]);
      body.replaceChildren(group("Old Testament", "OT"), group("New Testament", "NT"));
    }
    booksView();
    if (current) {
      const b = findBook(current.book);
      if (b && b.chapters > 1) chapters(b);
    }
  }

  // ---------------------------------------------------------------------
  // Highlights: one colour per verse, shown in every translation
  // ---------------------------------------------------------------------
  async function loadHighlights(token) {
    if (!cave().signedIn()) {
      highlights = new Map();
      return paintHighlights();
    }
    try {
      const params = new URLSearchParams({ book: current.book, chapter: String(current.chapter) });
      const rows = await cave().api(`/me/highlights?${params}`);
      if (token !== loadToken) return;
      highlights = new Map(rows.map((r) => [r.verse, r.color]));
    } catch {
      highlights = new Map(); // the chapter still reads fine without them
    }
    paintHighlights();
  }

  function paintHighlights() {
    $$("#readerText .v").forEach((s) => {
      const color = highlights.get(Number(s.dataset.v));
      for (const [c] of HIGHLIGHT_COLORS) s.classList.toggle(`hl-${c}`, c === color);
    });
  }

  function closeHighlightPicker() {
    const picker = $("#highlightPicker");
    if (picker) picker.hidden = true;
    const btn = $("#verseBarHighlight");
    if (btn) btn.setAttribute("aria-expanded", "false");
  }

  // A row of colour swatches just above the verse bar, plus "Remove" when any
  // selected verse is already highlighted.
  function toggleHighlightPicker() {
    if (!cave().signedIn()) {
      cave().toast("Create a free account to highlight verses.");
      app().go("join");
      return;
    }
    const picker = $("#highlightPicker");
    if (!picker.hidden) return closeHighlightPicker();
    const s = selection();
    let anyLit = false;
    for (let n = s.start; n <= s.end; n++) if (highlights.has(n)) anyLit = true;
    const swatches = HIGHLIGHT_COLORS.map(([color, name]) =>
      el("button", { class: `hl-swatch hl-${color}`, type: "button", "aria-label": `Highlight ${name.toLowerCase()}`, title: name, onclick: () => paint(s, color) })
    );
    if (anyLit) swatches.push(el("button", { class: "act", type: "button", text: "Remove", onclick: () => unpaint(s) }));
    picker.replaceChildren(...swatches);
    picker.hidden = false;
    $("#verseBarHighlight").setAttribute("aria-expanded", "true");
    picker.querySelector("button").focus();
  }

  async function paint(s, color) {
    try {
      await cave().api("/me/highlights", {
        method: "PUT",
        body: { book: s.book, chapter: s.chapter, verse_start: s.start, verse_end: s.end, color, translation: s.translation },
      });
      for (let n = s.start; n <= s.end; n++) highlights.set(n, color);
      clearSelection();
      paintHighlights();
    } catch (err) {
      cave().toast(err.message);
    }
  }

  async function unpaint(s) {
    try {
      const params = new URLSearchParams({ book: s.book, chapter: String(s.chapter), verse_start: String(s.start), verse_end: String(s.end) });
      await cave().api(`/me/highlights?${params}`, { method: "DELETE" });
      for (let n = s.start; n <= s.end; n++) highlights.delete(n);
      clearSelection();
      paintHighlights();
    } catch (err) {
      cave().toast(err.message);
    }
  }

  // Everything personal about the open chapter: notes and highlights.
  function loadPersonal(token) {
    loadNotes(token);
    loadHighlights(token);
  }

  // ---------------------------------------------------------------------
  // Notes
  // ---------------------------------------------------------------------
  async function loadNotes(token) {
    notesSignedIn = cave().signedIn();
    if (!notesSignedIn) {
      notes = [];
      renderNotes();
      return;
    }
    try {
      const params = new URLSearchParams({ book: current.book, chapter: String(current.chapter) });
      const rows = await cave().api(`/me/notes?${params}`);
      if (token !== loadToken) return;
      notes = rows;
    } catch {
      notes = []; // the chapter still reads fine without them
    }
    renderNotes();
  }

  function renderNotes() {
    $$("#readerText .v").forEach((s) => {
      const n = Number(s.dataset.v);
      const has = notes.some((x) => n >= x.verse_start && n <= x.verse_end);
      s.classList.toggle("has-note", has);
    });
    const box = $("#readerNotes");
    if (!current) return box.replaceChildren();
    if (!cave().signedIn()) {
      box.replaceChildren(el("p", { class: "muted reader-hint" }, [
        "Tap any verse to ask Aquila about it. ",
        el("a", { href: "#join", text: "Create a free account" }),
        " to keep notes as you read.",
      ]));
      return;
    }
    if (!notes.length) {
      box.replaceChildren(el("p", { class: "muted reader-hint", text: "Tap a verse to write a note or ask Aquila about it." }));
      return;
    }
    box.replaceChildren(
      el("h2", { class: "section-title", text: `Your notes on ${current.book} ${current.chapter}` }),
      el("div", { class: "entries" }, notes.map((n) => noteCard(n, { onChange: () => loadNotes(loadToken) })))
    );
  }

  function noteCard(n, { showRead = false, onChange } = {}) {
    const node = el("article", { class: "entry note-card fade-in" });
    const meta = el("div", { class: "entry-meta" }, [el("span", { text: cave().when(n.updated_at || n.created_at) })]);
    if (n.translation) meta.append(el("span", { class: "badge plain", text: n.translation }));
    const body = el("p", { class: "refl", text: n.body });
    const actions = el("div", { class: "entry-actions" }, [
      showRead ? el("a", { class: "act", href: `#${hashFor(n.book, n.chapter, n.verse_start)}`, html: `${ICON.book}<span>Read</span>` }) : null,
      el("button", { class: "act", type: "button", html: `${ICON.aquila}<span>Ask Aquila</span>`, onclick: () => openAskSheet({ ref: n.ref, text: n.verse_text || "", note: n.body }) }),
      el("button", {
        class: "act", type: "button", text: "Edit",
        onclick: () => openNoteSheet({ ref: n.ref, text: n.verse_text || "", existing: n }, () => onChange && onChange()),
      }),
      el("button", {
        class: "act danger", type: "button", text: "Delete",
        onclick: async () => {
          if (!confirm(`Delete your note on ${n.ref}? This can't be undone.`)) return;
          try {
            await cave().api(`/me/notes/${n.id}`, { method: "DELETE" });
            node.remove();
            if (onChange) onChange();
          } catch (err) {
            cave().toast(err.message);
          }
        },
      }),
    ]);
    const title = showRead ? el("h3", {}, el("a", { href: `#${hashFor(n.book, n.chapter, n.verse_start)}`, text: n.ref })) : el("h3", { text: n.ref });
    node.append(meta, title);
    if (n.verse_text && showRead) node.append(el("p", { class: "verse", text: n.verse_text }));
    node.append(body, actions);
    return node;
  }

  function openNoteSheet(s, onSaved) {
    if (!cave().signedIn()) {
      cave().toast("Create a free account to keep notes.");
      app().go("join");
      return;
    }
    const existing = s.existing;
    const ta = el("textarea", { id: "noteBody", placeholder: "What do you notice? A question, a prayer, a line to remember." });
    ta.value = existing ? existing.body : "";
    const msg = cave().formMessage();
    const save = el("button", { class: "btn btn-ember btn-sm", type: "submit", text: existing ? "Save changes" : "Save note" });
    const form = el("form", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "noteTitle" }, [
      el("h3", { id: "noteTitle", text: existing ? `Your note on ${s.ref}` : `A note on ${s.ref}` }),
      el("p", { class: "sheet-lede", text: "Only you can see your notes." }),
      s.text ? el("div", { class: "journal-preview" }, [el("strong", { text: s.ref }), document.createTextNode(s.text)]) : null,
      el("label", { class: "field-wrap" }, ["Your note", ta]),
      msg.node,
      el("div", { class: "sheet-actions" }, [el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Cancel", onclick: () => close() }), save]),
    ]);
    const close = cave().overlay(form);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const text = ta.value.trim();
      if (!text) return msg.say("Write a line or two first.", true);
      save.disabled = true;
      try {
        const note = existing
          ? await cave().api(`/me/notes/${existing.id}`, { method: "PATCH", body: { body: text } })
          : await cave().api("/me/notes", {
              method: "POST",
              body: { book: s.book, chapter: s.chapter, verse_start: s.start, verse_end: s.end, translation: s.translation, verse_text: s.text, body: text },
            });
        close();
        cave().toast(existing ? "Note saved." : `Note kept on ${note.ref}.`);
        if (!existing) clearSelection();
        if (current && note.book === current.book && note.chapter === current.chapter) loadNotes(loadToken);
        if (onSaved) onSaved(note);
      } catch (err) {
        msg.say(err.message, true);
        save.disabled = false;
      }
    });
  }

  // Sends a question to Aquila with the passage named first, so retrieval's
  // reference lookup (app/retrieval.py::parse_reference) pulls exactly those
  // verses. A note goes in quoted as the person's own words, not as Scripture.
  function askQuery(s, question) {
    const q = question.trim();
    if (s.note) return `On ${s.ref}, I wrote this note: "${s.note.trim()}" ${q}`;
    return `On ${s.ref}: ${q}`;
  }

  function openAskSheet(s) {
    const ta = el("textarea", { id: "askAbout", rows: "3", placeholder: "Or ask in your own words" });
    const send = (q) => {
      if (!q.trim()) return;
      close();
      clearSelection();
      app().submitQuery(askQuery(s, q));
    };
    const ideas = el("div", { class: "topics" }, (s.note ? ASK_NOTE : ASK_VERSE).map((q) =>
      el("button", { class: "topic", type: "button", text: q, onclick: () => send(q) })
    ));
    const form = el("form", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "askTitle" }, [
      el("h3", { id: "askTitle", text: `Ask Aquila about ${s.ref}` }),
      s.text ? el("div", { class: "journal-preview" }, [el("strong", { text: s.ref }), document.createTextNode(s.text)]) : null,
      s.note ? el("div", { class: "journal-preview note-preview" }, [el("strong", { text: "Your note" }), document.createTextNode(s.note)]) : null,
      ideas,
      el("label", { class: "field-wrap", style: "margin-top:14px" }, [el("span", { class: "sr", text: "Your question" }), ta]),
      el("div", { class: "sheet-actions" }, [
        el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Cancel", onclick: () => close() }),
        el("button", { class: "btn btn-ember btn-sm", type: "submit", text: "Ask" }),
      ]),
    ]);
    const close = cave().overlay(form);
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      send(ta.value);
    });
  }

  // One highlighted passage in My notes.
  function highlightCard(h, onChange) {
    const node = el("article", { class: `entry highlight-card hl-edge-${h.color} fade-in` });
    const meta = el("div", { class: "entry-meta" }, [
      el("span", { class: `hl-dot hl-${h.color}`, "aria-hidden": "true" }),
      el("span", { text: cave().when(h.created_at) }),
      h.translation ? el("span", { class: "badge plain", text: h.translation }) : null,
    ]);
    // Optional parts are null; filtered out because DOM append would print them.
    node.append(...[
      meta,
      el("h3", {}, el("a", { href: `#${hashFor(h.book, h.chapter, h.verse_start)}`, text: h.ref })),
      h.text ? el("p", { class: "verse", text: h.text }) : null,
      el("div", { class: "entry-actions" }, [
        el("button", { class: "act", type: "button", html: `${ICON.aquila}<span>Ask Aquila</span>`, onclick: () => openAskSheet({ ref: h.ref, text: h.text }) }),
        el("button", {
          class: "act danger", type: "button", text: "Remove",
          onclick: async () => {
            const params = new URLSearchParams({ book: h.book, chapter: String(h.chapter), verse_start: String(h.verse_start), verse_end: String(h.verse_end) });
            try {
              await cave().api(`/me/highlights?${params}`, { method: "DELETE" });
              node.remove();
              if (onChange) onChange();
            } catch (err) {
              cave().toast(err.message);
            }
          },
        }),
      ]),
    ].filter(Boolean));
    return node;
  }

  // The person's own pages in the Bible, opened from the reader bar. Each has
  // a heading, what a guest is told instead, and what draws it.
  const MINE = {
    notes: {
      title: "My notes",
      sub: "Everything you've highlighted and written as you read. They show beside the verse in every translation.",
      guest: ["Keep notes as you read", "Create a free account to highlight verses and write down what they stir in you."],
      draw: (box) => renderAllNotes(box),
    },
    memorize: {
      title: "Verses to learn",
      sub: "Learn a verse by heart, a few minutes a day. Tap any verse as you read and choose Memorize to add it here.",
      guest: ["Learn verses by heart", "Create a free account to keep verses to learn and practise them a little each day."],
      draw: (box) => window.Memorize.renderTab(box),
    },
  };

  // ---------------------------------------------------------------------
  // The front page (#bible)
  // ---------------------------------------------------------------------
  // The Bible tab opens here rather than straight into a chapter, so it's
  // plain that notes and memorizing live in this tab too. "Bible" carries
  // on where the person left off; the other two open MINE. For someone
  // signed in, small counts arrive afterwards (notes kept, verses due), each
  // left off quietly if its request fails.
  function door({ href, icon, title, text, primary = false }) {
    const count = el("span", { class: "bible-door-count", hidden: true });
    const link = el("a", { class: `bible-door${primary ? " is-primary" : ""}`, href }, [
      el("span", { class: "bible-door-icon", html: icon }),
      el("span", { class: "bible-door-text" }, [el("strong", { text: title }), el("small", { text })]),
      count,
      el("span", { class: "bible-door-go", html: ICON.next }),
    ]);
    return { link, count };
  }

  function showHub() {
    setMode("hub");
    clearSelection();
    document.title = "The Bible, Adullum";
    window.scrollTo({ top: 0 });

    const place = lastPlace();
    const read = door({
      href: `#${hashFor(place.book, place.chapter)}`,
      icon: ICON.book,
      title: "Bible",
      text: place.read ? `Carry on at ${place.book} ${place.chapter}` : "Start at Genesis 1, or open any book",
      primary: true,
    });
    const mine = door({ href: "#bible/notes", icon: ICON.note, title: MINE.notes.title, text: "Your highlights and notes, kept beside the verses" });
    const learn = door({ href: "#bible/memorize", icon: ICON.heart, title: "Memorize", text: "Learn verses by heart, a few minutes a day" });

    $("#readerMine").replaceChildren(
      el("div", { class: "page-head" }, el("div", {}, [
        el("h1", { class: "page-title", text: "The Bible" }),
        el("p", { class: "page-sub", text: "Read, keep notes as you go, and learn the verses you want to carry with you." }),
      ])),
      el("nav", { class: "bible-doors", "aria-label": "In the Bible" }, [read.link, mine.link, learn.link]),
    );
    if (cave().signedIn()) fillHubCounts(mine, learn);
  }

  async function fillHubCounts(mine, learn) {
    const setCount = ({ count, link }, n, label) => {
      if (!n) return;
      count.textContent = String(n);
      count.hidden = false;
      link.setAttribute("aria-label", `${link.querySelector("strong").textContent}, ${label}`);
    };
    const [notesRows, marks, verses] = await Promise.allSettled([
      cave().api("/me/notes"),
      cave().api("/me/highlights"),
      cave().api(`/me/memorize?today=${cave().localToday()}`),
    ]);
    const kept = (notesRows.status === "fulfilled" ? notesRows.value.length : 0) + (marks.status === "fulfilled" ? marks.value.length : 0);
    setCount(mine, kept, `${kept} kept`);
    if (verses.status === "fulfilled") {
      const due = verses.value.due;
      setCount(learn, due, `${due} due today`);
      if (due) learn.count.classList.add("is-due");
    }
  }

  // Opens one of MINE, with the way back to the chapter that was open.
  async function showMine(kind) {
    const page = MINE[kind];
    setMode(kind);
    clearSelection();
    document.title = `${page.title}, Adullum`;
    window.scrollTo({ top: 0 });
    $("#readerBack span").textContent = current ? `Back to ${current.book} ${current.chapter}` : "Back to the Bible";
    $("#readerBack").href = current ? `#${hashFor(current.book, current.chapter)}` : "#bible";
    const box = $("#readerMine");
    const head = el("div", { class: "page-head" }, el("div", {}, [
      el("h1", { class: "page-title", text: page.title }),
      el("p", { class: "page-sub", text: page.sub }),
    ]));
    if (!cave().signedIn()) {
      box.replaceChildren(head, el("div", { class: "empty" }, [
        el("strong", { text: page.guest[0] }),
        page.guest[1],
        el("div", {}, el("a", { class: "btn btn-ember btn-sm", href: "#join", text: "Create an account" })),
      ]));
      return;
    }
    const list = el("div", {}, el("div", { class: "empty", text: "Opening..." }));
    box.replaceChildren(head, list);
    try {
      await page.draw(list);
    } catch (err) {
      list.replaceChildren(el("div", { class: "empty" }, [el("strong", { text: "Couldn't open this" }), err.message]));
    }
  }

  // Highlights first (a quick row of colour filters when there are several
  // colours), then written notes. Used by showAllNotes.
  async function renderAllNotes(panel, colorFilter = null) {
    const rerender = (c = colorFilter) => renderAllNotes(panel, c);
    const [rows, marks] = await Promise.all([
      cave().api("/me/notes"),
      // Highlights are optional here: before their migration runs, the tab
      // still shows notes.
      cave().api("/me/highlights").catch(() => []),
    ]);
    if (!rows.length && !marks.length) {
      panel.replaceChildren(el("div", { class: "empty" }, [
        el("strong", { text: "No notes or highlights yet" }),
        "Open the Bible, tap a verse, and highlight it or write down what it stirs in you.",
        el("div", {}, el("a", { class: "btn btn-ember btn-sm", href: "#bible", text: "Open the Bible" })),
      ]));
      return;
    }
    const sections = [];
    if (marks.length) {
      const colors = HIGHLIGHT_COLORS.filter(([c]) => marks.some((m) => m.color === c));
      const shown = colorFilter ? marks.filter((m) => m.color === colorFilter) : marks;
      sections.push(el("section", { class: "cave-section" }, [
        el("div", { class: "row-between" }, [
          el("h2", { class: "section-title", text: "Highlights" }),
          colors.length > 1
            ? el("div", { class: "moods", role: "group", "aria-label": "Filter highlights by colour" }, [[null, "All"], ...colors].map(([c, name]) =>
                el("button", { class: "mood", type: "button", "aria-pressed": String(c === colorFilter), onclick: () => rerender(c) }, [
                  c ? el("span", { class: `hl-dot hl-${c}`, "aria-hidden": "true" }) : null,
                  name,
                ])
              ))
            : null,
        ]),
        el("div", { class: "entries" }, shown.map((h) => highlightCard(h, () => rerender()))),
      ]));
    }
    sections.push(el("section", { class: "cave-section" }, [
      marks.length ? el("h2", { class: "section-title", text: "Notes" }) : null,
      rows.length
        ? el("div", { class: "entries" }, rows.map((n) => noteCard(n, { showRead: true, onChange: () => rerender() })))
        : el("p", { class: "muted", text: "No written notes yet. Tap a verse in the Bible and choose Note." }),
    ]));
    panel.replaceChildren(...sections);
  }

  // ---------------------------------------------------------------------
  // Wiring
  // ---------------------------------------------------------------------
  document.addEventListener("adullum:profile", (e) => applyPreferred(e.detail && e.detail.preferred_translation));

  document.addEventListener("DOMContentLoaded", () => {
    loadTranslations();
    ensureBooks().catch(() => {});
    wireBar();
    $("#readerPick").addEventListener("click", openPicker);
    $("#readerPrev").addEventListener("click", () => current && current.prev && app().go(hashFor(current.prev.book, current.prev.chapter)));
    $("#readerNext").addEventListener("click", () => current && current.next && app().go(hashFor(current.next.book, current.next.chapter)));
    $$("select[data-translation-picker]").forEach((s) => s.addEventListener("change", () => setTranslation(s.value)));
    document.addEventListener("keydown", (e) => {
      if ($("[data-view='bible']").hidden || !current || mode !== "read") return;
      if (e.target.closest("input, textarea, select, .sheet-overlay, .graph-overlay")) return;
      if (e.key === "Escape" && range) clearSelection();
      else if (e.key === "ArrowLeft" && current.prev && !e.metaKey && !e.altKey) app().go(hashFor(current.prev.book, current.prev.chapter));
      else if (e.key === "ArrowRight" && current.next && !e.metaKey && !e.altKey) app().go(hashFor(current.next.book, current.next.chapter));
    });
  });

  window.Reader = {
    show,
    hide: clearSelection,
    href,
    renderAllNotes,
    translation,
    setTranslation,
    nameOf,
  };
})();
