// Everything personal: sign-in, the home screen, the cave (journal, reading
// plans), past conversations with Aquila, settings (profile, theme, what
// Aquila remembers), the signed-out page, and the extras under each answer.
// The cave's Prayers tab lives in web/prayers.js and its Refuge tab in
// web/refuge.js; this file hands them their panel. Notes, highlights and
// verses to learn live in the Bible (web/reader.js, web/memorize.js).
//
// Loaded before index.html's main script, so it only defines things here and
// reaches back into that script (window.AdullumApp) at call time. All talk with
// Supabase goes through our own API (see app/auth.py): this file holds the
// person's tokens and nothing else.
(function () {
  const STORE_KEY = "adullumSession";
  const THEME_NAMES = { dawn: "Dawn", olive: "Olive Grove", twilight: "Twilight", hearth: "Hearth" };
  // Starting points offered under the plan builder. Tapping one fills the box.
  const PLAN_IDEAS = ["The Gospels in a month", "Two weeks on anxiety", "Psalms for hard nights", "Romans, slowly"];

  const ICON = {
    bookmark: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 3h12v18l-6-4-6 4z"/></svg>',
    graph: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="8" r="2.5"/><circle cx="10" cy="18" r="2.5"/><path d="M8.3 7l7.3.7M7 8.3l2.2 7.4M16.4 10l-4.8 6"/></svg>',
    speaker: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 5L6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"/></svg>',
    share: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v12M7 8l5-5 5 5"/><path d="M5 13v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6"/></svg>',
    check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
    download: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg>',
    book: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M4 21V5M9 7h6"/></svg>',
    ember: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2c1 4 6 6 6 12a6 6 0 0 1-12 0c0-3 2-5 3-6 0 2 1 3 2 3 0-4 1-6 1-9z"/></svg>',
    heart: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/></svg>',
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
    return "a while back";
  }
  function partOfDay() {
    const h = new Date().getHours();
    return h < 12 ? "morning" : h < 17 ? "afternoon" : "evening";
  }

  // "Matthew 1", "Matthew 2", "Matthew 3", "Mark 1" -> "Matthew 1-3", "Mark 1".
  // A plan stores one reference per chapter; people read runs of them.
  function compactRefs(refs) {
    const runs = [];
    for (const ref of refs || []) {
      const m = ref.match(/^(.*\S)\s+(\d+)$/);
      const last = runs[runs.length - 1];
      if (m && last && last.book === m[1] && Number(m[2]) === last.end + 1) last.end += 1;
      else if (m) runs.push({ book: m[1], start: Number(m[2]), end: Number(m[2]) });
      else runs.push({ label: ref });
    }
    return runs.map((r) => r.label || (r.start === r.end ? `${r.book} ${r.start}` : `${r.book} ${r.start}-${r.end}`));
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

  // Shows `content` in a dimmed overlay that closes on Escape or an outside
  // click. Returns the function that closes it.
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

  // A one-line bar above a list: a quiet count on the left, and an optional
  // filter on the right. Takes far less room than a row of pills.
  function listBar(count, filter) {
    return el("div", { class: "list-bar" }, [el("span", { class: "list-count", text: count }), filter]);
  }

  // A small dropdown filter. `options` is [[value, label], ...]; `onPick`
  // gets the chosen value.
  function filterSelect(label, options, selected, onPick) {
    const select = el("select", { class: "filter-select", "aria-label": label }, options.map(([value, text]) =>
      el("option", { value, text, selected: value === selected })
    ));
    select.addEventListener("change", () => onPick(select.value));
    return select;
  }

  function formMessage() {
    const node = el("p", { class: "form-msg", role: "alert" });
    return {
      node,
      say(text, bad) {
        node.textContent = text || "";
        node.classList.toggle("bad", !!bad);
      },
    };
  }

  // ---------------------------------------------------------------------
  // Themes. index.html's early script applies the saved one before paint;
  // this keeps every picker and the saved choice in step.
  // ---------------------------------------------------------------------
  function setTheme(t) {
    if (!THEME_NAMES[t]) t = "dawn";
    document.documentElement.dataset.theme = t;
    $$("[data-set-theme]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.setTheme === t)));
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
  let lastName = "";
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
    lastName = displayName();
    writeSession(null);
    profile = null;
    updateChrome();
    app().go("signedout");
  }

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
      setTimeout(() => toast("You're signed in."), 300);
    } else if (params.get("error_description")) {
      history.replaceState(null, "", location.pathname + location.search + "#signin");
      setTimeout(() => toast(params.get("error_description").replace(/\+/g, " ")), 300);
    }
  }

  async function loadProfile() {
    if (!signedIn()) return null;
    try {
      const me = await api("/me");
      profile = { ...me.profile, email: me.user.email, is_admin: !!me.is_admin, desk_waiting: me.desk_waiting };
      if (session && !session.user) writeSession({ ...session, user: me.user });
      // web/reader.js listens for this to apply the saved translation.
      document.dispatchEvent(new CustomEvent("adullum:profile", { detail: profile }));
    } catch {
      /* the header falls back to the email initial */
    }
    updateChrome();
    return profile;
  }

  function displayName() {
    return (profile && profile.display_name) || "";
  }
  function email() {
    return (profile && profile.email) || (session && session.user && session.user.email) || "";
  }

  function updateChrome(embers) {
    const name = displayName();
    const me = $("#meBtn");
    if (me) me.textContent = ((name || email() || "A").trim()[0] || "A").toUpperCase();
    if ($("#menuName")) $("#menuName").textContent = name || "Your account";
    if ($("#menuEmail")) $("#menuEmail").textContent = email();
    // The admin desk link is only there for the people in ADMIN_EMAILS.
    const desk = $("#menuDesk");
    if (desk) {
      desk.hidden = !(profile && profile.is_admin);
      const waiting = profile && profile.desk_waiting;
      desk.textContent = waiting ? `Admin desk (${waiting} waiting)` : "Admin desk";
    }
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
    $("#authHeading").textContent = join ? "Create your account" : "Welcome back";
    $("#authSub").textContent = join
      ? "Free, private, and yours: a journal, your conversations, and reading plans."
      : "Your journal, conversations and plans are where you left them.";
    $("#nameRow").hidden = !join;
    $("#pwRow").hidden = authMethod !== "password";
    $("#authPassword").autocomplete = join ? "new-password" : "current-password";
    $$("[data-method]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.method === authMethod)));
    $("#authPrimary").textContent = authMethod === "link" ? "Email me a sign-in link" : join ? "Create account" : "Sign in";
    $("#switchPrompt").textContent = join ? "Already have an account?" : "New here?";
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
      const address = $("#authEmail").value.trim();
      await api("/auth/magic-link", { method: "POST", body: { email: address, display_name: $("#authName").value.trim() || null } });
      $("#sentTo").textContent = address;
      authMode = "sent";
      renderAuth();
    }

    $("#authForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const address = $("#authEmail").value.trim();
      const password = $("#authPassword").value;
      if (!address) return say("#authMsg", "Add your email first.", true);
      if (authMethod === "password" && password.length < 6) return say("#authMsg", "Passwords need at least 6 characters.", true);
      say("#authMsg", "");
      busy(true);
      try {
        if (authMethod === "link") {
          await sendLink();
        } else if (authMode === "join") {
          const res = await api("/auth/signup", { method: "POST", body: { email: address, password, display_name: $("#authName").value.trim() || null } });
          if (res.status === "confirm_email") say("#authMsg", "Almost there. Confirm your email from the message we just sent, then sign in.");
          else await startSession(res.session, { welcome: "Your account is ready." });
        } else {
          const res = await api("/auth/signin", { method: "POST", body: { email: address, password } });
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
        await startSession(res.session, { welcome: "You're signed in." });
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
        preview.textContent = `"${(await verseText("Matthew 11:28-29")).text}"`;
      } catch {
        /* the example still reads without its quote */
      }
    }
  }

  // ---------------------------------------------------------------------
  // Shared pieces: cards, reading plans, the plan builder
  // ---------------------------------------------------------------------
  // A card with a small label (or a head row) followed by its body.
  function card(head, { warm } = {}, body = []) {
    return el("section", { class: `card fade-in${warm ? " warm" : ""}` }, [
      typeof head === "string" ? el("h2", { class: "kicker", text: head }) : head,
      ...body,
    ]);
  }
  function cardHead(label, aside) {
    return el("div", { class: "card-head" }, [el("h2", { class: "kicker", text: label }), aside]);
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

  async function startWholeBiblePlan(button, onDone) {
    if (button) button.disabled = true;
    try {
      await api("/plan", { method: "POST", body: { start_date: localToday(), days: 365, translation: translation() } });
      toast("Your one-year plan starts today.");
      onDone();
    } catch (err) {
      if (button) button.disabled = false;
      toast(err.message);
    }
  }

  // The box where someone tells Aquila what they'd like to read. Used on the
  // home screen (compact, inside a card) and at the top of the Plans tab.
  function planBuilder({ onBuilt, compact = false }) {
    const id = compact ? "homePlanRequest" : "planRequest";
    const input = el("textarea", { id, rows: "2", maxlength: "500", placeholder: "For example: the Gospels in a month, or two weeks on anxiety" });
    const msg = formMessage();
    const build = el("button", { class: "btn btn-ember btn-sm", type: "submit", text: "Shape my plan" });
    const whole = el("button", { class: "linkish", type: "button", text: "Or read the whole Bible in a year" });
    whole.onclick = () => startWholeBiblePlan(whole, onBuilt);

    const form = el("form", { class: `plan-builder${compact ? "" : " card"}` }, [
      compact ? null : el("h2", { class: "section-title", text: "Plan with Aquila" }),
      el("p", {
        class: "muted", style: "margin:0 0 12px;font-size:15px",
        text: "Tell Aquila what you'd like to read, or what you're walking through, and how long you have. She'll lay it out day by day.",
      }),
      el("label", { class: "sr", for: id, text: "What would you like to read?" }),
      input,
      el("div", { class: "topics" }, PLAN_IDEAS.map((idea) =>
        el("button", { class: "topic", type: "button", text: idea, onclick: () => { input.value = idea; input.focus(); } })
      )),
      msg.node,
      el("div", { class: "builder-actions" }, [build, whole]),
    ]);

    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        form.requestSubmit();
      }
    });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const request = input.value.trim();
      if (request.length < 3) return msg.say("Tell Aquila a little about what you'd like to read.", true);
      msg.say("");
      build.disabled = true;
      build.textContent = "Shaping your plan...";
      try {
        const plan = await api("/me/plans/build", { method: "POST", body: { request, today: localToday(), translation: translation() } });
        toast(`"${plan.title}" starts today.`);
        onBuilt(plan);
      } catch (err) {
        msg.say(err.message, true);
        build.disabled = false;
        build.textContent = "Shape my plan";
      }
    });
    return form;
  }

  // One reading plan: where it stands today, today's chapters, and its
  // actions. `compact` is the home screen's version.
  function planItem(plan, { compact = false, onChange }) {
    const bar = el("span", { style: `width:${Math.max(plan.progress_pct, 1)}%` });
    const progressText = el("span");
    const doneBtn = el("button", { type: "button" });
    const paint = (p) => {
      doneBtn.className = p.done_today ? "btn btn-sm btn-ghost" : "btn btn-sm btn-ember";
      doneBtn.innerHTML = p.done_today ? `${ICON.check}<span>Read today</span>` : "<span>Mark as read</span>";
      bar.style.width = `${Math.max(p.progress_pct, 1)}%`;
      progressText.textContent = `${p.completed} of ${p.days} days read`;
    };
    paint(plan);
    doneBtn.addEventListener("click", async () => {
      const next = !plan.done_today;
      try {
        plan = { ...plan, ...(await api(`/me/plans/${plan.id}/progress`, { method: "POST", body: { day: plan.day, done: next, today: localToday() } })) };
        paint(plan);
        if (next) toast(`Day ${plan.day} read. ${plan.completed} of ${plan.days} done.`);
      } catch (err) {
        toast(err.message);
      }
    });

    const refs = compactRefs(plan.refs);
    const body = [
      !compact && plan.overview ? el("p", { class: "overview", text: plan.overview }) : null,
      el("div", { class: "bar", role: "progressbar", "aria-label": `${plan.title} progress`, "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(plan.progress_pct) }, bar),
      el("div", { class: "progress-line" }, [progressText, el("span", { text: `Day ${plan.day} of ${plan.days}` })]),
      el("div", { class: "refs" }, [
        el("span", { class: "kicker", text: "Today" }),
        ...refs.map((r) => el("button", { class: "chapter", type: "button", text: r, title: `Read ${r} with Aquila`, onclick: () => app().submitQuery(`Walk me through ${r}.`) })),
      ]),
      el("div", { class: "card-actions-row" }, [
        doneBtn,
        compact ? el("a", { class: "act", href: "#plans", text: "All plans" }) : null,
        compact ? null : el("a", { class: "act", href: `${apiBase()}/plan/${plan.id}/pdf`, html: `${ICON.download}<span>PDF</span>` }),
        compact
          ? null
          : el("button", {
              class: "act danger", type: "button", text: "Delete",
              onclick: async () => {
                if (!confirm(`Delete "${plan.title}"? Your progress in it goes too.`)) return;
                try {
                  await api(`/me/plans/${plan.id}`, { method: "DELETE" });
                  onChange();
                } catch (err) {
                  toast(err.message);
                }
              },
            }),
      ]),
    ];
    if (compact) return card(cardHead("Today's reading", el("span", { class: "faint", style: "font-size:13px", text: plan.title })), {}, body);
    return el("article", { class: "card plan-item" }, [el("h3", { class: "section-title", text: plan.title }), ...body]);
  }

  // ---------------------------------------------------------------------
  // Home
  // ---------------------------------------------------------------------
  function homeVerseCard(v) {
    return el("section", { class: "card warm today-band fade-in" }, [
      el("div", {}, [
        el("h2", { class: "kicker ember", text: "Verse for today" }),
        el("p", { class: "scripture-lg", text: `"${v.text}"` }),
        el("p", { class: "verse-ref", style: "margin-top:8px", text: `${v.ref} · ${v.translation}` }),
      ]),
      el("div", { class: "row", style: "gap:2px" }, [
        el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Reflect with Aquila", onclick: () => app().submitQuery(`Help me reflect on ${v.ref}.`) }),
        el("button", { class: "act", type: "button", html: `${ICON.bookmark}<span>Keep</span>`, onclick: () => openJournal({ passage_ref: v.ref, verse_text: v.text }) }),
        el("button", { class: "act", type: "button", html: `${ICON.heart}<span>Learn it</span>`, onclick: () => window.Memorize.add(v.ref, v.translation) }),
        el("button", { class: "act", type: "button", html: `${ICON.graph}<span>Connections</span>`, onclick: () => window.Graph.open([`${v.book} ${v.chapter}:${v.verse}`]) }),
        el("button", { class: "act", type: "button", html: `${ICON.share}<span>Share</span>`, onclick: () => shareCard(v) }),
      ]),
    ]);
  }

  function continueCard(s) {
    if (!s) {
      return card("Your first conversation", {}, [
        el("p", { class: "muted", style: "margin:0 0 16px", text: "Ask about a passage, a hard question, or the season you're in. Every conversation is kept in your cave so you can pick it back up." }),
        el("a", { class: "btn btn-ember btn-sm", href: "#aquila", text: "Ask Aquila" }),
      ]);
    }
    return card(cardHead("Pick up where you left off", el("span", { class: "faint", style: "font-size:13px", text: when(s.updated_at) })), {}, [
      el("p", { class: "big-q", text: s.title || "Your last conversation" }),
      s.refs.length ? el("p", { class: "muted", style: "font-size:15px", text: `You were reading ${s.refs.join(", ")}.` }) : null,
      el("div", { class: "card-actions-row" }, [
        el("button", { class: "btn btn-ember btn-sm", type: "button", text: "Continue", onclick: () => openSession(s.id) }),
        s.followup ? el("button", { class: "btn btn-ghost btn-sm btn-wrap", type: "button", text: s.followup, onclick: () => openSession(s.id, s.followup) }) : null,
      ]),
    ]);
  }

  function homePlanCard(plan) {
    if (plan) return planItem(plan, { compact: true, onChange: showHome });
    return card("Reading plan", {}, [planBuilder({ compact: true, onBuilt: showHome })]);
  }

  function weekCard(e) {
    const line = e.streak > 1 ? `${e.streak} days in a row.` : e.streak === 1 ? "Day one. Come back tomorrow to keep it going." : "One ember for every day you come in.";
    return card("This week", {}, [
      el("p", { class: "faint", style: "margin:-4px 0 14px;font-size:14px", text: line }),
      el("div", { class: "week" }, e.week.map((d) =>
        el("div", {}, [
          el("div", { class: `day-dot${d.lit ? " lit" : ""}`, html: ICON.ember, title: d.lit ? "You came in" : "" }),
          el("span", { class: `day-label${d.today ? " today" : ""}`, text: d.label }),
        ])
      )),
    ]);
  }

  function revisitCard(r) {
    const where = r.passage_ref || r.question || "a passage";
    const reflection = r.reflection.length > 220 ? `${r.reflection.slice(0, 217)}...` : r.reflection;
    return card(`From your journal, ${agoPhrase(r.created_at)}`, {}, [
      el("p", { style: "margin:0 0 6px;font-size:15px" }, ["You were with ", el("strong", { text: where }), r.mood ? ` in a season of ${r.mood}, and wrote:` : ", and wrote:"]),
      el("p", { class: "scripture", style: "font-size:17px;color:var(--soft);font-style:italic;margin:0 0 12px", text: `"${reflection}"` }),
      el("p", { class: "muted", style: "font-size:15px", text: "How is that now?" }),
      el("div", { class: "card-actions-row" }, [
        el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Return to it with Aquila", onclick: () => app().submitQuery(`I'd like to come back to ${where}. Last time I wrote: "${r.reflection.slice(0, 300)}"`) }),
        el("a", { class: "act", href: "#journal", text: "Open journal" }),
      ]),
    ]);
  }

  function setGreeting() {
    const name = displayName();
    $("#greet").textContent = `Good ${partOfDay()}${name ? `, ${name}` : ""}`;
  }

  async function showHome() {
    setGreeting();
    $("#dayLine").textContent = new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
    const main = $("#homeMain");
    const side = $("#homeSide");
    if (!main.children.length) main.append(el("div", { class: "empty", text: "Opening your cave..." }));

    // The verse is public and cached for the day, so it loads alongside the
    // home request rather than after it.
    const versePromise = verseOfTheDay().catch(() => null);
    let data;
    try {
      data = await api(`/me/home?today=${localToday()}`);
    } catch (err) {
      main.replaceChildren(el("div", { class: "empty" }, [el("strong", { text: "Your cave isn't open yet" }), err.message]));
      side.replaceChildren();
      return;
    }
    // /me may still be loading on a fresh visit, so the home payload's profile
    // fills in the name rather than waiting for it.
    if (data.profile) profile = { ...(profile || {}), ...data.profile };
    setGreeting();
    updateChrome(data.embers);

    const v = await versePromise;
    $("#homeVerse").replaceChildren(...(v ? [homeVerseCard(v)] : []));
    // Amens sits with the main cards so it's seen on arrival. It is null
    // until the Refuge migration has run.
    main.replaceChildren(...[
      continueCard(data.last_session),
      data.amens ? window.Refuge.homeCard(data.amens) : null,
      homePlanCard(data.plan),
    ].filter(Boolean));
    // The prayer and memory-verse cards are null until their migration has
    // run, and the memory-verse card only appears when something is due.
    side.replaceChildren(...[
      data.embers ? weekCard(data.embers) : null,
      data.memorize ? window.Memorize.homeCard(data.memorize, showHome) : null,
      data.prayers ? window.Prayers.homeCard(data.prayers, showHome) : null,
      data.revisit ? revisitCard(data.revisit) : null,
    ].filter(Boolean));
  }

  // ---------------------------------------------------------------------
  // Past conversations: the Ask rail on wide screens, a sheet on phones
  // ---------------------------------------------------------------------
  // One past conversation: tap to open, and a small button beside it to
  // rename or delete it. `onChanged` redraws whichever list it sits in.
  function conversationButton(s, onOpen, onChanged) {
    const open = el("button", { class: "rail-item", type: "button", "aria-current": String(s.id === (app() && app().getSessionId())), onclick: onOpen }, [
      el("span", { text: s.title || "Untitled" }),
      el("small", { text: when(s.updated_at || s.created_at) }),
    ]);
    const more = el("button", { class: "rail-more", type: "button", "aria-label": `Rename or delete "${s.title || "Untitled"}"`, html: ICON_MORE, onclick: () => manageConversation(s, onChanged) });
    return el("div", { class: "rail-row" }, [open, more]);
  }

  const ICON_MORE = '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="19" cy="12" r="1.8"/></svg>';

  function manageConversation(s, onChanged) {
    const title = el("input", { class: "field", maxlength: "120", "aria-label": "Name" });
    title.value = s.title || "";
    const msg = formMessage();
    const save = el("button", { class: "btn btn-ember btn-sm", type: "submit", text: "Save" });
    const remove = el("button", { class: "btn btn-ghost btn-sm danger-text", type: "button", text: "Delete" });
    const form = el("form", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "manageConvTitle" }, [
      el("h3", { id: "manageConvTitle", text: "This conversation" }),
      el("label", { class: "field-wrap" }, ["Name", title]),
      msg.node,
      el("div", { class: "sheet-actions" }, [remove, el("span", { style: "flex:1" }), el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Cancel", onclick: () => close() }), save]),
    ]);
    const close = overlay(form);
    const changed = () => {
      refreshRail();
      if (onChanged) onChanged();
    };
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!title.value.trim()) return msg.say("Give it a name.", true);
      save.disabled = true;
      try {
        await api(`/me/sessions/${s.id}`, { method: "PATCH", body: { title: title.value.trim() } });
        close();
        toast("Renamed.");
        changed();
      } catch (err) {
        msg.say(err.message, true);
        save.disabled = false;
      }
    });
    remove.onclick = async () => {
      if (!confirm("Delete this conversation? This can't be undone.")) return;
      try {
        await api(`/me/sessions/${s.id}`, { method: "DELETE" });
        close();
        toast("Deleted.");
        // Deleting the conversation on screen starts a fresh one.
        if (app() && app().getSessionId() === s.id) app().newConversation();
        changed();
      } catch (err) {
        msg.say(err.message, true);
      }
    };
  }

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
        list.replaceChildren(
          ...(rows.length
            ? rows.slice(0, 30).map((s) => conversationButton(s, () => openSession(s.id)))
            : [el("p", { class: "faint", style: "padding:4px 10px;font-size:14px", text: "Your conversations will appear here." })])
        );
      } catch {
        /* the rail is a convenience */
      }
    }, 1200);
  }

  async function openConversations() {
    const list = el("div", { class: "conv-list" }, el("p", { class: "faint", text: "Opening..." }));
    const sheet = el("div", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "convTitle" }, [
      el("div", { class: "row-between" }, [
        el("h3", { id: "convTitle", text: "Conversations" }),
        el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "New", onclick: () => { close(); app().newConversation(); } }),
      ]),
      list,
    ]);
    const close = overlay(sheet);
    const fill = async () => {
      try {
        const rows = await api("/me/sessions");
        list.replaceChildren(
          ...(rows.length
            ? rows.slice(0, 30).map((s) => conversationButton(s, () => { close(); openSession(s.id); }, fill))
            : [el("p", { class: "faint", text: "Your conversations will appear here." })])
        );
      } catch (err) {
        list.replaceChildren(el("p", { class: "form-msg bad", text: err.message }));
      }
    };
    fill();
  }

  // ---------------------------------------------------------------------
  // Journal sheet: save an answer, a verse, or a free-written entry
  // ---------------------------------------------------------------------
  // An entry's tags as the person sees them. Older entries may also carry a
  // "season" from before tags replaced it; it shows as one more tag.
  function entryTags(e) {
    const tags = [...(e.tags || [])];
    if (e.mood && !tags.includes(e.mood)) tags.push(e.mood);
    return tags;
  }

  function openJournal(item = {}, onSaved) {
    if (!signedIn()) {
      toast("Create a free account to keep a journal.");
      app().go("join");
      return;
    }
    const reflection = el("textarea", { id: "journalReflection", placeholder: "What is this stirring in you? A sentence is plenty." });
    const passage = el("input", { id: "journalPassage", placeholder: "Psalm 23, or leave blank" });
    const tags = el("input", { id: "journalTags", placeholder: "prayer, family, small group" });
    const msg = formMessage();
    const save = el("button", { class: "btn btn-ember btn-sm", type: "submit", text: "Save" });
    const freeWrite = !item.passage_ref && !item.question;

    const preview = freeWrite
      ? el("label", { class: "field-wrap" }, ["Passage (optional)", passage])
      : el("div", { class: "journal-preview" }, item.passage_ref
          ? [el("strong", { text: item.passage_ref }), document.createTextNode(item.verse_text || "")]
          : [el("strong", { text: item.question || "" }), document.createTextNode((item.answer || "").replace(/^#+\s*/gm, "").slice(0, 400))]);

    const formEl = el("form", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "journalTitle" }, [
      el("h3", { id: "journalTitle", text: freeWrite ? "New journal entry" : "Save to your journal" }),
      el("p", { class: "sheet-lede", text: "Only you can see this. Aquila may bring it up gently next time you talk." }),
      preview,
      el("label", { class: "field-wrap" }, ["Your reflection", reflection]),
      el("label", { class: "field-wrap" }, ["Tags (separate with commas)", tags]),
      msg.node,
      el("div", { class: "sheet-actions" }, [el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Cancel", onclick: () => close() }), save]),
    ]);
    const close = overlay(formEl);

    formEl.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (freeWrite && !reflection.value.trim()) return msg.say("Write a line or two first.", true);
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
            tags: tags.value.split(",").map((t) => t.trim()).filter(Boolean),
            session_id: item.question ? app().getSessionId() : null,
          },
        });
        close();
        toast("Saved to your journal.");
        if (onSaved) onSaved(entry);
      } catch (err) {
        msg.say(err.message, true);
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
          el("strong", { text: `Close to ${ref}:` }),
          el("span", { class: "muted", text: near.join(" · ") }),
          el("button", { class: "linkish", type: "button", style: "padding:0", text: "See all connections", onclick: () => window.Graph.open([ref]) }),
        ])
      );
    } catch {
      /* the connections line is extra */
    }
  }

  function decorateAnswer(msg, data) {
    if (!msg || msg.querySelector(".answer-actions") || !data.answer) return;
    const refs = (data.citations || []).map((c) => `${c.book} ${c.chapter}:${c.verse}`);
    const saveBtn = el("button", { class: "act", type: "button", html: `${ICON.bookmark}<span>Save to journal</span>` });
    saveBtn.onclick = () =>
      openJournal({ question: data.query, answer: data.answer, citations: data.citations }, () => {
        saveBtn.classList.add("is-done");
        saveBtn.innerHTML = `${ICON.check}<span>Saved</span>`;
      });
    const listenBtn = el("button", { class: "act", type: "button", html: `${ICON.speaker}<span>Listen</span>` });
    listenBtn.onclick = () => listen(listenBtn, data.answer);
    const row = el("div", { class: "answer-actions" }, [
      saveBtn,
      refs.length ? el("a", { class: "act", href: `#${window.Reader.href(refs[0])}`, title: `Open ${refs[0]} in the Bible`, html: `${ICON.book}<span>Read in context</span>` }) : null,
      refs.length ? el("button", { class: "act", type: "button", html: `${ICON.graph}<span>Connections</span>`, onclick: () => window.Graph.open(refs.slice(0, 4)) }) : null,
      listenBtn,
      refs.length
        ? el("button", {
            class: "act", type: "button", html: `${ICON.share}<span>Share</span>`,
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
      class: "memory-mark", href: "#remembers",
      title: "Aquila drew on what she remembers about you. See or change it in Settings.",
      html: `${ICON.ember.replace("<svg ", '<svg fill="#F4A14C" ')}<span>Aquila remembered something you shared</span>`,
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
    ctx.fillStyle = token("--ground");
    ctx.fillRect(0, 0, W, H);

    let size = 64;
    let lines;
    do {
      ctx.font = `400 ${size}px "Source Serif 4", Georgia, serif`;
      lines = wrapLines(ctx, `"${text}"`, W - 200);
      size -= 4;
    } while (lines.length * size * 1.3 > H - 520 && size > 30);
    const lineH = (size + 4) * 1.4;
    let y = (H - lines.length * lineH) / 2;
    ctx.fillStyle = token("--text");
    ctx.textBaseline = "top";
    for (const l of lines) {
      ctx.fillText(l, 100, y);
      y += lineH;
    }
    ctx.font = `600 36px "Inter", system-ui, sans-serif`;
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
    ctx.font = `600 38px "Inter", system-ui, sans-serif`;
    ctx.fillStyle = token("--text");
    ctx.fillText("Adullum", 205, H - 150);

    const blob = await new Promise((resolve) => c.toBlob(resolve, "image/png"));
    const file = new File([blob], `${ref.replace(/[^\w]+/g, "-")}.png`, { type: "image/png" });
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      try {
        await navigator.share({ files: [file], title: ref });
      } catch {
        /* cancelled */
      }
      return;
    }
    const a = el("a", { href: URL.createObjectURL(blob), download: file.name });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    toast("Card saved to your downloads.");
  }

  // ---------------------------------------------------------------------
  // The cave: Journal, Prayers, Refuge and Plans, side by side as tabs. Past
  // conversations live with Aquila (the rail, or the Conversations sheet on a
  // phone), where they can be opened, renamed and deleted; notes, highlights
  // and verses to learn live in the Bible (#bible/notes, #bible/memorize).
  // ---------------------------------------------------------------------
  // Hash routes that open a tab directly, and the header button each tab shows.
  // #amens opens Refuge already inside the Amens room.
  const CAVE_ROUTES = { journal: "journal", prayers: "prayers", refuge: "refuge", amens: "refuge", plans: "plans" };
  const CAVE_ACTIONS = {
    journal: ["New entry", () => openJournal({}, () => showCave("journal"))],
    prayers: ["New prayer", () => window.Prayers.openSheet({}, () => showCave("prayers"))],
    plans: ["New plan", () => { const box = $("#planRequest"); if (box) { box.scrollIntoView({ behavior: "smooth", block: "center" }); box.focus(); } }],
    // Refuge has no header button: its rooms are its own ways in.
  };
  let caveTab = "journal";
  let tagFilter = null;

  // `route` is the hash that opened the cave, passed on so a tab can open
  // somewhere inside itself (Refuge's #amens).
  async function showCave(tab, route) {
    caveTab = tab || caveTab;
    $$("[data-cave-tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.caveTab === caveTab)));
    const action = CAVE_ACTIONS[caveTab];
    $("#caveAction").hidden = !action;
    if (action) $("#caveAction").textContent = action[0];
    // Leaving Refuge settles the page back and lets an unkept talk vanish.
    if (caveTab !== "refuge") window.Refuge.hide();
    const panel = $("#cavePanel");
    panel.replaceChildren(el("div", { class: "empty", text: "Opening..." }));
    try {
      await {
        journal: renderJournal,
        prayers: (p) => window.Prayers.renderTab(p),
        refuge: (p) => window.Refuge.renderTab(p, route),
        plans: renderPlans,
      }[caveTab](panel);
    } catch (err) {
      panel.replaceChildren(el("div", { class: "empty" }, [el("strong", { text: "Couldn't open this" }), err.message]));
    }
  }

  async function renderJournal(panel) {
    const entries = await api("/me/journal");
    if (!entries.length) {
      panel.replaceChildren(el("div", { class: "empty" }, [
        el("strong", { text: "Nothing in your journal yet" }),
        "Save an answer or a verse from Aquila, or write about today.",
        el("div", {}, el("button", { class: "btn btn-ember btn-sm", type: "button", text: "Write an entry", onclick: () => openJournal({}, () => showCave("journal")) })),
      ]));
      return;
    }
    // Filter by the tags actually in use, most used first. Filtering happens
    // here rather than on the server: a journal is at most a hundred entries.
    const counts = new Map();
    entries.forEach((e) => entryTags(e).forEach((t) => counts.set(t, (counts.get(t) || 0) + 1)));
    const used = [...counts.keys()].sort((a, b) => counts.get(b) - counts.get(a) || a.localeCompare(b));
    if (tagFilter && !counts.has(tagFilter)) tagFilter = null;
    const shown = tagFilter ? entries.filter((e) => entryTags(e).includes(tagFilter)) : entries;
    const bar = listBar(
      `${shown.length} ${shown.length === 1 ? "entry" : "entries"}`,
      used.length
        ? filterSelect("Filter by tag", [["", "All tags"], ...used.map((t) => [t, `#${t}`])], tagFilter || "", (value) => {
            tagFilter = value || null;
            showCave("journal");
          })
        : null
    );
    panel.replaceChildren(bar, el("div", { class: "entries" }, shown.map(journalCard)));
  }

  function journalCard(e) {
    const node = el("article", { class: "entry fade-in" });
    const meta = el("div", { class: "entry-meta" }, [el("span", { text: when(e.created_at) })]);
    for (const t of entryTags(e)) meta.append(el("span", { class: "tag", text: `#${t}` }));
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
      refs.length ? el("button", { class: "act", type: "button", html: `${ICON.graph}<span>Connections</span>`, onclick: () => window.Graph.open(refs.slice(0, 4)) }) : null,
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

  async function renderPlans(panel) {
    const rows = await api(`/me/plans?today=${localToday()}`);
    const rerender = () => showCave("plans");
    panel.replaceChildren(
      planBuilder({ onBuilt: rerender }),
      rows.length
        ? el("div", { class: "plan-list" }, [el("h2", { class: "section-title", text: "Your plans" }), ...rows.map((p) => planItem(p, { onChange: rerender }))])
        : el("p", { class: "muted", style: "margin-top:20px", text: "No plans yet. Shape one with Aquila above, or read the whole Bible in a year." })
    );
  }

  // ---------------------------------------------------------------------
  // Settings: profile, theme, and what Aquila remembers
  // ---------------------------------------------------------------------
  function renderThemeOptions() {
    const box = $("#themeOptions");
    if (box.children.length) return;
    const current = document.documentElement.dataset.theme;
    box.append(
      ...Object.entries(THEME_NAMES).map(([key, name]) =>
        el("button", { class: "theme-option", type: "button", "data-set-theme": key, "aria-pressed": String(key === current) }, [
          el("span", { class: "swatch", "data-swatch": key, "aria-hidden": "true" }),
          name,
        ])
      )
    );
  }

  // Where each kind of memory came from, as shown under it in Settings.
  const MEMORY_SOURCES = { note: "from a conversation", journal: "from your journal", prayer: "from your prayer list" };

  async function renderMemories(panel) {
    panel.replaceChildren(el("p", { class: "faint", text: "Opening..." }));
    let rows;
    try {
      rows = await api("/me/memories");
    } catch (err) {
      panel.replaceChildren(el("p", { class: "form-msg bad", text: err.message }));
      return;
    }
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
      ? el("ul", { class: "memory-list" }, rows.map((m) => {
          const item = el("li", {}, [
            el("div", {}, [
              el("p", { text: m.content }),
              el("small", { text: `${when(m.created_at)} · ${MEMORY_SOURCES[m.kind] || MEMORY_SOURCES.note}` }),
            ]),
          ]);
          item.append(el("button", {
            class: "act danger", type: "button", text: "Forget",
            onclick: async () => {
              try {
                await api(`/me/memories/${m.id}`, { method: "DELETE" });
                item.remove();
              } catch (err) {
                toast(err.message);
              }
            },
          }));
          return item;
        }))
      : el("p", { class: "muted", text: "Nothing yet. As you share what you're studying or walking through, Aquila keeps a few short notes here." });
    panel.replaceChildren(
      el("p", { class: "section-sub", text: "Short notes Aquila keeps so she can know you over time. They are never treated as Scripture, and you can remove any of them." }),
      el("label", { class: "switch", for: "memoryToggle" }, [toggle, "Let Aquila remember me"]),
      list,
      rows.length
        ? el("div", { class: "row", style: "margin-top:16px" }, [el("button", {
            class: "btn btn-ghost btn-sm", type: "button", text: "Forget everything",
            onclick: async () => {
              if (!confirm("Let Aquila forget everything she has noted about you? Your journal stays.")) return;
              try {
                await api("/me/memories", { method: "DELETE" });
                renderMemories(panel);
              } catch (err) {
                toast(err.message);
              }
            },
          })])
        : null
    );
  }

  async function showSettings(route) {
    if (!profile) await loadProfile();
    $("#settingsEmail").textContent = email() ? `Signed in as ${email()}` : "";
    $("#settingsName").value = displayName();
    renderThemeOptions();
    renderMemories($("#memoryPanel"));
    if (route === "remembers") setTimeout(() => $("#remembers").scrollIntoView({ behavior: "smooth", block: "start" }), 120);
  }

  function wireSettings() {
    $("#nameForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const name = $("#settingsName").value.trim();
      if (!name) return toast("Add a name first.");
      try {
        const p = await api("/me", { method: "PATCH", body: { display_name: name } });
        profile = { ...profile, ...p };
        updateChrome();
        toast("Saved.");
      } catch (err) {
        toast(err.message);
      }
    });
    $$("[data-sign-out]").forEach((b) => b.addEventListener("click", signOut));
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
    if (view !== "cave") window.Refuge.hide();
    if (view === "welcome") showWelcome();
    else if (view === "signin") showSignin(route);
    else if (view === "home") showHome();
    else if (view === "aquila") refreshRail();
    else if (view === "cave") showCave(CAVE_ROUTES[route], route);
    else if (view === "settings") showSettings(route);
    else if (view === "signedout") showSignedOut();
    else if (view === "desk") window.Refuge.renderDesk();
  }

  window.Cave = {
    authHeaders,
    api,
    el,
    overlay,
    formMessage,
    listBar,
    filterSelect,
    when,
    agoPhrase,
    localToday,
    card,
    cardHead,
    showCave,
    signedIn,
    signOut,
    onView,
    openJournal,
    openConversations,
    decorateAnswer,
    markMemory,
    refreshRail,
    shareCard,
    toast,
    verseText,
  };

  consumeRedirect();
  document.addEventListener("DOMContentLoaded", () => {
    setTheme(document.documentElement.dataset.theme);
    wireAuth();
    wireSettings();
    $$("[data-cave-tab]").forEach((b) => b.addEventListener("click", () => showCave(b.dataset.caveTab)));
    $("#caveAction").addEventListener("click", () => CAVE_ACTIONS[caveTab] && CAVE_ACTIONS[caveTab][1]());
    if (signedIn()) loadProfile();
    else updateChrome();
  });
})();
