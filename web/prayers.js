// The prayer list: the cave's Prayers tab, the sheet for adding or editing a
// prayer, marking one answered, and the small card on the home screen.
//
// Prayers live in app/prayers.py. Each one is open until it's marked answered,
// with an optional line on how. Loaded after web/cave.js, whose helpers (el,
// overlay, api, toast, card) it borrows through window.Cave at call time.
(function () {
  const ICON = {
    check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
    aquila: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/></svg>',
    book: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M4 21V5M9 7h6"/></svg>',
  };

  const cave = () => window.Cave;
  const app = () => window.AdullumApp;
  const el = (...args) => cave().el(...args);

  // Which half of the list the tab is showing: "open" or "answered".
  let showing = "open";

  function shortDate(iso) {
    return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  }

  function clip(text, n) {
    return text.length > n ? `${text.slice(0, n - 3)}...` : text;
  }

  // Asks Aquila to pray alongside the person. "pray" mode answers with a few
  // verses, a prayer for the request and encouragement to keep praying, not a
  // study (app/agent/nodes.py::pray_with). A linked passage goes first so
  // retrieval (app/retrieval.py::parse_reference) starts from it.
  function prayWithAquila(p) {
    const ask = `Would you pray with me about this? ${p.body}`;
    app().submitQuery(p.passage_ref ? `On ${p.passage_ref}: ${ask}` : ask, { mode: "pray" });
  }

  // ---------------------------------------------------------------------
  // Sheets
  // ---------------------------------------------------------------------
  // Add a prayer, or edit one when `existing` is given.
  function openSheet({ existing } = {}, onSaved) {
    if (!cave().signedIn()) {
      cave().toast("Create a free account to keep a prayer list.");
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
      el("h3", { id: "prayerTitle", text: existing ? "Edit prayer" : "A new prayer" }),
      el("p", { class: "sheet-lede", text: "Only you can see your prayer list. If Aquila's memory is on, she'll keep it in mind when you talk." }),
      el("label", { class: "field-wrap" }, ["What you're praying for", body]),
      el("label", { class: "field-wrap" }, ["A verse to hold onto (optional)", passage]),
      msg.node,
      el("div", { class: "sheet-actions" }, [el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Cancel", onclick: () => close() }), save]),
    ]);
    const close = cave().overlay(form);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const text = body.value.trim();
      if (!text) return msg.say("Write a few words about what you're praying for.", true);
      save.disabled = true;
      try {
        const payload = { body: text, passage_ref: passage.value.trim() || null };
        const prayer = existing
          ? await cave().api(`/me/prayers/${existing.id}`, { method: "PATCH", body: payload })
          : await cave().api("/me/prayers", { method: "POST", body: payload });
        close();
        cave().toast(existing ? "Saved." : "Added to your prayer list.");
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
      el("div", { class: "sheet-actions" }, [el("button", { class: "btn btn-ghost btn-sm", type: "button", text: "Cancel", onclick: () => close() }), save]),
    ]);
    const close = cave().overlay(form);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      save.disabled = true;
      try {
        await cave().api(`/me/prayers/${p.id}`, { method: "PATCH", body: { status: "answered", answer_note: note.value.trim() || null } });
        close();
        cave().toast("Marked answered. Thanks be to God.");
        if (onSaved) onSaved();
      } catch (err) {
        msg.say(err.message, true);
        save.disabled = false;
      }
    });
  }

  // ---------------------------------------------------------------------
  // The Prayers tab
  // ---------------------------------------------------------------------
  function prayerCard(p, rerender) {
    const answered = p.status === "answered";
    const node = el("article", { class: `entry prayer-card${answered ? " is-answered" : ""} fade-in` });
    const meta = el("div", { class: "entry-meta" }, [
      answered
        ? el("span", { class: "badge answered", html: `${ICON.check}<span>Answered ${shortDate(p.answered_at)}</span>` })
        : el("span", { text: `Praying since ${shortDate(p.created_at)}` }),
    ]);
    const act = (label, onclick, extra = "") => el("button", { class: `act${extra}`, type: "button", onclick }, label);
    const remove = act("Delete", async () => {
      if (!confirm("Delete this prayer? This can't be undone.")) return;
      try {
        await cave().api(`/me/prayers/${p.id}`, { method: "DELETE" });
        rerender();
      } catch (err) {
        cave().toast(err.message);
      }
    }, " danger");

    const actions = answered
      ? [
          act("Reopen", async () => {
            try {
              await cave().api(`/me/prayers/${p.id}`, { method: "PATCH", body: { status: "open" } });
              rerender();
            } catch (err) {
              cave().toast(err.message);
            }
          }),
          remove,
        ]
      : [
          el("button", { class: "act", type: "button", html: `${ICON.aquila}<span>Pray with Aquila</span>`, onclick: () => prayWithAquila(p) }),
          act("Edit", () => openSheet({ existing: p }, rerender)),
          remove,
          // Quiet on purpose, at the end of the row: there when it's time,
          // without pressing the question every time the list is opened.
          el("button", { class: "act-quiet", type: "button", html: `${ICON.check}<span>Mark answered</span>`, onclick: () => openAnsweredSheet(p, rerender) }),
        ];

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
      el("div", { class: "entry-actions" }, actions),
    ].filter(Boolean));
    return node;
  }

  async function renderTab(panel) {
    const rerender = () => renderTab(panel);
    const rows = await cave().api("/me/prayers");
    const open = rows.filter((p) => p.status === "open");
    const answered = rows
      .filter((p) => p.status === "answered")
      .sort((a, b) => (b.answered_at || "").localeCompare(a.answered_at || ""));
    if (!rows.length) {
      panel.replaceChildren(el("div", { class: "empty" }, [
        el("strong", { text: "Your prayer list is empty" }),
        "Keep what you're praying for here. When one is answered, mark it, and look back on how God has been faithful.",
        el("div", {}, el("button", { class: "btn btn-ember btn-sm", type: "button", text: "Add a prayer", onclick: () => openSheet({}, rerender) })),
      ]));
      return;
    }
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
      bar,
      list.length ? el("div", { class: "entries prayer-list" }, list.map((p) => prayerCard(p, rerender))) : el("p", { class: "muted", text: empty })
    );
  }

  // ---------------------------------------------------------------------
  // Home
  // ---------------------------------------------------------------------
  // `summary` is app/prayers.py::prayer_summary.
  function homeCard(summary, onChange) {
    const add = el("button", { class: "act", type: "button", text: "Add a prayer", onclick: () => openSheet({}, onChange) });
    if (!summary.total) {
      return cave().card("Prayer list", {}, [
        el("p", { class: "muted", style: "margin:0 0 14px;font-size:15px", text: "Keep what you're praying for, and mark the day it's answered." }),
        el("div", { class: "card-actions-row", style: "margin-top:0" }, add),
      ]);
    }
    const latest = summary.latest_open;
    const answeredLine = summary.answered_recently
      ? `${summary.answered_recently} answered in the last month.`
      : null;
    return cave().card(cave().cardHead("Prayer list", el("span", { class: "faint", style: "font-size:13px", text: `${summary.open} open` })), {}, [
      latest ? el("p", { class: "prayer-body", style: "font-size:16px", text: clip(latest.body, 160) }) : el("p", { class: "muted", text: "No open prayers right now." }),
      answeredLine ? el("p", { class: "answered-line" }, [el("span", { html: ICON.check }), el("span", { text: answeredLine })]) : null,
      el("div", { class: "card-actions-row" }, [
        el("a", { class: "btn btn-ghost btn-sm", href: "#prayers", text: "Open list" }),
        add,
      ]),
    ]);
  }

  window.Prayers = { renderTab, openSheet, homeCard };
})();
