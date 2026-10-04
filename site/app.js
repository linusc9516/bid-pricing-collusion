"use strict";
// Static viewer for exported auction sessions (site/data/examples.js, built by scripts/export_examples.py).
// All text from the data goes in through textContent, never innerHTML.

const EXAMPLES = window.EXAMPLES.examples;
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
const state = { ex: 0, s: 0, round: 1, showCost: false, showBne: false };

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
const current = () => EXAMPLES[state.ex].sessions[state.s];

function readHash() {
  const [id, s, r] = location.hash.replace(/^#\/?/, "").split("/");
  const i = EXAMPLES.findIndex((e) => e.id === id);
  if (i < 0) return;
  state.ex = i;
  state.s = Math.min(Number(s) || 0, EXAMPLES[i].sessions.length - 1);
  state.round = Math.min(Math.max(Number(r) || 1, 1), current().rounds.length);
}
function writeHash() {
  history.replaceState(null, "", `#/${EXAMPLES[state.ex].id}/${state.s}/${state.round}`);
}

function renderNav() {
  const nav = document.getElementById("examples");
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
  return h("p", { class: "meta" },
    `${m.n_bidders} firms · ${m.n_rounds} rounds · costs uniform ${m.cost_range[0]}–${m.cost_range[1]} · bids in steps of ${m.increment} up to ${m.reserve} · tie rule ${m.tie_break_rule} · prompt ${m.prompt_version || "v0"}`);
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

function render() {
  const ex = EXAMPLES[state.ex], s = current();
  renderNav();
  const toggle = (key, text) => h("label", null, h("input", { type: "checkbox", checked: state[key], onchange: (e) => { state[key] = e.target.checked; render(); } }), text);
  document.getElementById("example").replaceChildren(...[
    h("div", { class: "intro" }, h("h2", null, ex.title), h("p", null, ex.blurb), h("p", { class: "look" }, h("b", null, "Look for: "), ex.look_for)),
    firmsLegend(s),
    renderStrips(ex),
    chips(s),
    metaLine(s),
    h("div", { class: "chartbox" }, chartFor(s)),
    h("div", { class: "toggles" }, "Filled dot = bid, ringed = winner.", toggle("showCost", "Show costs (hollow circle)"), toggle("showBne", "Show equilibrium bids (diamond)")),
    systemPrompt(s),
    roundPanel(s)].filter(Boolean));
  writeHash();
}

document.addEventListener("keydown", (e) => {
  if (e.target.matches("input, textarea") || e.metaKey || e.ctrlKey) return;
  const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
  if (!d) return;
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
readHash();
render();
