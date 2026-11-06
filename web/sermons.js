// Sermon notes: the cave's Sermons tab, and the read-only page a shared link
// opens (#sermon/<token>).
//
// A note is the sermon's details plus an ordered list of blocks (text, point,
// verse, photo, quote, to-do list, link), stored by app/sermons.py. The page
// saves the whole note a moment after each edit. The server finds every Bible
// reference in it (with the parser Aquila uses) and sends them back, so this
// file never has to recognise a reference itself: it shows the server's.
//
// Photos are shrunk here to about 1600 pixels before they're sent, which keeps
// each one to a few hundred KB of storage.
//
// Loaded after web/cave.js, whose helpers (el, api, overlay, toast) it borrows
// through window.Cave at call time.
(function () {
  const cave = () => window.Cave;
  const app = () => window.AdullumApp;
  const el = (...args) => cave().el(...args);
  const api = (...args) => cave().api(...args);
  const toast = (text) => cave().toast(text);

  const SAVE_DELAY_MS = 800;
  const PHOTO_MAX_SIDE = 1600;

  const svg = (d) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
  const ICON = {
    text: svg('<path d="M4 7V5h16v2"/><path d="M12 5v14"/><path d="M9 19h6"/>'),
    heading: svg('<path d="M6 4v16M18 4v16M6 12h12"/>'),
    verse: svg('<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16H6.5A2.5 2.5 0 0 0 4 21.5z"/><path d="M4 5.5v16"/>'),
    image: svg('<rect x="3" y="4" width="18" height="16" rx="2.5"/><circle cx="9" cy="10" r="1.8"/><path d="M21 16l-5-5-9 9"/>'),
    quote: svg('<path d="M7 17c-2 0-3-1.5-3-3.5C4 10 6 7 9 6"/><path d="M17 17c-2 0-3-1.5-3-3.5 0-3.5 2-6.5 5-7.5"/>'),
    todo: svg('<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8.5 12.5l2.5 2.5 4.5-5"/>'),
    link: svg('<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>'),
    up: svg('<path d="M12 19V5M6 11l6-6 6 6"/>'),
    down: svg('<path d="M12 5v14M6 13l6 6 6-6"/>'),
    trash: svg('<path d="M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13"/>'),
    check: svg('<path d="M5 12.5l4.5 4.5L19 7.5"/>'),
    book: svg('<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16H6.5A2.5 2.5 0 0 0 4 21.5z"/>'),
    export: svg('<path d="M12 4v11M7 10l5 5 5-5"/><path d="M5 20h14"/>'),
    share: svg('<circle cx="18" cy="5" r="2.5"/><circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="19" r="2.5"/><path d="M8.2 10.8l7.6-4.4M8.2 13.2l7.6 4.4"/>'),
    aquila: svg('<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/>'),
    graph: svg('<circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="8" r="2.5"/><circle cx="10" cy="18" r="2.5"/><path d="M8.2 7.2l7.6.6M7 8.3l2.2 7.3M16.6 10l-4.9 6.3"/>'),
    pen: svg('<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16z"/>'),
  };

  const ADD = [
    ["text", "Text"], ["heading", "Point"], ["verse", "Verse"], ["image", "Photo"],
    ["quote", "Quote"], ["todo", "To do"], ["link", "Link"],
  ];

  // ---------------------------------------------------------------------
  // State for the open tab
  // ---------------------------------------------------------------------
  let panel = null;      // the cave panel while the Sermons tab is open
  let notes = [];        // the list, without blocks
  let current = null;    // the open note, with blocks
  let query = "";
  let saveTimer = null;
  let dirty = false;
  let saving = Promise.resolve();

  const newId = () => (window.crypto && crypto.randomUUID ? crypto.randomUUID().replace(/-/g, "").slice(0, 16) : Math.random().toString(36).slice(2, 14));
  const translation = () => ((document.getElementById("translation") || {}).value || "BSB").trim() || "BSB";
  // Same server as every other call (web/cave.js::apiBase): the hidden #apiBase input, or this site.
  const apiBase = () => (((document.getElementById("apiBase") || {}).value || "").trim() || location.origin).replace(/\/$/, "");
  const isoToday = () => cave().localToday();

  function niceDate(iso) {
    if (!iso) return "";
    const d = new Date(`${iso.slice(0, 10)}T12:00:00`);
    return isNaN(d) ? "" : d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric" });
  }
  function clip(text, n) {
    return text.length > n ? `${text.slice(0, n - 3).trimEnd()}...` : text;
  }

  // A link is only ever kept as a web address. "example.com/talk" gains
  // https://; anything that isn't a web address is dropped, since a shared
  // note is opened by people who didn't write it.
  function webUrl(raw) {
    const url = (raw || "").trim();
    if (!url) return "";
    if (/^https?:\/\//i.test(url)) return url;
    if (/^[\w-]+(\.[\w-]+)+(\/\S*)?$/i.test(url)) return `https://${url}`;
    return "";
  }

  // A textarea that grows with what's written in it, so a block reads like a
  // page. Its height is measured again whenever its width changes and once
  // the web fonts arrive: Inter wraps differently from the fallback font, and
  // a height measured before it loads cuts off the last line.
  const fitArea = (area) => { area.style.height = "auto"; area.style.height = `${area.scrollHeight}px`; };
  const refit = window.ResizeObserver ? new ResizeObserver((entries) => entries.forEach((e) => fitArea(e.target))) : null;
  function grow(area) {
    area.addEventListener("input", () => fitArea(area));
    requestAnimationFrame(() => fitArea(area));
    if (refit) refit.observe(area);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => fitArea(area));
    return area;
  }

  function refChip(ref) {
    return el("a", { class: "ref-chip", href: `#${window.Reader.href(ref)}`, html: `${ICON.book}<span></span>` }, []);
  }
  function chip(ref) {
    const a = refChip(ref);
    a.querySelector("span").textContent = ref;
    return a;
  }

  // ---------------------------------------------------------------------
  // Saving: the whole note, a moment after the last edit, one save at a time
  // ---------------------------------------------------------------------
  function setStatus(text, ok = true) {
    const node = panel && panel.querySelector("#sermonSaved");
    if (!node) return;
    node.classList.toggle("is-error", !ok);
    node.innerHTML = `${ok ? ICON.check : ""}<span></span>`;
    node.lastChild.textContent = text;
  }

  function changed() {
    dirty = true;
    setStatus("Saving...");
    clearTimeout(saveTimer);
    saveTimer = setTimeout(save, SAVE_DELAY_MS);
  }

  function payload(note) {
    return {
      title: note.title || "",
      speaker: note.speaker || null,
      church: note.church || null,
      preached_on: note.preached_on || null,
      series: note.series || null,
      passage_ref: note.passage_ref || null,
      // `url` is a signed link for showing a photo, never stored.
      blocks: note.blocks.map((b) => {
        const { url, ...rest } = b;
        if (rest.type === "link") rest.url = webUrl(rest.url);
        return rest;
      }),
    };
  }

  function save() {
    clearTimeout(saveTimer);
    if (!dirty || !current) return saving;
    const note = current;
    dirty = false;
    saving = saving.then(async () => {
      try {
        const saved = await api(`/me/sermons/${note.id}`, { method: "PATCH", body: payload(note) });
        // Only what the server worked out is taken back, so nothing typed
        // since the save started is overwritten.
        note.passages = saved.passages;
        note.block_refs = saved.block_refs;
        note.updated_at = saved.updated_at;
        const listed = notes.find((n) => n.id === note.id);
        if (listed) Object.assign(listed, { title: note.title, speaker: note.speaker, preached_on: note.preached_on, passage_ref: saved.passage_ref, passages: saved.passages });
        if (note === current) {
          setStatus(dirty ? "Saving..." : "Saved");
          refreshRefs();
          renderList();
        }
      } catch (err) {
        dirty = true;
        if (note === current) setStatus("Couldn't save. Your next edit tries again.", false);
        toast(err.message);
      }
    });
    return saving;
  }

  // Leaving the tab (or the page) saves anything still waiting.
  function hide() {
    save();
    panel = null;
  }
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") save(); });

  // ---------------------------------------------------------------------
  // The tab: list on the left, the open note on the right
  // ---------------------------------------------------------------------
  async function renderTab(p) {
    panel = p;
    try {
      notes = await api("/me/sermons");
    } catch (err) {
      panel.replaceChildren(el("div", { class: "empty" }, [el("strong", { text: "Sermon notes aren't open yet" }), err.message]));
      return;
    }
    if (!notes.length) return renderEmpty();
    const keep = current && notes.find((n) => n.id === current.id);
    await openNote((keep || notes[0]).id);
  }

  function renderEmpty() {
    panel.replaceChildren(el("section", { class: "card sermon-empty fade-in" }, [
      el("span", { class: "sermon-empty-icon", html: ICON.verse }),
      el("h2", { class: "section-title", text: "Keep every sermon in one place" }),
      el("p", { class: "muted", text: "Take notes during the service: what you heard, the verses, a photo of the slides, a line worth keeping, and what you'll do about it this week. Every passage you write links to your Bible." }),
      el("button", { class: "btn btn-ember btn-sm", type: "button", text: "New sermon note", onclick: newNote }),
    ]));
  }

  function layout() {
    let shell = panel.querySelector(".sermons");
    if (shell) return shell;
    const search = el("input", { class: "field sermon-search", type: "search", placeholder: "Search sermons, speakers, passages", "aria-label": "Search your sermon notes" });
    search.value = query;
    search.addEventListener("input", () => { query = search.value.trim().toLowerCase(); renderList(); });
    shell = el("div", { class: "sermons" }, [
      el("aside", { class: "card sermon-list", "aria-label": "Your sermon notes" }, [search, el("div", { class: "sermon-items", id: "sermonItems" })]),
      el("div", { class: "sermon-main" }, [
        el("section", { class: "card sermon-editor", id: "sermonEditor", "aria-label": "Sermon note" }),
        el("div", { class: "sermon-connected", id: "sermonConnected" }),
      ]),
    ]);
    // A photo pasted anywhere in the note lands in a new photo block.
    shell.addEventListener("paste", (e) => {
      const file = [...((e.clipboardData && e.clipboardData.files) || [])].find((f) => f.type.startsWith("image/"));
      if (!file || !current) return;
      e.preventDefault();
      const block = { id: newId(), type: "image", path: null, caption: "" };
      current.blocks.push(block);
      renderBlocks();
      uploadPhoto(file, block);
    });
    panel.replaceChildren(shell);
    return shell;
  }

  function renderList() {
    if (!panel) return;
    const box = panel.querySelector("#sermonItems");
    if (!box) return;
    const shown = notes.filter((n) => !query || [n.title, n.speaker, n.church, n.series, ...(n.passages || [])].join(" ").toLowerCase().includes(query));
    box.replaceChildren(...(shown.length ? shown.map((n) => el("button", {
      class: "sermon-item", type: "button", "aria-current": String(!!current && n.id === current.id),
      onclick: () => openNote(n.id, { scroll: true }),
    }, [
      el("strong", { text: n.title || "Untitled sermon" }),
      el("span", { text: [niceDate(n.preached_on), n.speaker].filter(Boolean).join(" · ") }),
      el("span", { class: "sermon-item-foot" }, [
        n.passages && n.passages[0] ? el("span", { class: "verse-ref", text: n.passages[0] }) : null,
        n.shared ? el("span", { class: "badge plain", text: "Shared" }) : null,
      ]),
    ])) : [el("p", { class: "muted", style: "font-size:14px;padding:6px 4px", text: query ? "No sermon notes match that." : "No sermon notes yet." })]));
  }

  async function openNote(id, { scroll = false, focusTitle = false } = {}) {
    await save();
    let note;
    try {
      note = await api(`/me/sermons/${id}`);
    } catch (err) {
      return toast(err.message);
    }
    if (!panel) return;
    current = note;
    dirty = false;
    layout();
    renderList();
    renderEditor();
    renderConnected();
    if (scroll && window.innerWidth <= 820) panel.querySelector("#sermonEditor").scrollIntoView({ behavior: "smooth", block: "start" });
    if (focusTitle) panel.querySelector(".sermon-title").focus();
  }

  async function newNote() {
    if (!panel) {
      // From the header button on another tab: open the tab, then start one.
      await cave().showCave("sermons");
    }
    await save();
    try {
      const note = await api("/me/sermons", { method: "POST", body: { preached_on: isoToday(), blocks: [{ id: newId(), type: "text", text: "" }] } });
      notes.unshift({ ...note, shared: false });
      query = "";
      if (panel && panel.querySelector(".sermon-search")) panel.querySelector(".sermon-search").value = "";
      await openNote(note.id, { scroll: true, focusTitle: true });
    } catch (err) {
      toast(err.message);
    }
  }

  // ---------------------------------------------------------------------
  // The open note
  // ---------------------------------------------------------------------
  function metaField(label, key, type = "text", placeholder = "") {
    const input = el("input", { class: "sermon-meta-input", type, placeholder, "aria-label": label, maxlength: type === "text" ? "200" : null });
    input.value = current[key] || "";
    input.addEventListener("input", () => { current[key] = input.value; changed(); if (key === "title") renderList(); });
    return el("label", { class: "sermon-meta-field" }, [el("span", { text: label }), input]);
  }

  function renderEditor() {
    const editor = panel.querySelector("#sermonEditor");
    const title = el("input", { class: "sermon-title", maxlength: "200", placeholder: "Sermon title", "aria-label": "Sermon title" });
    title.value = current.title || "";
    title.addEventListener("input", () => { current.title = title.value; changed(); renderList(); });
    editor.replaceChildren(
      el("div", { class: "sermon-top" }, [
        el("span", { class: "sermon-saved", id: "sermonSaved", role: "status", html: `${ICON.check}<span>Saved</span>` }),
        el("div", { class: "row", style: "gap:6px" }, [
          el("button", { class: "act", type: "button", html: `${ICON.share}<span>${current.shared ? "Shared" : "Share"}</span>`, onclick: openShare }),
          el("button", { class: "act", type: "button", html: `${ICON.export}<span>Export</span>`, onclick: openExport }),
          el("button", { class: "act act-icon danger", type: "button", title: "Delete this note", "aria-label": "Delete this note", html: ICON.trash, onclick: deleteNote }),
        ]),
      ]),
      title,
      el("div", { class: "sermon-meta" }, [
        metaField("Speaker", "speaker", "text", "Who preached"),
        metaField("Church or group", "church", "text", "Where"),
        metaField("Date", "preached_on", "date"),
        metaField("Series", "series", "text", "Optional"),
        metaField("Main passage", "passage_ref", "text", "e.g. Philippians 4:4-9"),
      ]),
      el("div", { class: "sermon-blocks", id: "sermonBlocks" }),
      el("div", { class: "sermon-add" }, [
        el("span", { class: "kicker", text: "Add" }),
        ...ADD.map(([type, label]) => el("button", { type: "button", html: `${ICON[type]}<span>${label}</span>`, onclick: () => addBlock(type) })),
      ])
    );
    renderBlocks();
  }

  function blockTools(block) {
    const move = (dir) => {
      const i = current.blocks.indexOf(block);
      const j = i + dir;
      if (j < 0 || j >= current.blocks.length) return;
      [current.blocks[i], current.blocks[j]] = [current.blocks[j], current.blocks[i]];
      renderBlocks();
      changed();
    };
    return el("div", { class: "sermon-tools" }, [
      el("button", { type: "button", title: "Move up", "aria-label": "Move up", html: ICON.up, onclick: () => move(-1) }),
      el("button", { type: "button", title: "Move down", "aria-label": "Move down", html: ICON.down, onclick: () => move(1) }),
      el("button", { type: "button", title: "Remove", "aria-label": "Remove this block", html: ICON.trash, onclick: () => {
        current.blocks = current.blocks.filter((b) => b !== block);
        renderBlocks();
        changed();
      } }),
    ]);
  }

  function textArea(cls, value, placeholder, max, onText) {
    const area = el("textarea", { class: cls, rows: "1", maxlength: String(max), placeholder, "aria-label": placeholder });
    area.value = value || "";
    area.addEventListener("input", () => { onText(area.value); changed(); });
    return grow(area);
  }

  // A verse block shows the verse in the reader's translation, read from the
  // Bible (never typed in), once the reference is complete.
  function verseBody(block) {
    const input = el("input", { class: "sermon-verse-ref", maxlength: "120", placeholder: "John 3:16", "aria-label": "Verse reference" });
    input.value = block.ref || "";
    const text = el("div", { class: "sermon-verse-text" });
    let timer;
    const show = async () => {
      const ref = input.value.trim();
      if (!ref) return text.replaceChildren(el("p", { class: "muted", text: "Type a reference and the verse appears here." }));
      try {
        const v = await cave().verseText(ref);
        if (input.value.trim() !== ref) return;
        text.replaceChildren(el("p", { class: "scripture", text: `“${clip(v.text, 1200)}”` }));
        trans.textContent = v.translation;
      } catch {
        text.replaceChildren(el("p", { class: "muted", text: "Keep typing: that isn't a verse yet." }));
      }
    };
    input.addEventListener("input", () => { block.ref = input.value; changed(); clearTimeout(timer); timer = setTimeout(show, 500); });
    const trans = el("span", { class: "faint", style: "font-size:13px", text: translation() });
    show();
    return el("div", { class: "sermon-verse" }, [text, el("div", { class: "row", style: "gap:8px" }, [input, trans])]);
  }

  function photoBody(block) {
    if (block.path) {
      return el("figure", { class: "sermon-photo" }, [
        block.url ? el("img", { src: block.url, alt: block.caption || "A photo in this sermon note", loading: "lazy" }) : el("div", { class: "sermon-drop", text: "This photo couldn't be shown right now." }),
        el("input", { class: "sermon-caption", maxlength: "500", placeholder: "Add a caption", "aria-label": "Caption", value: block.caption || "", oninput: (e) => { block.caption = e.target.value; changed(); } }),
      ]);
    }
    const inputId = `photo-${block.id}`;
    const file = el("input", { type: "file", accept: "image/*", id: inputId, hidden: true });
    file.addEventListener("change", () => file.files[0] && uploadPhoto(file.files[0], block));
    const zone = el("label", { class: "sermon-drop", for: inputId }, [
      el("span", { html: ICON.image }),
      el("strong", { text: block.uploading ? "Adding your photo..." : "Add a photo" }),
      el("span", { text: "A slide, a page of handwritten notes, the bulletin. Drop it here, paste it, or choose a file." }),
    ]);
    zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("is-over"); });
    zone.addEventListener("dragleave", () => zone.classList.remove("is-over"));
    zone.addEventListener("drop", (e) => {
      e.preventDefault();
      zone.classList.remove("is-over");
      const dropped = e.dataTransfer.files[0];
      if (dropped) uploadPhoto(dropped, block);
    });
    return el("div", {}, [zone, file]);
  }

  // Shrinks a photo to PHOTO_MAX_SIDE on its long side, as a JPEG.
  async function shrink(file) {
    const src = URL.createObjectURL(file);
    try {
      const img = await new Promise((resolve, reject) => {
        const i = new Image();
        i.onload = () => resolve(i);
        i.onerror = () => reject(new Error("That file couldn't be opened as a photo."));
        i.src = src;
      });
      const scale = Math.min(1, PHOTO_MAX_SIDE / Math.max(img.naturalWidth, img.naturalHeight));
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(img.naturalWidth * scale);
      canvas.height = Math.round(img.naturalHeight * scale);
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = "#ffffff"; // a transparent PNG becomes white, not black
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.85));
      const dataUrl = await new Promise((resolve) => { const r = new FileReader(); r.onload = () => resolve(r.result); r.readAsDataURL(blob); });
      return String(dataUrl).split(",")[1];
    } finally {
      URL.revokeObjectURL(src);
    }
  }

  async function uploadPhoto(file, block) {
    if (!file.type.startsWith("image/")) return toast("That isn't a photo. Try a picture of a slide or your notebook.");
    const note = current;
    block.uploading = true;
    renderBlocks();
    try {
      const data = await shrink(file);
      const res = await api(`/me/sermons/${note.id}/images`, { method: "POST", body: { content_type: "image/jpeg", data } });
      block.path = res.path;
      block.url = res.url;
      delete block.uploading;
      if (note === current) { renderBlocks(); changed(); } else { dirty = true; }
    } catch (err) {
      delete block.uploading;
      if (note === current) renderBlocks();
      toast(err.message);
    }
  }

  function todoBody(block) {
    const rows = el("div", { class: "sermon-todo-rows" });
    const draw = () => rows.replaceChildren(...block.items.map((item, index) => {
      const row = el("div", { class: `sermon-todo-row${item.done ? " is-done" : ""}` });
      const box = el("input", { type: "checkbox", checked: item.done, "aria-label": "Done" });
      box.addEventListener("change", () => { item.done = box.checked; row.classList.toggle("is-done", item.done); changed(); });
      // A growing box rather than a one-line input, so a long step wraps on a phone.
      const text = grow(el("textarea", { class: "sermon-todo-text", rows: "1", maxlength: "500", placeholder: "Something to do this week", "aria-label": "Step" }));
      text.value = item.text || "";
      text.addEventListener("input", () => { item.text = text.value; changed(); });
      text.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); block.items.splice(index + 1, 0, { text: "", done: false }); draw(); rows.children[index + 1].querySelector(".sermon-todo-text").focus(); changed(); }
        if (e.key === "Backspace" && !text.value && block.items.length > 1) { e.preventDefault(); block.items.splice(index, 1); draw(); const prev = rows.children[Math.max(0, index - 1)]; if (prev) prev.querySelector(".sermon-todo-text").focus(); changed(); }
      });
      const pray = item.prayer_id
        ? el("a", { class: "sermon-to-prayers is-done", href: "#prayers", text: "On prayer list" })
        : el("button", { class: "sermon-to-prayers", type: "button", text: "Add to prayers", onclick: () => addToPrayers(item, pray) });
      row.append(box, text, pray);
      return row;
    }));
    draw();
    return el("div", { class: "sermon-todo" }, [
      el("p", { class: "kicker", text: "To live it out this week" }),
      rows,
      el("button", { class: "sermon-add-step", type: "button", text: "+ Add a step", onclick: () => {
        block.items.push({ text: "", done: false });
        draw();
        rows.lastChild.querySelector(".sermon-todo-text").focus();
        changed();
      } }),
    ]);
  }

  async function addToPrayers(item, button) {
    const body = (item.text || "").trim();
    if (!body) return toast("Write the step first, then add it to your prayers.");
    button.disabled = true;
    const main = current.passages && current.passages[0];
    try {
      const prayer = await api("/me/prayers", { method: "POST", body: { body, passage_ref: main && !/^[^:]+ \d+$/.test(main) ? main : null } });
      item.prayer_id = prayer.id;
      button.replaceWith(el("a", { class: "sermon-to-prayers is-done", href: "#prayers", text: "On prayer list" }));
      toast("Added to your prayer list.");
      changed();
      await save();
      renderConnected();
    } catch (err) {
      button.disabled = false;
      toast(err.message);
    }
  }

  function linkBody(block) {
    const label = el("input", { class: "sermon-link-label", maxlength: "200", placeholder: "What it is, e.g. Watch the recording", "aria-label": "Link name", value: block.label || "" });
    const url = el("input", { class: "sermon-link-url", maxlength: "1000", placeholder: "Paste the link", "aria-label": "Link address", value: block.url || "" });
    const open = el("a", { class: "act", target: "_blank", rel: "noopener", text: "Open" });
    const sync = () => {
      const href = webUrl(url.value);
      open.hidden = !href;
      if (href) open.href = href;
    };
    label.addEventListener("input", () => { block.label = label.value; changed(); });
    url.addEventListener("input", () => { block.url = url.value; sync(); changed(); });
    sync();
    return el("div", { class: "sermon-link" }, [el("span", { class: "sermon-link-icon", html: ICON.link }), el("div", { class: "sermon-link-fields" }, [label, url]), open]);
  }

  function renderBlock(block) {
    const wrap = el("div", { class: `sermon-block sermon-block-${block.type}`, "data-id": block.id });
    let body;
    if (block.type === "text") body = textArea("sermon-text", block.text, "Write what you're hearing...", 20000, (v) => { block.text = v; });
    else if (block.type === "heading") body = textArea("sermon-heading", block.text, "A point or heading", 300, (v) => { block.text = v; });
    else if (block.type === "verse") body = verseBody(block);
    else if (block.type === "image") body = photoBody(block);
    else if (block.type === "quote") body = el("blockquote", { class: "sermon-quote" }, [
      textArea("sermon-quote-text", block.text, "A line worth keeping", 2000, (v) => { block.text = v; }),
      el("input", { class: "sermon-quote-who", maxlength: "200", placeholder: "Who said it", "aria-label": "Who said it", value: block.who || "", oninput: (e) => { block.who = e.target.value; changed(); } }),
    ]);
    else if (block.type === "todo") body = todoBody(block);
    else if (block.type === "link") body = linkBody(block);
    wrap.append(body, el("div", { class: "ref-chips sermon-refs", "data-refs-for": block.id }), blockTools(block));
    return wrap;
  }

  function renderBlocks() {
    const box = panel && panel.querySelector("#sermonBlocks");
    if (!box) return;
    box.replaceChildren(...current.blocks.map(renderBlock));
    refreshRefs();
  }

  // Each block's references, as the server found them at the last save.
  // Verse blocks show their own passage already, so they get no chips.
  function refreshRefs() {
    if (!panel || !current) return;
    const refs = current.block_refs || {};
    panel.querySelectorAll("[data-refs-for]").forEach((node) => {
      const block = current.blocks.find((b) => b.id === node.dataset.refsFor);
      const list = block && block.type !== "verse" ? refs[node.dataset.refsFor] || [] : [];
      node.replaceChildren(...list.map(chip));
    });
    renderPassages();
  }

  function addBlock(type) {
    const block = { id: newId(), type };
    if (type === "text" || type === "heading") block.text = "";
    if (type === "verse") block.ref = "";
    if (type === "image") { block.path = null; block.caption = ""; }
    if (type === "quote") { block.text = ""; block.who = current.speaker || ""; }
    if (type === "todo") block.items = [{ text: "", done: false }];
    if (type === "link") { block.url = ""; block.label = ""; }
    current.blocks.push(block);
    renderBlocks();
    const last = panel.querySelector("#sermonBlocks").lastChild;
    const target = last.querySelector("textarea, input:not([type=file]):not([type=checkbox]), label");
    if (target) target.focus({ preventScroll: true });
    last.scrollIntoView({ behavior: "smooth", block: "center" });
    changed();
  }

  async function deleteNote() {
    if (!confirm(`Delete "${current.title || "Untitled sermon"}"? Its photos go with it, and a shared link stops working.`)) return;
    clearTimeout(saveTimer);
    dirty = false;
    try {
      await api(`/me/sermons/${current.id}`, { method: "DELETE" });
      notes = notes.filter((n) => n.id !== current.id);
      current = null;
      toast("Deleted.");
      if (!notes.length) return renderEmpty();
      await openNote(notes[0].id);
    } catch (err) {
      toast(err.message);
    }
  }

  // ---------------------------------------------------------------------
  // What the note connects to
  // ---------------------------------------------------------------------
  function renderPassages() {
    const box = panel && panel.querySelector("#sermonPassages");
    if (!box) return;
    const passages = current.passages || [];
    box.replaceChildren(
      el("h2", { class: "section-title", text: "Passages in this sermon" }),
      passages.length
        ? el("div", { class: "ref-chips" }, passages.map(chip))
        : el("p", { class: "muted", style: "font-size:14px", text: "Write a reference anywhere in your notes, like John 3:16, and it gathers here." }),
      passages.length ? el("button", { class: "linkish", type: "button", text: "See how they connect", onclick: () => window.Graph.open(passages.slice(0, 6)) }) : null
    );
  }

  function askAquila() {
    const main = (current.passages || [])[0];
    const words = current.blocks.filter((b) => ["text", "heading", "quote"].includes(b.type)).map((b) => b.text || "").join(" ").replace(/\s+/g, " ").trim();
    const heard = current.title ? `I heard a sermon called "${current.title}"` : "I heard a sermon";
    // The reference goes first so retrieval starts from it, and the notes go
    // in quoted as the person's own words, like a note from the reader.
    const ask = `${heard}. Help me understand the passage and how to live it out this week.${words ? ` My notes say: "${clip(words, 400)}"` : ""}`;
    app().submitQuery(main ? `On ${main}: ${ask}` : ask);
  }

  async function renderConnected() {
    const box = panel && panel.querySelector("#sermonConnected");
    if (!box) return;
    const note = current;
    const linked = el("section", { class: "card sermon-panel" }, [el("h2", { class: "section-title", text: "Also in your cave" }), el("p", { class: "muted", style: "font-size:14px", text: "Looking..." })]);
    box.replaceChildren(
      el("section", { class: "card sermon-panel", id: "sermonPassages" }),
      linked,
      el("section", { class: "card sermon-panel" }, [
        el("h2", { class: "section-title", text: "Keep going" }),
        el("div", { class: "sermon-actions" }, [
          el("button", { class: "btn btn-ember btn-sm", type: "button", html: `${ICON.aquila}<span>Ask Aquila about this sermon</span>`, onclick: askAquila }),
          el("button", { class: "btn btn-ghost btn-sm", type: "button", html: `${ICON.pen}<span>Journal about it</span>`, onclick: () => {
            const main = (current.passages || [])[0];
            cave().openJournal({ passage_ref: main || undefined, question: current.title ? `Sermon: ${current.title}` : undefined });
          } }),
        ]),
      ])
    );
    renderPassages();
    let found;
    try {
      found = await api(`/me/sermons/${note.id}/connected`);
    } catch {
      found = { prayers: [], journal: [], sermons: [] };
    }
    if (note !== current) return;
    const rows = [
      ...found.prayers.map((p) => el("a", { class: "sermon-linked", href: "#prayers" }, [
        el("span", { class: "faint", text: p.status === "answered" ? "Prayer, answered" : "Prayer list" }), el("span", { text: clip(p.body, 140) }),
      ])),
      ...found.journal.map((j) => el("a", { class: "sermon-linked", href: "#journal" }, [
        el("span", { class: "faint", text: `Journal · ${j.passage_ref || ""}` }), el("span", { text: clip(j.reflection || "", 140) }),
      ])),
      ...found.sermons.map((s) => el("button", { class: "sermon-linked", type: "button", onclick: () => openNote(s.id, { scroll: true }) }, [
        el("span", { class: "faint", text: `Sermon${s.preached_on ? ` · ${niceDate(s.preached_on)}` : ""}` }), el("span", { text: s.title || "Untitled sermon" }),
      ])),
    ];
    linked.replaceChildren(
      el("h2", { class: "section-title", text: "Also in your cave" }),
      ...(rows.length ? rows : [el("p", { class: "muted", style: "font-size:14px", text: "Add a step to your prayers, or journal on one of these passages, and it shows up here. So do other sermons on the same books." })])
    );
  }

  // ---------------------------------------------------------------------
  // Sharing and export
  // ---------------------------------------------------------------------
  const shareUrl = (token) => `${location.origin}${location.pathname}#sermon/${token}`;

  async function openShare() {
    await save();
    const note = current;
    const body = el("div", { class: "sermon-share-body" });
    const close = cave().overlay(el("div", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "shareTitle" }, [
      el("h3", { id: "shareTitle", text: "Share with your small group" }),
      el("p", { class: "sheet-lede", text: "Anyone with the link can read this note: its text, verses, photos and to-do list. They can't change it, and they can't see anything else in your cave." }),
      body,
    ]));

    const showOff = () => body.replaceChildren(el("div", { class: "sheet-actions" }, [
      el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Not now", onclick: () => close() }),
      el("button", { class: "btn btn-ember btn-sm", type: "button", text: "Create a link", onclick: async (e) => {
        e.target.disabled = true;
        try {
          const res = await api(`/me/sermons/${note.id}/share`, { method: "POST" });
          note.share_token = res.token;
          setShared(note, true);
          showOn(res.token);
        } catch (err) {
          e.target.disabled = false;
          toast(err.message);
        }
      } }),
    ]));

    const showOn = (token) => {
      const url = shareUrl(token);
      const field = el("input", { class: "field", readonly: true, value: url, "aria-label": "Link to this note", onfocus: (e) => e.target.select() });
      const copy = el("button", { class: "btn btn-ember btn-sm", type: "button", text: "Copy link", onclick: () => {
        const done = () => toast("Link copied. Paste it into your group chat.");
        if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(url).then(done, () => { field.select(); toast("Press Ctrl+C or Cmd+C to copy."); });
        else { field.select(); toast("Press Ctrl+C or Cmd+C to copy."); }
      } });
      const native = navigator.share ? el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Share...", onclick: () => navigator.share({ title: note.title || "Sermon notes", url }).catch(() => {}) }) : null;
      const stop = el("button", { class: "btn btn-ghost btn-sm danger-text", type: "button", text: "Stop sharing", onclick: async () => {
        if (!confirm("Stop sharing? The link stops working for everyone who has it. Sharing again makes a new link.")) return;
        try {
          await api(`/me/sermons/${note.id}/share`, { method: "DELETE" });
          note.share_token = null;
          setShared(note, false);
          toast("This note is private again.");
          showOff();
        } catch (err) {
          toast(err.message);
        }
      } });
      body.replaceChildren(field, el("div", { class: "sheet-actions" }, [stop, el("span", { style: "flex:1" }), native, copy]));
    };

    if (note.share_token) showOn(note.share_token);
    else showOff();
  }

  function setShared(note, on) {
    note.shared = on;
    const listed = notes.find((n) => n.id === note.id);
    if (listed) listed.shared = on;
    renderList();
    if (note === current && panel) {
      const button = [...panel.querySelectorAll(".sermon-top .act")].find((b) => /Share/.test(b.textContent));
      if (button) button.lastChild.textContent = on ? "Shared" : "Share";
    }
  }

  // Downloads go through fetch, since the export needs the sign-in header.
  async function download(path, fallbackName) {
    const resp = await fetch(`${apiBase()}${path}`, { headers: await cave().authHeaders() });
    if (!resp.ok) {
      let detail = "";
      try { detail = (await resp.json()).detail; } catch { /* not JSON */ }
      throw new Error(typeof detail === "string" && detail ? detail : `The export didn't work (${resp.status}).`);
    }
    const disposition = resp.headers.get("Content-Disposition") || "";
    const match = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
    const name = match ? decodeURIComponent(match[1]) : fallbackName;
    const url = URL.createObjectURL(await resp.blob());
    const a = el("a", { href: url, download: name });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }

  async function openExport() {
    await save();
    const note = current;
    const tr = encodeURIComponent(translation());
    const run = (format, label) => async (e) => {
      const button = e.currentTarget;
      button.disabled = true;
      try {
        await download(`/me/sermons/${note.id}/export?format=${format}&translation=${tr}`, `Sermon.${format}`);
        close();
      } catch (err) {
        toast(err.message);
      } finally {
        button.disabled = false;
      }
    };
    const option = (format, name, line) => el("button", { class: "sermon-format", type: "button", onclick: run(format) }, [el("strong", { text: name }), el("span", { text: line })]);
    const close = cave().overlay(el("div", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "exportTitle" }, [
      el("h3", { id: "exportTitle", text: `Export "${note.title || "Untitled sermon"}"` }),
      el("p", { class: "sheet-lede", text: `Verses are written out in ${translation()}, the translation you read in.` }),
      el("div", { class: "sermon-formats" }, [
        option("pdf", "PDF", "With photos, ready to print or send"),
        option("docx", "Word", "To keep editing elsewhere"),
        option("md", "Markdown", "For Notion, Obsidian and similar apps"),
      ]),
      el("div", { class: "sheet-actions" }, [
        el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Export all sermons (.zip)", onclick: async (e) => {
          e.currentTarget.disabled = true;
          try {
            await download(`/me/sermons/export.zip?translation=${tr}`, "Sermon notes.zip");
            close();
          } catch (err) {
            toast(err.message);
          }
        } }),
        el("span", { style: "flex:1" }),
        el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Close", onclick: () => close() }),
      ]),
    ]));
  }

  // ---------------------------------------------------------------------
  // The shared page (#sermon/<token>): read-only, no account needed
  // ---------------------------------------------------------------------
  async function renderShared() {
    const root = document.getElementById("sharedSermon");
    if (!root) return;
    const token = decodeURIComponent((location.hash.split("/")[1] || "").trim());
    root.replaceChildren(el("div", { class: "empty", text: "Opening..." }));
    let note;
    try {
      const resp = await fetch(`${apiBase()}/shared/sermons/${encodeURIComponent(token)}`);
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(typeof data.detail === "string" ? data.detail : "This sermon note couldn't be opened.");
      note = data;
    } catch (err) {
      root.replaceChildren(el("div", { class: "empty" }, [el("strong", { text: "This link isn't working" }), err.message]));
      return;
    }
    document.title = `${note.title || "Sermon notes"}, Adullum`;
    const refs = note.block_refs || {};
    const blocks = (note.blocks || []).map((b) => {
      const chips = b.type !== "verse" && (refs[b.id] || []).length ? el("div", { class: "ref-chips" }, refs[b.id].map(chip)) : null;
      let body = null;
      if (b.type === "text" && b.text) body = el("p", { class: "sermon-read-text", text: b.text });
      else if (b.type === "heading" && b.text) body = el("h2", { class: "sermon-read-heading", text: b.text });
      else if (b.type === "verse" && b.ref) {
        const text = el("p", { class: "scripture", text: "" });
        const box = el("div", { class: "sermon-verse" }, [text, el("div", { class: "row", style: "gap:8px" }, [chip(b.ref)])]);
        cave().verseText(b.ref).then((v) => { text.textContent = `“${clip(v.text, 1200)}”`; }).catch(() => text.remove());
        body = box;
      } else if (b.type === "image" && b.url) body = el("figure", { class: "sermon-photo" }, [
        el("img", { src: b.url, alt: b.caption || "A photo from the sermon", loading: "lazy" }),
        b.caption ? el("figcaption", { class: "sermon-read-caption", text: b.caption }) : null,
      ]);
      else if (b.type === "quote" && b.text) body = el("blockquote", { class: "sermon-quote" }, [el("p", { class: "sermon-read-quote", text: b.text }), b.who ? el("p", { class: "faint", style: "font-size:13px", text: b.who }) : null]);
      else if (b.type === "todo" && (b.items || []).some((i) => i.text)) body = el("div", { class: "sermon-todo" }, [
        el("p", { class: "kicker", text: "To live it out this week" }),
        ...b.items.filter((i) => i.text).map((i) => el("p", { class: `sermon-read-step${i.done ? " is-done" : ""}`, html: i.done ? ICON.check : "" }, [el("span", { text: i.text })])),
      ]);
      else if (b.type === "link" && webUrl(b.url)) body = el("p", {}, el("a", { class: "act", href: webUrl(b.url), target: "_blank", rel: "noopener", html: `${ICON.link}<span></span>` }));
      if (body && b.type === "link") body.querySelector("span").textContent = b.label || webUrl(b.url);
      return body ? el("div", { class: "sermon-read-block" }, [body, chips]) : null;
    }).filter(Boolean);

    const main = (note.passages || [])[0];
    root.replaceChildren(el("article", { class: "card sermon-read fade-in" }, [
      el("p", { class: "kicker ember", text: "Sermon notes, shared from Adullum" }),
      el("h1", { class: "page-title", text: note.title || "Untitled sermon" }),
      el("p", { class: "muted", text: [note.speaker, note.church, niceDate(note.preached_on)].filter(Boolean).join(" · ") }),
      note.series ? el("p", { class: "faint", style: "font-size:14px", text: `Series: ${note.series}` }) : null,
      main ? el("div", { class: "ref-chips" }, [chip(main)]) : null,
      el("div", { class: "sermon-read-blocks" }, blocks),
      el("div", { class: "sermon-read-foot" }, [
        el("p", { class: "faint", style: "font-size:14px", text: "These are someone's own notes. Verses are read from the Bible in your chosen translation." }),
        main ? el("div", { class: "row" }, [
          el("a", { class: "btn btn-ghost btn-sm", href: `#${window.Reader.href(main)}`, text: `Read ${main}` }),
          el("button", { class: "btn btn-ember btn-sm", type: "button", text: "Ask Aquila about it", onclick: () => app().submitQuery(`On ${main}: help me understand this passage and how to live it out.`) }),
        ]) : null,
      ]),
    ]));
  }

  window.Sermons = { renderTab, renderShared, newNote, hide };
})();
