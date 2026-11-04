// My Cave: sign-in, the journal, past conversations, and what Aquila remembers.
//
// Loaded before index.html's main script, so it only defines things here and
// reaches back into that script (through window.AdullumApp) at call time,
// never at load time. All talk with Supabase goes through our own API (see
// app/auth.py): this file holds the person's tokens, and nothing else.
(function () {
  const STORE_KEY = "adullumSession";
  const MOODS = ["grief", "joy", "waiting", "decision", "gratitude", "doubt", "peace", "longing"];

  const ICONS = {
    cave: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 20c0-8 4-14 9-14s9 6 9 14"/><path d="M9 20c0-3 1.3-5 3-5s3 2 3 5"/></svg>',
    bookmark: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3h12v18l-6-4-6 4z"/></svg>',
    graph: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="8" r="2.5"/><circle cx="10" cy="18" r="2.5"/><path d="M8.3 7l7.3.7M7 8.3l2.2 7.4M16.4 10l-4.8 6"/></svg>',
    ember: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2c1 4 6 6 6 12a6 6 0 0 1-12 0c0-3 2-5 3-6 0 2 1 3 2 3 0-4 1-6 1-9z"/></svg>',
    check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
  };

  // ---------------------------------------------------------------------
  // Session storage. Wrapped in try/catch because private windows and
  // blocked storage throw on access; the site still works signed out.
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
      /* storage unavailable: stays signed in for this tab only */
    }
    session = s;
  }
  let session = readSession();
  let profile = null;
  const listeners = [];

  function apiBase() {
    const el = document.getElementById("apiBase");
    return ((el && el.value) || location.origin).trim().replace(/\/$/, "");
  }

  let refreshing = null;
  async function freshToken() {
    if (!session) return null;
    const soon = Math.floor(Date.now() / 1000) + 60;
    if (session.expires_at && session.expires_at > soon) return session.access_token;
    // One refresh at a time, however many requests ask for a token at once.
    if (!refreshing) {
      refreshing = fetch(`${apiBase()}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: session.refresh_token }),
      })
        .then(async (r) => {
          if (!r.ok) throw new Error("expired");
          const body = await r.json();
          writeSession(body.session);
        })
        .catch(() => signOut({ quiet: true }))
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
    const resp = await fetch(`${apiBase()}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    let data = null;
    try {
      data = await resp.json();
    } catch {
      /* empty body */
    }
    if (resp.status === 401 && session) signOut({ quiet: true });
    if (!resp.ok) {
      const detail = data && data.detail;
      const msg = typeof detail === "string" ? detail : Array.isArray(detail) ? "Please check what you entered." : `Something went wrong (${resp.status}).`;
      throw new Error(msg);
    }
    return data;
  }

  function signedIn() {
    return !!session;
  }

  function setSession(s) {
    writeSession(s);
    profile = null;
    listeners.forEach((fn) => fn());
    refreshHeader();
    loadLanding();
  }

  function signOut({ quiet = false } = {}) {
    writeSession(null);
    profile = null;
    closeDrawer();
    refreshHeader();
    loadLanding();
    if (!quiet) toast("Signed out. The cave will be here when you come back.");
  }

  // Magic links land back here with the tokens in the URL fragment
  // (implicit flow, see app/auth.py). Read them once, then scrub the URL so
  // the tokens never sit in the address bar or the history.
  function consumeRedirect() {
    if (!location.hash || location.hash.length < 2) return;
    const params = new URLSearchParams(location.hash.slice(1));
    const clean = () => history.replaceState(null, "", location.pathname + location.search);
    if (params.get("access_token")) {
      const expiresIn = Number(params.get("expires_in") || 3600);
      writeSession({
        access_token: params.get("access_token"),
        refresh_token: params.get("refresh_token"),
        expires_at: Number(params.get("expires_at")) || Math.floor(Date.now() / 1000) + expiresIn,
        user: null,
      });
      clean();
      setTimeout(() => toast("Welcome in. Your cave is ready."), 300);
    } else if (params.get("error_description")) {
      clean();
      setTimeout(() => toast(params.get("error_description").replace(/\+/g, " ")), 300);
    }
  }

  // ---------------------------------------------------------------------
  // Small DOM helpers
  // ---------------------------------------------------------------------
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
    for (const c of [].concat(children)) if (c) node.append(c);
    return node;
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
    return "A while back";
  }

  let toastTimer = null;
  function toast(text) {
    let t = document.getElementById("caveToast");
    if (!t) {
      t = el("div", { id: "caveToast", role: "status", "aria-live": "polite" });
      Object.assign(t.style, {
        position: "fixed", left: "50%", top: "4.5rem", transform: "translateX(-50%)", zIndex: 40,
        background: "var(--text)", color: "var(--bg)", padding: "0.6rem 1rem", borderRadius: "999px",
        font: "500 0.86rem/1.3 var(--font)", boxShadow: "var(--shadow-lg)", maxWidth: "calc(100vw - 2rem)", textAlign: "center",
      });
      document.body.append(t);
    }
    t.textContent = text;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (t.hidden = true), 3200);
  }

  function overlay(content, { onClose } = {}) {
    const wrap = el("div", { class: "sheet-overlay" }, content);
    const close = () => {
      wrap.remove();
      document.removeEventListener("keydown", onKey);
      if (onClose) onClose();
    };
    const onKey = (e) => e.key === "Escape" && close();
    wrap.addEventListener("click", (e) => e.target === wrap && close());
    document.addEventListener("keydown", onKey);
    document.body.append(wrap);
    const first = wrap.querySelector("input, textarea, button.btn-primary");
    if (first) setTimeout(() => first.focus(), 50);
    return close;
  }

  // ---------------------------------------------------------------------
  // Header button
  // ---------------------------------------------------------------------
  let headerBtn = null;
  function mountHeader() {
    const actions = document.querySelector(".header-actions");
    if (!actions) return;
    const mapBtn = el("button", {
      class: "icon-btn", type: "button", title: "Explore how Scripture connects", "aria-label": "Open the knowledge graph",
      html: ICONS.graph, onclick: () => window.Graph && window.Graph.open([]),
    });
    headerBtn = el("button", { class: "cave-btn", type: "button", onclick: () => (signedIn() ? openDrawer() : openAuth()) });
    actions.prepend(headerBtn);
    actions.prepend(mapBtn);
    refreshHeader();
  }

  function initialOf(name) {
    return ((name || "").trim()[0] || "A").toUpperCase();
  }

  function refreshHeader() {
    if (!headerBtn) return;
    if (signedIn()) {
      const name = (profile && profile.display_name) || (session.user && session.user.email) || "";
      headerBtn.innerHTML = "";
      headerBtn.append(el("span", { class: "cave-glyph", text: initialOf(name) }), el("span", { class: "cave-label", text: "My Cave" }));
      headerBtn.title = "Open My Cave";
      headerBtn.setAttribute("aria-label", "Open My Cave");
    } else {
      headerBtn.innerHTML = "";
      headerBtn.append(el("span", { class: "cave-glyph", html: ICONS.cave }), el("span", { class: "cave-label", text: "Enter the cave" }));
      headerBtn.title = "Sign in to save your studies";
      headerBtn.setAttribute("aria-label", "Sign in");
    }
  }

  async function loadProfile() {
    if (!signedIn()) return null;
    try {
      const me = await api("/me");
      profile = me.profile;
      profile._counts = me.counts;
      if (session && !session.user) writeSession({ ...session, user: me.user });
      refreshHeader();
      return me;
    } catch (err) {
      return { error: err.message };
    }
  }

  // ---------------------------------------------------------------------
  // Sign-in sheet
  // ---------------------------------------------------------------------
  function openAuth(reason) {
    let mode = "link";
    const msg = el("p", { class: "sheet-msg" });
    const email = el("input", { type: "email", autocomplete: "email", placeholder: "you@example.com", required: true });
    const password = el("input", { type: "password", autocomplete: "current-password", placeholder: "At least 6 characters", minlength: "6" });
    const code = el("input", { inputmode: "numeric", autocomplete: "one-time-code", placeholder: "123456", maxlength: "10" });
    const passwordField = el("label", { class: "field", hidden: true }, ["Password", password]);
    const codeField = el("label", { class: "field", hidden: true }, ["Or type the code from the email", code]);
    const primary = el("button", { class: "btn-primary", type: "submit", text: "Email me a link" });
    const secondary = el("button", { class: "btn-ghost", type: "button", text: "Create account", hidden: true });
    const verifyBtn = el("button", { class: "btn-ghost", type: "button", text: "Use code", hidden: true });

    const tabLink = el("button", { class: "tab", type: "button", role: "tab", "aria-selected": "true", text: "Email link" });
    const tabPass = el("button", { class: "tab", type: "button", role: "tab", "aria-selected": "false", text: "Password" });
    function setMode(m) {
      mode = m;
      tabLink.setAttribute("aria-selected", String(m === "link"));
      tabPass.setAttribute("aria-selected", String(m === "password"));
      passwordField.hidden = m !== "password";
      secondary.hidden = m !== "password";
      primary.textContent = m === "password" ? "Sign in" : "Email me a link";
      codeField.hidden = true;
      verifyBtn.hidden = true;
      msg.textContent = "";
      msg.className = "sheet-msg";
    }
    tabLink.onclick = () => setMode("link");
    tabPass.onclick = () => setMode("password");

    const say = (text, isError) => {
      msg.textContent = text;
      msg.className = isError ? "sheet-msg error-msg" : "sheet-msg";
    };
    const busy = (on) => [primary, secondary, verifyBtn].forEach((b) => (b.disabled = on));

    async function run(fn) {
      busy(true);
      try {
        await fn();
      } catch (err) {
        say(err.message, true);
      } finally {
        busy(false);
      }
    }

    const form = el("form", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "authTitle" }, [
      el("h3", { id: "authTitle", text: "Enter the cave" }),
      el("p", {
        class: "sheet-lede",
        text: reason || "A place to keep your studies, write what they stir in you, and let Aquila remember where you have been together.",
      }),
      el("div", { class: "tabs", role: "tablist" }, [tabLink, tabPass]),
      el("label", { class: "field" }, ["Email", email]),
      passwordField,
      codeField,
      msg,
      el("div", { class: "sheet-actions" }, [secondary, verifyBtn, primary]),
    ]);

    const close = overlay(form);

    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const addr = email.value.trim();
      if (!addr) return say("Add your email first.", true);
      if (mode === "password") {
        run(async () => {
          const res = await api("/auth/signin", { method: "POST", body: { email: addr, password: password.value } });
          setSession(res.session);
          close();
          toast("Welcome back.");
        });
      } else {
        run(async () => {
          await api("/auth/magic-link", { method: "POST", body: { email: addr } });
          say("Check your inbox. The link brings you straight back here, signed in.");
          codeField.hidden = false;
          verifyBtn.hidden = false;
          primary.textContent = "Send again";
        });
      }
    });

    secondary.onclick = () =>
      run(async () => {
        const addr = email.value.trim();
        if (!addr || password.value.length < 6) return say("Add your email and a password of at least 6 characters.", true);
        const res = await api("/auth/signup", { method: "POST", body: { email: addr, password: password.value } });
        if (res.status === "confirm_email") {
          say("Almost there. Confirm your email from the message we just sent, then sign in.");
        } else {
          setSession(res.session);
          close();
          toast("Your cave is ready.");
        }
      });

    verifyBtn.onclick = () =>
      run(async () => {
        const res = await api("/auth/verify", { method: "POST", body: { email: email.value.trim(), code: code.value.trim() } });
        setSession(res.session);
        close();
        toast("Welcome in.");
      });
  }

  // ---------------------------------------------------------------------
  // Journal: save sheet
  // ---------------------------------------------------------------------
  function moodPicker(initial) {
    let selected = initial || null;
    const wrap = el("div", { class: "moods", role: "group", "aria-label": "What season are you in?" });
    for (const m of MOODS) {
      const b = el("button", { class: "mood", type: "button", "aria-pressed": String(m === selected), text: m });
      b.onclick = () => {
        selected = selected === m ? null : m;
        wrap.querySelectorAll(".mood").forEach((x) => x.setAttribute("aria-pressed", String(x.textContent === selected)));
      };
      wrap.append(b);
    }
    return { node: wrap, value: () => selected };
  }

  // `item` is either an answer ({question, answer, citations}) or a single
  // verse ({passage_ref, verse_text}).
  function openJournal(item, onSaved) {
    if (!signedIn()) {
      openAuth("Sign in to keep this in your journal. It only takes an email.");
      return;
    }
    const reflection = el("textarea", { placeholder: "What is this stirring in you? A sentence is plenty." });
    const tags = el("input", { placeholder: "small group, romans, prayer" });
    const moods = moodPicker(null);
    const msg = el("p", { class: "sheet-msg" });
    const save = el("button", { class: "btn-primary", type: "submit", text: "Keep it" });

    const preview = el("div", { class: "journal-preview" });
    if (item.passage_ref) {
      preview.append(el("strong", { text: item.passage_ref }), document.createTextNode(item.verse_text || ""));
    } else {
      preview.append(el("strong", { text: item.question || "" }), document.createTextNode((item.answer || "").replace(/^#+\s*/gm, "").slice(0, 400)));
    }

    const form = el("form", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "journalTitle" }, [
      el("h3", { id: "journalTitle", text: "Into the journal" }),
      el("p", { class: "sheet-lede", text: "Only you can read this. Aquila will remember it, gently, next time you talk." }),
      preview,
      el("label", { class: "field" }, ["Your reflection", reflection]),
      el("div", { class: "field", style: "margin-bottom:0" }, [el("span", { text: "The season you're in" })]),
      moods.node,
      el("label", { class: "field" }, ["Tags", tags]),
      msg,
      el("div", { class: "sheet-actions" }, [el("button", { class: "btn-ghost", type: "button", text: "Cancel", onclick: () => close() }), save]),
    ]);
    const close = overlay(form);

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      save.disabled = true;
      try {
        const app = window.AdullumApp;
        const firstCitation = (item.citations || [])[0];
        const entry = await api("/me/journal", {
          method: "POST",
          body: {
            question: item.question || null,
            answer: item.answer || null,
            passage_ref: item.passage_ref || (firstCitation ? `${firstCitation.book} ${firstCitation.chapter}:${firstCitation.verse}` : null),
            verse_text: item.verse_text || null,
            citations: item.citations || [],
            reflection: reflection.value.trim(),
            mood: moods.value(),
            tags: tags.value.split(",").map((t) => t.trim()).filter(Boolean),
            session_id: app && item.question ? app.getSessionId() : null,
          },
        });
        close();
        toast("Kept in your journal.");
        if (onSaved) onSaved(entry);
      } catch (err) {
        msg.textContent = err.message;
        msg.className = "sheet-msg error-msg";
        save.disabled = false;
      }
    });
  }

  // ---------------------------------------------------------------------
  // Under each answer: save + explore, and the "Aquila remembers" mark
  // ---------------------------------------------------------------------
  function decorateAnswer(bubble, data) {
    if (!bubble || bubble.querySelector(".answer-actions") || !data.answer) return;
    const row = el("div", { class: "answer-actions" });
    const saveBtn = el("button", { class: "chip-btn", type: "button", html: `${ICONS.bookmark}<span>Save to journal</span>` });
    saveBtn.onclick = () =>
      openJournal({ question: data.query, answer: data.answer, citations: data.citations }, () => {
        saveBtn.classList.add("is-done");
        saveBtn.innerHTML = `${ICONS.check}<span>In your journal</span>`;
      });
    row.append(saveBtn);
    if (data.citations && data.citations.length) {
      const refs = data.citations.slice(0, 4).map((c) => `${c.book} ${c.chapter}:${c.verse}`);
      row.append(
        el("button", {
          class: "chip-btn", type: "button", html: `${ICONS.graph}<span>Explore connections</span>`,
          onclick: () => window.Graph && window.Graph.open(refs),
        })
      );
    }
    bubble.append(row);
  }

  function markMemory(bubble) {
    if (!bubble || bubble.querySelector(".memory-mark")) return;
    const mark = el("div", {
      class: "memory-mark",
      title: "Aquila drew on what she remembers about you. See or change it in My Cave.",
      html: `${ICONS.ember}<span>Aquila remembers you</span>`,
    });
    const name = bubble.querySelector(".name");
    if (name) name.after(mark);
  }

  // ---------------------------------------------------------------------
  // Landing: welcome back, and one older journal entry to return to
  // ---------------------------------------------------------------------
  const defaultTagline = () => document.querySelector(".tagline");
  let originalTagline = null;

  async function loadLanding() {
    const tagline = defaultTagline();
    if (tagline && originalTagline === null) originalTagline = tagline.textContent;
    const old = document.getElementById("revisit");
    if (old) old.remove();
    if (!signedIn()) {
      if (tagline) tagline.textContent = originalTagline;
      return;
    }
    const me = await loadProfile();
    if (tagline && profile && profile.display_name) tagline.textContent = `Welcome back, ${profile.display_name}.`;
    if (!me || me.error) return;
    let entry = null;
    try {
      entry = (await api("/me/journal/revisit")).entry;
    } catch {
      return;
    }
    if (!entry || document.body.classList.contains("chatting")) return;
    const where = entry.passage_ref || entry.question || "a passage";
    const card = el("div", { class: "revisit", id: "revisit" }, [
      el("p", { class: "revisit-kicker", text: "From your journal" }),
      el("p", { class: "revisit-line", text: `${agoPhrase(entry.created_at)} you sat with ${where}${entry.mood ? `, in a season of ${entry.mood}` : ""}. How is that now?` }),
      entry.reflection ? el("p", { class: "revisit-quote", text: `"${entry.reflection.length > 180 ? entry.reflection.slice(0, 177) + "..." : entry.reflection}"` }) : null,
      el("div", { class: "revisit-actions" }, [
        el("button", {
          class: "chip-btn", type: "button", text: "Return to it",
          onclick: () => {
            const app = window.AdullumApp;
            if (app) app.submitQuery(`I'd like to come back to ${where}. Last time I wrote: "${(entry.reflection || "").slice(0, 300)}"`);
          },
        }),
        el("button", { class: "chip-btn", type: "button", text: "Open journal", onclick: () => openDrawer("journal") }),
      ]),
    ]);
    const heroBottom = document.getElementById("heroBottom");
    if (heroBottom) heroBottom.prepend(card);
  }

  // ---------------------------------------------------------------------
  // The drawer
  // ---------------------------------------------------------------------
  let drawerEls = null;

  function closeDrawer() {
    if (!drawerEls) return;
    drawerEls.overlay.remove();
    drawerEls.drawer.remove();
    document.removeEventListener("keydown", drawerEls.onKey);
    drawerEls = null;
  }

  async function openDrawer(tab = "journal") {
    if (!signedIn()) return openAuth();
    closeDrawer();
    const body = el("div", { class: "drawer-body" });
    const sub = el("p", { class: "drawer-sub", text: (session.user && session.user.email) || "" });
    const tabs = {};
    const tabBar = el("div", { class: "tabs", role: "tablist" });
    for (const [key, label] of [["journal", "Journal"], ["sessions", "Conversations"], ["memories", "Remembers"], ["plans", "Plans"]]) {
      tabs[key] = el("button", { class: "tab", type: "button", role: "tab", text: label, onclick: () => show(key) });
      tabBar.append(tabs[key]);
    }
    const memoryToggle = el("input", { type: "checkbox", checked: true });
    const foot = el("div", { class: "drawer-foot" }, [
      el("label", { class: "toggle", title: "When on, Aquila keeps short notes about you to make future studies more personal." }, [memoryToggle, "Let Aquila remember me"]),
      el("button", { class: "chip-btn danger", type: "button", text: "Sign out", onclick: () => signOut() }),
    ]);
    const drawer = el("aside", { class: "drawer", role: "dialog", "aria-modal": "true", "aria-label": "My Cave" }, [
      el("div", { class: "drawer-head" }, [
        el("div", { class: "drawer-title-row" }, [
          el("h2", { class: "drawer-title", text: "My Cave" }),
          el("button", {
            class: "icon-btn", type: "button", "aria-label": "Close",
            html: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
            onclick: closeDrawer,
          }),
        ]),
        sub,
        tabBar,
      ]),
      body,
      foot,
    ]);
    const ov = el("div", { class: "drawer-overlay", onclick: closeDrawer });
    const onKey = (e) => e.key === "Escape" && !document.querySelector(".sheet-overlay") && closeDrawer();
    document.addEventListener("keydown", onKey);
    document.body.append(ov, drawer);
    drawerEls = { overlay: ov, drawer, onKey };

    const me = await loadProfile();
    if (me && me.error) {
      body.innerHTML = "";
      body.append(el("div", { class: "empty" }, [el("strong", { text: "Your cave isn't open yet" }), me.error]));
      return;
    }
    if (profile) {
      sub.textContent = `${profile.display_name || ""}${session.user && session.user.email ? ` · ${session.user.email}` : ""}`;
      memoryToggle.checked = profile.memory_enabled !== false;
    }
    memoryToggle.onchange = async () => {
      try {
        profile = await api("/me", { method: "PATCH", body: { memory_enabled: memoryToggle.checked } });
        toast(memoryToggle.checked ? "Aquila will remember." : "Aquila won't keep new notes, or use old ones.");
      } catch (err) {
        memoryToggle.checked = !memoryToggle.checked;
        toast(err.message);
      }
    };

    async function show(key) {
      for (const [k, b] of Object.entries(tabs)) b.setAttribute("aria-selected", String(k === key));
      body.innerHTML = "";
      body.append(el("div", { class: "empty", text: "Gathering..." }));
      try {
        const render = { journal: renderJournal, sessions: renderSessions, memories: renderMemories, plans: renderPlans }[key];
        await render(body);
      } catch (err) {
        body.innerHTML = "";
        body.append(el("div", { class: "empty" }, [el("strong", { text: "Couldn't open this" }), err.message]));
      }
    }
    show(tab);
  }

  async function renderJournal(body, mood = null) {
    const entries = await api(`/me/journal${mood ? `?mood=${mood}` : ""}`);
    body.innerHTML = "";
    const filters = el("div", { class: "filter-row" });
    for (const m of [null, ...MOODS]) {
      filters.append(
        el("button", {
          class: "mood", type: "button", "aria-pressed": String(m === mood), text: m || "all",
          onclick: () => renderJournal(body, m),
        })
      );
    }
    body.append(filters);
    if (!entries.length) {
      body.append(
        el("div", { class: "empty" }, [
          el("strong", { text: mood ? `Nothing kept in a season of ${mood} yet` : "Your journal is waiting" }),
          'Ask Aquila something, then press "Save to journal" under her answer. Or tap a verse in the knowledge graph.',
        ])
      );
      return;
    }
    for (const e of entries) body.append(journalCard(e, body));
  }

  function journalCard(e, body) {
    const card = el("article", { class: "card" });
    const title = e.passage_ref || e.question || "A saved moment";
    const meta = el("div", { class: "card-meta" }, [el("span", { text: when(e.created_at) })]);
    if (e.mood) meta.append(el("span", { class: "badge warm", text: e.mood }));
    for (const t of e.tags || []) meta.append(el("span", { class: "tag", text: `#${t}` }));
    const reflection = el("p", { class: "card-text", text: e.reflection || "No reflection yet. Tap Edit to add one." });
    const actions = el("div", { class: "card-actions" });

    const editBtn = el("button", { class: "chip-btn", type: "button", text: "Edit" });
    editBtn.onclick = () => {
      const ta = el("textarea", {});
      ta.value = e.reflection || "";
      reflection.replaceWith(ta);
      ta.focus();
      editBtn.textContent = "Save";
      editBtn.onclick = async () => {
        try {
          const updated = await api(`/me/journal/${e.id}`, { method: "PATCH", body: { reflection: ta.value.trim() } });
          card.replaceWith(journalCard(updated, body));
        } catch (err) {
          toast(err.message);
        }
      };
    };
    actions.append(editBtn);

    const refs = (e.citations || []).map((c) => `${c.book} ${c.chapter}:${c.verse}`);
    if (!refs.length && e.passage_ref) refs.push(e.passage_ref);
    if (refs.length) {
      actions.append(
        el("button", { class: "chip-btn", type: "button", html: `${ICONS.graph}<span>Explore</span>`, onclick: () => { closeDrawer(); window.Graph.open(refs.slice(0, 4)); } })
      );
    }
    if (e.question) {
      actions.append(
        el("button", {
          class: "chip-btn", type: "button", text: "Ask again",
          onclick: () => { closeDrawer(); window.AdullumApp.submitQuery(e.question); },
        })
      );
    }
    actions.append(
      el("button", {
        class: "chip-btn danger", type: "button", text: "Delete",
        onclick: async () => {
          if (!confirm("Delete this journal entry? This can't be undone.")) return;
          try {
            await api(`/me/journal/${e.id}`, { method: "DELETE" });
            card.remove();
          } catch (err) {
            toast(err.message);
          }
        },
      })
    );

    card.append(meta, el("h3", { class: "card-title", text: title }));
    if (e.verse_text) card.append(el("p", { class: "card-text verse", text: e.verse_text }));
    card.append(reflection, actions);
    return card;
  }

  async function renderSessions(body) {
    const rows = await api("/me/sessions");
    body.innerHTML = "";
    if (!rows.length) {
      body.append(el("div", { class: "empty" }, [el("strong", { text: "No conversations kept yet" }), "Everything you ask while signed in is kept here, so you can pick a study back up."]));
      return;
    }
    for (const s of rows) {
      const row = el("div", { class: "list-row", role: "button", tabindex: "0" }, [
        el("span", { class: "grow" }, [document.createTextNode(s.title || "Untitled"), el("span", { class: "when", text: when(s.updated_at || s.created_at) })]),
      ]);
      const del = el("button", {
        class: "chip-btn danger row-x", type: "button", text: "Delete",
        onclick: async (ev) => {
          ev.stopPropagation();
          if (!confirm("Delete this conversation?")) return;
          try {
            await api(`/me/sessions/${s.id}`, { method: "DELETE" });
            row.remove();
          } catch (err) {
            toast(err.message);
          }
        },
      });
      row.append(del);
      const open = async () => {
        try {
          const full = await api(`/me/sessions/${s.id}`);
          closeDrawer();
          window.AdullumApp.loadConversation(s.id, full.messages);
        } catch (err) {
          toast(err.message);
        }
      };
      row.addEventListener("click", open);
      row.addEventListener("keydown", (ev) => (ev.key === "Enter" || ev.key === " ") && (ev.preventDefault(), open()));
      body.append(row);
    }
  }

  async function renderMemories(body) {
    const rows = await api("/me/memories");
    body.innerHTML = "";
    body.append(
      el("p", {
        class: "note-hint",
        text: "These are the notes Aquila keeps so she can know you over time. Only you can see them, they are never treated as Scripture, and you can let any of them go.",
      })
    );
    if (!rows.length) {
      body.append(el("div", { class: "empty" }, [el("strong", { text: "Nothing remembered yet" }), "As you share what you're studying or walking through, Aquila will keep a few quiet notes here."]));
      return;
    }
    for (const m of rows) {
      const card = el("div", { class: "card" }, [
        el("div", { class: "card-meta" }, [el("span", { text: when(m.created_at) }), el("span", { class: m.kind === "journal" ? "badge warm" : "badge", text: m.kind === "journal" ? "from journal" : "noticed" })]),
        el("p", { class: "card-text", text: m.content }),
      ]);
      card.append(
        el("div", { class: "card-actions" }, [
          el("button", {
            class: "chip-btn danger", type: "button", text: "Forget this",
            onclick: async () => {
              try {
                await api(`/me/memories/${m.id}`, { method: "DELETE" });
                card.remove();
              } catch (err) {
                toast(err.message);
              }
            },
          }),
        ])
      );
      body.append(card);
    }
    body.append(
      el("div", { class: "card-actions", style: "justify-content:center;margin-top:1rem" }, [
        el("button", {
          class: "chip-btn danger", type: "button", text: "Forget everything",
          onclick: async () => {
            if (!confirm("Let Aquila forget everything she has noted about you? Your journal stays.")) return;
            try {
              await api("/me/memories", { method: "DELETE" });
              renderMemories(body);
            } catch (err) {
              toast(err.message);
            }
          },
        }),
      ])
    );
  }

  async function renderPlans(body) {
    const rows = await api("/me/plans");
    body.innerHTML = "";
    if (!rows.length) {
      body.append(el("div", { class: "empty" }, [el("strong", { text: "No reading plans yet" }), "Reading plans you build while signed in are kept here, ready to download again."]));
      return;
    }
    for (const p of rows) {
      body.append(
        el("div", { class: "card" }, [
          el("div", { class: "card-meta" }, [el("span", { text: `Starts ${new Date(p.start_date + "T00:00:00").toLocaleDateString()}` }), el("span", { class: "badge", text: p.translation })]),
          el("h3", { class: "card-title", text: `Through the whole Bible in ${p.days} days` }),
          el("div", { class: "card-actions" }, [el("a", { class: "chip-btn", href: `${apiBase()}/plan/${p.id}/pdf`, text: "Download PDF" })]),
        ])
      );
    }
  }

  // ---------------------------------------------------------------------
  window.Cave = {
    authHeaders,
    api,
    signedIn,
    openAuth,
    openDrawer,
    openJournal,
    decorateAnswer,
    markMemory,
    toast,
    onChange: (fn) => listeners.push(fn),
  };

  consumeRedirect();
  document.addEventListener("DOMContentLoaded", () => {
    mountHeader();
    loadLanding();
  });
})();
