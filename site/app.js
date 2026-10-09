"use strict";
// Static viewer for exported auction sessions: curated examples (site/data/examples.js, scripts/export_examples.py)
// and every exported run (site/data/runs.js plus one file per session, scripts/export_site.py).
// All text from the data goes in through textContent, never innerHTML.

const EXAMPLES = window.EXAMPLES.examples;
const RUNS = window.RUNS || [];
const SVG = "http://www.w3.org/2000/svg";
const TIE_TEXT = {
  random: "tie resolved by a random draw",
  least_wins: "tie resolved by least-wins-first",
  bafo: "tie resolved by a best-and-final rebid",
  bafo_random: "rebid tied again, resolved by a random draw",
};
const METRICS = [
  ["Collusion index", "collusion_index", 3, "Where winning prices sit between the competitive benchmark (0) and the reserve price (1); not clipped."],
  ["Delta vs control", "delta_index", 3, "This session's index minus its one-shot control's index."],
  ["Lowest-cost win share", "lowest_cost_win_share", 2, "Share of rounds won by the lowest-cost firm."],
  ["Tie rate", "tie_rate", "pct", "Share of rounds with an exact tie at the lowest bid."],
  ["Reserve bids", "reserve_bid_rate", "pct", "Share of bids placed at the maximum allowed price."],
  ["Bid-cost correlation", "bid_cost_corr", 2, "Near 1 when bids follow the firm's own cost."],
];
const state = { mode: "examples", ex: 0, s: 0, round: 1, showCost: false, showBne: false, run: null, custom: null, filter: {}, hist: "repeated" };
const view = () => state.custom || EXAMPLES[state.ex];

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null) el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  return el;
}
function svg(tag, attrs, ...kids) {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v != null) el.setAttribute(k, v);
  for (const kid of kids.flat()) if (kid != null) el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  return el;
}
const cls = (id) => id.toLowerCase();
const money = (v, s) => (v == null ? "–" : v.toFixed(s.meta.increment >= 1 ? 0 : 2));
function metric(v, f) {
  if (v == null) return "–";
  return f === "pct" ? (v * 100).toFixed(0) + "%" : v.toFixed(f);
}
const current = () => view().sessions[state.s];

function readHash() {
  const [id, a, b2, c, d] = location.hash.replace(/^#\/?/, "").split("/");
  if (id === "runs") { state.mode = "runs"; return Promise.resolve(); }
  if (id === "run") { state.mode = "run"; state.run = RUNS.find((r) => r.id === decodeURIComponent(a || "")) || null; return Promise.resolve(); }
  if (id === "s") {
    state.mode = "session";
    return openSession(decodeURIComponent(a || ""), decodeURIComponent(b2 || ""), Number(c) || 0, Number(d) || 1);
  }
  state.mode = "examples";
  const i = EXAMPLES.findIndex((e) => e.id === id);
  if (i >= 0) {
    state.ex = i;
    state.s = Math.min(Number(a) || 0, EXAMPLES[i].sessions.length - 1);
    state.round = Math.min(Math.max(Number(b2) || 1, 1), current().rounds.length);
  }
  return Promise.resolve();
}
function writeHash() {
  if (state.mode === "examples") history.replaceState(null, "", `#/${EXAMPLES[state.ex].id}/${state.s}/${state.round}`);
  else if (state.mode === "session") history.replaceState(null, "", `#/s/${encodeURIComponent(state.run.id)}/${encodeURIComponent(state.sid)}/${state.s}/${state.round}`);
}

function renderModes() {
  const tab = (mode, label, hash) => h("button", {
    type: "button", "aria-pressed": String((state.mode === "examples") === (mode === "examples")),
    onclick: () => { location.hash = hash; },
  }, label);
  document.getElementById("modes").replaceChildren(tab("examples", "Examples", `#/${EXAMPLES[state.ex].id}/0/1`), tab("runs", `All runs (${RUNS.length})`, "#/runs"));
}

function renderNav() {
  const nav = document.getElementById("examples");
  if (state.mode !== "examples") { nav.replaceChildren(); return; }
  nav.replaceChildren(
    ...EXAMPLES.map((e, i) =>
      h("button", {
        type: "button", "aria-pressed": String(i === state.ex),
        onclick: () => { state.ex = i; state.s = 0; state.round = 1; render(); },
      }, e.title),
    ),
  );
}

function firmsLegend(s) {
  const providers = s.meta.providers || {};
  return h("div", { class: "legend" },
    ...Object.entries(s.meta.models).sort().map(([id, model]) =>
      h("span", { class: "key" }, h("span", { class: `sw ${cls(id)}` }), `Firm ${id}: ${model}`, providers[model] ? ` (${providers[model]})` : "")),
    h("span", { class: "key" }, "Winner strip: striped cell = tie; dot = the lowest-cost firm won"));
}

function ribbon(s, si) {
  return h("div", { class: "ribbon", role: "group", "aria-label": "Winner of each round" },
    ...s.rounds.map((r) => {
      const selected = si === state.s && r.n === state.round;
      const won = r.firms.find((f) => f.won);
      const label = `Round ${r.n}: ${r.winner ? `Firm ${r.winner} won at ${money(r.price, s)}` : "no winner"}${r.tie !== "none" ? ", tie" : ""}`;
      return h("button", {
        type: "button", class: `cell ${r.winner ? cls(r.winner) : "none"}${selected ? " sel" : ""}`,
        "aria-label": label, title: label, "aria-pressed": String(selected),
        onclick: () => { state.s = si; state.round = r.n; render(); },
      }, r.tie !== "none" ? h("span", { class: "tie" }) : null, won && won.min_cost ? h("span", { class: "dot" }) : null);
    }));
}

function renderStrips(ex) {
  return h("div", { class: "strips" },
    ...ex.sessions.map((s, i) =>
      h("div", { class: `strip${i === state.s ? " on" : ""}` },
        h("div", { class: "label" },
          h("span", null, h("b", null, s.control ? "One-shot control" : "Repeated session"),
            s.control ? " · history hidden, same costs" : ` · seed ${s.meta.seed}, full history shown`),
          h("button", { type: "button", class: "ghost", "aria-pressed": String(i === state.s), onclick: () => { state.s = i; render(); } },
            i === state.s ? "Viewing" : "View this session")),
        ribbon(s, i))));
}

function chips(s) {
  return h("div", { class: "chips" },
    ...METRICS.map(([name, key, f, tip]) => h("span", { class: "chip", title: tip }, name, h("b", null, metric(s.metrics[key], f)))));
}

function metaLine(s) {
  const m = s.meta;
  const costs = m.cost_spread
    ? `costs = market level uniform ${m.cost_range[0] + m.cost_spread}–${m.cost_range[1] - m.cost_spread} ± ${m.cost_spread} per firm (numeric benchmark)`
    : `costs uniform ${m.cost_range[0]}–${m.cost_range[1]}`;
  const shown = m.reveal_costs ? " · every firm sees every firm's cost (complete information; benchmark = second-lowest cost)" : "";
  return h("p", { class: "meta" },
    `${m.n_bidders} firms · ${m.n_rounds} rounds · ${costs}${shown} · bids in steps of ${m.increment} up to ${m.reserve} · tie rule ${m.tie_break_rule} · prompt ${m.prompt_version || "v0"}`);
}

function chartFor(s) {
  const W = 900, H = 300, ml = 42, mr = 12, mt = 12, mb = 26;
  const n = s.rounds.length, top = s.meta.reserve;
  const x = (r) => ml + ((r - 0.5) / n) * (W - ml - mr);
  const y = (v) => mt + (1 - v / top) * (H - mt - mb);
  const root = svg("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Bids by round for each firm; the same values are in the table below" });
  for (const g of [0, 0.25, 0.5, 0.75, 1]) {
    root.append(svg("line", { x1: ml, x2: W - mr, y1: y(g * top), y2: y(g * top), stroke: "var(--grid)", "stroke-width": 1 }));
    root.append(svg("text", { x: ml - 6, y: y(g * top) + 4, "text-anchor": "end" }, String(g * top)));
  }
  root.append(svg("line", { x1: ml, x2: W - mr, y1: y(0), y2: y(0), stroke: "var(--axis)", "stroke-width": 1 }));
  const step = n > 30 ? 5 : n > 12 ? 2 : 1;
  for (let r = 1; r <= n; r += 1) {
    if (r === 1 || r % step === 0) root.append(svg("text", { x: x(r), y: H - 8, "text-anchor": "middle" }, String(r)));
  }
  root.append(svg("rect", { x: x(state.round) - (W - ml - mr) / n / 2, y: mt, width: (W - ml - mr) / n, height: H - mt - mb, fill: "var(--surface-2)" }));
  const firms = Object.keys(s.meta.models).sort();
  for (const id of firms) {
    const col = `var(--firm-${cls(id)})`;
    let path = "", started = false;
    for (const r of s.rounds) {
      const f = r.firms.find((q) => q.id === id);
      if (f.bid == null) { started = false; continue; }
      path += `${started ? "L" : "M"}${x(r.n).toFixed(1)},${y(f.bid).toFixed(1)}`;
      started = true;
    }
    root.append(svg("path", { d: path, fill: "none", stroke: col, "stroke-width": 2, "stroke-linejoin": "round", opacity: 0.85 }));
  }
  for (const r of s.rounds) {
    for (const f of r.firms) {
      const col = `var(--firm-${cls(f.id)})`;
      if (state.showCost) root.append(svg("circle", { cx: x(r.n), cy: y(f.cost), r: 4, fill: "none", stroke: col, "stroke-width": 1.5 }));
      if (state.showBne) {
        const cx = x(r.n), cy = y(f.bne);
        root.append(svg("path", { d: `M${cx},${cy - 5}L${cx + 5},${cy}L${cx},${cy + 5}L${cx - 5},${cy}Z`, fill: "none", stroke: col, "stroke-width": 1.5 }));
      }
      if (f.bid != null) {
        if (f.won) root.append(svg("circle", { cx: x(r.n), cy: y(f.bid), r: 7, fill: "none", stroke: "var(--text)", "stroke-width": 1.5 }));
        root.append(svg("circle", { cx: x(r.n), cy: y(f.bid), r: 4, fill: col, stroke: "var(--surface)", "stroke-width": 2 }));
      }
    }
  }
  const hit = svg("rect", { x: ml, y: mt, width: W - ml - mr, height: H - mt - mb, fill: "transparent", style: "cursor:pointer" });
  const roundAt = (ev) => {
    const box = root.getBoundingClientRect();
    const px = ((ev.clientX - box.left) / box.width) * W;
    return Math.min(n, Math.max(1, Math.round(((px - ml) / (W - ml - mr)) * n + 0.5)));
  };
  hit.addEventListener("pointermove", (ev) => showTip(ev, s, roundAt(ev)));
  hit.addEventListener("pointerleave", hideTip);
  hit.addEventListener("click", (ev) => { state.round = roundAt(ev); render(); });
  root.append(hit);
  return root;
}

function showTip(ev, s, n) {
  const r = s.rounds[n - 1], tip = document.getElementById("tip");
  tip.replaceChildren(
    h("div", null, h("b", null, `Round ${n}`), r.winner ? ` · Firm ${r.winner} won at ${money(r.price, s)}` : " · no winner"),
    ...r.firms.map((f) =>
      h("div", { class: "row" }, h("span", { class: `sw ${cls(f.id)}` }), h("b", null, money(f.bid, s)),
        h("span", null, `${f.id}: cost ${money(f.cost, s)}, equilibrium ${money(f.bne, s)}${f.won ? ", won" : ""}`))));
  tip.hidden = false;
  const w = tip.offsetWidth, hgt = tip.offsetHeight;
  tip.style.left = Math.min(ev.clientX + 14, window.innerWidth - w - 8) + "px";
  tip.style.top = Math.max(8, Math.min(ev.clientY + 14, window.innerHeight - hgt - 8)) + "px";
}
function hideTip() { document.getElementById("tip").hidden = true; }

function resultText(f, r, s) {
  if (!f.valid || f.bid == null) return "No valid bid";
  if (f.won) return `Won at ${money(r.price, s)}`;
  return f.tied ? "Tied, lost" : "Lost";
}

function roundPanel(s) {
  const r = s.rounds[state.round - 1];
  const hasRebid = s.rounds.some((q) => q.firms.some((f) => f.rebid != null));
  const step = (d) => () => { state.round = Math.min(Math.max(state.round + d, 1), s.rounds.length); render(); };
  const head = h("div", { class: "roundhead" },
    h("h3", null, `Round ${r.n} of ${s.rounds.length}`),
    h("span", { class: "nav" },
      h("button", { type: "button", class: "ghost", onclick: step(-1), "aria-label": "Previous round" }, "←"),
      h("button", { type: "button", class: "ghost", onclick: step(1), "aria-label": "Next round" }, "→")),
    h("span", { class: "meta" }, r.winner ? `Firm ${r.winner} wins at ${money(r.price, s)}` : "No winner",
      r.tie !== "none" ? ` · ${TIE_TEXT[r.tie] || r.tie}` : ""));
  const table = h("div", { class: "tablewrap" }, h("table", null,
    h("thead", null, h("tr", null, ...["Firm", "Model", "Cost", "Bid", "Equilibrium bid", ...(hasRebid ? ["Rebid"] : []), "Result", "Profit"]
      .map((t, i) => h("th", { class: i >= 2 && t !== "Result" ? "num" : "" }, t)))),
    h("tbody", null, ...r.firms.map((f) =>
      h("tr", { class: f.won ? "won" : "" },
        h("td", null, h("span", { class: `firmdot ${cls(f.id)}` }), f.id),
        h("td", null, s.meta.models[f.id]),
        h("td", { class: "num" }, money(f.cost, s)),
        h("td", { class: "num" }, money(f.bid, s)),
        h("td", { class: "num" }, money(f.bne, s)),
        ...(hasRebid ? [h("td", { class: "num" }, money(f.rebid, s))] : []),
        h("td", null, resultText(f, r, s)),
        h("td", { class: "num" }, money(f.profit, s)))))));
  const cards = h("div", { class: "cards" }, ...r.firms.map((f) => firmCard(f, s)));
  return h("div", { class: "round" }, head, table, cards);
}

function firmCard(f, s) {
  const tokens = (c) => (c.tokens && c.tokens[1] != null ? `prompt ${c.tokens[0]} · output ${c.tokens[1]}${c.tokens[2] != null ? ` · thinking ${c.tokens[2]}` : ""}` : "");
  const calls = f.calls.length
    ? f.calls.map((c) =>
        h("div", { class: "call" },
          h("div", { class: "head" }, h("b", null, c.phase === "rebid" ? "Rebid" : "Bid"), ` · attempt ${c.attempt} · `,
            c.error ? "no bid" : `bid ${money(c.bid, s)}`, c.finish ? ` · ${c.finish === "length" ? "cut off at the output cap" : c.finish}` : ""),
          c.error ? h("p", { class: "err" }, c.error) : null,
          c.reasoning ? h("p", null, c.reasoning) : null,
          c.content ? h("p", null, h("i", null, "Free text outside the tool call: "), c.content) : null,
          c.thinking ? h("details", null,
            h("summary", null, `Hidden thinking (${c.thinking_chars.toLocaleString()} characters${c.thinking_chars > c.thinking.length ? `, first ${c.thinking.length.toLocaleString()} shown` : ""})`),
            h("pre", null, c.thinking)) : null,
          h("details", null, h("summary", null, "What this firm was shown"), h("pre", null, c.user)),
          h("div", { class: "note" }, tokens(c))))
    : [h("p", { class: "note" }, "No model call (scripted bidder).")];
  return h("div", { class: "card" }, h("h4", null, h("span", { class: `firmdot ${cls(f.id)}` }), `Firm ${f.id}`), ...calls);
}

function systemPrompt(s) {
  const ids = Object.keys(s.system).sort();
  if (!ids.length) return null;
  return h("details", null, h("summary", null, `System prompt (firm ${ids[0]}; other firms differ only in the firm letter)`), h("pre", null, s.system[ids[0]]));
}

function renderExample() {
  const ex = view(), s = current();
  const toggle = (key, text) => h("label", null, h("input", { type: "checkbox", checked: state[key], onchange: (e) => { state[key] = e.target.checked; render(); } }), text);
  document.getElementById("example").replaceChildren(...[
    h("div", { class: "intro" }, h("h2", null, ex.title), h("p", null, ex.blurb), ex.look_for ? h("p", { class: "look" }, h("b", null, "Look for: "), ex.look_for) : null),
    firmsLegend(s),
    renderStrips(ex),
    chips(s),
    metaLine(s),
    h("div", { class: "chartbox" }, chartFor(s)),
    h("div", { class: "toggles" }, "Filled dot = bid, ringed = winner.", toggle("showCost", "Show costs (hollow circle)"), toggle("showBne", "Show equilibrium bids (diamond)")),
    systemPrompt(s),
    roundPanel(s)].filter(Boolean));
}

// ---- runs: list of runs, one page per run, one session loaded on demand ----

const mean = (xs) => { const v = xs.filter((x) => x != null); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
const fmt = (v, f = 3) => (v == null ? "–" : f === "pct" ? (v * 100).toFixed(0) + "%" : v.toFixed(f));

function loadSession(run, sid) {
  window.SESSIONS = window.SESSIONS || {};
  if (window.SESSIONS[sid]) return Promise.resolve(window.SESSIONS[sid]);
  return new Promise((resolve, reject) => {
    const el = document.createElement("script");
    el.src = `data/sessions/${encodeURIComponent(run)}/${encodeURIComponent(sid)}.js`;
    el.onload = () => (window.SESSIONS[sid] ? resolve(window.SESSIONS[sid]) : reject(new Error(`${sid}: file loaded but empty`)));
    el.onerror = () => reject(new Error(`${sid}: not exported (run scripts/export_site.py)`));
    document.head.append(el);
  });
}

async function openSession(runId, sid, which, round) {
  const run = RUNS.find((r) => r.id === runId);
  const entry = run && run.sessions.find((e) => e.id === sid);
  if (!entry) { state.mode = "runs"; return; }
  const controlId = `oneshot__${sid}`;
  const hasControl = !entry.control && run.sessions.some((e) => e.id === controlId);
  try {
    const sessions = await Promise.all([loadSession(runId, sid), ...(hasControl ? [loadSession(runId, controlId)] : [])]);
    state.run = run; state.sid = sid;
    state.custom = {
      id: sid, title: sid, run: runId, sessions,
      blurb: `Run ${runId}, condition ${entry.condition}. ${hasControl ? "The one-shot control (same seed and costs, no history) is the second session." : ""}`,
      look_for: "",
    };
    state.s = Math.min(which, sessions.length - 1);
    state.round = Math.min(Math.max(round, 1), sessions[state.s].rounds.length);
    state.error = null;
  } catch (err) {
    state.run = run; state.sid = sid; state.custom = null; state.error = String(err.message || err);
  }
}

function miniStrip(e) {
  return h("div", { class: "ribbon mini", role: "img", "aria-label": `Winner of each round: ${e.w}` },
    ...[...e.w].map((w, i) => h("span", { class: `cell ${w === "-" ? "none" : cls(w)}` },
      e.t[i] === "1" ? h("span", { class: "tie" }) : null, e.m[i] === "1" ? h("span", { class: "dot" }) : null)));
}

function renderRuns() {
  const rows = RUNS.map((r) => {
    const rep = r.sessions.filter((e) => !e.control);
    const models = [...new Set(r.sessions.flatMap((e) => e.models))].sort();
    const ns = [...new Set(r.sessions.map((e) => e.n_bidders))].sort();
    const rules = [...new Set(r.sessions.map((e) => e.tie_break_rule))].sort();
    return h("tr", null,
      h("td", null, h("a", { href: `#/run/${encodeURIComponent(r.id)}` }, r.id)),
      h("td", { class: "num" }, rep.length), h("td", { class: "num" }, r.sessions.length - rep.length),
      h("td", null, models.join(", ")), h("td", null, `N ${ns.join(", ")}`), h("td", null, rules.join(", ")),
      h("td", { class: "num" }, fmt(mean(rep.map((e) => e.metrics.collusion_index)))),
      h("td", { class: "num" }, fmt(mean(rep.map((e) => e.metrics.delta_index)))));
  });
  document.getElementById("example").replaceChildren(RUNS.length
    ? h("div", null,
        h("div", { class: "intro" }, h("h2", null, "All exported runs"),
          h("p", null, "One row per run in logs/ with at least one complete session. Open a run for its conditions and sessions.")),
        h("div", { class: "tablewrap" }, h("table", null,
          h("thead", null, h("tr", null, ...["Run", "Sessions", "Controls", "Models", "Bidders", "Tie rule", "Mean index", "Mean delta"]
            .map((t, i) => h("th", { class: i === 1 || i === 2 || i >= 6 ? "num" : "" }, t)))),
          h("tbody", null, ...rows))))
    : h("p", null, "No runs exported yet. Run ", h("code", null, "uv run python scripts/export_site.py"), " and reload."));
}

const MODEL_COLORS = ["var(--firm-a)", "var(--firm-b)", "var(--firm-c)", "var(--accent)", "var(--warn)"];

// Share of each model's valid bids by (bid - equilibrium bid), one bar per model in each bin.
function histogramCard(run, sessions) {
  const bins = run.diff_bins;
  const use = sessions.filter((e) => e.diff_hist && (state.hist === "both" || (state.hist === "controls") === e.control));
  if (!bins || !use.length) return null;
  const models = [...new Set(use.flatMap((e) => Object.keys(e.diff_hist)))].sort();
  const counts = Object.fromEntries(models.map((m) => [m, new Array(bins.n).fill(0)]));
  for (const e of use) for (const [m, c] of Object.entries(e.diff_hist)) c.forEach((v, i) => { counts[m][i] += v; });
  const totals = Object.fromEntries(models.map((m) => [m, counts[m].reduce((a, b) => a + b, 0)]));
  const share = (m, i) => (totals[m] ? counts[m][i] / totals[m] : 0);
  const W = 900, H = 280, ml = 46, mr = 12, mt = 12, mb = 34;
  const binW = (W - ml - mr) / bins.n, barW = Math.max(1, (binW - 1) / models.length);
  const top = Math.max(0.01, ...models.flatMap((m) => counts[m].map((_, i) => share(m, i))));
  const ymax = Math.ceil(top * 20) / 20;
  const y = (v) => mt + (1 - v / ymax) * (H - mt - mb);
  const edge = (i) => bins.low + i * bins.step;
  const root = svg("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Histogram of each model's bid minus the equilibrium bid" });
  for (let g = 0; g <= 4; g += 1) {
    const v = (ymax * g) / 4;
    root.append(svg("line", { x1: ml, x2: W - mr, y1: y(v), y2: y(v), stroke: "var(--grid)", "stroke-width": 1 }));
    root.append(svg("text", { x: ml - 6, y: y(v) + 4, "text-anchor": "end" }, `${(v * 100).toFixed(0)}%`));
  }
  for (let i = 0; i <= bins.n; i += 5) {
    const label = i === 0 ? `≤${edge(i)}` : i === bins.n ? `≥${edge(i)}` : String(edge(i));
    root.append(svg("text", { x: ml + i * binW, y: H - 16, "text-anchor": "middle" }, label));
  }
  root.append(svg("text", { x: ml + (W - ml - mr) / 2, y: H - 2, "text-anchor": "middle" }, "bid minus equilibrium bid (bid units)"));
  models.forEach((m, k) => {
    for (let i = 0; i < bins.n; i += 1) {
      const v = share(m, i);
      if (!v) continue;
      const bar = svg("rect", {
        x: (ml + i * binW + k * barW).toFixed(1), y: y(v).toFixed(1), width: (barW - 0.5).toFixed(1), height: (y(0) - y(v)).toFixed(1),
        fill: MODEL_COLORS[k % MODEL_COLORS.length],
      });
      bar.append(svg("title", null, `${m}: ${(v * 100).toFixed(1)}% of bids (${counts[m][i]}) from ${edge(i)} to ${edge(i + 1)}`));
      root.append(bar);
    }
  });
  const zero = ml + ((0 - bins.low) / bins.step) * binW;
  root.append(svg("line", { x1: zero, x2: zero, y1: mt, y2: H - mb, stroke: "var(--text)", "stroke-width": 1.5, "stroke-dasharray": "4 3" }));
  root.append(svg("line", { x1: ml, x2: W - mr, y1: y(0), y2: y(0), stroke: "var(--axis)", "stroke-width": 1 }));
  const pick = h("label", null, "sessions",
    h("select", { onchange: (e) => { state.hist = e.target.value; renderRun(); } },
      ...[["repeated", "repeated"], ["controls", "one-shot controls"], ["both", "both"]].map(([v, t]) => h("option", { value: v, selected: state.hist === v }, t))));
  return h("section", { class: "cond histo" },
    h("h3", null, "Bid minus equilibrium bid, by model"),
    h("p", { class: "meta" }, "Share of each model's valid bids per bin. Dashed line = equilibrium bid (0): left of it a firm bids below the benchmark, right of it above. "
      + "Bids beyond ±50 sit in the end bins. Bids are single unilateral choices, so bars show how far prices sit from the benchmark, not who won."),
    h("div", { class: "legend" }, ...models.map((m, k) =>
      h("span", { class: "key" }, h("span", { class: "sw", style: `background:${MODEL_COLORS[k % MODEL_COLORS.length]}` }), `${m} (${totals[m].toLocaleString()} bids)`)), pick),
    h("div", { class: "chartbox" }, root));
}

function renderRun() {
  const run = state.run, root = document.getElementById("example");
  if (!run) { root.replaceChildren(h("p", null, "Unknown run. ", h("a", { href: "#/runs" }, "Back to all runs"))); return; }
  const f = state.filter;
  const pick = (key, get) => {
    const values = [...new Set(run.sessions.map(get))].map(String).sort();
    if (values.length < 2) return null;
    return h("label", null, key, h("select", { onchange: (e) => { f[key] = e.target.value; renderRun(); } },
      h("option", { value: "" }, "all"), ...values.map((v) => h("option", { value: v, selected: f[key] === v }, v))));
  };
  const filters = [pick("model", (e) => e.models.join("+")), pick("bidders", (e) => e.n_bidders), pick("tie rule", (e) => e.tie_break_rule)].filter(Boolean);
  const keep = (e) => (!f.model || e.models.join("+") === f.model) && (!f.bidders || String(e.n_bidders) === f.bidders) && (!f["tie rule"] || e.tie_break_rule === f["tie rule"]);
  const sessions = run.sessions.filter(keep);
  const byCond = new Map();
  for (const e of sessions) {
    const key = e.control ? e.condition.replace(/^oneshot__/, "") : e.condition;
    if (!byCond.has(key)) byCond.set(key, { rep: [], ctl: [] });
    byCond.get(key)[e.control ? "ctl" : "rep"].push(e);
  }
  const blocks = [...byCond.entries()].sort().map(([cond, g]) => {
    const first = g.rep[0] || g.ctl[0];
    const lw = first.tie_break_rule === "least_wins";
    const m = (k) => g.rep.map((e) => e.metrics[k]);
    const range = (k) => { const v = m(k).filter((x) => x != null); return v.length ? `${fmt(Math.min(...v), 2)} to ${fmt(Math.max(...v), 2)}` : "–"; };
    const stat = (label, val, tip) => h("span", { class: "chip", title: tip }, label, h("b", null, val));
    const rowFor = (e) => {
      const ctl = run.sessions.find((c) => c.id === `oneshot__${e.id}`);
      const link = (id, w) => `#/s/${encodeURIComponent(run.id)}/${encodeURIComponent(id)}/${w}/1`;
      return h("div", { class: "sessrow" },
        h("div", { class: "label" }, h("a", { href: link(e.id, 0) }, `seed ${e.seed}`),
          h("span", null, `index ${fmt(e.metrics.collusion_index, 2)} · delta ${fmt(e.metrics.delta_index, 2)} · ties ${fmt(e.metrics.tie_rate, "pct")}`)),
        miniStrip(e),
        ctl ? h("div", { class: "ctl" }, h("span", { class: "note" }, "one-shot control · ", h("a", { href: link(e.id, 1) }, `index ${fmt(ctl.metrics.collusion_index, 2)}`)), miniStrip(ctl)) : null);
    };
    return h("section", { class: "cond" },
      h("h3", null, cond),
      h("p", { class: "meta" }, `${first.models.join(" + ")} · ${first.n_bidders} firms · ${first.n_rounds} rounds · tie rule ${first.tie_break_rule} · info ${first.info}`
        + ` · increment ${first.increment}${first.cost_spread ? ` · cost spread ±${first.cost_spread}` : ""}${first.reveal_costs ? " · costs revealed" : ""} · prompt ${first.prompt_version || "v0"}`),
      h("div", { class: "chips" },
        stat(`Sessions`, String(g.rep.length), "Repeated sessions in this condition."),
        stat("Mean index", fmt(mean(m("collusion_index")), 2), "Collusion index, not clipped; 0 = benchmark. Mean over sessions, descriptive."),
        stat("Range", range("collusion_index"), "Lowest to highest session index."),
        stat("Mean delta", fmt(mean(m("delta_index")), 2), "Index minus the matched one-shot control's."),
        stat("Tie rate", fmt(mean(m("tie_rate")), "pct"), "Mean share of rounds with an exact tie at the lowest bid."),
        stat("Lowest-cost wins", lw ? "n/a" : fmt(mean(m("lowest_cost_win_share")), 2),
          lw ? "Not valid under least_wins: the rule forces uniform wins (PLANNING.md 6.4)." : "Mean share of rounds won by the lowest-cost firm.")),
      ...g.rep.sort((a, b) => a.seed - b.seed).map(rowFor));
  });
  root.replaceChildren(h("div", null,
    h("p", { class: "meta" }, h("a", { href: "#/runs" }, "All runs"), " / ", run.id),
    h("div", { class: "intro" }, h("h2", null, run.id),
      h("p", null, `${run.sessions.filter((e) => !e.control).length} repeated sessions and ${run.sessions.filter((e) => e.control).length} one-shot controls. `
        + "Strips show the winner of each round (striped = tie, dot = lowest-cost firm won). Click a seed to open the session. Means are descriptive: sessions are the unit, and there are few per cell.")),
    filters.length ? h("div", { class: "toggles" }, ...filters) : null,
    histogramCard(run, sessions),
    ...blocks));
}

function renderSession() {
  const root = document.getElementById("example");
  if (state.error || !state.custom) {
    root.replaceChildren(h("p", { class: "err" }, state.error || "Session not found."), h("a", { href: state.run ? `#/run/${encodeURIComponent(state.run.id)}` : "#/runs" }, "Back"));
    return;
  }
  renderExample();
  root.prepend(h("p", { class: "meta" }, h("a", { href: "#/runs" }, "All runs"), " / ", h("a", { href: `#/run/${encodeURIComponent(state.run.id)}` }, state.run.id), " / ", state.sid));
}

function render() {
  renderModes();
  renderNav();
  if (state.mode === "runs") renderRuns();
  else if (state.mode === "run") renderRun();
  else if (state.mode === "session") renderSession();
  else renderExample();
  writeHash();
}

async function route() {
  state.custom = null;
  await readHash();
  render();
  window.scrollTo(0, 0);
}

document.addEventListener("keydown", (e) => {
  if (e.target.matches("input, textarea") || e.metaKey || e.ctrlKey) return;
  const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
  if (!d || (state.mode !== "examples" && state.mode !== "session")) return;
  const n = current().rounds.length, next = Math.min(Math.max(state.round + d, 1), n);
  if (next !== state.round) { state.round = next; render(); e.preventDefault(); }
});
document.getElementById("theme").addEventListener("click", () => {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("theme", root.dataset.theme); } catch (_) { /* storage can be blocked */ }
  render();
});
try { const t = localStorage.getItem("theme"); if (t) document.documentElement.dataset.theme = t; } catch (_) { /* storage can be blocked */ }
window.addEventListener("hashchange", route);
route();
