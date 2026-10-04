# Log viewer plan

A static website for tracing auction sessions round by round: who bid what, who won, how ties resolved, what each firm reasoned, and exactly what each firm was shown. Modelled on the [Agent Collusion Explorer](https://salt-nlp.github.io/agent-collusion-website/) (SALT-NLP), adapted from chat episodes to sealed-bid rounds.

**Status:** a lite version is built (4 October 2026): one page, 7 curated examples, no router or all-runs index; see README.md "Example viewer". The rest of this plan is not built. Not part of the build order in `PLANNING.md` section 4; it reads the logs that order produces and changes nothing in them.

## 1. Purpose

- **Trace a session.** Follow bids, winners, ties, rebids and reasoning round by round, the way the main experiment's hand-coding and the pilot review need.
- **Check the harness by eye.** CLAUDE.md asks for a manual check for off-by-one errors in history formatting before scaling up. The viewer shows the exact prompt each firm received in each round, next to the round it was sent in.
- **Show rotation at a glance.** A winner ribbon per session (one cell per round, coloured by firm) makes turn-taking, ties and the lowest-cost winner visible without reading tables, and puts each session beside its one-shot control.
- **Pitch material.** Phase A's output is a pitch to prospective teammates (`PLANNING.md` 7.1). A link to a browsable pilot is easier to share than CSVs.

Not a goal: inference. The viewer shows per-session metrics already computed by `analysis/metrics.py`; intervals and tests stay in step 3b.

## 2. What the reference site does

Plain JavaScript modules and one stylesheet, no build step. It loads one small index file, then fetches each run's data only when it is opened. Pages link by URL fragment (`#/explore`, `#/c/<condition>`), so every view can be linked to directly. Three levels: a filterable grid of condition cards; every run in a condition, each with a ribbon summarising its episodes; and one run, with a clickable episode strip and collapsible sections per phase.

This plan keeps that structure. The ribbon becomes the round-by-round winner sequence; the phases become a round's bids, tie resolution, reasoning and prompts.

## 3. Architecture

```
scripts/export_site.py        logs/<run_id>/ -> site/data/<run_id>/
site/
  index.html
  assets/css/app.css
  assets/js/app.js            router (URL fragment) and page shell
  assets/js/store.js          loads runs.json and index.json once, session bundles on demand
  assets/js/overview.js       run picker and condition table
  assets/js/condition.js      sessions of one condition, with control ribbons
  assets/js/session.js        one session: header, round strip, chart, round panel
  assets/js/charts.js         hand-drawn SVG: ribbon, bids-over-rounds chart
  assets/js/visibility.js     agent's-view filter (mirrors prompts.visible_rows)
  assets/js/dom.js            small element helpers
  data/runs.json              exported runs
  data/<run_id>/index.json
  data/<run_id>/sessions/<session_id>.json
tests/test_export_site.py
```

No framework and no external JavaScript, so it can be served by any static host as-is.

### 3.1 Exporter

`uv run python scripts/export_site.py logs/<run_id> [--out site/data/<run_id>] [--no-prompts] [--no-thinking]`; `--no-thinking` leaves out the hidden thinking text and keeps its token count, for a smaller export to share

- **`index.json`:** run metadata; conditions with their settings; one entry per session with the `session_metrics.csv` row (reusing `analysis/metrics.py`) and a compact winner string for the ribbon (winning firm per round, tie flag, lowest-cost-won flag).
- **`sessions/<session_id>.json`:** `session.json` contents; rounds with every firm's cost, bid, rebid, BNE bid, winner, profit, tie fields and attempts; calls grouped by round, firm and phase, with the tool call's reasoning, the hidden `thinking` text, any free `content` outside the tool call, `finish_reason` (a reply cut off at the cap shows as `length`), retries, errors and tokens including `reasoning_tokens`.
- **Prompts:** each firm's system prompt once per session, and the per-call user message for each call. Raw API responses are left out.
- **`runs.json`:** appended or updated per export.
- Only complete sessions by default, as in `analyze.py`. Missing values are JSON null; output is deterministic (sorted keys and rows).

### 3.2 Pages

| Page | Route | Contents |
|---|---|---|
| Overview | `#/` | Run picker. Rule × model table: index, control index, delta, lowest-cost-wins share, tie rate, tie-price index, rebid delta; a sample-size caption ("n = 5, directional only" for the pilot). Win-pattern columns greyed under `least_wins` (`PLANNING.md` 6.4). |
| Condition | `#/c/<condition_id>` | One row per session: winner ribbon and key metrics, with the matched one-shot control's ribbon directly underneath (same seed, same costs). |
| Session | `#/s/<session_id>/r/<round>` | Header, round strip, chart and round panel (3.3). |

### 3.3 Session page

- **Header:** model per slot, rule, information level, seed, host and quantisation, status, metric chips.
- **Round strip:** the ribbon, clickable; arrow keys step rounds; a play button steps automatically.
- **Chart:** bids over rounds, one line per firm; costs dotted; BNE bid and reserve marked; the winning bid highlighted; ties and rebids flagged.
- **Round panel:**
  - Per-firm table: cost, bid, rebid, BNE bid, winner, profit, tied, attempts.
  - Reasoning card per firm for the bid and, under `bafo`, the rebid; failed retries folded away with their error.
  - "What firm X saw": the system prompt and that round's user message, from `calls.jsonl`.
- **Agent's-view toggle:** hides what the selected firm could not see under the session's information level, using the same rules as `prompts.visible_rows`.

### 3.4 Ribbon encoding

One cell per round. Fill colour is the winning firm (a fixed colourblind-safe palette, consistent across pages). Hatching marks a round decided by a tie, with the resolution (`random`, `least_wins`, `bafo`, `bafo_random`) in the tooltip. A dot marks a round the lowest-cost firm won. An empty cell is a round with no valid bid.

## 4. Size

| Data | Sessions | Per session | Total |
|---|---|---|---|
| Scripted demo (sanity configs) | 324 | ~20 KB | ~6 MB |
| Phase A pilot (90 sessions, thinking on for all three models; thinking text about 5–8 KB per DeepSeek or Qwen call) | 90 | 0.4–1 MB | about 65 MB |
| Phase A pilot, `--no-thinking` | 90 | about 0.3 MB | about 25 MB |
| Main experiment, with prompts (thinking off; thinking text would add a few MB per session) | 432 | 350–600 KB | 150–250 MB |
| Main experiment, `--no-prompts` | 432 | ~60 KB | ~25 MB |

GitHub Pages caps a site at 1 GB and recommends staying well under it.

## 5. Testing

- **Exporter (pytest):** bundle shape, round and call counts against the logs, metrics equal to `session_metrics_table`, null for missing values, deterministic output, a control linked to every repeated session that has one.
- **Agent's-view filter:** the JavaScript filter is checked against `prompts.visible_rows` on exported fixtures, so the two cannot drift apart.
- **Manual:** served locally on the scripted demo data, then on the pilot before it is shared.

## 6. Estimate

About 400 lines for the exporter and its tests, and about 1,200 lines of JavaScript and CSS; roughly 300–500k tokens. No API spend.

## 7. Decisions

Answered on 3 October 2026:

- **Hosting:** local for now (`uv run python -m http.server -d site 8000`). A GitHub Actions workflow deploys to Pages once there is a public home; the repo is private, and Pages on a private repo needs a paid plan.
- **Data in git:** commit the scripted demo export and, once it exists, the Phase A pilot export (about 65 MB with the thinking text, about 25 MB with `--no-thinking`; decide which before committing). Other runs under `site/data/` stay gitignored until a decision to share them.
- **Private costs:** the researcher view, with every firm's cost and BNE bid, is the default. The agent's-view toggle switches to what one firm saw. The site is never shown to an agent, so this does not touch the rule that agents never see other agents' costs.
- **First version's scope:** all three pages (overview, condition, session), with the agent's-view toggle and the prompt viewer.

Still open:

- **Large runs:** whether a published main-experiment export keeps prompts (150–250 MB) or uses `--no-prompts` (~25 MB). Decided before Phase B data is exported.
