// Connections (the nav item, once called "Map"): a force-directed graph of
// how passages connect in meaning. Not a geographic map.
//
// Seeds come from an answer's citations, a journal entry, or the search box.
// Each seed's neighbours come from GET /connections (app/connections.py): its
// classic cross-references (dashed lines) and the verses nearest in meaning
// anywhere else in the canon (solid lines); a pair that is both is drawn
// solid in the accent colour. Clicking a node opens it in the side panel;
// "Follow this thread" fetches that verse's own neighbours and grows the
// graph from there. Clicking a line, or a neighbour listed in the panel,
// asks Aquila why the two connect (POST /connections/explain).
//
// d3 is only fetched the first time the graph opens, so the chat page itself
// pays nothing for it.
(function () {
  const D3_URL = "https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js";
  const GENRES = ["law", "history", "poetry", "prophecy", "gospel", "epistle", "apocalyptic"];

  let d3Promise = null;
  function loadD3() {
    if (window.d3) return Promise.resolve(window.d3);
    if (!d3Promise) {
      d3Promise = new Promise((resolve, reject) => {
        const s = document.createElement("script");
        s.src = D3_URL;
        s.onload = () => resolve(window.d3);
        s.onerror = () => {
          d3Promise = null;
          reject(new Error("The graph library didn't load. Check your connection and try again."));
        };
        document.head.append(s);
      });
    }
    return d3Promise;
  }

  function apiBase() {
    const el = document.getElementById("apiBase");
    return ((el && el.value) || location.origin).trim().replace(/\/$/, "");
  }
  function translation() {
    const el = document.getElementById("translation");
    return (el && el.value.trim()) || "BSB";
  }

  function genreColor(genre) {
    return getComputedStyle(document.documentElement).getPropertyValue(`--g-${genre}`).trim() || "#888";
  }

  // ---------------------------------------------------------------------
  let ui = null; // the open overlay's elements and graph state, or null

  function close() {
    if (!ui) return;
    ui.sim && ui.sim.stop();
    ui.root.remove();
    document.removeEventListener("keydown", ui.onKey);
    document.body.style.overflow = "";
    ui = null;
  }

  function build() {
    const root = document.createElement("div");
    root.className = "graph-overlay";
    root.setAttribute("role", "dialog");
    root.setAttribute("aria-modal", "true");
    root.setAttribute("aria-label", "Connections");
    root.innerHTML = `
      <div class="graph-top">
        <div>
          <h3>How Scripture connects</h3>
          <div class="graph-sub">Dashed lines are classic cross-references, solid lines join verses close in meaning. Tap a line to ask why.</div>
        </div>
        <form class="graph-search">
          <input type="text" placeholder="Add a passage, e.g. Psalm 23:1" aria-label="Add a passage" />
          <button class="btn-primary" type="submit">Add</button>
        </form>
        <button class="icon-btn graph-close" type="button" aria-label="Close the graph">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>
        </button>
      </div>
      <div class="graph-stage">
        <svg aria-label="Graph of connected verses"></svg>
        <div class="graph-hint">Drag to move · scroll or pinch to zoom · tap a verse or a line</div>
        <div class="graph-status"></div>
        <div class="graph-legend"></div>
      </div>`;
    document.body.append(root);
    document.body.style.overflow = "hidden";

    const legend = root.querySelector(".graph-legend");
    for (const g of GENRES) {
      const span = document.createElement("span");
      const dot = document.createElement("i");
      dot.style.background = genreColor(g);
      span.append(dot, document.createTextNode(g));
      legend.append(span);
    }
    // The two kinds of line, each a toggle, and the credit the
    // cross-reference data's licence (CC BY) asks for.
    const kinds = document.createElement("div");
    kinds.className = "graph-kinds";
    for (const [kind, label] of LINK_KINDS) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = `graph-kind kind-${kind}`;
      b.setAttribute("aria-pressed", "true");
      b.innerHTML = `<svg viewBox="0 0 28 8" aria-hidden="true"><line x1="1" y1="4" x2="27" y2="4"/></svg>`;
      b.append(document.createTextNode(label));
      b.addEventListener("click", () => toggleKind(kind, b));
      kinds.append(b);
    }
    const credit = document.createElement("a");
    credit.className = "graph-credit";
    credit.href = "https://www.openbible.info/labs/cross-references/";
    credit.target = "_blank";
    credit.rel = "noopener";
    credit.textContent = "Cross-references: OpenBible.info, CC BY";
    kinds.append(credit);
    legend.append(kinds);

    const onKey = (e) => e.key === "Escape" && close();
    document.addEventListener("keydown", onKey);
    root.querySelector(".graph-close").addEventListener("click", close);
    root.querySelector(".graph-search").addEventListener("submit", (e) => {
      e.preventDefault();
      const input = root.querySelector(".graph-search input");
      const ref = input.value.trim();
      if (!ref) return;
      input.value = "";
      grow([ref]);
    });

    return {
      root,
      onKey,
      // Scoped to the stage: the close button carries an <svg> icon too.
      svgEl: root.querySelector(".graph-stage svg"),
      stage: root.querySelector(".graph-stage"),
      status: root.querySelector(".graph-status"),
      nodes: new Map(),
      links: new Map(),
      expanded: new Set(),
      selected: null,
      sim: null,
      // Which kinds of line are showing (the legend's toggles).
      shown: { cross_ref: true, meaning: true },
    };
  }

  const LINK_KINDS = [["cross_ref", "Cross-reference"], ["meaning", "Close in meaning"]];

  function toggleKind(kind, button) {
    if (!ui) return;
    ui.shown[kind] = !ui.shown[kind];
    button.setAttribute("aria-pressed", String(ui.shown[kind]));
    if (window.d3 && ui.linkLayer) paintLinks(window.d3);
  }

  const idOf = (end) => end.id || end;
  const isCrossRef = (l) => l.kinds.includes("cross_ref");
  const isMeaning = (l) => l.kinds.includes("meaning");

  function setStatus(text) {
    if (ui) ui.status.textContent = text || "";
  }

  async function fetchConnections(refs) {
    const params = new URLSearchParams({ refs: refs.join(";"), translation: translation(), k: "6" });
    const resp = await fetch(`${apiBase()}/connections?${params}`);
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Couldn't find connections for those passages.");
    return body;
  }

  // Merge a /connections response into the running graph. New nodes start
  // next to whatever they connect to, so growth reads as branching outward
  // instead of nodes flying in from the corner.
  function merge(data) {
    const added = [];
    for (const n of data.nodes) {
      // Seeds already have their neighbours drawn. Keyed by the server's id,
      // since "Psalm 23:1" typed in comes back as "Psalms 23:1".
      if (n.seed) ui.expanded.add(n.id);
      const existing = ui.nodes.get(n.id);
      if (existing) {
        if (n.seed) existing.seed = true;
        continue;
      }
      ui.nodes.set(n.id, { ...n });
      added.push(n.id);
    }
    for (const e of data.edges) {
      const key = [e.source, e.target].sort().join("|");
      const kinds = e.kinds || ["meaning"];
      const prev = ui.links.get(key);
      if (!prev) {
        ui.links.set(key, { source: e.source, target: e.target, weight: e.weight, kinds: [...kinds], votes: e.votes || 0, passage: e.passage || null, key });
        continue;
      }
      // The same pair seen again (from another seed): keep everything known about it.
      kinds.forEach((k) => prev.kinds.includes(k) || prev.kinds.push(k));
      if (e.weight != null && (prev.weight == null || prev.weight < e.weight)) prev.weight = e.weight;
      if (e.votes) prev.votes = Math.max(prev.votes, e.votes);
      if (e.passage && !prev.passage) prev.passage = e.passage;
    }
    const { width, height } = ui.svgEl.getBoundingClientRect();
    for (const id of added) {
      const node = ui.nodes.get(id);
      const anchorLink = [...ui.links.values()].find((l) => (l.target.id || l.target) === id || (l.source.id || l.source) === id);
      const anchorId = anchorLink && ((anchorLink.source.id || anchorLink.source) === id ? anchorLink.target.id || anchorLink.target : anchorLink.source.id || anchorLink.source);
      const anchor = anchorId && ui.nodes.get(anchorId);
      if (anchor && anchor.x !== undefined) {
        node.x = anchor.x + (Math.random() - 0.5) * 40;
        node.y = anchor.y + (Math.random() - 0.5) * 40;
      } else {
        node.x = width / 2 + (Math.random() - 0.5) * 80;
        node.y = height / 2 + (Math.random() - 0.5) * 80;
      }
    }
    return added;
  }

  function closeness(weight) {
    if (weight == null) return 0.4;
    return Math.min(1, Math.max(0, (weight - 0.35) / 0.35));
  }

  // How strong a line looks: meaning by similarity, a cross-reference by how
  // many readers voted for it (most useful links have tens to hundreds).
  function strength(l) {
    const votes = isCrossRef(l) ? Math.min(1, Math.log10(1 + l.votes) / 2.3) : 0;
    return Math.max(isMeaning(l) ? closeness(l.weight) : 0, votes);
  }

  function linkClass(l) {
    const kind = isCrossRef(l) && isMeaning(l) ? "both" : isCrossRef(l) ? "cross-ref" : "meaning";
    const hidden = !l.kinds.some((k) => ui.shown[k]);
    return `graph-link ${kind}${hidden ? " is-hidden" : ""}`;
  }

  function paintLinks() {
    ui.linkLayer.selectAll("line.graph-link").attr("class", linkClass);
    ui.linkLayer.selectAll("line.graph-link-hit").attr("class", (l) => `graph-link-hit${l.kinds.some((k) => ui.shown[k]) ? "" : " is-hidden"}`);
  }

  function shortLabel(n) {
    return `${n.book} ${n.chapter}:${n.verse}`;
  }

  function draw(d3) {
    const svg = d3.select(ui.svgEl);
    if (!ui.layer) {
      ui.layer = svg.append("g");
      ui.linkLayer = ui.layer.append("g");
      ui.nodeLayer = ui.layer.append("g");
      ui.zoom = d3.zoom().scaleExtent([0.25, 4]).on("zoom", (ev) => ui.layer.attr("transform", ev.transform));
      svg.call(ui.zoom).on("dblclick.zoom", null);
      svg.on("click", (ev) => {
        if (ev.target === ui.svgEl) select(null);
      });
    }
    const nodes = [...ui.nodes.values()];
    const links = [...ui.links.values()];

    const linkSel = ui.linkLayer
      .selectAll("line.graph-link")
      .data(links, (d) => d.key)
      .join("line")
      .attr("class", linkClass)
      // Cosine similarity between verses mostly lands in 0.35-0.7, so the
      // scale is stretched over that band rather than the full 0-1.
      .attr("stroke-width", (d) => 0.9 + strength(d) * 3.6)
      .attr("stroke-opacity", (d) => 0.35 + strength(d) * 0.55);
    // A wide invisible line over each one, so a thin line is easy to tap.
    const hitSel = ui.linkLayer
      .selectAll("line.graph-link-hit")
      .data(links, (d) => d.key)
      .join((enter) =>
        enter.append("line").on("click", (ev, d) => {
          ev.stopPropagation();
          selectLink(d);
        })
      )
      .attr("class", (l) => `graph-link-hit${l.kinds.some((k) => ui.shown[k]) ? "" : " is-hidden"}`);

    const nodeSel = ui.nodeLayer
      .selectAll("g.graph-node")
      .data(nodes, (d) => d.id)
      .join((enter) => {
        const g = enter.append("g").attr("class", "graph-node").attr("tabindex", 0).attr("role", "button");
        g.append("circle");
        g.append("text").attr("dy", "0.32em");
        g.append("title");
        g.on("click", (ev, d) => {
          ev.stopPropagation();
          select(d);
        });
        g.on("keydown", (ev, d) => {
          if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            select(d);
          }
        });
        g.call(
          d3
            .drag()
            .on("start", (ev, d) => {
              if (!ev.active) ui.sim.alphaTarget(0.25).restart();
              d.fx = d.x;
              d.fy = d.y;
            })
            .on("drag", (ev, d) => {
              d.fx = ev.x;
              d.fy = ev.y;
            })
            .on("end", (ev, d) => {
              if (!ev.active) ui.sim.alphaTarget(0);
              d.fx = null;
              d.fy = null;
            })
        );
        return g;
      });

    nodeSel
      .classed("seed", (d) => d.seed)
      .classed("expanded", (d) => ui.expanded.has(d.id))
      .classed("selected", (d) => ui.selected === d.id)
      .attr("aria-label", (d) => `${d.book} ${d.chapter}:${d.verse}`);
    nodeSel.select("circle").attr("r", (d) => (d.seed ? 11 : 7)).attr("fill", (d) => genreColor(d.genre));
    nodeSel.select("text").attr("x", (d) => (d.seed ? 15 : 11)).text(shortLabel);
    nodeSel.select("title").text((d) => `${d.book} ${d.chapter}:${d.verse}\n${d.text}`);

    if (!ui.sim) {
      const { width, height } = ui.svgEl.getBoundingClientRect();
      ui.sim = d3
        .forceSimulation()
        .force("charge", d3.forceManyBody().strength(-260))
        .force("center", d3.forceCenter(width / 2, height / 2).strength(0.05))
        .force("collide", d3.forceCollide().radius((d) => (d.seed ? 34 : 26)))
        .force("x", d3.forceX(width / 2).strength(0.03))
        .force("y", d3.forceY(height / 2).strength(0.03));
    }
    ui.sim
      .nodes(nodes)
      .force("link", d3.forceLink(links).id((d) => d.id).distance((d) => 60 + (1 - strength(d)) * 200).strength(0.6))
      .on("tick", () => {
        for (const sel of [linkSel, hitSel]) {
          sel.attr("x1", (d) => d.source.x).attr("y1", (d) => d.source.y).attr("x2", (d) => d.target.x).attr("y2", (d) => d.target.y);
        }
        nodeSel.attr("transform", (d) => `translate(${d.x},${d.y})`);
      })
      .alpha(0.9)
      .restart();
  }

  async function grow(refs, focusId) {
    if (!ui) return;
    setStatus(ui.nodes.size ? "" : "Tracing the threads...");
    try {
      const [d3, data] = await Promise.all([loadD3(), fetchConnections(refs)]);
      if (!ui) return;
      merge(data);
      setStatus("");
      draw(d3);
      if (focusId && ui.nodes.get(focusId)) select(ui.nodes.get(focusId));
    } catch (err) {
      if (!ui) return;
      if (ui.nodes.size) {
        window.Cave ? window.Cave.toast(err.message) : alert(err.message);
      } else {
        setStatus(err.message);
      }
    }
  }

  // Marks the chosen node or line, and clears the side panel.
  function mark({ node = null, link = null } = {}) {
    ui.selected = node;
    if (window.d3) {
      const svg = window.d3.select(ui.svgEl);
      svg.selectAll("g.graph-node").classed("selected", (n) => ui.selected === n.id);
      svg.selectAll("line.graph-link").classed("selected", (l) => link === l.key);
    }
    const old = ui.stage.querySelector(".graph-panel");
    if (old) old.remove();
  }

  // A link's two ends as passages. A cross-reference to a run of verses
  // ("Proverbs 8:22-30") is drawn to its first verse but explained whole.
  function linkEnds(l) {
    const end = (id) => (l.passage && (l.passage === id || l.passage.startsWith(`${id}-`)) ? l.passage : id);
    return [end(idOf(l.source)), end(idOf(l.target))];
  }

  function kindTags(l) {
    const tags = [];
    if (isCrossRef(l)) tags.push(l.votes ? `Cross-reference · ${l.votes} votes` : "Cross-reference");
    if (isMeaning(l)) tags.push("Close in meaning");
    return tags;
  }

  function panelButton(actions, label, fn, cls = "chip-btn") {
    const b = document.createElement("button");
    b.type = "button";
    b.className = cls;
    b.textContent = label;
    b.addEventListener("click", fn);
    actions.append(b);
    return b;
  }

  // "Why are these connected?": both passages and Aquila's few sentences on
  // the link, asked once per link and kept for the rest of the visit.
  const explained = new Map();
  async function selectLink(l) {
    if (!ui) return;
    mark({ link: l.key });
    const [a, b] = linkEnds(l);
    const panel = document.createElement("div");
    panel.className = "graph-panel";
    const h = document.createElement("h4");
    h.textContent = `${a} and ${b}`;
    const meta = document.createElement("div");
    meta.className = "panel-tags";
    for (const t of kindTags(l)) {
      const tag = document.createElement("span");
      tag.className = `panel-tag${t.startsWith("Cross") ? " cross-ref" : ""}`;
      tag.textContent = t;
      meta.append(tag);
    }
    panel.append(h, meta);

    for (const end of [l.source, l.target]) {
      const n = ui.nodes.get(idOf(end));
      if (!n) continue;
      const quote = document.createElement("button");
      quote.type = "button";
      quote.className = "panel-quote";
      quote.title = `Open ${n.id}`;
      quote.innerHTML = "<strong></strong><span></span>";
      quote.querySelector("strong").textContent = n.id;
      quote.querySelector("span").textContent = n.text;
      quote.addEventListener("click", () => select(n));
      panel.append(quote);
    }

    const why = document.createElement("div");
    why.className = "panel-why";
    why.innerHTML = '<p class="panel-why-label">Why they connect</p><p class="panel-why-text"></p>';
    const whyText = why.querySelector(".panel-why-text");
    panel.append(why);

    const actions = document.createElement("div");
    actions.className = "card-actions";
    panelButton(actions, "Ask Aquila more", () => {
      close();
      window.AdullumApp && window.AdullumApp.submitQuery(`How do ${a} and ${b} connect?`);
    });
    panelButton(actions, `Read ${a}`, () => {
      close();
      if (window.Reader && window.AdullumApp) window.AdullumApp.go(window.Reader.href(a));
    });
    panel.append(actions);
    if (isCrossRef(l)) {
      const credit = document.createElement("p");
      credit.className = "panel-credit";
      credit.innerHTML = 'Cross-reference from <a href="https://www.openbible.info/labs/cross-references/" target="_blank" rel="noopener">OpenBible.info</a> (CC BY), built on the Treasury of Scripture Knowledge.';
      panel.append(credit);
    }
    ui.stage.append(panel);

    const key = `${a}|${b}|${translation()}`;
    if (explained.has(key)) {
      whyText.textContent = explained.get(key);
      return;
    }
    whyText.textContent = "Asking Aquila...";
    why.classList.add("is-loading");
    try {
      const resp = await fetch(`${apiBase()}/connections/explain`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ a, b, translation: translation(), kinds: l.kinds }),
      });
      const body = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Aquila couldn't explain this one right now.");
      explained.set(key, body.explanation);
      if (panel.isConnected) whyText.textContent = body.explanation;
    } catch (err) {
      if (panel.isConnected) whyText.textContent = err.message;
    } finally {
      why.classList.remove("is-loading");
    }
  }

  function select(d) {
    if (!ui) return;
    mark({ node: d ? d.id : null });
    if (!d) return;

    const panel = document.createElement("div");
    panel.className = "graph-panel";
    const h = document.createElement("h4");
    h.textContent = `${d.book} ${d.chapter}:${d.verse}`;
    const meta = document.createElement("div");
    meta.className = "panel-meta";
    meta.textContent = `${d.genre} · ${d.testament === "OT" ? "Old Testament" : "New Testament"} · ${translation()}`;
    const p = document.createElement("p");
    p.textContent = d.text;
    const actions = document.createElement("div");
    actions.className = "card-actions";

    const ref = `${d.book} ${d.chapter}:${d.verse}`;
    const btn = (label, fn, cls = "chip-btn") => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = cls;
      b.textContent = label;
      b.addEventListener("click", fn);
      actions.append(b);
      return b;
    };
    if (!ui.expanded.has(d.id)) {
      btn("Follow this thread", () => {
        ui.expanded.add(d.id);
        grow([ref], d.id);
      });
    }
    btn("Ask Aquila", () => {
      close();
      window.AdullumApp && window.AdullumApp.submitQuery(`What does ${ref} mean, and how does it connect with the rest of Scripture?`);
    });
    btn("Read in context", () => {
      close();
      if (window.Reader && window.AdullumApp) window.AdullumApp.go(window.Reader.href(ref));
    });
    btn("Save to journal", () => window.Cave && window.Cave.openJournal({ passage_ref: ref, verse_text: d.text }));

    // Everything this verse is joined to, each a way into "why".
    const joined = [...ui.links.values()]
      .filter((l) => (idOf(l.source) === d.id || idOf(l.target) === d.id) && l.kinds.some((k) => ui.shown[k]))
      .sort((x, y) => strength(y) - strength(x));
    let list = null;
    if (joined.length) {
      list = document.createElement("div");
      list.className = "panel-links";
      const label = document.createElement("p");
      label.className = "panel-why-label";
      label.textContent = "Connected to";
      list.append(label);
      for (const l of joined) {
        // linkEnds follows [source, target], so the far end is the one that isn't d.
        const [start, end] = linkEnds(l);
        const other = idOf(l.source) === d.id ? end : start;
        const row = document.createElement("button");
        row.type = "button";
        row.className = "panel-link";
        row.innerHTML = "<strong></strong><span></span><em>Why?</em>";
        row.querySelector("strong").textContent = other;
        row.querySelector("span").textContent = kindTags(l).map((t) => t.split(" ·")[0]).join(" · ");
        row.addEventListener("click", () => selectLink(l));
        list.append(row);
      }
    }

    panel.append(...[h, meta, p, actions, list].filter(Boolean));
    ui.stage.append(panel);
  }

  function open(refs) {
    close();
    ui = build();
    const seeds = (refs || []).filter(Boolean);
    if (!seeds.length) {
      setStatus("Add a passage above to begin. Try John 1:1, Psalm 23:1, or Romans 8:28.");
      setTimeout(() => ui && ui.root.querySelector(".graph-search input").focus(), 50);
      return;
    }
    grow(seeds);
  }

  window.Graph = { open, close };
})();
