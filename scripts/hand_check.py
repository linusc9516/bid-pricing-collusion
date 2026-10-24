"""CLI: judge hand-check files -> local HTML pages for reading and coding them.

Usage: hand_check.py [RUN[:STEM] ...] [--all] [--open]

By default only the declared hand checks (REQUIRED) are built; --all builds every check file, and RUN or RUN:STEM picks
some. For each results/<run>/<stem>_check.csv (stem trace_judge, notes_judge or messages_judge) whose logs are present, writes
logs/hand_check/<run>__<stem>.html: each checked row beside the full text the judge saw, with the judge's quotes
marked, a verdict per label, and buttons to code each label as right or wrong. Codes are kept in the browser and
exported as CSV (save it as results/<run>/<stem>_handcheck.csv). Also writes logs/hand_check/index.html. The pages
embed hidden thinking, so they stay under logs/, which git ignores.
"""

import argparse
import html
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

from bidrig.analysis.trace_judge import (
    BID_RUBRIC,
    MESSAGES_RUBRIC,
    NOTES_RUBRIC,
    Rubric,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from judge_traces import load_traces

PHASES: dict[str, tuple[str, Rubric]] = {"trace_judge": ("bid", BID_RUBRIC), "notes_judge": ("reflect", NOTES_RUBRIC), "messages_judge": ("message", MESSAGES_RUBRIC)}
# Declared before their labels are reported (channel_c1, notes_deepseek, notes_luna); channel_extensions and luna_long
# declare none of their own and rely on channel_c1's messages check.
REQUIRED = (("channel_c1", "messages_judge"), ("notes_deepseek", "notes_judge"), ("notes_luna", "notes_judge"))
# Labels the paper reports; the other labels are coded only where the judge marks them true.
PRIMARY = {"messages_judge": ("proposes_coordination", "accepts_coordination", "rejects_coordination", "threatens_rival", "reveals_own_cost"),
           "notes_judge": ("uses_rival_notes", "aware_rival_reads", "proposes_coordination", "reveals_own_cost")}
ARMS = (("__pn", "M1 private notes"), ("__ws", "M2 shared notes"), ("__msg", "C1 messages"), ("oneshot__", "one-shot control"))


def arm_of(session_id: str) -> str:
    """Arm label from a session id's condition suffix; 'repeated' when it has none."""
    return next((name for key, name in ARMS if key in session_id), "repeated")


def earlier_messages(logs_root: Path, run: str, session_id: str, before: int, rounds: int = 2) -> list[dict]:
    """Messages both firms sent after the `rounds` rounds before round `before`: what a firm had read in that step."""
    path = next((logs_root / run).glob(f"*/{session_id}/messages.jsonl"), None)
    if path is None:
        return []
    events = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [{"round": e["round"], "firm": e["firm_id"], "text": e.get("text") or ""} for e in events
            if e.get("op") == "write" and before - rounds <= e["round"] < before]


def page_data(run: str, stem: str, logs_root: Path, results_root: Path, check_root: Path | None = None) -> dict | None:
    """Rows of one check file (under `check_root`, default `results_root`) with their full trace text; None if the run's logs are missing."""
    phase, rubric = PHASES[stem]
    check = pd.read_csv((check_root or results_root) / run / f"{stem}_check.csv")
    if not (logs_root / run).is_dir():
        return None
    wanted = set(check["session_id"])
    traces, info = load_traces(logs_root / run, only=sorted(wanted), phase=phase)
    text = {(t.session_id, t.round, t.firm_id): (t.text, t.model) for t in traces}
    # A check file written under an older rubric version has fewer label columns than the current rubric.
    labels = [label for label in rubric.labels if f"{label}_quote" in check.columns]
    version = rubric.version if labels == rubric.labels else f"older than {rubric.version}"
    primary = [label for label in PRIMARY.get(stem, labels) if label in labels]
    # accepts_coordination needs to know whose proposal a firm follows, which one judged step does not show.
    first_proposal: dict[str, dict[str, int]] = {}
    judged_path = results_root / run / f"{stem}.csv"
    if "proposes_coordination" in labels and judged_path.exists():
        judged = pd.read_csv(judged_path)
        proposed = judged[judged["proposes_coordination"].astype(str).str.lower() == "true"]
        for (session, firm), g in proposed.groupby(["session_id", "firm_id"]):
            first_proposal.setdefault(session, {})[str(firm)] = int(g["round"].min())
    rows = []
    for r in check.itertuples(index=False):
        body, model = text.get((r.session_id, int(r.round), str(r.firm_id)), ("(trace not found in the logs)", ""))
        quotes = {label: getattr(r, f"{label}_quote") for label in labels}
        rows.append({
            "key": f"{r.session_id}|{int(r.round)}|{r.firm_id}", "session": r.session_id, "round": int(r.round), "firm": str(r.firm_id),
            "model": model, "arm": arm_of(r.session_id), "seed": info.get(r.session_id, {}).get("seed"), "text": body,
            "quotes": {k: (v if isinstance(v, str) and v.strip() else None) for k, v in quotes.items()},
            "first_proposal": first_proposal.get(r.session_id, {}),
            "earlier": earlier_messages(logs_root, run, r.session_id, int(r.round)) if phase == "message" else [],
        })  # fmt: skip
    return {"run": run, "stem": stem, "rubric": version, "phase": phase, "labels": labels, "primary": primary, "definitions": rubric.definitions, "rows": rows}


TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hand check: __TITLE__</title>
<style>
:root { --bg:#fbfbfa; --panel:#fff; --text:#1d1d1f; --muted:#6e6e73; --line:#e3e3e0; --accent:#2f6fdb; --ok:#1f8a4c; --bad:#c2372f; --hl:#fff1a8; --hl2:#ffd9a8; }
@media (prefers-color-scheme: dark) { :root { --bg:#161617; --panel:#1f1f21; --text:#ececee; --muted:#9a9aa0; --line:#2e2e31; --accent:#6aa0ff; --ok:#4cc27e; --bad:#ff6b61; --hl:#5a4f12; --hl2:#5e3b12; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text); font:14px/1.5 -apple-system, system-ui, sans-serif; }
header { padding:12px 16px; border-bottom:1px solid var(--line); display:flex; gap:12px; align-items:center; flex-wrap:wrap; }
header h1 { font-size:16px; margin:0; } header .meta { color:var(--muted); }
header .spacer { flex:1; } button { font:inherit; cursor:pointer; border:1px solid var(--line); background:var(--panel); color:var(--text); border-radius:6px; padding:4px 10px; }
button.on.ok { background:var(--ok); color:#fff; border-color:var(--ok); } button.on.bad { background:var(--bad); color:#fff; border-color:var(--bad); }
.wrap { display:grid; grid-template-columns: 240px 1fr; min-height: calc(100vh - 56px); }
nav { border-right:1px solid var(--line); overflow:auto; max-height: calc(100vh - 56px); }
nav a { display:block; padding:6px 12px; color:var(--text); text-decoration:none; border-bottom:1px solid var(--line); font-size:13px; }
nav a.cur { background:var(--panel); border-left:3px solid var(--accent); } nav a .s { float:right; color:var(--muted); }
main { padding:16px; overflow:auto; max-height: calc(100vh - 56px); }
.card { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:14px 16px; margin-bottom:14px; }
table { border-collapse:collapse; width:100%; } td, th { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); vertical-align:top; }
th { color:var(--muted); font-weight:500; font-size:12px; }
.lab { font-family: ui-monospace, monospace; font-size:12.5px; } .def { color:var(--muted); font-size:12px; }
.yes { color:var(--accent); font-weight:600; } .no { color:var(--muted); }
.quote { font-style:italic; color:var(--accent); } .miss { color:var(--bad); font-size:12px; }
pre { white-space:pre-wrap; overflow-wrap:anywhere; font:13px/1.55 ui-monospace, monospace; margin:0; }
mark { background:var(--hl); color:inherit; border-radius:3px; } mark.sel { background:var(--hl2); outline:2px solid var(--accent); }
textarea { width:100%; min-height:48px; font:inherit; background:var(--bg); color:var(--text); border:1px solid var(--line); border-radius:6px; padding:6px; }
.keys { color:var(--muted); font-size:12px; }
@media (max-width: 760px) { .wrap { grid-template-columns: 1fr; } nav { max-height: 180px; border-right:0; border-bottom:1px solid var(--line); } main { max-height:none; } }
</style></head><body>
<header><h1>__TITLE__</h1><span class="meta" id="meta"></span><span class="spacer"></span>
<span class="meta" id="progress"></span><button id="export">Export codes (CSV)</button></header>
<div class="wrap"><nav id="nav"></nav><main id="main"></main></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById("data").textContent);
const KEY = `handcheck:${D.run}:${D.stem}:${D.rubric}`;
let codes = {}; try { codes = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) {}
const save = () => { try { localStorage.setItem(KEY, JSON.stringify(codes)); } catch (e) {} };
let cur = 0;
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const norm = (s) => s.replace(/\\s+/g, " ").toLowerCase();
function locate(text, quote) {
  // The judge's quote is verbatim up to whitespace; map a whitespace-squashed match back to the raw text.
  const map = []; let squashed = "";
  for (let i = 0; i < text.length; i++) { const ch = /\\s/.test(text[i]) ? " " : text[i].toLowerCase(); if (ch === " " && squashed.endsWith(" ")) continue; squashed += ch; map.push(i); }
  const at = squashed.indexOf(norm(quote).trim());
  if (at < 0) return null;
  return [map[at], map[at + norm(quote).trim().length - 1] + 1];
}
function highlighted(text, quotes, selected) {
  const spans = [];
  for (const [label, q] of Object.entries(quotes)) { if (!q) continue; const r = locate(text, q); if (r) spans.push([...r, label]); }
  spans.sort((a, b) => a[0] - b[0]);
  let out = "", pos = 0;
  for (const [a, b, label] of spans) { if (a < pos) continue; out += esc(text.slice(pos, a)) + `<mark data-l="${label}" class="${label === selected ? "sel" : ""}" title="${label}">${esc(text.slice(a, b))}</mark>`; pos = b; }
  return out + esc(text.slice(pos));
}
const isPrimary = (l) => D.primary.includes(l);
const toCode = (row) => D.labels.filter((l) => isPrimary(l) || row.quotes[l]);
const done = (row) => toCode(row).every((l) => codes[row.key] && codes[row.key][l]);
function renderNav() {
  document.getElementById("nav").innerHTML = D.rows.map((r, i) =>
    `<a href="#" data-i="${i}" class="${i === cur ? "cur" : ""}">${i + 1}. ${esc(r.arm)} · seed ${r.seed ?? "?"} · r${r.round} ${esc(r.firm)}<span class="s">${done(r) ? "✓" : ""}</span></a>`).join("");
  document.querySelectorAll("nav a").forEach((a) => a.onclick = (e) => { e.preventDefault(); cur = +a.dataset.i; render(); });
  const n = D.rows.filter(done).length;
  document.getElementById("progress").textContent = `${n} / ${D.rows.length} rows coded`;
}
let selected = null;
function render() {
  const r = D.rows[cur], c = codes[r.key] || (codes[r.key] = {});
  const labelRow = (l) => {
    const q = r.quotes[l], found = q ? !!locate(r.text, q) : true, v = c[l], codable = isPrimary(l) || q;
    return `<tr><td><div class="lab">${l}</div><div class="def">${esc(D.definitions[l] || "")}</div></td>
      <td class="${q ? "yes" : "no"}">${q ? "true" : "false"}</td>
      <td>${q ? `<a href="#" class="quote" data-l="${l}">“${esc(q)}”</a>${found ? "" : '<div class="miss">quote not found verbatim in the text</div>'}` : ""}</td>
      <td style="white-space:nowrap">${codable ? `<button class="ok ${v === "right" ? "on" : ""}" data-l="${l}" data-v="right">right</button>
        <button class="bad ${v === "wrong" ? "on" : ""}" data-l="${l}" data-v="wrong">wrong</button>` : '<span class="def">not coded</span>'}</td></tr>`;
  };
  const head = '<thead><tr><th>Label</th><th>Judge</th><th>Quote (click to find)</th><th>Your code</th></tr></thead>';
  const primaryRows = D.labels.filter(isPrimary).map(labelRow).join("");
  const otherLabels = D.labels.filter((l) => !isPrimary(l));
  const fp = Object.entries(r.first_proposal || {}).sort().map(([f, rd]) => `firm ${esc(f)} round ${rd}`).join(", ");
  const proposalLine = r.first_proposal ? `<p class="def">First step the judge labels <i>proposes coordination</i>, per firm, anywhere in this session: ${fp || "none"}. Use it for accepts_coordination: accepting means following the other firm's proposal.</p>` : "";
  const earlierCard = (r.earlier || []).length ? `<div class="card"><b>Messages already read in this step</b> <span class="def">(both firms, the two rounds before; the judge did not see these)</span>
      ${r.earlier.map((m) => `<p><b>round ${m.round} · firm ${esc(m.firm)}${m.firm === r.firm ? " (this firm)" : ""}:</b> ${esc(m.text) || '<span class="def">(empty)</span>'}</p>`).join("")}</div>` : "";
  const otherCard = otherLabels.length ? `<div class="card"><b>Other labels</b> <span class="def">(not reported in the paper; code only those the judge marks true)</span>
      <table>${head}<tbody>${otherLabels.map(labelRow).join("")}</tbody></table></div>` : "";
  document.getElementById("main").innerHTML = `
    <div class="card"><b>${esc(r.arm)}</b> · ${esc(r.model)} · seed ${r.seed ?? "?"} · round ${r.round} · firm ${esc(r.firm)}
      <div class="def">${esc(r.session)}</div>
      <div class="keys">Keys: ← → rows · mark each label right (judge correct) or wrong; a false label that should be true is wrong. “All shown right” marks every uncoded label that needs a code right.</div></div>
    <div class="card"><b>Labels used in the paper</b><table>${head}<tbody>${primaryRows}</tbody></table>${proposalLine}
      <p><button id="allright">All shown right</button></p>
      <textarea id="note" placeholder="Note for this row">${esc(c._note || "")}</textarea></div>
    ${earlierCard}
    ${otherCard}
    <div class="card"><pre id="text">${highlighted(r.text, r.quotes, selected)}</pre></div>`;
  document.querySelectorAll("button[data-v]").forEach((b) => b.onclick = () => { c[b.dataset.l] = c[b.dataset.l] === b.dataset.v ? undefined : b.dataset.v; save(); render(); });
  document.querySelectorAll("a.quote").forEach((a) => a.onclick = (e) => { e.preventDefault(); selected = a.dataset.l; render(); const m = document.querySelector("mark.sel"); if (m) m.scrollIntoView({ block: "center" }); });
  document.getElementById("allright").onclick = () => { toCode(r).forEach((l) => { if (!c[l]) c[l] = "right"; }); save(); render(); };
  document.getElementById("note").oninput = (e) => { c._note = e.target.value; save(); renderNav(); };
  renderNav();
}
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "TEXTAREA") return;
  if (e.key === "ArrowRight" && cur < D.rows.length - 1) { cur++; selected = null; render(); }
  if (e.key === "ArrowLeft" && cur > 0) { cur--; selected = null; render(); }
});
document.getElementById("export").onclick = () => {
  const q = (s) => `"${String(s ?? "").replace(/"/g, '""')}"`;
  const lines = [["session_id", "round", "firm_id", "label", "judge", "coder", "note"].join(",")];
  for (const r of D.rows) { const c = codes[r.key] || {}; for (const l of D.labels) lines.push([r.session, r.round, r.firm, l, r.quotes[l] ? "true" : "false", c[l] || "", q(c._note)].join(",")); }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([lines.join("\\n") + "\\n"], { type: "text/csv" }));
  a.download = `${D.stem}_handcheck.csv`; a.click();
};
document.getElementById("meta").textContent = `rubric ${D.rubric} · ${D.rows.length} rows · ${D.labels.length} labels`;
render();
</script></body></html>
"""


def write_page(data: dict, out: Path, suffix: str = "") -> Path:
    """Render one check file's page into `out`; returns its path."""
    title = f"{data['run']} · {data['stem'].replace('_', ' ')}" + (f" · {suffix}" if suffix else "")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    path = out / f"{data['run']}__{data['stem']}{'__' + suffix if suffix else ''}.html"
    path.write_text(TEMPLATE.replace("__TITLE__", html.escape(title)).replace("__DATA__", payload))
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs", nargs="*", help="RUN or RUN:STEM (default: the declared hand checks, REQUIRED)")
    parser.add_argument("--all", action="store_true", help="every run with a *_check.csv in results/")
    parser.add_argument("--logs-root", type=Path, default=ROOT / "logs")
    parser.add_argument("--results-root", type=Path, default=ROOT / "results")
    parser.add_argument("--check-root", type=Path, help="read the check files from here instead (a subsample); judged files still come from --results-root")
    parser.add_argument("--suffix", default="", help="added to the page file names, so a subsample page does not replace a full one")
    parser.add_argument("--open", action="store_true", help="open the index page in the browser")
    args = parser.parse_args()

    out = args.logs_root / "hand_check"
    out.mkdir(parents=True, exist_ok=True)
    if args.all:
        wanted = [(run, stem) for run in sorted({p.parent.name for p in args.results_root.glob("*/*_check.csv")}) for stem in PHASES]
    elif args.runs:
        wanted = [tuple(spec.split(":", 1)) if ":" in spec else (spec, stem) for spec in args.runs for stem in ([None] if ":" in spec else PHASES)]
        wanted = [(run, stem) for run, stem in wanted if stem is not None]
    else:
        wanted = list(REQUIRED)
    pages = []
    for run, stem in wanted:
        if not ((args.check_root or args.results_root) / run / f"{stem}_check.csv").exists():
            continue
        data = page_data(run, stem, args.logs_root, args.results_root, args.check_root)
        if data is None:
            print(f"{run} {stem}: no logs under {args.logs_root / run}, skipped")
            continue
        missing = sum(r["text"] == "(trace not found in the logs)" for r in data["rows"])
        path = write_page(data, out, args.suffix)
        pages.append(path)
        print(f"{path.name}: {len(data['rows'])} rows" + (f", {missing} without a trace" if missing else ""))
    listed = sorted(p for p in out.glob("*.html") if p.name != "index.html")
    items = "".join(f'<li><a href="{html.escape(p.name)}">{html.escape(p.stem.replace("__", " · "))}</a></li>' for p in listed)
    index = out / "index.html"
    index.write_text(f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
                     f'<title>Hand checks</title><style>body{{font:15px/1.6 -apple-system,system-ui,sans-serif;max-width:720px;margin:32px auto;padding:0 16px}}'
                     f'@media (prefers-color-scheme: dark){{body{{background:#161617;color:#ececee}} a{{color:#6aa0ff}}}}</style></head>'
                     f'<body><h1>Hand checks</h1><p>The declared hand checks: code every row of each page, then export it as CSV to results/&lt;run&gt;/&lt;stem&gt;_handcheck.csv. Codes stay in this browser.</p><ul>{items}</ul></body></html>')  # fmt: skip
    print(f"wrote {index}")
    if args.open:
        subprocess.run(["open", str(index)], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
