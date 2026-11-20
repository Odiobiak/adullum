// The Numbers tab on the admin desk (#desk, web/refuge.js::renderDesk): how
// many people use Adullam, what they use, and how the server is holding up.
//
// Everything comes from GET /admin/numbers (app/numbers.py) as counts only,
// never a person or anything anyone wrote. The server's memory shows even
// before the migration runs, since it's read from the process itself.
//
// Reached as window.Numbers. Loaded after cave.js, whose helpers it borrows.
(function () {
  const { el } = window.Cave;
  const cave = () => window.Cave;

  // Each part of the app, by the key admin_numbers gives it.
  const FEATURES = {
    conversations: "Aquila conversations",
    journal: "Journal entries",
    prayers: "Prayers",
    sermons: "Sermon notes",
    declarations: "Declarations",
    amens_posts: "Amens posts",
    amens_prayed: "Amens prayed for",
    saved: "Saved",
    bible_notes: "Bible notes",
    highlights: "Highlights",
    plans: "Reading plans",
    reflections: "Reflections",
    churches: "Churches added",
    fasts: "Fasts",
    writings: "Refuge writings kept",
    talks: "Refuge talks kept",
  };
  // What's counted against the daily limits (app/quota.py), as columns.
  const USAGE = [["question", "Questions"], ["talk", "Refuge talks"], ["voice", "Calls"], ["speech", "Spoken"]];

  const short = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  const count = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

  function tile(n, label) {
    return el("div", { class: "desk-stat" }, [el("strong", { text: String(n) }), el("span", { text: label })]);
  }

  function table(head, rows) {
    return el("div", { class: "num-scroll" }, [
      el("table", { class: "num-table" }, [
        el("thead", {}, [el("tr", {}, head.map((h, i) => el("th", { scope: "col", class: i ? "n" : "", text: h })))]),
        el("tbody", {}, rows.map((r) => el("tr", {}, r.map((c, i) => el(i ? "td" : "th", i ? { class: "n", text: String(c) } : { scope: "row", text: c }))))),
      ]),
    ]);
  }

  function section(title, about, children) {
    return el("section", { class: "card num-card" }, [cave().titleInfo(el("h2", { class: "section-title", text: title }), about), ...children]);
  }

  // Memory against the instance's limit. Render restarts the server at its
  // limit, so a reading that climbs hour after hour with nobody about is a leak.
  function serverCard(s) {
    const used = s.memory_mb;
    const share = used && s.limit_mb ? Math.min(1, used / s.limit_mb) : null;
    const line = used == null
      ? "Memory shows once this runs on Render."
      : `${used} MB${s.limit_mb ? ` of ${s.limit_mb} MB` : ""} in use`;
    return section("Server", "Read from the server as this page opened. Up is how long since it last started; a restart empties memory, so compare readings at the same uptime.", [
      el("p", { class: `num-mem${share > 0.85 ? " high" : ""}`, text: line }),
      share == null ? null : el("div", { class: "num-meter", role: "meter", "aria-valuemin": "0", "aria-valuemax": String(s.limit_mb), "aria-valuenow": String(used), "aria-label": "Memory in use" }, [
        el("span", { style: `width:${Math.round(share * 100)}%` }),
      ]),
      el("p", { class: "faint", text: `Up ${s.up_hours} hours · ${count(s.threads, "thread")}` }),
    ].filter(Boolean));
  }

  // People each day: one bar a day for the last 30, hover or focus to read one.
  function daysChart(days) {
    const top = Math.max(1, ...days.map((d) => d.active));
    const say = (d) => `${short(d.day)}: ${count(d.active, "person", "people")}${d.joined ? `, ${d.joined} joined` : ""}`;
    const last = days[days.length - 1];
    const readout = el("p", { class: "num-readout", "aria-live": "polite", text: say(last) });
    const bars = el("div", { class: "num-bars", role: "group", "aria-label": "People each day, last 30 days" }, days.map((d) => {
      const bar = el("span", { class: "num-bar", tabindex: "0", "aria-label": say(d) }, [
        el("i", { style: `height:${d.active ? Math.max(4, (d.active / top) * 100) : 0}%` }),
      ]);
      const show = () => { readout.textContent = say(d); };
      bar.addEventListener("mouseenter", show);
      bar.addEventListener("focus", show);
      return bar;
    }));
    bars.addEventListener("mouseleave", () => { readout.textContent = say(last); });
    return [
      readout,
      bars,
      el("div", { class: "num-axis faint" }, [el("span", { text: short(days[0].day) }), el("span", { text: `most: ${top}` }), el("span", { text: "today" })]),
      el("details", { class: "num-details" }, [
        el("summary", { text: "As a table" }),
        table(["Day", "People", "Joined"], days.slice().reverse().map((d) => [short(d.day), d.active, d.joined])),
      ]),
    ];
  }

  // What costs money, by day, from the daily limits (kept a week).
  function usageTable(usage, spend) {
    const days = [...new Set([...usage.map((u) => u.day), ...spend.map((s) => s.day)])].sort().reverse();
    if (!days.length) return el("p", { class: "muted", text: "Nothing counted this week yet." });
    const cell = (day, kind) => {
      const u = usage.find((r) => r.day === day && r.kind === kind);
      if (!u) return "0";
      return kind === "question" ? `${u.uses} (${u.people} in, ${u.guests} guests)` : String(u.uses);
    };
    return table(
      ["Day", ...USAGE.map(([, label]) => label), "Spend"],
      days.map((day) => [short(day), ...USAGE.map(([kind]) => cell(day, kind)), `$${(spend.find((s) => s.day === day)?.usd ?? 0).toFixed(2)}`]),
    );
  }

  function featureTable(features) {
    const rows = features
      .slice()
      .sort((a, b) => b.month - a.month || b.total - a.total)
      .map((f) => [FEATURES[f.key] || f.key, f.week, f.month, f.people_month, f.total]);
    return table(["Part", "7 days", "30 days", "People, 30 days", "All time"], rows);
  }

  async function renderAdmin(box) {
    if (!box.firstChild) box.replaceChildren(el("div", { class: "empty", text: "Opening..." }));
    let data;
    try {
      data = await cave().api(`/admin/numbers?today=${cave().localToday()}`);
    } catch (err) {
      box.replaceChildren(el("p", { class: "setup-note", text: err.message }));
      return;
    }
    const c = data.counts;
    if (!c) {
      box.replaceChildren(el("p", { class: "setup-note", text: data.setup }), serverCard(data.server));
      return;
    }
    box.replaceChildren(
      el("div", { class: "desk-stats" }, [
        tile(c.active_today, "Active today"),
        tile(c.active_week, "Active this week"),
        tile(c.active_month, "Active this month"),
        tile(c.joined_week, "Joined this week"),
        tile(c.accounts, "Accounts"),
      ]),
      section("People each day", "Signed-in people who opened Adullam that day, by the day on their own device. Guests aren't counted here; their questions are under Aquila and voice.", daysChart(c.days)),
      section("What people make", "How many of each thing were made, and by how many people. Things since deleted aren't counted.", [featureTable(c.features)]),
      section("Aquila and voice, this week", "From the daily limits, kept a week. Questions count Aquila, Pray with Aquila, Declare and the plan builder; in means signed in. Spend is the estimate the budget uses.", [usageTable(c.usage || [], c.spend || [])]),
      serverCard(data.server),
    );
  }

  window.Numbers = { renderAdmin };
})();
