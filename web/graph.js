// Connections (the nav item, once called "Map"): a force-directed graph of
// how passages connect in meaning. Not a geographic map.
//
// Seeds come from an answer's citations, a journal entry, or the search box.
// Each seed's neighbours come from GET /connections (app/connections.py),
// which finds the verses nearest in meaning anywhere else in the canon.
// Clicking a node opens it in the side panel; "Follow this thread" fetches
// that verse's own neighbours and grows the graph from there.
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
          <div class="graph-sub">Each line joins two verses close in meaning. Thicker means closer.</div>
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
        <div class="graph-hint">Drag to move · scroll or pinch to zoom · tap a verse to read it</div>
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
    };
  }

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
      const prev = ui.links.get(key);
      if (!prev || prev.weight < e.weight) ui.links.set(key, { source: e.source, target: e.target, weight: e.weight, key });
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
    return Math.min(1, Math.max(0, (weight - 0.35) / 0.35));
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
      .selectAll("line")
      .data(links, (d) => d.key)
      .join("line")
      .attr("class", "graph-link")
      // Cosine similarity between verses mostly lands in 0.35-0.7, so the
      // scale is stretched over that band rather than the full 0-1.
      .attr("stroke-width", (d) => 0.8 + closeness(d.weight) * 4)
      .attr("stroke-opacity", (d) => 0.3 + closeness(d.weight) * 0.6);

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
      .force("link", d3.forceLink(links).id((d) => d.id).distance((d) => 60 + (1 - d.weight) * 220).strength(0.6))
      .on("tick", () => {
        linkSel.attr("x1", (d) => d.source.x).attr("y1", (d) => d.source.y).attr("x2", (d) => d.target.x).attr("y2", (d) => d.target.y);
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

  function select(d) {
    if (!ui) return;
    ui.selected = d ? d.id : null;
    window.d3 && window.d3.select(ui.svgEl).selectAll("g.graph-node").classed("selected", (n) => ui.selected === n.id);
    const old = ui.stage.querySelector(".graph-panel");
    if (old) old.remove();
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

    panel.append(h, meta, p, actions);
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
