# CLAUDE.md

## Project
LLM agent collusion experiment: sealed-bid procurement auctions, testing whether
tacit bid rotation emerges, and whether tie-break rule design (random /
least-wins-first / BAFO rebid) acts as a lever on it. Target: Apart Research
AI Collusion Sprint, Track 1 (Markets and Collusion), question 1.5.

Full design: see BidPricingCollusion.md and PLANNING.md. Read both before
making structural changes.

## Commands
Dependencies are managed with uv (`uv sync` once; then prefix commands with `uv run`).

- `uv run pytest` — run before any PR-equivalent milestone
- `uv run python scripts/run_experiment.py configs/pilot.yaml` — Phase A pilot
  (all three tie-break conditions are in the one config; add `--dry-run` for a
  call and cost estimate without spending)
- `uv run python scripts/run_experiment.py configs/<name>.yaml --run-id <id>` —
  Phase B: `main_tiebreak.yaml`, then the `supporting_*.yaml` configs, under one run id
- `uv run python scripts/analyze.py logs/<run_id>` — logs to result tables
- `uv run python scripts/check_logs.py logs/<run_id>` — checks the raw logs (auction rules, every
  prompt, hosts); `--pick` / `--show` print prompts to read by hand. Run it on every live run first
- Lint: `uv run ruff check src/` (fix with `uv run ruff check --fix src/` before committing)

Configs that call models ask for confirmation unless `--yes` is given. Before the first
live call, run `uv run python scripts/smoke_test.py` (prints the plan) and then with
`--yes`, then the end-to-end check `configs/pilot_tiny.yaml` (PLANNING.md 5.5). If a
pinned host fails, rerun with `--host fallback`, then `--host backup`.

## Code style
- Comments: one-line docstrings stating units, ranges, and return semantics —
  not what the code visibly does. Inline comments only for non-obvious
  rationale (e.g. *why* a formula/constant is what it is). No narration, no
  restating the line below it, no comments on routine filesystem/logging code.
- Don't delete an existing comment without flagging it first — some encode
  design decisions from BidPricingCollusion.md discussions.
- Type hints on all function signatures (this is a stats-correctness-critical
  repo; a wrong type silently corrupts a metric).

## Non-negotiable constraints
- **Auctioneer is rule-based code, never an LLM call.** Deterministic winner
  determination, uncorrelated with agent behavior. Don't "improve" this with
  an LLM-based auctioneer.
- **Agents never see other agents' private costs**, in any info-revelation
  condition. Only bids/outcomes are ever shown. If a change risks leaking
  cost data into an agent-facing prompt, stop and ask.
- **No agent-to-agent communication channel.** Deliberate, to avoid
  steganography-related scope creep. Don't add one without being asked.
- **tie_break_rule config flag** (`random` | `least_wins` | `bafo`) stays a
  single parameter on the auctioneer, not three separate code paths.
- Models: only call models from `configs/models.yaml`. Don't swap in a
  different model "for convenience."

## Metrics — condition-specific, don't mix these up
- Primary outcome in every condition: `delta_index`, the session's collusion
  index minus that of its matched one-shot control. It measures price, not who
  won, so it is valid under all three tie-break rules. The index is not a 0-1
  scale; never clip it.
- Win-rate chi-square vs. uniform is a **descriptive** statistic per session,
  never a pooled test. `random` / `bafo`: valid to read.
- `least_wins`: win-rate chi-square is **not valid** here (the rule forces
  uniformity by construction). Use tie-frequency-over-time and
  tie-price-vs-BNE-benchmark instead. See PLANNING.md section 6.4.
- `bafo`: also report the rebid price delta (rebid minus original tied bid).
- All inference is at session level; a round is never an observation.
- BNE benchmark formula is closed-form (`b*(c) = c + (c_max - c) / n`),
  computed once per bidder-count condition, not re-derived per round.

## Workflow
- Two-phase execution: Phase A (two cheap models, small pilot) must
  complete and be reviewed before Phase B (full model lineup, full reps)
  starts. Don't begin Phase B without explicit confirmation — see
  PLANNING.md "Phased Execution Plan."
- REMINDER before Phase B: thinking mode, output-token cap and reasoning length
  are all TBD (the Phase B configs say TBD and the runner refuses to call models).
  Phase A runs DeepSeek and Qwen with thinking off, gpt-oss at low effort, and a
  2-3 sentence reasoning field (PLANNING.md 5.6). If an LLM judge will analyse the
  traces, Phase B needs longer reasoning and a re-estimated budget (7.2). Ask the
  user before the main run.
- Always run the positive control first: confirm baseline rotation-like
  behavior exists under `random` tie-break before comparing conditions.
- Log every round to JSONL, not just summary stats — raw per-round data is
  needed for bootstrap CIs and CoT review. One directory per session,
  `logs/<run_id>/<condition_id>/<session_id>/`, holding `session.json`,
  `bids.jsonl` (one row per firm per round) and `calls.jsonl` (one row per LLM
  attempt). Schema in PLANNING.md section 3.

## File structure
```
BidPricingCollusion.md   experimental design
PLANNING.md              build plan, data schema, budget, phased execution, risks
README.md                setup, how to run, what the experiments are
PREP_LOG.md              dated record of pre-sprint work (disclosure)
CLAUDE.md                this file
pyproject.toml, uv.lock  dependencies (uv)
.env.example             expected env vars; .env holds the key and is gitignored
configs/
  base.yaml              shared defaults: auction, session, llm, budget
  models.yaml            model aliases -> OpenRouter slugs and prices
  analysis.yaml          pre-declared outcome, comparisons, correction
  sanity_dummy.yaml      scripted bidders, no API calls
  sanity_tiebreak.yaml   scripted bidders under the three tie-break rules
  pilot_tiny.yaml        end-to-end check before the pilot: 18 sessions of 3 rounds
  pilot.yaml             Phase A pilot: three models, three tie-break rules
  main_tiebreak.yaml     main experiment: tie-break rule, with one-shot controls
  supporting_info.yaml   supporting ablation: information revelation
  supporting_n.yaml      supporting ablation: number of bidders
  supporting_lineup.yaml supporting ablation: same-model vs. mixed lineup
prompts/                 bidder_system.md, the bidder system prompt template
src/bidrig/              all built except analysis/stats.py and analysis/report.py (step 3b)
  schema.py              session / bid-row / call-row dataclasses
  bne.py                 closed-form BNE benchmark
  auction.py             rule-based auctioneer
  bidders.py             Bidder interface, scripted bidders, LLM bidder
  prompts.py             visibility filter and history formatters
  llm.py                 OpenRouter wrapper
  runner.py              sweep orchestrator
  analysis/              metrics.py, stats.py, report.py
scripts/
  run_experiment.py      CLI: run a config
  analyze.py             CLI: logs -> results
  smoke_test.py          CLI: one call per pinned host (PLANNING.md 5.5)
  check_logs.py          CLI: consistency checks on a run's raw logs (src/bidrig/checks.py)
tests/                   one test file per built module; helpers.py builds scripted sessions;
                         snapshots/ holds the prompt snapshots (regenerate with UPDATE_SNAPSHOTS=1)
logs/                    raw per-session output (gitignored)
results/                 aggregated tables and figures
```

## Gotchas
- Off-by-one in history formatting (showing round *t*'s bid before round *t*
  happened) is the most common bug class here — check manually on a pilot
  before scaling up.
- History length must stay identical across info-revelation conditions — it's
  a confound if it isn't. The plan shows the whole session (`history_window:
  null`), with no rolling window; `0` is reserved for the one-shot control.
- Use the uv-managed `.venv`, not system pip. If console scripts fail with
  "No such file or directory" after the repo directory is moved or renamed,
  rebuild it: `rm -rf .venv && uv sync`.
- PLANNING.md, README.md and BidPricingCollusion.md are symlinked into an
  Obsidian vault. If one is open there with unsaved edits, Obsidian can write
  its older copy back over a change made here. Re-check the file after editing.
