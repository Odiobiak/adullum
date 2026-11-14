// Support Adullam (#support): give once, or monthly as a friend of the cave.
//
// The page is open to everyone, and the rest of the site points people here:
// the account menu, a card on the home screen, Settings, the welcome page and
// the signed-out page. The giving itself happens somewhere else: a Stripe
// checkout once it's registered, and the ways to give an admin sets on the
// desk's Giving tab (PayPal, Venmo, Cash App, Zelle, anything else), all
// from GET /support. This file never touches a card or an account. With
// nothing set, the page still explains why Adullam asks and says giving
// opens soon, so no button leads nowhere.
//
// The desk's Giving tab is drawn here too (renderAdmin), since it decides
// what this page shows.
//
// Friends of the cave get thank-you gifts only: a mark on their account chip
// and the supporter themes (cave.js::SUPPORTER_THEMES). Nothing anyone relies
// on is held back. See app/support.py for how someone becomes one.
//
// Reached as window.Support. Loaded after cave.js, whose helpers it borrows.
(function () {
  const { el, card, toast } = window.Cave;
  const cave = () => window.Cave;
  const $ = (sel) => document.querySelector(sel);

  // "Not now" on the home card hides it on this device for this long, so the
  // ask is there to find without turning into a nag.
  const SNOOZE_KEY = "adullumSupportSnoozedUntil";
  const SNOOZE_DAYS = 30;

  // The thank-you gifts, as the page lists them. Keep in step with
  // cave.js::SUPPORTER_THEMES and the mark in cave.js::updateChrome.
  const GIFTS = [
    "A small ember on your account, so you know you're helping keep the lights on.",
    "Two extra themes, Almond and Cedar, in Settings.",
    "Our thanks, every month.",
  ];

  // The verse at the foot of the page. Its text is always read from the
  // database, like every verse on screen.
  const GIVING_VERSE = "2 Corinthians 9:7";

  // Each way to give gets a round mark with a letter, in the theme's own
  // colours (never a company's logo).
  const MARKS = { card: "S", paypal: "P", venmo: "V", cashapp: "$", zelle: "Z" };

  let linksPromise = null;
  function links() {
    if (!linksPromise) {
      linksPromise = fetch(`${apiBase()}/support`)
        .then((res) => (res.ok ? res.json() : {}))
        .catch(() => ({}));
    }
    return linksPromise;
  }

  // Same server as every other call (web/cave.js::apiBase): the hidden #apiBase input, or this site.
  const apiBase = () => (((document.getElementById("apiBase") || {}).value || "").trim() || location.origin).replace(/\/$/, "");

  // The Stripe checkout link, carrying who is giving when they're signed in.
  // Stripe fills in their email, and keeps their id as client_reference_id so
  // a future webhook can mark the right account.
  function checkoutHref(base) {
    const who = window.Cave.account();
    try {
      const url = new URL(base);
      if (who.id) url.searchParams.set("client_reference_id", who.id);
      if (who.email) url.searchParams.set("prefilled_email", who.email);
      return url.toString();
    } catch {
      return base;
    }
  }

  const outLink = (href, text, className) => el("a", { class: className, href, target: "_blank", rel: "noopener noreferrer", text });

  // The thank-you line for a friend of the cave. An admin counts as a friend
  // without a giving date, so they get the line without one.
  function sinceLine(since) {
    if (!since) return "You're a friend of the cave. Thank you for looking after it.";
    const date = new Date(since);
    return Number.isNaN(date.getTime())
      ? "You're a friend of the cave. Thank you."
      : `You've been a friend of the cave since ${date.toLocaleDateString(undefined, { month: "long", year: "numeric" })}. Thank you.`;
  }

  async function copy(text, what) {
    try {
      await navigator.clipboard.writeText(text);
      toast(`${what} copied.`);
    } catch {
      window.prompt(`Copy ${what}:`, text);
    }
  }

  const mark = (kind, name) => el("span", { class: `give-mark give-mark-${kind}`, "aria-hidden": "true", text: MARKS[kind] || (name || "?").charAt(0).toUpperCase() });

  // One way to give: its mark, name, handle and note, then Copy (when there's
  // a handle to send to) and Give (when there's a link to open).
  function wayRow(way) {
    const sendTo = way.kind === "zelle" ? `Send to ${way.handle}` : way.handle;
    return el("li", { class: "give-row" }, [
      mark(way.kind, way.name),
      el("div", { class: "give-row-text" }, [
        el("strong", { text: way.name }),
        way.handle ? el("span", { class: "give-handle", text: sendTo }) : null,
        way.note ? el("small", { class: "muted", text: way.note }) : null,
      ]),
      el("div", { class: "give-row-actions" }, [
        way.handle ? el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Copy", "aria-label": `Copy ${way.name} details`, onclick: () => copy(way.handle, `${way.name} details`) }) : null,
        way.link ? outLink(way.link, "Give", "btn btn-ember btn-sm") : null,
      ]),
    ]);
  }

  // Who handles the gifts, in words, for the line under the options.
  function handledBy(data, methods) {
    const names = [...new Set([data.once_url || data.monthly_url ? "Stripe" : null, ...methods.filter((m) => m.kind !== "other").map((m) => m.name)].filter(Boolean))];
    if (!names.length) return "Adullam never sees your card or bank details.";
    const list = names.length === 1 ? names[0] : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
    return `Gifts go through ${list}, so Adullam never sees your card or bank details.`;
  }

  // ---------------------------------------------------------------------
  // The page
  // ---------------------------------------------------------------------
  async function show() {
    const page = $("#supportPage");
    const data = await links();
    const methods = data.methods || [];
    const signedIn = window.Cave.signedIn();
    const since = window.Cave.supporterSince();
    const friend = window.Cave.isFriend();
    const amount = data.monthly_amount || "";
    const anything = Boolean(data.once_url || data.monthly_url || methods.length);

    // Giving monthly: Stripe's checkout when it's set, else any way marked
    // monthly. Gifts outside Stripe can't mark an account on their own, so
    // the page says how the thank-you reaches them.
    const monthlyWays = methods.filter((m) => m.monthly && m.link);
    const email = (window.Cave.account() || {}).email;
    let monthlyFoot;
    if (friend) {
      monthlyFoot = [el("p", { class: "support-thanks", text: sinceLine(since) })];
    } else {
      monthlyFoot = [
        data.monthly_url
          ? outLink(checkoutHref(data.monthly_url), amount ? `Give ${amount} a month` : "Give monthly", "btn btn-ember")
          : monthlyWays.length
            ? el("div", { class: "support-monthly-ways" }, monthlyWays.map((m, i) => outLink(m.link, `Monthly with ${m.name}`, i ? "btn btn-ghost" : "btn btn-ember")))
            : el("button", { class: "btn btn-ember", type: "button", disabled: "", text: methods.length ? "Any way below can repeat monthly" : "Giving opens soon" }),
        !data.monthly_url && methods.length
          ? el("p", { class: "faint support-note", text: `Giving monthly another way? Put ${email ? email : "the email you sign in with"} in your gift's note, and we'll add your thank-you gifts.` })
          : null,
        signedIn ? null : el("p", { class: "faint support-note" }, [el("a", { href: "#signin", text: "Sign in" }), " first, so the thank-you gifts reach your account."]),
      ];
    }
    const monthly = el("section", { class: "card warm support-option" }, [
      el("h2", { class: "support-option-title", text: "Become a friend of the cave" }),
      el("p", { class: "muted", text: amount && data.monthly_url ? `${amount} a month, and you can stop any time. As a thank-you:` : "Give monthly, and stop any time. As a thank-you:" }),
      el("ul", { class: "support-gifts" }, GIFTS.map((gift) => el("li", { text: gift }))),
      el("div", { class: "support-swatches", "aria-hidden": "true" }, [
        el("span", { class: "swatch", "data-swatch": "almond" }),
        el("span", { class: "swatch", "data-swatch": "cedar" }),
      ]),
      el("div", { class: "support-option-foot" }, monthlyFoot),
    ]);

    const ways = [
      data.once_url ? { kind: "card", name: "Card", note: "Through Stripe", link: checkoutHref(data.once_url) } : null,
      ...methods,
    ].filter(Boolean);
    const once = el("section", { class: "card support-option" }, [
      el("h2", { class: "support-option-title", text: "Give once" }),
      el("p", { class: "muted", text: "A gift of any size, whenever you'd like. It goes straight to keeping Adullam running." }),
      ways.length
        ? el("ul", { class: "give-list" }, ways.map(wayRow))
        : el("div", { class: "support-option-foot" }, [el("button", { class: "btn btn-ghost", type: "button", disabled: "", text: "Give once" })]),
    ]);

    const verse = el("blockquote", { class: "support-verse", hidden: "" }, [
      el("p", { class: "scripture", "data-text": "" }),
      el("footer", { class: "verse-ref", "data-ref": "" }),
    ]);

    page.replaceChildren(
      el("div", { class: "page-head" }, [
        el("div", {}, [
          el("h1", { class: "page-title", text: "Support Adullam" }),
          el("p", {
            class: "page-sub",
            text: "Adullam is free for everyone. There are no ads, and nobody's data is ever sold. What people give pays for the hosting, the database that holds the Bible and your cave, and Aquila's answers.",
          }),
        ]),
      ]),
      el("div", { class: "support-options" }, [monthly, once]),
      el("p", {
        class: "faint support-small",
        text: anything
          ? `${handledBy(data, methods)} Everything here stays free whether you give or not.`
          : "Giving opens soon. Thank you for wanting to. Everything here stays free whether you give or not.",
      }),
      verse
    );

    try {
      const v = await window.Cave.verseText(GIVING_VERSE);
      verse.querySelector("[data-text]").textContent = `"${v.text}"`;
      verse.querySelector("[data-ref]").textContent = `${GIVING_VERSE} · ${v.translation}`;
      verse.hidden = false;
    } catch {
      /* the page reads fine without it */
    }
  }

  // ---------------------------------------------------------------------
  // The home screen card, for people who aren't friends of the cave yet
  // ---------------------------------------------------------------------
  function snoozed() {
    try {
      return Number(localStorage.getItem(SNOOZE_KEY) || 0) > Date.now();
    } catch {
      return false;
    }
  }

  function snooze() {
    try {
      localStorage.setItem(SNOOZE_KEY, String(Date.now() + SNOOZE_DAYS * 24 * 60 * 60 * 1000));
    } catch {
      /* private window: it comes back next visit */
    }
  }

  function homeCard() {
    if (window.Cave.isFriend() || snoozed()) return null;
    const node = card("Keep the fire lit", { warm: true }, [
      el("p", { class: "muted", style: "margin:0;font-size:15px", text: "Adullam is free, with no ads. If it helps you, you can help keep it going." }),
      el("div", { class: "card-actions-row" }, [
        el("a", { class: "btn btn-ember btn-sm", href: "#support", text: "Support Adullam" }),
        el("button", {
          class: "act", type: "button", text: "Not now",
          onclick: () => {
            snooze();
            node.remove();
            toast("It'll be in the account menu whenever you want it.", { tone: "info" });
          },
        }),
      ]),
    ]);
    return node;
  }

  // ---------------------------------------------------------------------
  // The card in Settings
  // ---------------------------------------------------------------------
  function renderSettings() {
    const box = $("#supportSettings");
    if (!box) return;
    const since = window.Cave.supporterSince();
    const friend = window.Cave.isFriend();
    box.replaceChildren(
      el("p", { class: "section-sub", text: friend ? sinceLine(since) : "Free, with no ads. Giving keeps it that way." }),
      el("a", { class: friend ? "btn btn-ghost" : "btn btn-ember", href: "#support", text: friend ? "Give a little more" : "Support Adullam" })
    );
  }

  // ---------------------------------------------------------------------
  // The Giving tab on the admin desk (#desk, web/refuge.js::renderDesk):
  // the ways to give the page above shows, and marking friends of the cave
  // who give monthly outside Stripe. Everything set here is public.
  // ---------------------------------------------------------------------
  const KINDS = [["paypal", "PayPal"], ["venmo", "Venmo"], ["cashapp", "Cash App"], ["zelle", "Zelle"], ["other", "Something else"]];
  // For each kind: what its handle is called, an example, and a hint.
  const HANDLE_FIELD = {
    paypal: ["PayPal.me username", "adullam", "The page links to paypal.me/your-name. Have a PayPal donate link instead? Paste it under Link."],
    venmo: ["Venmo username", "@adullam", "The page links to your Venmo profile and shows the username to copy."],
    cashapp: ["$Cashtag", "$adullam", "The page links to cash.app/$your-tag."],
    zelle: ["Email or phone gifts go to", "give@example.org", "Zelle has no link: people send from their own bank's app, so the page shows this to copy."],
    other: ["Details to copy (optional)", "Account name, number and sort code", "A bank transfer, Givebutter, a church's giving page... Shown to anyone with a Copy button, so only what you're happy to share."],
  };
  const KIND_NAME = Object.fromEntries(KINDS);

  function methodSheet(existing, done) {
    const m = existing || { kind: "paypal", enabled: true, monthly: false };
    const msg = cave().formMessage();
    const field = (text, input, hint) => el("label", { class: "field-wrap" }, [text, input, hint || null]);
    const kind = el("select", { class: "field" }, KINDS.map(([value, text]) => el("option", { value, text, selected: value === m.kind })));
    const label = el("input", { class: "field", maxlength: "40", value: m.label || "" });
    const handle = el("input", { class: "field", maxlength: "80", autocapitalize: "off", spellcheck: "false", value: m.handle || "" });
    const handleHint = el("small", { class: "faint" });
    const handleLabel = el("span");
    const url = el("input", { class: "field", type: "text", inputmode: "url", autocapitalize: "off", spellcheck: "false", maxlength: "500", placeholder: "https://", value: m.url || "" });
    const note = el("input", { class: "field", maxlength: "200", placeholder: "Optional, like: Put \"Adullam\" in the note", value: m.note || "" });
    const monthly = el("input", { type: "checkbox", checked: !!m.monthly });
    const enabled = el("input", { type: "checkbox", checked: m.enabled !== false });
    const paint = () => {
      const [name, example, hint] = HANDLE_FIELD[kind.value];
      handleLabel.textContent = name;
      handle.placeholder = example;
      handleHint.textContent = hint;
      label.placeholder = kind.value === "other" ? "Bank transfer" : KIND_NAME[kind.value];
      label.required = kind.value === "other";
    };
    kind.addEventListener("change", paint);
    paint();
    const save = el("button", { class: "btn btn-ember btn-sm", type: "submit", text: existing ? "Save" : "Add" });
    const form = el("form", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "givingSheetTitle" }, [
      cave().sheetTitle("givingSheetTitle", existing ? "Edit a way to give" : "Add a way to give", "Everything here is shown to anyone on the Support page. Never a password or a login."),
      field("How", kind),
      field("Name shown", label),
      el("label", { class: "field-wrap" }, [handleLabel, handle, handleHint]),
      field("Link", url, el("small", { class: "faint", text: "Optional. Where Give goes, if not made from the username." })),
      field("Note", note),
      el("label", { class: "check-row" }, [monthly, " This link sets up a monthly gift"]),
      el("label", { class: "check-row" }, [enabled, " Show it on the Support page"]),
      msg.node,
      el("div", { class: "sheet-actions" }, [el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Cancel", onclick: () => close() }), save]),
    ]);
    const close = cave().overlay(form);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      save.disabled = true;
      const body = {
        kind: kind.value, label: label.value.trim() || null, handle: handle.value.trim() || null,
        url: url.value.trim() || null, note: note.value.trim() || null, monthly: monthly.checked, enabled: enabled.checked,
      };
      try {
        await cave().api(existing ? `/admin/giving/${existing.id}` : "/admin/giving", { method: existing ? "PUT" : "POST", body });
        close();
        toast(existing ? "Saved." : "Added to the Support page.", enabled.checked ? { action: { label: "View", href: "#support" } } : {});
        done();
      } catch (err) {
        msg.say(err.message, true);
        save.disabled = false;
      }
    });
  }

  // One way to give as the desk lists it, with what can be done to it.
  function adminRow(m, i, all, redraw) {
    const send = (body) => cave().api(`/admin/giving/${m.id}`, { method: "PUT", body: { ...m, ...body } });
    const move = async (by) => {
      const ids = all.map((x) => x.id);
      [ids[i], ids[i + by]] = [ids[i + by], ids[i]];
      await cave().api("/admin/giving/order", { method: "POST", body: { ids } });
      redraw();
    };
    const run = (fn) => async () => {
      try {
        await fn();
      } catch (err) {
        toast(err.message, { tone: "error" });
      }
    };
    const name = m.label || KIND_NAME[m.kind];
    const shown = m.kind === "cashapp" && m.handle ? `$${m.handle}` : m.kind === "venmo" && m.handle ? `@${m.handle}` : m.handle;
    return el("li", { class: `give-row${m.enabled ? "" : " is-off"}` }, [
      mark(m.kind, name),
      el("div", { class: "give-row-text" }, [
        el("strong", {}, [name, m.monthly ? el("span", { class: "badge plain", text: "Monthly" }) : null, m.enabled ? null : el("span", { class: "badge plain", text: "Hidden" })]),
        shown ? el("span", { class: "give-handle", text: shown }) : null,
        m.link ? el("small", { class: "faint give-link", text: m.link }) : null,
        m.note ? el("small", { class: "muted", text: m.note }) : null,
      ]),
      el("div", { class: "give-row-actions" }, [
        el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Edit", onclick: () => methodSheet(m, redraw) }),
        cave().moreMenu(`More for ${name}`, [
          { label: m.enabled ? "Hide from the page" : "Show on the page", onClick: run(async () => { await send({ enabled: !m.enabled }); redraw(); }) },
          i > 0 ? { label: "Move up", onClick: run(() => move(-1)) } : null,
          i < all.length - 1 ? { label: "Move down", onClick: run(() => move(1)) } : null,
          { label: "Delete", danger: true, onClick: run(async () => {
            if (!confirm(`Remove ${name} from the ways to give?`)) return;
            await cave().api(`/admin/giving/${m.id}`, { method: "DELETE" });
            redraw();
          }) },
        ].filter(Boolean)),
      ]),
    ]);
  }

  // Monthly givers outside Stripe are marked by hand, by their account email.
  function friendsCard() {
    const email = el("input", { class: "field", type: "email", required: true, autocapitalize: "off", spellcheck: "false", placeholder: "Their account email", "aria-label": "Account email" });
    const msg = cave().formMessage();
    const send = async (supporter) => {
      if (!email.reportValidity()) return;
      try {
        await cave().api("/admin/supporters", { method: "POST", body: { email: email.value.trim(), supporter } });
        msg.say(supporter ? `${email.value.trim()} is a friend of the cave now.` : `${email.value.trim()} is no longer marked.`);
        email.value = "";
      } catch (err) {
        msg.say(err.message, true);
      }
    };
    return el("section", { class: "card giving-card" }, [
      cave().titleInfo(el("h2", { class: "section-title", text: "Friends of the cave" }), "Someone giving monthly through PayPal, Venmo or anything but Stripe can't be marked automatically. When their gift's note names their account email, mark them here, and remove them when they stop."),
      el("div", { class: "giving-friends" }, [
        email,
        el("button", { class: "btn btn-ember btn-sm", type: "button", text: "Mark as friend", onclick: () => send(true) }),
        el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Remove", onclick: () => send(false) }),
      ]),
      msg.node,
    ]);
  }

  async function renderAdmin(box) {
    const redraw = () => { linksPromise = null; renderAdmin(box); };
    if (!box.firstChild) box.replaceChildren(el("div", { class: "empty", text: "Opening..." }));
    let data;
    try {
      data = await cave().api("/admin/giving");
    } catch (err) {
      box.replaceChildren(el("p", { class: "setup-note", text: err.message }), friendsCard());
      return;
    }
    const stripe = data.stripe.once || data.stripe.monthly
      ? `Stripe is set up (${[data.stripe.monthly ? "monthly" : null, data.stripe.once ? "once" : null].filter(Boolean).join(" and ")}).`
      : "Stripe isn't set up yet. Once it is, its links go in SUPPORT_ONCE_URL and SUPPORT_MONTHLY_URL on Render, and show above these.";
    box.replaceChildren(
      el("section", { class: "card giving-card" }, [
        el("div", { class: "card-head" }, [
          cave().titleInfo(el("h2", { class: "section-title", text: "Ways to give" }), "What the Support page offers, in this order. Add a PayPal, Venmo, Cash App or Zelle, or anything else with a link or details to copy. Everything here is public, so never a password or a login."),
          el("button", { class: "btn btn-ember btn-sm", type: "button", text: "Add", onclick: () => methodSheet(null, redraw) }),
        ]),
        data.methods.length
          ? el("ul", { class: "give-list" }, data.methods.map((m, i) => adminRow(m, i, data.methods, redraw)))
          : el("p", { class: "muted", text: "None yet. Until you add one, the Support page says giving opens soon." }),
        el("p", { class: "faint giving-stripe", text: stripe }),
        el("a", { class: "act", href: "#support", text: "See the Support page" }),
      ]),
      friendsCard(),
    );
  }

  window.Support = { show, homeCard, renderSettings, renderAdmin };
})();
