# Tie-break rules and tacit bid rotation among LLM bidders

Can the rule an auction uses to break exact-match bids hand LLM bidders an easy way to collude, and can a different rule take it away? Firm-agents bid repeatedly in a first-price sealed-bid procurement auction (lowest bid wins) with private costs drawn fresh each round. They are told only to maximise cumulative profit; there is no communication channel, and the auctioneer is deterministic code. The main experiment compares three tie-break rules: random, least-wins-first, and a best-and-final-offer rebid. Prices are measured with a collusion index (0 at the competitive Bayes-Nash benchmark, 1 at the reserve price, negative below the benchmark), and every condition is compared with a one-shot control that shows no history, so that models which simply bid high are not mistaken for models that collude.

Design: [`BidPricingCollusion.md`](BidPricingCollusion.md). Build plan, budget and open questions: [`PLANNING.md`](PLANNING.md). [`CLAUDE.md`](CLAUDE.md) documents repo conventions and the non-negotiable design constraints for anyone, human or Claude Code, working on the codebase.

> **Status: scaffolding only.** Modules under `src/bidrig/` are stubs; the commands below describe the intended interface.

## Disclosure

The design was done before the sprint weekend (Oct 23–25, 2026), and a pre-team feasibility pilot (Phase A in `PLANNING.md` section 7) is planned for before it. [`PREP_LOG.md`](PREP_LOG.md) is the dated record of what has actually been done; the pilot is logged there once it has run. The full ablation sweep and the analysis are conducted during the sprint.

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
# 1. Sanity checks: scripted bidders only, no API calls
uv run python scripts/run_experiment.py configs/sanity_dummy.yaml
uv run python scripts/run_experiment.py configs/sanity_tiebreak.yaml

# 2. Phase A pilot: two models under all three tie-break rules, on its own seeds
uv run python scripts/run_experiment.py configs/pilot.yaml --dry-run   # call + cost estimate
uv run python scripts/run_experiment.py configs/pilot.yaml

# 3. Phase B, only after Phase A is reviewed: main experiment, then the
#    supporting ablations, under one run id
uv run python scripts/run_experiment.py configs/main_tiebreak.yaml     --run-id run1
uv run python scripts/run_experiment.py configs/supporting_info.yaml   --run-id run1
uv run python scripts/run_experiment.py configs/supporting_n.yaml      --run-id run1
uv run python scripts/run_experiment.py configs/supporting_lineup.yaml --run-id run1
```

Run the sanity checks first and confirm the scripted bidders read as expected before spending on LLM calls: BNE bidders near 0, markup bidders negative, the overbidding bidder high but not flagged as collusive, the rotating cartel flagged, and bid-matching bidders rotating exactly under least-wins-first. Commit `configs/analysis.yaml` before the main experiment; it pre-declares the comparisons. Runs are resumable: completed sessions are skipped.

The Phase A budget is $10 of OpenRouter credits (estimated spend about $0.50). The Phase B budget is not set yet and is expected to be much higher if needed; it is decided after Phase A measures tokens per call, which the estimates depend on. See `PLANNING.md` section 5.4.

## Experiments

### Main experiment: tie-break rule

All four models, same-model lineup, full history, N = 3, 18 sessions per condition, each with a matched one-shot control.

| Rule | How an exact tie at the lowest bid resolves |
|---|---|
| Random (default) | The winner is drawn at random from the tied firms |
| Least-wins-first | The tied firm with the fewest wins so far this session wins |
| BAFO rebid | The tied firms submit one private rebid; the lowest rebid wins |

Least-wins-first lets firms rotate by simply matching bids, with none of the execution risk of cover-bidding. BAFO instead reopens competition among the tied firms, so tying high earns no guaranteed win. The two are a deliberate contrast: the finding is not "tie-breaks are bad" but "some tie-break designs are exploitable and some are not". BAFO is not assumed collusion-proof; firms could learn to coordinate on the rebid.

The conditions need different metrics. Under least-wins-first the rule forces uniform wins whenever firms tie, so win uniformity is not diagnostic; use tie frequency over the session, the tie price against the competitive benchmark, and the reasoning traces. Under BAFO the win-pattern statistics remain valid, with one addition: the rebid price against the original tied bid. Details in `PLANNING.md` section 6.

### Supporting ablations

Reduced scale: DeepSeek only, 9 sessions, random tie-break. They establish that the baseline rotation phenomenon exists and behaves as expected, which is the premise the main claim builds on. They are reported as context, with intervals and without tests, not as separate findings.

| Ablation | Levels | What it shows |
|---|---|---|
| Information revelation | all bids + winner / winner + price / winner only | How much signal rotation needs |
| Number of bidders | 2 / 3 / 5 | Whether coordination decays as N grows, as IO theory predicts |
| Model lineup | same-model / one mixed lineup of three models | Whether rotation survives mixed models |

### Reading the results

- **High prices are not collusion.** The collusion index rises if a model just overbids. Read it against its one-shot control and beside the lowest-cost-wins share, which stays near 1 under uniform overbidding and falls toward 1/N under rotation. A cell counts as consistent with tacit rotation only if the index exceeds its control and that share falls.
- **The index is not a 0–1 scale.** It is negative when bids are below the competitive benchmark, and is reported unclipped.
- **Two confirmatory comparisons, Holm-corrected:** least-wins-first vs. random, and BAFO vs. random. Both are on the index minus its control and are declared in `configs/analysis.yaml`. Each is pooled across models; per-model results are exploratory. The branch `per-model-tests` holds the variant that tests each model separately. Everything else is exploratory.
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
- `confirmatory_tests.csv` — the pre-declared comparisons with raw and Holm-adjusted p-values

## Structure

```
configs/        base defaults, model list, sanity checks, pilot, main experiment, supporting ablations, analysis plan
prompts/        bidder system prompt template
src/bidrig/     auction, bidders, prompts, llm, bne, runner, analysis/
scripts/        run_experiment.py, analyze.py
tests/
logs/           raw output (gitignored)
results/        aggregated tables and figures
```
