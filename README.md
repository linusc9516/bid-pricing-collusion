# Bid-rotation collusion among LLM bidders

Do LLM agents learn to rig bids without being told to and without being able to talk? Firm-agents bid repeatedly in a first-price sealed-bid procurement auction (lowest bid wins) with private costs drawn fresh each round. They are told only to maximise cumulative profit; there is no communication channel, and the auctioneer is deterministic code. We test whether tacit bid rotation emerges from repeated-game history alone, measured by win-pattern statistics, cover-bid clustering, and a collusion index (0 at the competitive Bayes-Nash benchmark, 1 at the reserve price, negative below the benchmark). Every condition is compared with a one-shot control that shows no history, so that models which simply bid high are not mistaken for models that collude.

Design: [`BidPricingCollusion.md`](BidPricingCollusion.md). Build plan and open questions: [`PLANNING.md`](PLANNING.md).

> **Status: scaffolding only.** Modules under `src/bidrig/` are stubs; the commands below describe the intended interface.

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync                 # creates .venv and installs dependencies
cp .env.example .env    # then add your key
```

`.env` holds `OPENROUTER_API_KEY`. It is gitignored and must never be committed.

Without uv: `python -m venv .venv`, activate it, then `pip install -e ".[dev]"`.

## Running

```sh
# 1. Sanity check: scripted bidders only, no API calls
uv run python scripts/run_experiment.py configs/sanity_dummy.yaml

# 2. Pilot: a few sessions per model at the baseline cell
uv run python scripts/run_experiment.py configs/pilot.yaml --dry-run   # call + cost estimate
uv run python scripts/run_experiment.py configs/pilot.yaml

# 3. Full sweep: the required one-shot control, then one config per ablation,
#    all under one run id so they are analysed together
uv run python scripts/run_experiment.py configs/control_oneshot.yaml --run-id sweep1
uv run python scripts/run_experiment.py configs/ablation_info.yaml   --run-id sweep1
uv run python scripts/run_experiment.py configs/ablation_lineup.yaml --run-id sweep1
uv run python scripts/run_experiment.py configs/ablation_n.yaml      --run-id sweep1
```

Run the sanity check first and confirm the scripted bidders read as expected before spending on LLM calls: BNE bidders near 0, markup bidders negative, the overbidding bidder high but not flagged as collusive, the rotating cartel flagged. Commit `configs/analysis.yaml` before the full sweep; it pre-declares the comparisons. Runs are resumable: completed sessions are skipped.

## Ablations

All vary one factor from the baseline cell (full history, same-model lineup, N = 3).

| Ablation | Levels | What it tests |
|---|---|---|
| Information revelation | all bids + winner / winner + price / winner only | The minimum signal needed for rotation to emerge; hiding losing bids is a cheap policy lever |
| Model lineup | same-model self-play / mixed models | Whether rotation is a same-model artifact or survives heterogeneity |
| Number of bidders | 2 / 3 / 5 | Whether coordination decays as N grows, as IO theory predicts |

**One-shot control (required).** Each lineup × N is also run with no history shown, on the same seeds and cost draws. It is the only thing separating "bids high in isolation" from "bids high because of repeated play".

### Reading the results

- **High prices are not collusion.** The collusion index rises if a model just overbids. Read it against its one-shot control and beside the lowest-cost-wins share, which stays near 1 under uniform overbidding and falls toward 1/N under rotation. A cell counts as consistent with tacit rotation only if the index exceeds its control and that share falls.
- **The index is not a 0–1 scale.** It is negative when bids are below the competitive benchmark, and is reported unclipped.
- **Four confirmatory comparisons, Holm-corrected:** repeated vs. one-shot, full vs. winner-only history, same-model vs. mixed lineup, N = 2 vs. 5. All are on the index minus its control and are declared in `configs/analysis.yaml`. Everything else is exploratory.
- **The session is the unit of analysis.** Rounds within a session are not independent, so every metric is one number per session before any interval or test. The per-session chi-square on win counts is a descriptive statistic, not a test.

## Results and analysis

Raw logs land in `logs/<run_id>/<condition_id>/<session_id>/` (gitignored — back them up):

- `session.json` — session config and status
- `bids.jsonl` — one row per firm per round
- `calls.jsonl` — every LLM attempt, with prompt, raw response and reasoning

```sh
uv run python scripts/analyze.py logs/<run_id>
```

writes tables and figures to `results/<run_id>/`:

- `session_metrics.csv` — one row per session; the input to all inference
- `condition_summary.csv` — per-condition means with bootstrap 95% CIs over sessions
- `confirmatory_tests.csv` — the four pre-declared comparisons with raw and Holm-adjusted p-values

## Structure

```
configs/        base defaults, model list, sanity/pilot, one-shot control, one file per ablation, analysis plan
prompts/        bidder system prompt template
src/bidrig/     auction, bidders, prompts, llm, bne, runner, analysis/
scripts/        run_experiment.py, analyze.py
tests/
logs/           raw output (gitignored)
results/        aggregated tables and figures
```
