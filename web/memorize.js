// Verses to learn by heart: the cave's Memorize tab, the practice sheet, the
// home card that appears when something is due, and `add`, which the reader
// and the verse of the day call.
//
// The schedule lives on the server (app/memorize.py::next_review): after each
// verse the person says "Not yet", "Almost" or "Got it", and the server picks
// the day it comes back. Practice shows the first letter of every word as the
// prompt, then the whole verse. Loaded after web/cave.js, whose helpers it
// borrows through window.Cave at call time.
(function () {
  const GRADES = [
    ["again", "Not yet", "btn-ghost"],
    ["hard", "Almost", "btn-ghost"],
    ["good", "Got it", "btn-ember"],
  ];

  const cave = () => window.Cave;
  const app = () => window.AdullumApp;
  const el = (...args) => cave().el(...args);

  // "For God so loved the world," -> "F G s l t w,". Keeps the punctuation so
  // the rhythm of the sentence is still there to lean on.
  function firstLetters(text) {
    return text
      .split(/\s+/)
      .filter(Boolean)
      .map((word) => {
        const m = word.match(/^([^\p{L}\p{N}]*)([\p{L}\p{N}])[\p{L}\p{N}'’-]*(.*)$/u);
        return m ? m[1] + m[2] + m[3] : word;
      })
      .join(" ");
  }

  // Whole days from today (local) until an ISO date.
  function daysUntil(isoDate) {
    const [y, m, d] = isoDate.split("-").map(Number);
    const [ty, tm, td] = cave().localToday().split("-").map(Number);
    return Math.round((Date.UTC(y, m - 1, d) - Date.UTC(ty, tm - 1, td)) / 86400000);
  }

  function statusBadge(v) {
    if (v.status === "due") return el("span", { class: "badge", text: "Due today" });
    if (v.status === "learned") return el("span", { class: "badge learned", text: "Learned" });
    const days = daysUntil(v.due);
    return el("span", { class: "badge plain", text: days <= 1 ? "Next tomorrow" : `Next in ${days} days` });
  }

  // ---------------------------------------------------------------------
  // Adding a verse
  // ---------------------------------------------------------------------
  // Returns true when the verse is now on the list (newly or already).
  async function add(ref, translation) {
    if (!cave().signedIn()) {
      cave().toast("Create a free account to learn verses by heart.");
      app().go("join");
      return false;
    }
    try {
      const v = await cave().api("/me/memorize", { method: "POST", body: { ref, translation, today: cave().localToday() } });
      cave().toast(v.already ? `You're already learning ${v.ref}.` : `${v.ref} added to your verses to learn.`);
      return true;
    } catch (err) {
      cave().toast(err.message);
      return false;
    }
  }

  // ---------------------------------------------------------------------
  // Practice
  // ---------------------------------------------------------------------
  // Practises the given verses, or everything due today when none are given.
  // A verse marked "Not yet" comes round once more at the end of the session.
  async function practise(onDone, verses) {
    let queue = verses;
    if (!queue) {
      try {
        queue = (await cave().api(`/me/memorize?today=${cave().localToday()}`)).verses.filter((v) => v.status === "due");
      } catch (err) {
        cave().toast(err.message);
        return;
      }
    }
    if (!queue.length) {
      cave().toast("Nothing is due today. Well done.");
      return;
    }
    queue = [...queue];
    const total = queue.length;
    const seenAgain = new Set();
    let practised = 0;
    let revealed = false;

    const sheet = el("div", { class: "sheet practice", role: "dialog", "aria-modal": "true", "aria-labelledby": "practiceRef" });
    const finish = () => {
      close();
      if (onDone) onDone();
    };
    const close = cave().overlay(sheet);

    function showCard() {
      const v = queue[0];
      revealed = false;
      const hint = el("p", { class: "scripture-lg practice-text", text: firstLetters(v.verse_text) });
      const reveal = el("button", { class: "btn btn-ember btn-block", type: "button", text: "Show the verse" });
      const grades = el("div", { class: "practice-grades", hidden: true }, GRADES.map(([grade, label, style]) =>
        el("button", { class: `btn ${style}`, type: "button", text: label, onclick: () => grade_(v, grade) })
      ));
      reveal.onclick = () => {
        revealed = true;
        hint.textContent = v.verse_text;
        hint.classList.add("is-revealed");
        reveal.hidden = true;
        grades.hidden = false;
        grades.lastChild.focus();
      };
      sheet.replaceChildren(
        el("div", { class: "row-between" }, [
          el("p", { class: "kicker", style: "margin:0", text: `${Math.min(practised + 1, total)} of ${total}` }),
          el("button", { class: "linkish", type: "button", text: "Stop", onclick: finish }),
        ]),
        el("h3", { id: "practiceRef", text: `${v.ref} · ${v.translation}` }),
        el("p", { class: "faint", style: "margin:0 0 6px;font-size:14px", text: "Say it from memory, using the first letters as a guide." }),
        hint,
        reveal,
        grades
      );
      reveal.focus();
    }

    async function grade_(v, grade) {
      try {
        await cave().api(`/me/memorize/${v.id}/review`, { method: "POST", body: { grade, today: cave().localToday() } });
      } catch (err) {
        cave().toast(err.message);
        return;
      }
      queue.shift();
      if (grade === "again" && !seenAgain.has(v.id)) {
        seenAgain.add(v.id);
        queue.push(v);
      } else {
        practised += 1;
      }
      if (queue.length) showCard();
      else showDone();
    }

    function showDone() {
      sheet.replaceChildren(
        el("h3", { id: "practiceRef", text: "Well done" }),
        el("p", { class: "sheet-lede", text: `${total} ${total === 1 ? "verse" : "verses"} practised. Each one will come back when it's time, a little further apart as it settles in.` }),
        el("div", { class: "sheet-actions" }, el("button", { class: "btn btn-ember btn-sm", type: "button", text: "Close", onclick: finish }))
      );
      sheet.querySelector("button").focus();
    }

    // Once the verse is showing, 1, 2 and 3 answer "Not yet", "Almost" and
    // "Got it". (Before that, Space or Enter presses the focused Show button.)
    sheet.addEventListener("keydown", (e) => {
      if (!queue.length) return;
      const i = ["1", "2", "3"].indexOf(e.key);
      if (revealed && i >= 0) {
        e.preventDefault();
        grade_(queue[0], GRADES[i][0]);
      }
    });

    showCard();
  }

  // ---------------------------------------------------------------------
  // The Memorize tab
  // ---------------------------------------------------------------------
  function verseCard(v, rerender) {
    return el("article", { class: "entry memory-card fade-in" }, [
      el("div", { class: "entry-meta" }, [statusBadge(v), el("span", { class: "badge plain", text: v.translation })]),
      el("h3", {}, el("a", { href: `#${window.Reader.href(v.ref)}`, text: v.ref })),
      el("p", { class: "verse", text: v.verse_text }),
      el("div", { class: "entry-actions" }, [
        el("button", { class: "act", type: "button", text: "Practise", onclick: () => practise(rerender, [v]) }),
        el("button", {
          class: "act danger", type: "button", text: "Remove",
          onclick: async () => {
            if (!confirm(`Stop learning ${v.ref}? Its progress goes too.`)) return;
            try {
              await cave().api(`/me/memorize/${v.id}`, { method: "DELETE" });
              rerender();
            } catch (err) {
              cave().toast(err.message);
            }
          },
        }),
      ]),
    ]);
  }

  async function renderTab(panel) {
    const rerender = () => renderTab(panel);
    const data = await cave().api(`/me/memorize?today=${cave().localToday()}`);
    if (!data.total) {
      panel.replaceChildren(el("div", { class: "empty" }, [
        el("strong", { text: "No verses to learn yet" }),
        "In the Bible, tap a verse and choose Memorize, or tap Learn it on the verse for today. A few minutes a day is enough.",
        el("div", {}, el("a", { class: "btn btn-ember btn-sm", href: "#bible", text: "Open the Bible" })),
      ]));
      return;
    }
    const counts = [`${data.total} ${data.total === 1 ? "verse" : "verses"}`, `${data.learned} learned`].join(" · ");
    const head = el("section", { class: "card warm memorize-head" }, [
      el("div", {}, [
        el("h2", { class: "section-title", text: data.due ? `${data.due} due today` : "All caught up for today" }),
        el("p", { class: "muted", style: "font-size:15px", text: counts }),
      ]),
      data.due
        ? el("button", { class: "btn btn-ember btn-sm", type: "button", text: "Practise now", onclick: () => practise(rerender) })
        : null,
    ]);
    panel.replaceChildren(head, el("div", { class: "entries" }, data.verses.map((v) => verseCard(v, rerender))));
  }

  // ---------------------------------------------------------------------
  // Home: only shown when something is due today
  // ---------------------------------------------------------------------
  // `summary` is app/memorize.py::memorize_summary.
  function homeCard(summary, onChange) {
    if (!summary.due) return null;
    return cave().card("Verses to learn", {}, [
      el("p", { class: "big-q", text: `${summary.due} ${summary.due === 1 ? "verse is" : "verses are"} ready to practise` }),
      el("p", { class: "muted", style: "font-size:15px", text: "A couple of minutes keeps them fresh." }),
      el("div", { class: "card-actions-row" }, [
        el("button", { class: "btn btn-ember btn-sm", type: "button", text: "Practise", onclick: () => practise(onChange) }),
        el("a", { class: "act", href: "#memorize", text: "All verses" }),
      ]),
    ]);
  }

  window.Memorize = { add, practise, renderTab, homeCard, firstLetters };
})();
