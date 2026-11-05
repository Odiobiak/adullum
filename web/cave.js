// Everything personal: sign-in, the home screen, My Cave, the journal, the
// signed-out page, themes, and the extras under each of Aquila's answers.
//
// Loaded before index.html's main script, so it only defines things here and
// reaches back into that script (window.AdullumApp) at call time. All talk with
// Supabase goes through our own API (see app/auth.py): this file holds the
// person's tokens and nothing else.
(function () {
  const STORE_KEY = "adullumSession";
  const MOODS = ["grief", "joy", "waiting", "decision", "gratitude", "doubt", "peace", "longing"];
  const THEME_NAMES = { dawn: "Dawn", olive: "Olive Grove", twilight: "Twilight", hearth: "Hearth" };

  const ICON = {
    bookmark: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 3h12v18l-6-4-6 4z"/></svg>',
    graph: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="8" r="2.5"/><circle cx="10" cy="18" r="2.5"/><path d="M8.3 7l7.3.7M7 8.3l2.2 7.4M16.4 10l-4.8 6"/></svg>',
    speaker: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 5L6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"/></svg>',
    image: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="3"/><path d="M3 15l5-5 4 4 3-3 6 6"/></svg>',
    check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
    ember: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2c1 4 6 6 6 12a6 6 0 0 1-12 0c0-3 2-5 3-6 0 2 1 3 2 3 0-4 1-6 1-9z"/></svg>',
  };

  // ---------------------------------------------------------------------
  // Small helpers
  // ---------------------------------------------------------------------
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const app = () => window.AdullumApp;

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
    for (const c of [].concat(children)) if (c !== null && c !== undefined && c !== false) node.append(c);
    return node;
  }

  function apiBase() {
    const input = $("#apiBase");
    return ((input && input.value) || location.origin).trim().replace(/\/$/, "");
  }
  function translation() {
    const input = $("#translation");
    return (input && input.value.trim()) || "BSB";
  }
  function localToday() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
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
  function partOfDay() {
    const h = new Date().getHours();
    return h < 12 ? "morning" : h < 17 ? "afternoon" : "evening";
  }

  let toastTimer = null;
  function toast(text) {
    let t = $("#toast");
    if (!t) {
      t = el("div", { id: "toast", class: "toast", role: "status", "aria-live": "polite" });
      document.body.append(t);
    }
    t.textContent = text;
    t.hidden = false;
    t.style.animation = "none";
    void t.offsetWidth;
    t.style.animation = "";
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (t.hidden = true), 3400);
  }

  function overlay(content) {
    const wrap = el("div", { class: "sheet-overlay" }, content);
    const close = () => {
      wrap.remove();
      document.removeEventListener("keydown", onKey);
    };
    const onKey = (e) => e.key === "Escape" && close();
    wrap.addEventListener("click", (e) => e.target === wrap && close());
    document.addEventListener("keydown", onKey);
    document.body.append(wrap);
    const first = wrap.querySelector("textarea, input");
    if (first) setTimeout(() => first.focus(), 50);
    return close;
  }

  // ---------------------------------------------------------------------
  // Themes. index.html's early script applies the saved one before paint;
  // this keeps the pickers and the saved choice in step.
  // ---------------------------------------------------------------------
  function setTheme(t) {
    if (!THEME_NAMES[t]) t = "dawn";
    document.documentElement.dataset.theme = t;
    $$("[data-set-theme]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.setTheme === t)));
    $$("[data-theme-name]").forEach((n) => (n.textContent = THEME_NAMES[t]));
    try {
      localStorage.setItem("adullumTheme", t);
    } catch {
      /* private window: the theme lasts for this visit */
    }
  }
  document.addEventListener(
    "click",
    (e) => {
      const sw = e.target.closest("[data-set-theme]");
      if (!sw) return;
      e.stopPropagation();
      setTheme(sw.dataset.setTheme);
    },
    true
  );

  // ---------------------------------------------------------------------
  // Session. Wrapped in try/catch because private windows and blocked
  // storage throw on access; the site still works signed out.
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
      /* storage unavailable: signed in for this tab only */
    }
    session = s;
  }
  let session = readSession();
  let profile = null;
  const signedIn = () => !!session;

  let refreshing = null;
  async function freshToken() {
    if (!session) return null;
    const soon = Math.floor(Date.now() / 1000) + 60;
    if (session.expires_at && session.expires_at > soon) return session.access_token;
    // One refresh at a time, however many requests want a token at once.
    if (!refreshing) {
      refreshing = fetch(`${apiBase()}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: session.refresh_token }),
      })
        .then(async (r) => {
          if (!r.ok) throw new Error("expired");
          writeSession((await r.json()).session);
        })
        .catch(() => endSession())
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
    const resp = await fetch(`${apiBase()}${path}`, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
    let data = null;
    try {
      data = await resp.json();
    } catch {
      /* empty body */
    }
    if (resp.status === 401 && session) endSession();
    if (!resp.ok) {
      const detail = data && data.detail;
      throw new Error(typeof detail === "string" ? detail : Array.isArray(detail) ? "Please check what you entered." : `Something went wrong (${resp.status}).`);
    }
    return data;
  }

  // A session that expired or was revoked: drop it quietly and redraw as a guest.
  function endSession() {
    writeSession(null);
    profile = null;
    updateChrome();
    if (app()) app().render();
  }

  async function startSession(s, { welcome } = {}) {
    writeSession(s);
    await loadProfile();
    if (welcome) toast(welcome);
    app().go("home");
  }

  function signOut() {
    lastName = (profile && profile.display_name) || "";
    writeSession(null);
    profile = null;
    updateChrome();
    app().go("signedout");
  }
  let lastName = "";

  // Magic links and Google land back here with tokens in the URL fragment
  // (implicit flow, see app/auth.py). Read them once, then scrub the URL so
  // the tokens never sit in the address bar or history.
  function consumeRedirect() {
    if (!location.hash || location.hash.length < 2) return;
    const params = new URLSearchParams(location.hash.slice(1));
    if (params.get("access_token")) {
      const expiresIn = Number(params.get("expires_in") || 3600);
      writeSession({
        access_token: params.get("access_token"),
        refresh_token: params.get("refresh_token"),
        expires_at: Number(params.get("expires_at")) || Math.floor(Date.now() / 1000) + expiresIn,
        user: null,
      });
      history.replaceState(null, "", location.pathname + location.search + "#home");
      setTimeout(() => toast("Welcome in. Your cave is ready."), 300);
    } else if (params.get("error_description")) {
      history.replaceState(null, "", location.pathname + location.search + "#signin");
      setTimeout(() => toast(params.get("error_description").replace(/\+/g, " ")), 300);
    }
  }

  async function loadProfile() {
    if (!signedIn()) return null;
    try {
      const me = await api("/me");
      profile = { ...me.profile, email: me.user.email };
      if (session && !session.user) writeSession({ ...session, user: me.user });
    } catch {
      /* the header falls back to the email initial */
    }
    updateChrome();
    return profile;
  }

  function displayName() {
    return (profile && profile.display_name) || "";
  }

  function updateChrome(embers) {
    const name = displayName();
    const email = (profile && profile.email) || (session && session.user && session.user.email) || "";
    const me = $("#meBtn");
    if (me) me.textContent = ((name || email || "A").trim()[0] || "A").toUpperCase();
    if ($("#menuName")) $("#menuName").textContent = name || "Friend";
    if ($("#menuEmail")) $("#menuEmail").textContent = email;
    if (embers !== undefined) {
      const pill = $("#streakPill");
      if (embers && embers.streak > 0) {
        $("#streakCount").textContent = embers.streak;
        pill.title = `${embers.streak} ${embers.streak === 1 ? "day" : "days"} in a row`;
        pill.hidden = false;
      } else {
        pill.hidden = true;
      }
    }
  }

  // ---------------------------------------------------------------------
  // Sign in / join
  // ---------------------------------------------------------------------
  let authMode = "signin";
  let authMethod = "link";
  let providersLoaded = false;

  function renderAuth() {
    const join = authMode === "join";
    $("#authForm").hidden = authMode === "sent";
    $("#authSent").hidden = authMode !== "sent";
    $("#authHeading").textContent = join ? "Make your cave" : "Welcome back";
    $("#authSub").textContent = join
      ? "A private place for your studies, your journal, and a companion who remembers."
      : "Your journal, your conversations, and Aquila are right where you left them.";
    $("#nameRow").hidden = !join;
    $("#pwRow").hidden = authMethod !== "password";
    $("#authPassword").autocomplete = join ? "new-password" : "current-password";
    $$("[data-method]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.method === authMethod)));
    $("#authPrimary").textContent = authMethod === "link" ? "Email me a sign-in link" : join ? "Create my cave" : "Sign in";
    $("#switchPrompt").textContent = join ? "Already have a cave?" : "New here?";
    $("#switchMode").textContent = join ? "Sign in" : "Create one";
  }
  function say(id, text, bad) {
    const m = $(id);
    m.textContent = text || "";
    m.classList.toggle("bad", !!bad);
  }

  function wireAuth() {
    $$("[data-method]").forEach((b) =>
      b.addEventListener("click", () => {
        authMethod = b.dataset.method;
        say("#authMsg", "");
        renderAuth();
      })
    );
    $("#switchMode").addEventListener("click", () => app().go(authMode === "join" ? "signin" : "join"));
    $("#diffEmail").addEventListener("click", () => {
      authMode = "signin";
      renderAuth();
      $("#authEmail").focus();
    });

    const busy = (on) => ($("#authPrimary").disabled = on);
    async function sendLink() {
      const email = $("#authEmail").value.trim();
      await api("/auth/magic-link", { method: "POST", body: { email, display_name: $("#authName").value.trim() || null } });
      $("#sentTo").textContent = email;
      authMode = "sent";
      renderAuth();
    }

    $("#authForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const email = $("#authEmail").value.trim();
      const password = $("#authPassword").value;
      if (!email) return say("#authMsg", "Add your email first.", true);
      if (authMethod === "password" && password.length < 6) return say("#authMsg", "Passwords need at least 6 characters.", true);
      say("#authMsg", "");
      busy(true);
      try {
        if (authMethod === "link") {
          await sendLink();
        } else if (authMode === "join") {
          const res = await api("/auth/signup", { method: "POST", body: { email, password, display_name: $("#authName").value.trim() || null } });
          if (res.status === "confirm_email") say("#authMsg", "Almost there. Confirm your email from the message we just sent, then sign in.");
          else await startSession(res.session, { welcome: "Your cave is ready." });
        } else {
          const res = await api("/auth/signin", { method: "POST", body: { email, password } });
          await startSession(res.session, { welcome: "Welcome back." });
        }
      } catch (err) {
        say("#authMsg", err.message, true);
      } finally {
        busy(false);
      }
    });

    $("#sendAgain").addEventListener("click", async () => {
      try {
        await sendLink();
        toast("Sent again. Give it a minute.");
      } catch (err) {
        toast(err.message);
      }
    });

    $("#codeForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        const res = await api("/auth/verify", { method: "POST", body: { email: $("#sentTo").textContent, code: $("#authCode").value.trim() } });
        await startSession(res.session, { welcome: "Welcome in." });
      } catch (err) {
        say("#codeMsg", err.message, true);
      }
    });
  }

  async function showSignin(route) {
    authMode = route === "join" ? "join" : "signin";
    say("#authMsg", "");
    renderAuth();
    if (!providersLoaded) {
      providersLoaded = true;
      try {
        const p = await (await fetch(`${apiBase()}/auth/providers`)).json();
        $("#googleBlock").hidden = !p.google;
      } catch {
        /* no Google button, email still works */
      }
    }
  }

  // ---------------------------------------------------------------------
  // Verses fetched for display (always the real text of the translation)
  // ---------------------------------------------------------------------
  let votd = null;
  async function verseOfTheDay() {
    if (votd && votd.today === localToday()) return votd;
    const res = await fetch(`${apiBase()}/verse-of-the-day?today=${localToday()}&translation=${encodeURIComponent(translation())}`);
    if (!res.ok) throw new Error("no verse");
    votd = { ...(await res.json()), today: localToday() };
    return votd;
  }
  async function verseText(ref) {
    const res = await fetch(`${apiBase()}/verse?ref=${encodeURIComponent(ref)}&translation=${encodeURIComponent(translation())}`);
    if (!res.ok) throw new Error("not found");
    const data = await res.json();
    return { ref, text: data.verses.map((v) => v.text).join(" "), translation: data.translation };
  }

  async function showWelcome() {
    try {
      const v = await verseOfTheDay();
      $("[data-votd-text]").textContent = `"${v.text}"`;
      $("[data-votd-ref]").textContent = `${v.ref} · ${v.translation}`;
      $("[data-votd-reflect]").onclick = () => app().submitQuery(`Help me reflect on ${v.ref}.`);
      $("[data-votd-map]").onclick = () => window.Graph.open([`${v.book} ${v.chapter}:${v.verse}`]);
    } catch {
      $("#today").hidden = true;
    }
    const preview = $("#previewPassage");
    if (preview && !preview.textContent) {
      try {
        preview.textContent = `"${(await verseText("Romans 5:3-4")).text}"`;
      } catch {
        /* the example still reads without its quote */
      }
    }
  }

  // ---------------------------------------------------------------------
  // Home
  // ---------------------------------------------------------------------
  function card(kicker, { warm, ember } = {}, body = []) {
    return el("section", { class: `card fade-in${warm ? " warm" : ""}` }, [
      typeof kicker === "string" ? el("h2", { class: `kicker${ember ? " ember" : ""}`, text: kicker }) : kicker,
      ...body,
    ]);
  }

  async function openSession(id, then) {
    try {
      const full = await api(`/me/sessions/${id}`);
      app().loadConversation(id, full.messages);
      if (then) setTimeout(() => app().submitQuery(then), 150);
    } catch (err) {
      toast(err.message);
    }
  }

  function planCard(plan, rerender) {
    if (!plan) {
      return card("Read through the Bible", {}, [
        el("p", { class: "muted", style: "margin:0 0 18px", text: "A chapter or so a day, Genesis to Revelation. Aquila keeps your place and lets you know what's next." }),
        el("button", {
          class: "btn btn-ember btn-sm", type: "button", text: "Start a one-year plan",
          onclick: async (e) => {
            e.target.disabled = true;
            try {
              await api("/plan", { method: "POST", body: { start_date: localToday(), days: 365, translation: translation() } });
              toast("Your plan starts today.");
              rerender();
            } catch (err) {
              e.target.disabled = false;
              toast(err.message);
            }
          },
        }),
      ]);
    }
    const bar = el("span", { style: `width:${Math.max(plan.progress_pct, 1)}%` });
    const doneBtn = el("button", { class: `btn btn-sm ${plan.done_today ? "act is-done" : "btn-ember"}`, type: "button" });
    const paint = (p) => {
      doneBtn.className = `btn btn-sm ${p.done_today ? "act is-done" : "btn-ember"}`;
      doneBtn.innerHTML = `${ICON.check}<span>${p.done_today ? "Read today" : "Mark as read"}</span>`;
      bar.style.width = `${Math.max(p.progress_pct, 1)}%`;
    };
    paint(plan);
    doneBtn.addEventListener("click", async () => {
      const next = !plan.done_today;
      try {
        plan = await api(`/me/plans/${plan.id}/progress`, { method: "POST", body: { day: plan.day, done: next, today: localToday() } });
        paint(plan);
        if (next) toast(`Day ${plan.day} read. ${plan.completed} of ${plan.days} done.`);
      } catch (err) {
        toast(err.message);
      }
    });
    return card(
      el("div", { class: "row-between" }, [
        el("h2", { class: "kicker", text: "Today in your plan" }),
        el("span", { class: "faint", style: "font-size:14px", text: `Through the Bible in ${plan.days} days · Day ${plan.day}` }),
      ]),
      {},
      [
        el("div", { class: "bar", role: "progressbar", "aria-label": "Plan progress", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(plan.progress_pct) }, bar),
        el("div", { class: "row-between", style: "margin:0" }, [
          el("div", { class: "row", style: "gap:8px" }, plan.refs.map((r) =>
            el("button", { class: "chapter", type: "button", text: r, title: `Read ${r} with Aquila`, onclick: () => app().submitQuery(`Walk me through ${r}.`) })
          )),
          doneBtn,
        ]),
      ]
    );
  }

  async function showHome() {
    const name = displayName();
    $("#greet").textContent = `Good ${partOfDay()}${name ? `, ${name}` : ""}.`;
    $("#dayLine").textContent = `${new Date().toLocaleDateString(undefined, { weekday: "long" })} ${partOfDay()}`;
    $("#homeQuery").placeholder = `What are you carrying this ${partOfDay()}?`;
    const main = $("#homeMain");
    const side = $("#homeSide");
    if (!main.children.length) main.append(el("div", { class: "empty", text: "Gathering your cave..." }));

    let data;
    try {
      data = await api(`/me/home?today=${localToday()}`);
    } catch (err) {
      main.replaceChildren(el("div", { class: "empty" }, [el("strong", { text: "Your cave isn't open yet" }), err.message]));
      return;
    }
    if (data.profile && data.profile.display_name && profile) profile.display_name = data.profile.display_name;
    const nm = displayName();
    $("#greet").textContent = `Good ${partOfDay()}${nm ? `, ${nm}` : ""}.`;
    updateChrome(data.embers);

    const e = data.embers;
    $("#streakLine").textContent = !e
      ? ""
      : e.streak > 1
        ? `${e.streak} days in a row. The fire is warm.`
        : e.streak === 1
          ? "Your first ember is lit. Come back tomorrow and keep it going."
          : "";
    $("#streakLine").hidden = !$("#streakLine").textContent;

    // Main column
    const mainCards = [];
    const s = data.last_session;
    if (s) {
      mainCards.push(
        card(
          el("div", { class: "row-between" }, [
            el("h2", { class: "kicker", text: "Pick up where you left off" }),
            el("span", { class: "faint", style: "font-size:14px", text: when(s.updated_at) }),
          ]),
          {},
          [
            el("p", { class: "big-q", text: s.title || "Your last conversation" }),
            s.refs.length ? el("p", { class: "muted", style: "margin:0 0 20px", text: `You were sitting with ${s.refs.join(", ")}.` }) : el("div", { style: "height:12px" }),
            el("div", { class: "row" }, [
              el("button", { class: "btn btn-ember btn-sm", type: "button", text: "Continue with Aquila", onclick: () => openSession(s.id) }),
              s.followup ? el("button", { class: "btn btn-ghost btn-sm btn-wrap", type: "button", text: s.followup, onclick: () => openSession(s.id, s.followup) }) : null,
            ]),
          ]
        )
      );
    } else {
      mainCards.push(
        card("Your first conversation", {}, [
          el("p", { class: "muted", style: "margin:0 0 18px", text: "Ask about a passage, a hard question, or the season you're in. Everything you ask is kept here so you can pick it back up." }),
          el("a", { class: "btn btn-ember btn-sm", href: "#ask", text: "Ask Aquila" }),
        ])
      );
    }
    mainCards.push(planCard(data.plan, showHome));
    const r = data.revisit;
    if (r) {
      const where = r.passage_ref || r.question || "a passage";
      mainCards.push(
        card(`From your journal, ${agoPhrase(r.created_at).toLowerCase()}`, { ember: true }, [
          el("p", { style: "font-size:19px;margin:0 0 8px" }, ["You sat with ", el("strong", { text: where }), r.mood ? ` in a season of ${r.mood}, and wrote:` : ", and wrote:"]),
          el("p", { style: "font-size:18px;color:var(--soft);font-style:italic;margin:0 0 18px", text: `"${r.reflection.length > 220 ? r.reflection.slice(0, 217) + "..." : r.reflection}"` }),
          el("p", { class: "muted", style: "margin:0 0 14px", text: "How is that now?" }),
          el("div", { class: "row" }, [
            el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Return to it with Aquila", onclick: () => app().submitQuery(`I'd like to come back to ${where}. Last time I wrote: "${r.reflection.slice(0, 300)}"`) }),
            el("a", { class: "btn btn-ghost btn-sm", href: "#cave", text: "Open my journal" }),
          ]),
        ])
      );
    }
    main.replaceChildren(...mainCards);

    // Side column
    const sideCards = [];
    if (e) {
      sideCards.push(
        card("Your embers this week", {}, [
          el("p", { class: "faint", style: "margin:-6px 0 18px;font-size:15px", text: "One for every day you come in." }),
          el("div", { class: "week" }, e.week.map((d) =>
            el("div", {}, [
              el("div", { class: `day-dot${d.lit ? " lit" : ""}`, html: ICON.ember, title: d.lit ? "You came in" : "" }),
              el("span", { class: `day-label${d.today ? " today" : ""}`, text: d.label }),
            ])
          )),
        ])
      );
    }
    try {
      const v = await verseOfTheDay();
      sideCards.push(
        card("Verse for today", { warm: true, ember: true }, [
          el("p", { style: "font:600 21px/1.4 var(--display);margin:0 0 10px", text: `"${v.text}"` }),
          el("p", { class: "verse-ref", style: "margin:0 0 18px", text: `${v.ref} · ${v.translation}` }),
          el("div", { class: "row", style: "gap:8px" }, [
            el("button", { class: "act", type: "button", html: `${ICON.bookmark}<span>Keep it</span>`, onclick: () => openJournal({ passage_ref: v.ref, verse_text: v.text }) }),
            el("button", { class: "act", type: "button", html: `${ICON.graph}<span>Connections</span>`, onclick: () => window.Graph.open([`${v.book} ${v.chapter}:${v.verse}`]) }),
            el("button", { class: "act", type: "button", html: `${ICON.image}<span>Share</span>`, onclick: () => shareCard(v) }),
          ]),
        ])
      );
    } catch {
      /* no verse card today */
    }
    if (data.memories && data.memories.length) {
      sideCards.push(
        card(
          el("div", { class: "row-between", style: "margin-bottom:12px" }, [
            el("h2", { class: "kicker", text: "Aquila remembers" }),
            el("a", { href: "#remembers", style: "font-size:14px;font-weight:600;text-decoration:none", text: "Manage" }),
          ]),
          {},
          [el("ul", { class: "remember" }, data.memories.map((m) => el("li", { text: m.replace(/^They /, "You ").replace(/^They're /, "You're ") })))]
        )
      );
    }
    side.replaceChildren(...sideCards);
  }

  // ---------------------------------------------------------------------
  // The Ask Aquila rail: past conversations, current one highlighted
  // ---------------------------------------------------------------------
  let railTimer = null;
  function refreshRail() {
    if (!signedIn()) return;
    clearTimeout(railTimer);
    // The conversation is saved just after the answer finishes streaming, so a
    // brand new one appears in the list a moment later.
    railTimer = setTimeout(async () => {
      const list = $("#railList");
      if (!list) return;
      try {
        const rows = await api("/me/sessions");
        const current = app() && app().getSessionId();
        list.replaceChildren(
          ...(rows.length
            ? rows.slice(0, 30).map((s) =>
                el("button", { class: "rail-item", type: "button", "aria-current": String(s.id === current), onclick: () => openSession(s.id) }, [
                  el("span", { text: s.title || "Untitled" }),
                  el("small", { text: when(s.updated_at || s.created_at) }),
                ])
              )
            : [el("p", { class: "faint", style: "padding:8px 14px;font-size:14px", text: "Your conversations will appear here." })])
        );
      } catch {
        /* the rail is a convenience */
      }
    }, 1200);
  }

  // ---------------------------------------------------------------------
  // Journal sheet: save an answer, a verse, or a free-written entry
  // ---------------------------------------------------------------------
  function moodPicker() {
    let selected = null;
    const wrap = el("div", { class: "moods", role: "group", "aria-label": "The season you're in", style: "margin:8px 0 16px" });
    for (const m of MOODS) {
      const b = el("button", { class: "mood", type: "button", "aria-pressed": "false", text: m });
      b.onclick = () => {
        selected = selected === m ? null : m;
        $$(".mood", wrap).forEach((x) => x.setAttribute("aria-pressed", String(x.textContent === selected)));
      };
      wrap.append(b);
    }
    return { node: wrap, value: () => selected };
  }

  function openJournal(item = {}, onSaved) {
    if (!signedIn()) {
      toast("Sign in to keep this in your journal.");
      app().go("join");
      return;
    }
    const reflection = el("textarea", { id: "journalReflection", placeholder: "What is this stirring in you? A sentence is plenty." });
    const passage = el("input", { id: "journalPassage", placeholder: "Psalm 23, or leave blank" });
    const tags = el("input", { id: "journalTags", placeholder: "prayer, small group" });
    const moods = moodPicker();
    const msg = el("p", { class: "form-msg", role: "alert" });
    const save = el("button", { class: "btn btn-ember btn-sm", type: "submit", text: "Keep it" });
    const freeWrite = !item.passage_ref && !item.question;

    const preview = freeWrite
      ? el("label", { class: "field-wrap" }, ["Passage (optional)", passage])
      : el("div", { class: "journal-preview" }, item.passage_ref
          ? [el("strong", { text: item.passage_ref }), document.createTextNode(item.verse_text || "")]
          : [el("strong", { text: item.question || "" }), document.createTextNode((item.answer || "").replace(/^#+\s*/gm, "").slice(0, 400))]);

    const formEl = el("form", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "journalTitle" }, [
      el("h3", { id: "journalTitle", text: freeWrite ? "Write in your journal" : "Into the journal" }),
      el("p", { class: "sheet-lede", text: "Only you can read this. Aquila will remember it, gently, next time you talk." }),
      preview,
      el("label", { class: "field-wrap" }, ["Your reflection", reflection]),
      el("span", { class: "field-label" }, "The season you're in"),
      moods.node,
      el("label", { class: "field-wrap" }, ["Tags", tags]),
      msg,
      el("div", { class: "sheet-actions" }, [el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Cancel", onclick: () => close() }), save]),
    ]);
    const close = overlay(formEl);

    formEl.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (freeWrite && !reflection.value.trim()) {
        msg.textContent = "Write a line or two first.";
        msg.classList.add("bad");
        return;
      }
      save.disabled = true;
      try {
        const first = (item.citations || [])[0];
        const entry = await api("/me/journal", {
          method: "POST",
          body: {
            question: item.question || null,
            answer: item.answer || null,
            passage_ref: item.passage_ref || passage.value.trim() || (first ? `${first.book} ${first.chapter}:${first.verse}` : null),
            verse_text: item.verse_text || null,
            citations: item.citations || [],
            reflection: reflection.value.trim(),
            mood: moods.value(),
            tags: tags.value.split(",").map((t) => t.trim()).filter(Boolean),
            session_id: item.question ? app().getSessionId() : null,
          },
        });
        close();
        toast("Kept in your journal.");
        if (onSaved) onSaved(entry);
      } catch (err) {
        msg.textContent = err.message;
        msg.classList.add("bad");
        save.disabled = false;
      }
    });
  }

  // ---------------------------------------------------------------------
  // Under each answer
  // ---------------------------------------------------------------------
  function plainAnswer(text) {
    return text.replace(/^#{1,6}\s*(.+)$/gm, "$1.").replace(/\*\*(.+?)\*\*/g, "$1");
  }

  let speaking = null;
  function listen(btn, text) {
    if (!("speechSynthesis" in window)) return toast("Your browser can't read aloud.");
    if (speaking === btn) {
      speechSynthesis.cancel();
      return;
    }
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(plainAnswer(text));
    u.rate = 0.97;
    const label = btn.querySelector("span");
    u.onend = u.onerror = () => {
      if (speaking === btn) speaking = null;
      label.textContent = "Listen";
    };
    speaking = btn;
    label.textContent = "Stop";
    speechSynthesis.speak(u);
  }

  async function connectionsFor(msg, ref) {
    try {
      const params = new URLSearchParams({ refs: ref, translation: translation(), k: "3" });
      const res = await fetch(`${apiBase()}/connections?${params}`);
      if (!res.ok) return;
      const data = await res.json();
      const near = data.edges.sort((a, b) => b.weight - a.weight).slice(0, 3).map((e) => (e.source === ref ? e.target : e.source));
      if (!near.length) return;
      msg.querySelector(".answer-actions").after(
        el("div", { class: "connect fade-in" }, [
          el("span", {
            html: '<svg width="96" height="56" viewBox="0 0 120 70" fill="none" aria-hidden="true"><path d="M60 35L18 14M60 35L104 18M60 35L30 60M60 35L96 58" stroke="#F4A14C" stroke-opacity=".35" stroke-width="2"/><circle cx="60" cy="35" r="9" fill="#F4A14C"/><circle cx="18" cy="14" r="6" fill="#F4A14C" fill-opacity=".55"/><circle cx="104" cy="18" r="6" fill="#F4A14C" fill-opacity=".55"/><circle cx="30" cy="60" r="6" fill="#F4A14C" fill-opacity=".55"/><circle cx="96" cy="58" r="6" fill="#F4A14C" fill-opacity=".55"/></svg>',
          }),
          el("div", { style: "flex:1;min-width:200px" }, [
            el("p", { style: "font-weight:700;margin:0 0 4px", text: `${ref} sits close to` }),
            el("p", { class: "muted", style: "margin:0 0 8px", text: near.join(" · ") }),
            el("button", { class: "linkish", type: "button", style: "padding:0", text: "Open the map →", onclick: () => window.Graph.open([ref]) }),
          ]),
        ])
      );
    } catch {
      /* the map card is extra */
    }
  }

  function decorateAnswer(msg, data) {
    if (!msg || msg.querySelector(".answer-actions") || !data.answer) return;
    const refs = (data.citations || []).map((c) => `${c.book} ${c.chapter}:${c.verse}`);
    const saveBtn = el("button", { class: "act", type: "button", html: `${ICON.bookmark}<span>Save to journal</span>` });
    saveBtn.onclick = () =>
      openJournal({ question: data.query, answer: data.answer, citations: data.citations }, () => {
        saveBtn.classList.add("is-done");
        saveBtn.innerHTML = `${ICON.check}<span>In your journal</span>`;
      });
    const listenBtn = el("button", { class: "act", type: "button", html: `${ICON.speaker}<span>Listen</span>` });
    listenBtn.onclick = () => listen(listenBtn, data.answer);
    const row = el("div", { class: "answer-actions" }, [
      saveBtn,
      refs.length ? el("button", { class: "act", type: "button", html: `${ICON.graph}<span>Explore connections</span>`, onclick: () => window.Graph.open(refs.slice(0, 4)) }) : null,
      listenBtn,
      refs.length
        ? el("button", {
            class: "act", type: "button", html: `${ICON.image}<span>Share as a card</span>`,
            onclick: async () => {
              try {
                shareCard(await verseText(refs[0]));
              } catch {
                toast("Couldn't make the card. Try again in a moment.");
              }
            },
          })
        : null,
    ]);
    const cites = msg.querySelector(".cites");
    (cites || msg).after(row);
    if (refs.length) connectionsFor(msg, refs[0]);
  }

  function markMemory(msg) {
    if (!msg || msg.querySelector(".memory-mark")) return;
    const mark = el("a", {
      class: "memory-mark", href: "#remembers", style: "text-decoration:none",
      title: "Aquila drew on what she remembers about you. See or change it in My cave.",
      html: `<svg class="flame" viewBox="0 0 24 24" fill="#F4A14C" aria-hidden="true"><path d="M12 2c1 4 6 6 6 12a6 6 0 0 1-12 0c0-3 2-5 3-6 0 2 1 3 2 3 0-4 1-6 1-9z"/></svg><span>Aquila remembers you</span>`,
    });
    msg.querySelector(".stages").after(mark);
  }

  // A verse as an image to keep or send: drawn on a canvas in the current
  // theme's colours, shared through the device's share sheet where there is
  // one, downloaded otherwise.
  function wrapLines(ctx, text, maxWidth) {
    const words = text.split(/\s+/);
    const lines = [];
    let line = "";
    for (const w of words) {
      const test = line ? `${line} ${w}` : w;
      if (ctx.measureText(test).width > maxWidth && line) {
        lines.push(line);
        line = w;
      } else line = test;
    }
    if (line) lines.push(line);
    return lines;
  }
  async function shareCard({ ref, text, translation: tr }) {
    try {
      await document.fonts.ready;
    } catch {
      /* draw with whatever is loaded */
    }
    const css = getComputedStyle(document.documentElement);
    const token = (n) => css.getPropertyValue(n).trim();
    const W = 1080;
    const H = 1350;
    const c = document.createElement("canvas");
    c.width = W;
    c.height = H;
    const ctx = c.getContext("2d");
    const g = ctx.createRadialGradient(W / 2, H * 1.05, 40, W / 2, H * 0.9, H * 0.9);
    g.addColorStop(0, token("--glow-strong"));
    g.addColorStop(1, token("--ground"));
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, H);

    let size = 64;
    let lines;
    do {
      ctx.font = `600 ${size}px "Bricolage Grotesque", system-ui, sans-serif`;
      lines = wrapLines(ctx, `"${text}"`, W - 200);
      size -= 4;
    } while (lines.length * size * 1.3 > H - 520 && size > 30);
    const lineH = (size + 4) * 1.32;
    let y = (H - lines.length * lineH) / 2;
    ctx.fillStyle = token("--text");
    ctx.textBaseline = "top";
    for (const l of lines) {
      ctx.fillText(l, 100, y);
      y += lineH;
    }
    ctx.font = `600 38px "Figtree", system-ui, sans-serif`;
    ctx.fillStyle = token("--ember");
    ctx.fillText(`${ref} · ${tr}`, 100, y + 30);

    ctx.strokeStyle = token("--ember");
    ctx.lineWidth = 6;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(100, H - 100);
    ctx.bezierCurveTo(100, H - 190, 125, H - 220, 140, H - 220);
    ctx.bezierCurveTo(155, H - 220, 180, H - 190, 180, H - 100);
    ctx.stroke();
    ctx.font = `700 40px "Bricolage Grotesque", system-ui, sans-serif`;
    ctx.fillStyle = token("--text");
    ctx.fillText("Adullum", 205, H - 152);

    const blob = await new Promise((resolve) => c.toBlob(resolve, "image/png"));
    const file = new File([blob], `${ref.replace(/[^\w]+/g, "-")}.png`, { type: "image/png" });
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      try {
        await navigator.share({ files: [file], title: ref });
        return;
      } catch {
        /* cancelled: fall through to nothing */
        return;
      }
    }
    const a = el("a", { href: URL.createObjectURL(blob), download: file.name });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    toast("Card saved to your downloads.");
  }

  // ---------------------------------------------------------------------
  // My cave
  // ---------------------------------------------------------------------
  let caveTab = "journal";
  let moodFilter = null;

  async function showCave(tab) {
    caveTab = tab || caveTab;
    $$("[data-cave-tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.caveTab === caveTab)));
    const panel = $("#cavePanel");
    panel.replaceChildren(el("div", { class: "empty", text: "Gathering..." }));
    try {
      await { journal: renderJournal, sessions: renderSessions, memories: renderMemories, plans: renderPlans }[caveTab](panel);
    } catch (err) {
      panel.replaceChildren(el("div", { class: "empty" }, [el("strong", { text: "Couldn't open this" }), err.message]));
    }
  }

  async function renderJournal(panel) {
    const entries = await api(`/me/journal${moodFilter ? `?mood=${moodFilter}` : ""}`);
    const filters = el("div", { class: "moods" }, [null, ...MOODS].map((m) =>
      el("button", { class: "mood", type: "button", "aria-pressed": String(m === moodFilter), text: m || "All", onclick: () => { moodFilter = m; showCave("journal"); } })
    ));
    const grid = el("div", { class: "entries" }, [
      el("button", { class: "new-entry", type: "button", onclick: () => openJournal({}, () => showCave("journal")) }, [
        el("span", { html: '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#F4A14C" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>' }),
        el("strong", { text: "Write about today" }),
        el("span", { text: "A verse, a prayer, a sentence. It all counts." }),
      ]),
      ...entries.map(journalCard),
    ]);
    panel.replaceChildren(filters, grid);
    if (!entries.length && moodFilter) grid.append(el("p", { class: "faint", style: "align-self:center", text: `Nothing kept in a season of ${moodFilter} yet.` }));
  }

  function journalCard(e) {
    const node = el("article", { class: "entry" });
    const meta = el("div", { class: "entry-meta" }, [el("span", { text: when(e.created_at) })]);
    if (e.mood) meta.append(el("span", { class: "badge", text: e.mood }));
    for (const t of e.tags || []) meta.append(el("span", { class: "tag", text: `#${t}` }));
    const refl = el("p", { class: "refl", text: e.reflection || "No reflection yet. Tap Edit to add one." });
    const editBtn = el("button", { class: "act", type: "button", text: "Edit" });
    editBtn.onclick = () => {
      const ta = el("textarea", { "aria-label": "Your reflection" });
      ta.value = e.reflection || "";
      refl.replaceWith(ta);
      ta.focus();
      editBtn.textContent = "Save";
      editBtn.onclick = async () => {
        try {
          node.replaceWith(journalCard(await api(`/me/journal/${e.id}`, { method: "PATCH", body: { reflection: ta.value.trim() } })));
        } catch (err) {
          toast(err.message);
        }
      };
    };
    const refs = (e.citations || []).map((c) => `${c.book} ${c.chapter}:${c.verse}`);
    if (!refs.length && e.passage_ref) refs.push(e.passage_ref);
    const actions = el("div", { class: "entry-actions" }, [
      e.question
        ? el("button", { class: "act", type: "button", text: "Ask again", onclick: () => app().submitQuery(e.question) })
        : e.passage_ref
          ? el("button", { class: "act", type: "button", text: "Return to it", onclick: () => app().submitQuery(`I'd like to come back to ${e.passage_ref}.`) })
          : null,
      refs.length ? el("button", { class: "act", type: "button", html: `${ICON.graph}<span>Explore</span>`, onclick: () => window.Graph.open(refs.slice(0, 4)) }) : null,
      editBtn,
      el("button", {
        class: "act danger", type: "button", text: "Delete",
        onclick: async () => {
          if (!confirm("Delete this journal entry? This can't be undone.")) return;
          try {
            await api(`/me/journal/${e.id}`, { method: "DELETE" });
            node.remove();
          } catch (err) {
            toast(err.message);
          }
        },
      }),
    ]);
    node.append(meta, el("h3", { text: e.passage_ref || e.question || "A moment kept" }));
    if (e.verse_text) node.append(el("p", { class: "verse", text: e.verse_text }));
    node.append(refl, actions);
    return node;
  }

  async function renderSessions(panel) {
    const rows = await api("/me/sessions");
    if (!rows.length) {
      panel.replaceChildren(el("div", { class: "empty" }, [el("strong", { text: "No conversations yet" }), "Every conversation with Aquila is kept here, newest first, ready to pick back up."]));
      return;
    }
    panel.replaceChildren(
      el("p", { class: "muted", style: "margin:0 0 18px", text: "Every conversation with Aquila, newest first, ready to pick back up." }),
      el("div", { class: "entries" }, rows.map((s) => {
        const node = el("article", { class: "entry" }, [
          el("div", { class: "entry-meta" }, [el("span", { text: when(s.updated_at || s.created_at) })]),
          el("h3", { text: s.title || "Untitled" }),
        ]);
        node.append(
          el("div", { class: "entry-actions" }, [
            el("button", { class: "act", type: "button", text: "Open conversation", onclick: () => openSession(s.id) }),
            el("button", {
              class: "act danger", type: "button", text: "Delete",
              onclick: async () => {
                if (!confirm("Delete this conversation?")) return;
                try {
                  await api(`/me/sessions/${s.id}`, { method: "DELETE" });
                  node.remove();
                } catch (err) {
                  toast(err.message);
                }
              },
            }),
          ])
        );
        return node;
      }))
    );
  }

  async function renderMemories(panel) {
    const rows = await api("/me/memories");
    const toggle = el("input", { type: "checkbox", id: "memoryToggle" });
    toggle.checked = !profile || profile.memory_enabled !== false;
    toggle.onchange = async () => {
      try {
        const p = await api("/me", { method: "PATCH", body: { memory_enabled: toggle.checked } });
        profile = { ...profile, ...p };
        toast(toggle.checked ? "Aquila will remember." : "Aquila won't keep new notes, or use old ones.");
      } catch (err) {
        toggle.checked = !toggle.checked;
        toast(err.message);
      }
    };
    const list = rows.length
      ? el("div", { class: "entries" }, rows.map((m) => {
          const node = el("article", { class: "entry" }, [
            el("div", { class: "entry-meta" }, [el("span", { text: when(m.created_at) }), el("span", { class: m.kind === "journal" ? "badge" : "badge plain", text: m.kind === "journal" ? "from journal" : "noticed" })]),
            el("p", { class: "refl", text: m.content }),
          ]);
          node.append(el("div", { class: "entry-actions" }, [el("button", {
            class: "act danger", type: "button", text: "Forget this",
            onclick: async () => {
              try {
                await api(`/me/memories/${m.id}`, { method: "DELETE" });
                node.remove();
              } catch (err) {
                toast(err.message);
              }
            },
          })]));
          return node;
        }))
      : el("div", { class: "empty" }, [el("strong", { text: "Nothing remembered yet" }), "As you share what you're studying or walking through, Aquila keeps a few quiet notes here."]);
    panel.replaceChildren(
      el("p", { class: "muted", style: "max-width:640px;margin:0 0 18px", text: "These are the notes Aquila keeps so she can know you over time. They are never treated as Scripture, and you can let any of them go." }),
      el("label", { class: "switch", for: "memoryToggle" }, [toggle, "Let Aquila remember me"]),
      list,
      rows.length
        ? el("div", { class: "row", style: "justify-content:center;margin-top:24px" }, [el("button", {
            class: "act danger", type: "button", text: "Forget everything",
            onclick: async () => {
              if (!confirm("Let Aquila forget everything she has noted about you? Your journal stays.")) return;
              try {
                await api("/me/memories", { method: "DELETE" });
                showCave("memories");
              } catch (err) {
                toast(err.message);
              }
            },
          })])
        : null
    );
  }

  async function renderPlans(panel) {
    const rows = await api("/me/plans");
    const start = el("button", {
      class: "btn btn-ember btn-sm", type: "button", text: "Start a one-year plan",
      onclick: async () => {
        start.disabled = true;
        try {
          await api("/plan", { method: "POST", body: { start_date: localToday(), days: 365, translation: translation() } });
          toast("Your plan starts today.");
          showCave("plans");
        } catch (err) {
          start.disabled = false;
          toast(err.message);
        }
      },
    });
    if (!rows.length) {
      panel.replaceChildren(el("div", { class: "empty" }, [el("strong", { text: "No reading plans yet" }), el("p", { style: "margin:0 0 16px", text: "Read through the whole Bible at your own pace. Aquila keeps your place." }), start]));
      return;
    }
    panel.replaceChildren(
      el("div", { class: "entries" }, rows.map((p) =>
        el("article", { class: "entry" }, [
          el("div", { class: "entry-meta" }, [el("span", { text: `Started ${new Date(p.start_date + "T00:00:00").toLocaleDateString()}` }), el("span", { class: "badge plain", text: p.translation })]),
          el("h3", { text: `Through the Bible in ${p.days} days` }),
          el("div", { class: "entry-actions" }, [
            el("a", { class: "act", href: "#home", text: "Today's reading" }),
            el("a", { class: "act", href: `${apiBase()}/plan/${p.id}/pdf`, text: "Download PDF" }),
          ]),
        ])
      )),
      el("div", { class: "row", style: "margin-top:24px" }, [start])
    );
  }

  // ---------------------------------------------------------------------
  // Signed out
  // ---------------------------------------------------------------------
  async function showSignedOut() {
    $("#farewellName").textContent = lastName ? `Rest well, ${lastName}.` : "Rest well.";
    const box = $("#farewellVerse");
    if (!box.dataset.loaded) {
      try {
        const v = await verseText("Psalm 4:8");
        box.querySelector("[data-text]").textContent = `"${v.text}"`;
        box.querySelector("[data-ref]").textContent = `Psalm 4:8 · ${v.translation}`;
        box.hidden = false;
        box.dataset.loaded = "1";
      } catch {
        /* the page reads fine without it */
      }
    }
  }

  // ---------------------------------------------------------------------
  // Called by index.html's router each time the view changes
  // ---------------------------------------------------------------------
  function onView(view, route) {
    if (view === "welcome") showWelcome();
    else if (view === "signin") showSignin(route);
    else if (view === "home") showHome();
    else if (view === "ask") refreshRail();
    else if (view === "cave") showCave(route === "remembers" ? "memories" : caveTab === "memories" ? "journal" : caveTab);
    else if (view === "signedout") showSignedOut();
  }

  window.Cave = {
    authHeaders,
    api,
    signedIn,
    signOut,
    onView,
    openJournal,
    decorateAnswer,
    markMemory,
    refreshRail,
    shareCard,
    toast,
  };

  consumeRedirect();
  document.addEventListener("DOMContentLoaded", () => {
    setTheme(document.documentElement.dataset.theme);
    wireAuth();
    $$("[data-cave-tab]").forEach((b) => b.addEventListener("click", () => showCave(b.dataset.caveTab)));
    $$("[data-new-entry]").forEach((b) => b.addEventListener("click", () => openJournal({}, () => showCave("journal"))));
    if (signedIn()) loadProfile();
    else updateChrome();
  });
})();
