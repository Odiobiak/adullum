// Saved (#bible/saved): everything the person saves with one tap, newest
// first. Verses come from the reader's Save, the verse for today and a
// sermon's week after; answers from Save under any reply from Aquila.
// app/saved.py keeps them, and a verse's words always come from the database,
// never from this page. It replaced Memorize in the Bible tab.
//
// Loaded after web/cave.js, whose helpers it borrows through window.Cave.
(function () {
  const cave = () => window.Cave;
  const el = (...args) => cave().el(...args);
  const toast = (...args) => cave().toast(...args);
  const app = () => window.AdullumApp;

  const FILTERS = [["all", "Everything"], ["verse", "Verses"], ["answer", "Answers"]];
  let filter = "all";

  // ---------------------------------------------------------------------
  // Saving, called from the reader, answers, home and Church. Each resolves
  // the saved item, or null when it couldn't (the toast says why).
  // ---------------------------------------------------------------------
  async function post(path, body) {
    if (!cave().signedIn()) {
      toast("Create a free account to save things.", { tone: "info" });
      return null;
    }
    try {
      return await cave().api(path, { method: "POST", body });
    } catch (err) {
      toast(err.message, { tone: "error" });
      return null;
    }
  }

  async function verse(ref, translation) {
    const item = await post("/me/saved/verse", { ref, translation });
    if (item) toast(item.already ? `${item.ref} is already saved.` : `${item.ref} saved.`, { action: { label: "View", href: "#bible/saved" } });
    return item;
  }

  async function answer({ question, answer: text, citations = [] }) {
    const item = await post("/me/saved/answer", {
      question,
      answer: text,
      citations: citations.map(({ book, chapter, verse: v }) => ({ book, chapter, verse: v })),
    });
    if (item) toast("Saved.", { action: { label: "View", href: "#bible/saved" } });
    return item;
  }

  // Resolves true once it's gone.
  async function remove(id) {
    try {
      await cave().api(`/me/saved/${id}`, { method: "DELETE" });
      return true;
    } catch (err) {
      toast(err.message, { tone: "error" });
      return false;
    }
  }

  // ---------------------------------------------------------------------
  // The Saved page
  // ---------------------------------------------------------------------
  function meta(label, item) {
    return el("div", { class: "entry-meta" }, [el("span", { class: "badge plain", text: label }), el("span", { text: cave().when(item.created_at) })]);
  }

  // The "⋯" menu every card ends with, after an optional primary action;
  // Remove takes the card off the page.
  function actions(primary, item, node, extra, onRemoved) {
    return el("div", { class: "entry-actions" }, [
      primary,
      cave().moreMenu("More", [
        ...extra,
        { label: "Remove", danger: true, onClick: async () => { if (await remove(item.id)) { node.remove(); onRemoved(); } } },
      ]),
    ]);
  }

  function verseCard(item, onRemoved) {
    const node = el("article", { class: "entry saved-card fade-in" });
    node.append(
      meta(item.translation, item),
      el("h3", {}, el("a", { href: `#${window.Reader.href(item.ref)}`, text: item.ref })),
      el("p", { class: "verse", text: item.verse_text }),
      actions(
        null, item, node,
        [
          { label: "Write about it", onClick: () => cave().openJournal({ passage_ref: item.ref, verse_text: item.verse_text }) },
          { label: "See connections", onClick: () => window.Graph.open([`${item.book} ${item.chapter}:${item.verse_start}`]) },
          { label: "Share", onClick: () => cave().shareCard({ ref: item.ref, text: item.verse_text, translation: item.translation }) },
        ],
        onRemoved
      )
    );
    return node;
  }

  // An answer shows its opening until "Read all" opens the rest.
  function answerCard(item, onRemoved) {
    const node = el("article", { class: "entry saved-card fade-in" });
    const body = el("div", { class: "answer saved-answer", html: app().renderAnswerHtml(item.answer) });
    const toggle = el("button", {
      class: "act", type: "button", text: "Read all", "aria-expanded": "false",
      onclick: () => {
        const open = node.classList.toggle("is-open");
        toggle.textContent = open ? "Show less" : "Read all";
        toggle.setAttribute("aria-expanded", String(open));
      },
    });
    node.append(
      meta("Aquila", item),
      el("h3", { text: item.question }),
      body,
      actions(toggle, item, node, [
        { label: "Ask again", onClick: () => app().submitQuery(item.question) },
        { label: "Write about it", onClick: () => cave().openJournal({ question: item.question, answer: item.answer, citations: item.citations }) },
      ], onRemoved)
    );
    return node;
  }

  async function renderTab(panel) {
    let items = await cave().api("/me/saved");
    const draw = () => {
      if (!items.length) {
        panel.replaceChildren(el("div", { class: "empty" }, [
          el("strong", { text: "Nothing saved yet" }),
          "Tap Save on a verse as you read, or under any answer from Aquila, and it lands here.",
          el("div", {}, el("a", { class: "btn btn-ember btn-sm", href: "#bible", text: "Start reading" })),
        ]));
        return;
      }
      const shown = filter === "all" ? items : items.filter((i) => i.kind === filter);
      const forget = (item) => () => { items = items.filter((i) => i !== item); draw(); };
      panel.replaceChildren(
        cave().listBar(`${shown.length} saved`, cave().filterSelect("What to show", FILTERS, filter, (value) => { filter = value; draw(); })),
        shown.length
          ? el("div", { class: "entries" }, shown.map((i) => (i.kind === "verse" ? verseCard(i, forget(i)) : answerCard(i, forget(i)))))
          : el("p", { class: "empty", text: filter === "verse" ? "No verses saved yet." : "No answers saved yet." })
      );
    };
    draw();
  }

  window.Saved = { verse, answer, remove, renderTab };
})();
