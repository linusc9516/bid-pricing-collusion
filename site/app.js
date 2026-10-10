"use strict";
// Static viewer for exported auction sessions: curated examples (site/data/examples.js, scripts/export_examples.py)
// and every exported run (site/data/runs.js plus one file per session, scripts/export_site.py).
// The committed bundle (site/data/published.js, export_site.py --publish) adds the findings page and the runs a fresh clone shows.
// All text from the logs goes in through textContent, never innerHTML. The one exception is the findings page, whose HTML
// is generated at export time from a Markdown file of this repository, not from model output.

const EXAMPLES = window.EXAMPLES.examples;
const PUBLISHED = window.PUBLISHED || null;
// A local export of a run takes precedence over its published copy.
const RUNS = [...(window.RUNS || [])];
if (PUBLISHED) for (const r of PUBLISHED.runs) if (!RUNS.some((x) => x.id === r.id)) RUNS.push({ ...r, published: true });
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
const state = { mode: "examples", ex: 0, s: 0, round: 1, showCost: false, showBne: false, run: null, custom: null, filter: {}, hist: "repeated", pair: "collusion_index" };
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
  if (id === "findings" || (!id && PUBLISHED && PUBLISHED.findings_html)) { state.mode = "findings"; return Promise.resolve(); }
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
  if (state.mode === "findings") history.replaceState(null, "", "#/findings");
  else if (state.mode === "examples") history.replaceState(null, "", `#/${EXAMPLES[state.ex].id}/${state.s}/${state.round}`);
  else if (state.mode === "session") history.replaceState(null, "", `#/s/${encodeURIComponent(state.run.id)}/${encodeURIComponent(state.sid)}/${state.s}/${state.round}`);
}

function renderModes() {
  const group = state.mode === "findings" ? "findings" : state.mode === "examples" ? "examples" : "runs";
  const tab = (name, label, hash) => h("button", { type: "button", "aria-pressed": String(group === name), onclick: () => { location.hash = hash; } }, label);
  document.getElementById("modes").replaceChildren(
    PUBLISHED && PUBLISHED.findings_html ? tab("findings", "Findings", "#/findings") : null,
    tab("examples", "Examples", `#/${EXAMPLES[state.ex].id}/0/1`), tab("runs", `All runs (${RUNS.length})`, "#/runs"));
  document.body.dataset.mode = group;
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
    h("section", { class: "panel" }, h("h3", null, "Who won each round"), firmsLegend(s), renderStrips(ex)),
    h("section", { class: "panel" }, h("h3", null, "Session measures"), chips(s), metaLine(s)),
    h("section", { class: "panel" }, h("h3", null, "Bids by round"),
      h("div", { class: "chartbox" }, chartFor(s)),
      h("div", { class: "toggles" }, "Filled dot = bid, ringed = winner.", toggle("showCost", "Show costs (hollow circle)"), toggle("showBne", "Show equilibrium bids (diamond)"))),
    s.system && Object.keys(s.system).length ? h("section", { class: "panel" }, systemPrompt(s)) : null,
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
    const dir = (RUNS.find((r) => r.id === run) || {}).published ? "published" : "sessions";
    el.src = `data/${dir}/${encodeURIComponent(run)}/${encodeURIComponent(sid)}.js`;
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
        h("section", { class: "panel" }, h("div", { class: "tablewrap" }, h("table", null,
          h("thead", null, h("tr", null, ...["Run", "Sessions", "Controls", "Models", "Bidders", "Tie rule", "Mean index", "Mean delta"]
            .map((t, i) => h("th", { class: i === 1 || i === 2 || i >= 6 ? "num" : "" }, t)))),
          h("tbody", null, ...rows)))))
    : h("p", null, "No runs exported yet. Run ", h("code", null, "uv run python scripts/export_site.py"), " and reload."));
}

const MODEL_COLORS = ["var(--firm-a)", "var(--firm-b)", "var(--firm-c)", "var(--accent)", "var(--warn)"];

const BID_CLASS_KEYS = [
  ["below own cost", "var(--cls-cost)"],
  ["below equilibrium, at or above cost", "var(--cls-below)"],
  ["at equilibrium", "var(--cls-at)"],
  ["above equilibrium", "var(--cls-above)"],
];

// Each valid bid classified against the equilibrium bid and the firm's own cost: one stacked bar per model, cost role and arm.
function classCard(sessions) {
  const use = sessions.filter((e) => e.bid_classes);
  if (!use.length) return null;
  const models = [...new Set(use.flatMap((e) => Object.keys(e.bid_classes)))].sort();
  const two = use.every((e) => e.n_bidders === 2);
  const roles = [["min", two ? "lower-cost firm" : "lowest-cost firm"], ["other", two ? "higher-cost firm" : "other firms"]];
  const arms = [[true, "one-shot"], [false, "repeated"]];
  const groups = [];
  for (const m of models) {
    const bars = [];
    for (const [role, roleName] of roles) for (const [control, armName] of arms) {
      const c = [0, 0, 0, 0, 0];
      for (const e of use) if (e.control === control && e.bid_classes[m]) e.bid_classes[m][role].forEach((v, i) => { c[i] += v; });
      const n = c[0] + c[1] + c[2] + c[3];
      if (n) bars.push({ label: `${roleName}, ${armName}`, c, n, gap: armName === "one-shot" && bars.length > 0 });
    }
    if (bars.length) groups.push({ m, bars });
  }
  if (!groups.length) return null;
  const W = 900, x0 = 210, x1 = W - 96, rowH = 24, barH = 16, headH = 26, gapH = 8, mb = 30;
  const H = groups.reduce((a, g) => a + headH + g.bars.length * rowH + g.bars.filter((b) => b.gap).length * gapH + 8, 4) + mb;
  const root = svg("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Share of bids below own cost, below, at and above the equilibrium bid, by model, cost role and arm" });
  const px = (share) => x0 + share * (x1 - x0);
  for (let g = 0; g <= 4; g += 1) root.append(svg("text", { x: px(g / 4), y: H - 10, "text-anchor": "middle" }, `${g * 25}%`));
  let y = 4;
  for (const g of groups) {
    root.append(svg("text", { class: "strong", x: 0, y: y + 17 }, g.m));
    y += headH;
    for (const b of g.bars) {
      if (b.gap) y += gapH;
      root.append(svg("text", { x: x0 - 8, y: y + barH - 4, "text-anchor": "end" }, b.label));
      let left = 0;
      b.c.slice(0, 4).forEach((count, i) => {
        const share = count / b.n;
        if (!count) return;
        const w = Math.max(1, px(left + share) - px(left) - 2);
        const seg = svg("rect", { x: px(left).toFixed(1), y, width: w.toFixed(1), height: barH, rx: 2, fill: BID_CLASS_KEYS[i][1] });
        seg.append(svg("title", null, `${g.m}, ${b.label}: ${(share * 100).toFixed(1)}% ${BID_CLASS_KEYS[i][0]} (${count} of ${b.n} bids)`));
        root.append(seg);
        if (share >= 0.07) root.append(svg("text", { class: "inbar", x: (px(left) + w / 2).toFixed(1), y: y + barH - 4, "text-anchor": "middle", "pointer-events": "none" }, `${(share * 100).toFixed(0)}%`));
        left += share;
      });
      root.append(svg("text", { x: x1 + 8, y: y + barH - 4 }, `won ${((b.c[4] / b.n) * 100).toFixed(0)}% · ${b.n.toLocaleString()}`));
      y += rowH;
    }
    y += 8;
  }
  return h("section", { class: "cond histo" },
    h("h3", null, "Where bids sit, by cost role"),
    h("p", { class: "meta" }, `Share of valid bids in each class, split by whether the firm had the round's lowest cost. "At equilibrium" is within 1 bid unit of the equilibrium bid `
      + "(one bid increment on a coarser grid). A bid under the firm's own cost counts as below cost whatever its distance from the equilibrium bid. "
      + "Right of each bar: share of those bids that won, and the number of bids."),
    h("div", { class: "legend" }, ...BID_CLASS_KEYS.map(([name, color]) => h("span", { class: "key" }, h("span", { class: "sw box", style: `background:${color}` }), name))),
    h("div", { class: "chartbox" }, root));
}

const SCATTER_MAX_POINTS = 3000; // per panel; above this every k-th bid is drawn
const SCATTER_HIT_PX = 22; // the nearest bid within this many screen pixels of the pointer is the one described
const NARROW = window.matchMedia("(max-width: 700px)"); // charts are redrawn narrower, not scaled down, so their text stays readable

// The tooltip at the pointer, shown at once (a <title> waits about a second and never shows on touch).
function tipAt(ev, ...kids) {
  const tip = document.getElementById("tip");
  tip.replaceChildren(...kids);
  tip.hidden = false;
  const w = tip.offsetWidth, hgt = tip.offsetHeight;
  tip.style.left = Math.max(8, Math.min(ev.clientX + 14, window.innerWidth - w - 8)) + "px";
  tip.style.top = Math.max(8, Math.min(ev.clientY + 14, window.innerHeight - hgt - 8)) + "px";
}

// Every valid bid against the firm's own cost, one panel per model and arm, with the equilibrium bid and bid = cost as lines.
function scatterCard(sessions) {
  const use = sessions.filter((e) => e.points);
  if (!use.length) return null;
  const models = [...new Set(use.flatMap((e) => Object.keys(e.points)))].sort();
  const arms = [[true, "one-shot"], [false, "repeated"]].filter(([c]) => use.some((e) => e.control === c));
  const lo = Math.min(...use.map((e) => e.cost_low)), hi = Math.max(...use.map((e) => e.cost_high)), top = Math.max(...use.map((e) => e.reserve));
  const narrow = NARROW.matches, cols = narrow ? 1 : 2;
  const W = narrow ? 460 : 900, ml = 44, gapX = 56, headH = 46, mb = 44, pw = narrow ? W - ml - 14 : 372, ph = narrow ? 290 : 260;
  const rowH = headH + ph + mb;
  const panels = models.flatMap((m, mi) => arms.map(([control, armName]) => ({ m, mi, control, armName })));
  const root = svg("svg", { class: "chart", viewBox: `0 0 ${W} ${Math.ceil(panels.length / cols) * rowH}`, role: "img", "aria-label": "Scatter of each bid against the firm's own cost, by model and arm" });
  let sampled = false, noLine = false;
  panels.forEach(({ m, mi, control, armName }, pi) => {
    const group = use.filter((e) => e.control === control && e.points[m]);
    const all = group.flatMap((e) => e.points[m].map((p) => [p[0], p[1], p[2], e.seed]));
    if (!all.length) return;
    const x0 = ml + (pi % cols) * (pw + gapX), y0 = Math.floor(pi / cols) * rowH + headH;
    const x = (c) => x0 + ((c - lo) / (hi - lo)) * pw, y = (b) => y0 + (1 - b / top) * ph;
    const clip = (a, b) => [[lo, a + b * lo], [hi, a + b * hi]].map(([c, v]) => `${x(c).toFixed(1)},${y(Math.max(0, Math.min(top, v))).toFixed(1)}`).join(" ");
    for (let g = 0; g <= 4; g += 1) {
      const c = lo + ((hi - lo) * g) / 4, b = (top * g) / 4;
      root.append(svg("line", { x1: x0, x2: x0 + pw, y1: y(b), y2: y(b), stroke: "var(--grid)", "stroke-width": 1 }));
      root.append(svg("text", { x: x0 - 6, y: y(b) + 4, "text-anchor": "end" }, String(Math.round(b))));
      root.append(svg("text", { x: x(c), y: y0 + ph + 16, "text-anchor": "middle" }, String(Math.round(c))));
    }
    root.append(svg("text", { x: x0 + pw / 2, y: y0 + ph + 34, "text-anchor": "middle" }, "own cost"));
    root.append(svg("text", { x: x0 - 30, y: y0 + ph / 2, "text-anchor": "middle", transform: `rotate(-90 ${x0 - 30} ${y0 + ph / 2})` }, "bid"));
    // Below the bid = cost line a winning bid loses money.
    root.append(svg("polygon", { points: `${x(lo)},${y(lo)} ${x(hi)},${y(Math.min(hi, top))} ${x(hi)},${y(0)} ${x(lo)},${y(0)}`, fill: "var(--cls-cost)", opacity: 0.07 }));
    root.append(svg("polyline", { points: clip(0, 1), fill: "none", stroke: "var(--cls-cost)", "stroke-width": 1.5 }));
    const step = Math.ceil(all.length / SCATTER_MAX_POINTS);
    if (step > 1) sampled = true;
    const color = MODEL_COLORS[mi % MODEL_COLORS.length], drawn = [];
    for (const won of [0, 1]) for (let i = 0; i < all.length; i += step) {
      const [c, b, flags, seed] = all[i];
      if ((flags & 1) !== won) continue;
      drawn.push({ px: x(c), py: y(b), c, b, flags, seed });
      root.append(svg("circle", { cx: x(c).toFixed(1), cy: y(b).toFixed(1), r: won ? 2.4 : 2.2, fill: won ? color : "none", stroke: won ? "none" : "var(--muted)", "stroke-width": 1, opacity: won ? 0.75 : 0.6 }));
    }
    const k = all.length, sx = all.reduce((t, p) => t + p[0], 0) / k, sy = all.reduce((t, p) => t + p[1], 0) / k;
    const sxx = all.reduce((t, p) => t + (p[0] - sx) ** 2, 0), sxy = all.reduce((t, p) => t + (p[0] - sx) * (p[1] - sy), 0);
    let fit = "";
    if (k >= 3 && sxx > 0) {
      const b = sxy / sxx, a = sy - b * sx;
      root.append(svg("polyline", { points: clip(a, b), fill: "none", stroke: "var(--surface)", "stroke-width": 5, opacity: 0.8 }));
      root.append(svg("polyline", { points: clip(a, b), fill: "none", stroke: color, "stroke-width": 2 }));
      fit = `fitted ${fmt(a, 1)} + ${fmt(b, 2)} × cost`;
    }
    const ns = new Set(group.map((e) => e.n_bidders));
    let eq = "no single equilibrium line for these sessions", eqAt = null;
    if (ns.size === 1 && group.every((e) => !e.reveal_costs && !e.cost_spread && e.cost_high === hi && e.cost_low === lo)) {
      const n = [...ns][0], a = hi / n, b = 1 - 1 / n;
      root.append(svg("polyline", { points: clip(a, b), fill: "none", stroke: "var(--text)", "stroke-width": 1.5, "stroke-dasharray": "5 4" }));
      eq = `equilibrium ${fmt(a, 1)} + ${fmt(b, 2)} × cost`;
      eqAt = (c) => a + b * c;
    } else noLine = true;
    root.append(svg("rect", { x: x0, y: y0, width: pw, height: ph, fill: "none", stroke: "var(--axis)", "stroke-width": 1 }));
    root.append(svg("text", { class: "strong", x: x0, y: y0 - 26 }, `${m} · ${armName}`));
    root.append(svg("text", { x: x0 + pw, y: y0 - 26, "text-anchor": "end" }, `${k.toLocaleString()} bids`));
    root.append(svg("text", { x: x0, y: y0 - 9 }, narrow ? fit : `${fit}${fit ? " · " : ""}${eq}`));
    // One hit area per panel: the pointer picks the nearest bid, so a 2-pixel dot does not have to be hit exactly.
    const ring = svg("circle", { class: "ring", r: 6, fill: "none", visibility: "hidden" });
    const hit = svg("rect", { class: "hit", x: x0, y: y0, width: pw, height: ph, fill: "transparent" });
    const leave = () => { ring.setAttribute("visibility", "hidden"); hideTip(); };
    const track = (ev) => {
      const box = root.getBoundingClientRect(), scale = W / box.width, mx = (ev.clientX - box.left) * scale, my = (ev.clientY - box.top) * scale;
      let best = null, bestD = (SCATTER_HIT_PX * scale) ** 2;
      for (const p of drawn) { const d = (p.px - mx) ** 2 + (p.py - my) ** 2; if (d < bestD) { best = p; bestD = d; } }
      if (!best) { leave(); return; }
      ring.setAttribute("cx", best.px); ring.setAttribute("cy", best.py); ring.setAttribute("visibility", "visible");
      const diff = eqAt ? best.b - eqAt(best.c) : null;
      tipAt(ev, h("div", null, h("b", null, `Bid ${best.b.toFixed(2)}`), ` · ${best.flags & 1 ? "won" : "lost"}`),
        h("div", { class: "row" }, h("span", null, `own cost ${best.c.toFixed(2)}${best.flags & 2 ? ", the round's lowest" : ""}`)),
        diff == null ? null : h("div", { class: "row" }, h("span", null, `equilibrium bid ${eqAt(best.c).toFixed(2)} (${diff >= 0 ? "+" : "−"}${Math.abs(diff).toFixed(2)})`)),
        h("div", { class: "row" }, h("span", null, `${m}, ${armName}, seed ${best.seed}`)));
    };
    hit.addEventListener("pointermove", track);
    hit.addEventListener("pointerdown", track);
    hit.addEventListener("pointerleave", leave);
    root.append(ring, hit);
  });
  const key = (cls, style, name) => h("span", { class: "key" }, h("span", { class: `sw ${cls}`, style }), name);
  return h("section", { class: "cond histo" },
    h("h3", null, "Bid against own cost"),
    h("p", { class: "meta" }, "One point per valid bid. A firm bidding the equilibrium sits on the dashed line; the fitted line is the least-squares line through the panel's bids, "
      + "so a lower line means lower bids at every cost and a flatter one means bids that react less to cost. Points in the shaded area are bids below the firm's own cost. "
      + "Point at a bid to read it."
      + (sampled ? ` Panels with more than ${SCATTER_MAX_POINTS.toLocaleString()} bids draw an even sample; the fitted line uses all of them.` : "")
      + (noLine ? " No equilibrium line is drawn where costs are revealed, share a common part, or the sessions differ in the number of firms." : "")),
    h("div", { class: "legend" }, key("dot", "background:var(--text-2)", "winning bid (in the model's colour)"), key("ring", "", "losing bid"),
      key("dash", "", "equilibrium bid"), key("line", "background:var(--text-2)", "fitted line"), key("line", "background:var(--cls-cost)", "bid = cost")),
    h("div", { class: "chartbox" }, root));
}

const PAIR_MEASURES = [
  ["collusion_index", "Index", "collusion index (price level)", () => 0],
  ["markup_ratio", "Markup ratio", "markup ratio, all bids", () => 1],
  ["markup_ratio_min_cost", "Markup, lowest-cost firm", "markup ratio, lowest-cost firm", () => 1],
  ["markup_ratio_other", "Markup, other firms", "markup ratio, other firms", () => 1],
  ["bid_slope", "Slope", "slope of bid on cost", (e) => (e.reveal_costs || e.cost_spread ? null : 1 - 1 / e.n_bidders)],
  ["bid_intercept", "Intercept", "intercept of bid on cost", (e) => (e.reveal_costs || e.cost_spread || e.cost_low ? null : e.cost_high / e.n_bidders)],
  ["bid_gap", "Gap", "mean distance of a bid from the equilibrium bid, in bid units", () => 0],
  ["joint_profit_ratio", "Joint profit", "the firms' total profit over their profit under equilibrium play", () => 1],
  ["switch_gain", "Switching gain", "gain if one firm switched alone to the equilibrium bid, the other's bids held fixed", () => 0],
];

// One dot per session, each repeated session joined to its one-shot control: the comparison the session-level tests make.
// `fixed` names one measure and hides the control, for a chart that sits under one finding.
function pairedCard(run, sessions, fixed = null) {
  const [key, , name, bench] = PAIR_MEASURES.find(([k]) => k === (fixed || state.pair)) || PAIR_MEASURES[0];
  const ids = new Map(run.sessions.map((e) => [e.id, e]));
  const groups = new Map();
  for (const e of sessions) {
    if (e.control) continue;
    const ctl = ids.get(`oneshot__${e.id}`);
    if (!ctl || e.metrics[key] == null || ctl.metrics[key] == null) continue;
    if (!groups.has(e.condition)) groups.set(e.condition, { first: e, pairs: [] });
    groups.get(e.condition).pairs.push({ seed: e.seed, a: ctl.metrics[key], b: e.metrics[key] });
  }
  // Only this card is rebuilt on a press, so the control answers at once however large the scatter above is.
  const pick = fixed ? null : h("div", { class: "seg", role: "group", "aria-label": "Measure" }, ...PAIR_MEASURES.map(([k, short, long]) =>
    h("button", { type: "button", "aria-pressed": String(k === key), title: long,
      onclick: (ev) => { state.pair = k; ev.currentTarget.closest("section").replaceWith(pairedCard(run, sessions)); } }, short)));
  const head = fixed ? [h("h3", null, name.charAt(0).toUpperCase() + name.slice(1)),
    h("p", { class: "meta" }, "One dot per session. A line joins a session with the history shown (right) to its one-shot control (left) on the same seed. The short bars are the means over sessions. Point at a line to read its pair."),
    null] : [h("h3", null, "Each session against its one-shot control"),
    h("p", { class: "meta" }, "One dot per session. A line joins a repeated session (right) to its one-shot control (left): same seed, same costs, no history shown. "
      + "A line that falls means the history lowered that measure. The short bars are the means over sessions. This is the comparison the session-level tests make; a round is never an observation. "
      + "Point at a line to read its pair."),
    pick];
  if (!groups.size) return h("section", { class: "cond histo" }, ...head, h("p", { class: "meta" }, "No session in this selection has a matched control with this measure."));
  const list = [...groups.entries()].sort();
  const lineups = [...new Set(run.sessions.map((e) => e.models.join("+")))].sort();
  const manyRules = new Set(list.map(([, g]) => g.first.tie_break_rule)).size > 1, manyN = new Set(list.map(([, g]) => g.first.n_bidders)).size > 1;
  const benches = list.map(([, g]) => bench(g.first));
  const values = list.flatMap(([, g]) => g.pairs.flatMap((p) => [p.a, p.b])).concat(benches.filter((v) => v != null));
  const span = Math.max(...values) - Math.min(...values) || 1;
  const tick = [1, 2, 2.5, 5, 10].map((m) => m * 10 ** Math.floor(Math.log10(span / 4))).find((t) => span / t <= 5);
  const vmin = Math.floor((Math.min(...values) - span * 0.04) / tick) * tick, vmax = Math.ceil((Math.max(...values) + span * 0.04) / tick) * tick;
  const narrow = NARROW.matches, perRowMax = narrow ? 2 : 6;
  const W = narrow ? 460 : 900, ml = 52, mr = 8, inset = narrow ? 26 : 34, mt = 14, ph = 250, mb = 58; // inset keeps the outer mean labels off the axis labels and the edge
  const colW = (W - ml - mr - 2 * inset) / Math.min(perRowMax, Math.max(list.length, narrow ? 2 : 3)), half = Math.min(34, colW * 0.2); // narrow enough that the mean labels of neighbouring groups cannot meet
  const y = (v, r) => r * (mt + ph + mb) + mt + (1 - (v - vmin) / (vmax - vmin)) * ph;
  const rows = Math.ceil(list.length / perRowMax);
  const root = svg("svg", { class: "chart", viewBox: `0 0 ${W} ${rows * (mt + ph + mb)}`, role: "img", "aria-label": `${name}: each repeated session joined to its one-shot control` });
  const digits = tick >= 1 ? 0 : tick >= 0.1 ? 1 : 2;
  const perRow = Math.min(perRowMax, list.length), left = ml + (W - ml - mr - perRow * colW) / 2;
  for (let r = 0; r < rows; r += 1) for (let v = vmin; v <= vmax + tick / 2; v += tick) {
    root.append(svg("line", { x1: ml, x2: W - mr, y1: y(v, r), y2: y(v, r), stroke: "var(--grid)", "stroke-width": 1 }));
    root.append(svg("text", { x: ml - 6, y: y(v, r) + 4, "text-anchor": "end" }, (Math.abs(v) < tick / 2 ? 0 : v).toFixed(digits)));
  }
  const labels = [];
  list.forEach(([, g], i) => {
    const r = Math.floor(i / perRowMax), cx = left + ((i % perRowMax) + 0.5) * colW, xa = cx - half, xb = cx + half;
    const color = MODEL_COLORS[lineups.indexOf(g.first.models.join("+")) % MODEL_COLORS.length];
    if (benches[i] != null) {
      root.append(svg("line", { x1: cx - colW / 2 + 6, x2: cx + colW / 2 - 6, y1: y(benches[i], r), y2: y(benches[i], r), stroke: "var(--text)", "stroke-width": 1.5, "stroke-dasharray": "5 4" }));
    }
    for (const p of g.pairs) {
      const change = p.b - p.a;
      const pair = svg("g", { class: "pair" },
        svg("line", { class: "vis", x1: xa, x2: xb, y1: y(p.a, r), y2: y(p.b, r), stroke: color, "stroke-width": 1.5 }),
        svg("line", { x1: xa - 8, x2: xb + 8, y1: y(p.a, r), y2: y(p.b, r), stroke: "transparent", "stroke-width": 16, "stroke-linecap": "round" }),
        svg("circle", { cx: xa, cy: y(p.a, r), r: 4, fill: color, stroke: "var(--surface)", "stroke-width": 1.5 }),
        svg("circle", { cx: xb, cy: y(p.b, r), r: 4, fill: color, stroke: "var(--surface)", "stroke-width": 1.5 }));
      const on = (ev) => {
        root.classList.add("focus"); pair.classList.add("hot");
        tipAt(ev, h("div", null, h("b", null, `Seed ${p.seed}`), ` · ${g.first.lineup}`),
          h("div", { class: "row" }, h("b", null, p.a.toFixed(3)), h("span", null, "one-shot control")),
          h("div", { class: "row" }, h("b", null, p.b.toFixed(3)), h("span", null, "repeated session")),
          h("div", { class: "row" }, h("b", null, `${change >= 0 ? "+" : "−"}${Math.abs(change).toFixed(3)}`), h("span", null, "change with history")));
      };
      pair.addEventListener("pointerenter", on);
      pair.addEventListener("pointermove", on);
      pair.addEventListener("pointerdown", on);
      pair.addEventListener("pointerleave", () => { root.classList.remove("focus"); pair.classList.remove("hot"); hideTip(); });
      root.append(pair);
    }
    const ma = mean(g.pairs.map((p) => p.a)), mb2 = mean(g.pairs.map((p) => p.b)), base = r * (mt + ph + mb) + mt + ph;
    for (const [px, v, side] of [[xa, ma, -1], [xb, mb2, 1]]) {
      labels.push(svg("line", { x1: px - 9, x2: px + 9, y1: y(v, r), y2: y(v, r), stroke: "var(--text)", "stroke-width": 3, "stroke-linecap": "round", "pointer-events": "none" }));
      // A mean close to the benchmark would put its label on the dashed line: move it to the mean's own side of that line.
      const gap = benches[i] == null ? 99 : y(v, r) - y(benches[i], r), nudge = Math.abs(gap) < 9 ? (gap >= 0 ? 9 : -9) - gap : 0;
      labels.push(svg("text", { class: "inbar halo", x: px + side * 12, y: y(v, r) + 4 + nudge, "text-anchor": side < 0 ? "end" : "start", "pointer-events": "none" }, (Math.abs(v) < 0.005 ? 0 : v).toFixed(Math.max(2, digits))));
    }
    root.append(svg("text", { x: xa, y: base + 16, "text-anchor": "middle" }, "one-shot"));
    root.append(svg("text", { x: xb, y: base + 16, "text-anchor": "middle" }, "repeated"));
    root.append(svg("text", { class: "strong", x: cx, y: base + 36, "text-anchor": "middle" }, g.first.lineup));
    root.append(svg("text", { x: cx, y: base + 51, "text-anchor": "middle" }, `${manyRules ? `${g.first.tie_break_rule} · ` : ""}${manyN ? `${g.first.n_bidders} firms · ` : ""}${g.pairs.length} pairs`));
  });
  root.append(...labels); // means and their labels sit above every pair
  return h("section", { class: "cond histo" }, ...head,
    h("div", { class: "legend" }, h("span", { class: "key" }, h("span", { class: "sw dash" }), "benchmark value"),
      h("span", { class: "key" }, h("span", { class: "sw line", style: "background:var(--text);height:3px" }), "mean over sessions"), fixed ? null : h("span", { class: "key" }, name)),
    h("div", { class: "chartbox" }, root));
}

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
    h("p", { class: "crumbs" }, h("a", { href: "#/runs" }, "All runs"), " / ", run.id),
    h("div", { class: "intro" }, h("h2", null, run.id),
      h("p", null, `${run.sessions.filter((e) => !e.control).length} repeated sessions and ${run.sessions.filter((e) => e.control).length} one-shot controls. `
        + "Strips show the winner of each round (striped = tie, dot = lowest-cost firm won). Click a seed to open the session. Means are descriptive: sessions are the unit, and there are few per cell.")),
    filters.length ? h("div", { class: "toggles filters" }, ...filters) : null,
    h("h2", { class: "sect" }, "Bids across the run"),
    h("p", { class: "sectnote" }, "Every valid bid in the sessions selected above, against the equilibrium bid; then each session against its one-shot control."),
    classCard(sessions),
    scatterCard(sessions),
    pairedCard(run, sessions),
    histogramCard(run, sessions),
    h("h2", { class: "sect" }, "Conditions and sessions"),
    h("p", { class: "sectnote" }, "One card per condition: its measures, then each repeated session above its matched one-shot control."),
    ...blocks));
}

function renderSession() {
  const root = document.getElementById("example");
  if (state.error || !state.custom) {
    root.replaceChildren(h("p", { class: "err" }, state.error || "Session not found."), h("a", { href: state.run ? `#/run/${encodeURIComponent(state.run.id)}` : "#/runs" }, "Back"));
    return;
  }
  renderExample();
  root.prepend(h("p", { class: "crumbs" }, h("a", { href: "#/runs" }, "All runs"), " / ", h("a", { href: `#/run/${encodeURIComponent(state.run.id)}` }, state.run.id), " / ", state.sid));
}

// Mean of (bid - equilibrium bid) by round block, one line per history session, with the one-shot mean for reference.
function blocksCard(run, table) {
  const lineups = [...new Set(table.map((r) => r.lineup_id))].sort();
  const blocks = [...new Set(table.map((r) => r.block))].sort((a, b) => parseInt(a, 10) - parseInt(b, 10));
  if (!lineups.length || blocks.length < 2) return null;
  const narrow = NARROW.matches, cols = narrow ? 1 : Math.min(2, lineups.length);
  const W = narrow ? 460 : 900, ml = 44, gapX = 64, mr = 46, headH = 34, mb = 46, ph = 250, pw = (W - ml - mr - (cols - 1) * gapX) / cols;
  const values = table.map((r) => r.mean_bid_minus_benchmark);
  const span = Math.max(...values) - Math.min(...values) || 1;
  const tick = [1, 2, 2.5, 5, 10].map((m) => m * 10 ** Math.floor(Math.log10(span / 4))).find((t) => span / t <= 6);
  const vmin = Math.floor(Math.min(...values, 0) / tick) * tick, vmax = Math.ceil(Math.max(...values, 0) / tick) * tick;
  const rowH = headH + ph + mb;
  const root = svg("svg", { class: "chart", viewBox: `0 0 ${W} ${Math.ceil(lineups.length / cols) * rowH}`, role: "img", "aria-label": "Bid minus equilibrium bid by round block, one line per session" });
  const labels = [];
  lineups.forEach((lineup, li) => {
    const x0 = ml + (li % cols) * (pw + gapX), y0 = Math.floor(li / cols) * rowH + headH;
    const x = (i) => x0 + (i / (blocks.length - 1)) * pw, y = (v) => y0 + (1 - (v - vmin) / (vmax - vmin)) * ph;
    const color = MODEL_COLORS[li % MODEL_COLORS.length];
    for (let v = vmin; v <= vmax + tick / 2; v += tick) {
      root.append(svg("line", { x1: x0, x2: x0 + pw, y1: y(v), y2: y(v), stroke: "var(--grid)", "stroke-width": 1 }));
      root.append(svg("text", { x: x0 - 6, y: y(v) + 4, "text-anchor": "end" }, (Math.abs(v) < tick / 2 ? 0 : v).toFixed(tick < 1 ? 1 : 0)));
    }
    blocks.forEach((b, i) => root.append(svg("text", { x: x(i), y: y0 + ph + 16, "text-anchor": "middle" }, b)));
    root.append(svg("text", { x: x0 + pw / 2, y: y0 + ph + 34, "text-anchor": "middle" }, "rounds"));
    root.append(svg("line", { x1: x0, x2: x0 + pw, y1: y(0), y2: y(0), stroke: "var(--text)", "stroke-width": 1.5, "stroke-dasharray": "5 4" }));
    root.append(svg("text", { class: "strong", x: x0, y: y0 - 14 }, lineup));
    const rows = table.filter((r) => r.lineup_id === lineup);
    const path = (pts) => pts.map(([i, v]) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
    const control = blocks.map((b, i) => [i, mean(rows.filter((r) => r.is_control && r.block === b).map((r) => r.mean_bid_minus_benchmark))]).filter(([, v]) => v != null);
    if (control.length > 1) root.append(svg("polyline", { points: path(control), fill: "none", stroke: "var(--muted)", "stroke-width": 2, "stroke-dasharray": "2 4", "stroke-linecap": "round" }));
    const seeds = [...new Set(rows.filter((r) => !r.is_control).map((r) => r.seed))].sort();
    const ends = [];
    for (const seed of seeds) {
      const pts = blocks.map((b, i) => [i, (rows.find((r) => !r.is_control && r.seed === seed && r.block === b) || {}).mean_bid_minus_benchmark]).filter(([, v]) => v != null);
      if (pts.length < 2) continue;
      const entry = run.sessions.find((e) => !e.control && e.seed === seed && e.lineup === lineup);
      const line = svg("g", { class: "pair" },
        svg("polyline", { class: "vis", points: path(pts), fill: "none", stroke: color, "stroke-width": 1.5, "stroke-linejoin": "round" }),
        svg("polyline", { points: path(pts), fill: "none", stroke: "transparent", "stroke-width": 14 }));
      const on = (ev) => {
        root.classList.add("focus"); line.classList.add("hot");
        tipAt(ev, h("div", null, h("b", null, `Seed ${seed}`), ` · ${lineup}`),
          ...pts.map(([i, v]) => h("div", { class: "row" }, h("b", null, `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}`), h("span", null, `rounds ${blocks[i]}`))),
          entry ? h("div", { class: "row" }, h("span", null, "Click to open the session")) : null);
      };
      line.addEventListener("pointerenter", on); line.addEventListener("pointermove", on); line.addEventListener("pointerdown", on);
      line.addEventListener("pointerleave", () => { root.classList.remove("focus"); line.classList.remove("hot"); hideTip(); });
      if (entry) line.addEventListener("click", () => { hideTip(); location.hash = `#/s/${encodeURIComponent(run.id)}/${encodeURIComponent(entry.id)}/0/1`; });
      root.append(line);
      ends.push({ seed, v: pts[pts.length - 1][1], xi: pts[pts.length - 1][0] });
    }
    // Name the three sessions that end highest, where their lines stop; labels that would touch are moved apart.
    let last = -Infinity;
    for (const e of ends.sort((p, q) => q.v - p.v).slice(0, 3)) {
      const ly = Math.max(y(e.v) + 4, last + 12);
      last = ly;
      labels.push(svg("text", { class: "inbar halo", x: x(e.xi) + 6, y: ly, "pointer-events": "none" }, String(e.seed).slice(-3)));
    }
  });
  root.append(...labels);
  return h("section", { class: "cond histo" },
    h("h3", null, "Bid minus equilibrium bid, as the session goes on"),
    h("p", { class: "meta" }, "One line per session with the history shown; the dotted grey line is the mean of the one-shot controls. Above the dashed line a firm bids over the equilibrium bid. "
      + "The numbers at the right are the last three digits of the seeds that end highest. Point at a line to read it; click to open that session."),
    h("div", { class: "legend" }, h("span", { class: "key" }, h("span", { class: "sw dash" }), "equilibrium bid"),
      h("span", { class: "key" }, h("span", { class: "sw line", style: "background:var(--muted)" }), "one-shot controls, mean")),
    h("div", { class: "chartbox" }, root));
}

const JUDGE_ROWS = [
  ["history_inference", "Infers the other firm's pattern from earlier rounds"],
  ["undercuts_rival_bid", "Sets its bid just below an earlier bid of the other firm"],
  ["anchors_on_past_price", "Takes a past price as the reference for its bid"],
  ["copies_rival_bid", "Copies the other firm's bid"],
  ["considers_coordination", "Considers coordinating"],
  ["adopts_coordination", "Decides to coordinate"],
  ["punish_reward", "Decides to punish or reward the other firm"],
];

// Share of judged calls with each label: one bar per model and arm.
function judgeCard(table) {
  if (!table || !table.length) return null;
  const lineups = [...new Set(table.map((r) => r.lineup_id))].sort();
  const series = lineups.flatMap((lineup, li) => [[lineup, false, "with history", 1], [lineup, true, "one-shot", 0.4]].map(([l, control, arm, alpha]) =>
    ({ row: table.find((r) => r.lineup_id === l && r.is_control === control), name: `${l}, ${arm}`, color: MODEL_COLORS[li % MODEL_COLORS.length], alpha }))).filter((s2) => s2.row);
  const narrow = NARROW.matches, W = narrow ? 460 : 900, x0 = narrow ? 12 : 330, x1 = W - 52, barH = 9, gap = 2, labelH = narrow ? 18 : 0;
  const groupH = labelH + series.length * (barH + gap) + 14;
  const H = JUDGE_ROWS.length * groupH + 26;
  const root = svg("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Share of judged calls with each label, by model and arm" });
  const px = (v) => x0 + v * (x1 - x0);
  for (let g = 0; g <= 4; g += 1) {
    root.append(svg("line", { x1: px(g / 4), x2: px(g / 4), y1: 0, y2: H - 22, stroke: "var(--grid)", "stroke-width": 1 }));
    root.append(svg("text", { x: px(g / 4), y: H - 6, "text-anchor": "middle" }, `${g * 25}%`));
  }
  JUDGE_ROWS.forEach(([key, label], gi) => {
    const top = gi * groupH + 4;
    root.append(narrow ? svg("text", { class: "strong", x: x0, y: top + 12 }, label)
      : svg("text", { x: x0 - 10, y: top + (series.length * (barH + gap)) / 2 + 4, "text-anchor": "end" }, label));
    series.forEach((s2, si) => {
      const v = s2.row[key] || 0, yb = top + labelH + si * (barH + gap);
      const bar = svg("rect", { class: "bar", x: x0, y: yb, width: Math.max(1, px(v) - x0).toFixed(1), height: barH, rx: 2, fill: s2.color, opacity: s2.alpha });
      const on = (ev) => tipAt(ev, h("div", null, h("b", null, `${(v * 100).toFixed(1)}%`), ` of ${s2.row.n_calls} judged calls`), h("div", { class: "row" }, h("span", null, s2.name)), h("div", { class: "row" }, h("span", null, label)));
      bar.addEventListener("pointermove", on); bar.addEventListener("pointerdown", on); bar.addEventListener("pointerleave", hideTip);
      root.append(bar);
      root.append(svg("text", { x: px(v) + 5, y: yb + barH - 1, "pointer-events": "none" }, `${(v * 100).toFixed(v > 0 && v < 0.1 ? 1 : 0)}%`));
    });
  });
  return h("section", { class: "cond histo" },
    h("h3", null, "What the reasoning says"),
    h("p", { class: "meta" }, "Share of judged calls carrying each label. Solid bars are sessions with the history shown; pale bars are the one-shot controls. "
      + "A label counts only with a word-for-word quote from the reasoning. The labels have not been checked by a person."),
    h("div", { class: "legend" }, ...series.map((s2) => h("span", { class: "key" }, h("span", { class: "sw box", style: `background:${s2.color};opacity:${s2.alpha}` }), s2.name))),
    h("div", { class: "chartbox" }, root));
}

function renderFindings() {
  const run = PUBLISHED.runs[0]; // the bundled copy, so the charts match the text even if a local export of the run is older
  const tables = PUBLISHED.tables[run.id] || {};
  const page = h("div", { class: "findings prose" });
  page.innerHTML = PUBLISHED.findings_html; // generated from a Markdown file of this repository at export time
  for (const slot of page.querySelectorAll(".chartslot")) {
    const [kind, arg] = slot.dataset.chart.split(":");
    const card = kind === "paired" ? pairedCard(run, run.sessions, arg) : kind === "scatter" ? scatterCard(run.sessions)
      : kind === "blocks" ? blocksCard(run, tables.round_blocks || []) : kind === "judge" ? judgeCard(tables.judge) : null;
    if (card) slot.replaceWith(card); else slot.remove();
  }
  const first = page.querySelector(".prosehead");
  if (first) first.append(h("p", { class: "meta" }, "The charts below are drawn from the bundled sessions of ",
    h("a", { href: `#/run/${encodeURIComponent(run.id)}` }, run.id), ". Open that run to see every session and step through its rounds."));
  document.getElementById("example").replaceChildren(page);
}

function render() {
  renderModes();
  renderNav();
  if (state.mode === "findings") renderFindings();
  else if (state.mode === "runs") renderRuns();
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
NARROW.addEventListener("change", () => { if (state.mode === "run") renderRun(); else if (state.mode === "findings") renderFindings(); });
if (PUBLISHED) document.getElementById("stamp").textContent = `Bundled data: ${PUBLISHED.runs.map((r) => r.id).join(", ")}, exported ${PUBLISHED.generated} at commit ${PUBLISHED.commit}.`;
window.addEventListener("hashchange", route);
route();
