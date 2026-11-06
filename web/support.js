// Support Adullum (#support): give once, or monthly as a friend of the cave.
//
// The page is open to everyone, and the rest of the site points people here:
// the account menu, a card on the home screen, Settings, the welcome page and
// the signed-out page. The giving itself happens on a checkout page somewhere
// else (Stripe Payment Links, whose addresses come from GET /support); this
// file never touches a card. Until the links are set, the page still explains
// why Adullum asks and says giving opens soon, so no button leads nowhere.
//
// Friends of the cave get thank-you gifts only: a mark on their account chip
// and the supporter themes (cave.js::SUPPORTER_THEMES). Nothing anyone relies
// on is held back. See app/support.py for how someone becomes one.
//
// Reached as window.Support. Loaded after cave.js, whose helpers it borrows.
(function () {
  const { el, card, toast } = window.Cave;
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

  // The checkout link, carrying who is giving when they're signed in. Stripe
  // fills in their email, and keeps their id as client_reference_id so a
  // future webhook can mark the right account.
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

  function giveButton(url, label, className) {
    if (!url) return el("button", { class: className, type: "button", disabled: "", text: label });
    return el("a", { class: className, href: checkoutHref(url), target: "_blank", rel: "noopener", text: label });
  }

  function sinceLine(since) {
    const date = new Date(since);
    return Number.isNaN(date.getTime())
      ? "You're a friend of the cave. Thank you."
      : `You've been a friend of the cave since ${date.toLocaleDateString(undefined, { month: "long", year: "numeric" })}. Thank you.`;
  }

  // ---------------------------------------------------------------------
  // The page
  // ---------------------------------------------------------------------
  async function show() {
    const page = $("#supportPage");
    const data = await links();
    const signedIn = window.Cave.signedIn();
    const since = window.Cave.supporterSince();
    const amount = data.monthly_amount || "";

    const once = el("section", { class: "card support-option" }, [
      el("h2", { class: "support-option-title", text: "Give once" }),
      el("p", { class: "muted", text: "A gift of any size, whenever you'd like. It goes straight to keeping Adullum running." }),
      el("div", { class: "support-option-foot" }, [giveButton(data.once_url, "Give once", "btn btn-ghost")]),
    ]);

    const monthlyFoot = since
      ? [el("p", { class: "support-thanks", text: sinceLine(since) })]
      : [
          giveButton(data.monthly_url, amount ? `Give ${amount} a month` : "Give monthly", "btn btn-ember"),
          signedIn
            ? null
            : el("p", { class: "faint support-note" }, [el("a", { href: "#signin", text: "Sign in" }), " first, so the thank-you gifts reach your account."]),
        ];
    const monthly = el("section", { class: "card warm support-option" }, [
      el("h2", { class: "support-option-title", text: "Become a friend of the cave" }),
      el("p", { class: "muted", text: amount ? `${amount} a month, and you can stop any time. As a thank-you:` : "Give monthly, and stop any time. As a thank-you:" }),
      el("ul", { class: "support-gifts" }, GIFTS.map((gift) => el("li", { text: gift }))),
      el("div", { class: "support-swatches", "aria-hidden": "true" }, [
        el("span", { class: "swatch", "data-swatch": "almond" }),
        el("span", { class: "swatch", "data-swatch": "cedar" }),
      ]),
      el("div", { class: "support-option-foot" }, monthlyFoot),
    ]);

    const verse = el("blockquote", { class: "support-verse", hidden: "" }, [
      el("p", { class: "scripture", "data-text": "" }),
      el("footer", { class: "verse-ref", "data-ref": "" }),
    ]);

    page.replaceChildren(
      el("div", { class: "page-head" }, [
        el("div", {}, [
          el("h1", { class: "page-title", text: "Support Adullum" }),
          el("p", {
            class: "page-sub",
            text: "Adullum is free for everyone. There are no ads, and nobody's data is ever sold. What people give pays for the hosting, the database that holds the Bible and your cave, and Aquila's answers.",
          }),
        ]),
      ]),
      el("div", { class: "support-options" }, [monthly, once]),
      data.once_url || data.monthly_url
        ? el("p", { class: "faint support-small", text: "Giving is handled by Stripe, so Adullum never sees your card. Everything here stays free whether you give or not." })
        : el("p", { class: "faint support-small", text: "Giving opens soon. Thank you for wanting to. Everything here stays free whether you give or not." }),
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
    if (window.Cave.supporterSince() || snoozed()) return null;
    const node = card("Keep the fire lit", { warm: true }, [
      el("p", { class: "muted", style: "margin:0;font-size:15px", text: "Adullum is free, with no ads. If it helps you, you can help keep it going." }),
      el("div", { class: "card-actions-row" }, [
        el("a", { class: "btn btn-ember btn-sm", href: "#support", text: "Support Adullum" }),
        el("button", {
          class: "act", type: "button", text: "Not now",
          onclick: () => {
            snooze();
            node.remove();
            toast("It'll be in the account menu whenever you want it.");
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
    box.replaceChildren(
      el("p", { class: "section-sub", text: since ? sinceLine(since) : "Adullum is free, with no ads. Giving keeps it that way, and friends of the cave get two extra themes as a thank-you." }),
      el("a", { class: since ? "btn btn-ghost" : "btn btn-ember", href: "#support", text: since ? "Give a little more" : "Support Adullum" })
    );
  }

  window.Support = { show, homeCard, renderSettings };
})();
