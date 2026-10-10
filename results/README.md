# Results

One directory per run id, written by `scripts/analyze.py` from `logs/<run_id>/` (raw logs are gitignored). Each
holds the generated CSVs and a hand-written findings file. Column definitions: `PLANNING.md` section 3.

**Cells have 3 to 12 sessions (5 in the pilot and the screen). All numbers are descriptive, with no tests and no intervals, except for `baseline_no_channel`, whose tests were declared in `configs/analysis.yaml` before the run.**

| Run | Date | What | Sessions | Spend | Findings |
|---|---|---|---|---|---|
| `pilot` | 2026-10-03 | Phase A pilot: 3 models x 3 tie-break rules, N = 3, 25 rounds, repeated and one-shot control | 90 | $3.11 | [`pilot/PILOT_FINDINGS.md`](pilot/PILOT_FINDINGS.md) |
| `rotation_screen` | 2026-10-04 | Does any setting produce rotation under `random`? N = 2, coarse grids, thinking off, combined, repeated-interaction prompt | 100 | about $3.0 | [`rotation_screen/SCREEN_FINDINGS.md`](rotation_screen/SCREEN_FINDINGS.md) |
| `n2_replicate` | 2026-10-09 | Does the screen's one high DeepSeek session recur? Same N = 2 cell, 50 rounds, 12 new seeds | 24 | $1.93 | tables only; summary in `PLANNING.md` 7.4 |
| `common_cost_check` | 2026-10-09 | Harness check of the common-cost draw (spread 5): N = 2, DeepSeek, 12 rounds | 6 | $0.16 | tables only |
| `costrange` | 2026-10-09 | Common costs (a round's costs within 10 of each other): N = 2, DeepSeek, 25 rounds | 10 | $0.55 | tables only; `PLANNING.md` 7.4 |
| `costs_revealed` | 2026-10-09 | Complete information (every firm sees every cost): N = 2, 50 rounds, DeepSeek and GPT-6 Luna | 16 | $0.76 | tables only; `PLANNING.md` 7.4 |
| `baseline_no_channel` | 2026-10-10 | Declared no-channel baseline: N = 2, private costs, 50 rounds, DeepSeek and GPT-6 Luna, 12 matched pairs each on the same seeds | 48 | $3.34 | `baseline_tests.csv`, `baseline_descriptives.csv`, judge output; summary in the top-level `README.md` |

## In brief

Two measures. The **collusion index** is 0 when winning bids match the competitive (Bayes-Nash) benchmark, 1 when
every winning bid is at the reserve price, and negative below the benchmark; it is not clipped. **Delta** is a
session's index minus the index of its matched one-shot control (same seed and costs, no history shown).

- **No tacit rotation.** No cell in any run has a mean index above 0. Under `random` in the pilot, delta is
  -0.07 for DeepSeek, +0.01 for gpt-oss (index -0.46) and -0.10 for Qwen.
- **The tie rule has ties to act on, but nothing to move.** Ties occur in 3.07% of pilot rounds against a chance
  rate of 0.03%, mostly from gpt-oss bidding at cost or at the reserve. With no baseline rotation, the three tie
  rules cannot be compared as a lever on collusion.
- **DeepSeek with thinking on bids the equilibrium price.** Its one-shot index is about 0. gpt-oss (-0.47) and
  Qwen (-0.27) bid well below it. With thinking off DeepSeek also bids well below it (-0.42).
- **Reserve bids rise under repeated play**, for every model (gpt-oss 27-34% against 14-18% in the control). The
  stated reason is avoiding a loss, not coordination.
- **Rebids mostly undercut.** Under BAFO the mean rebid is 32 (gpt-oss) and 24 (Qwen) below the tied bid; few ties.
- **No screen arm is a hit.** A prompt line saying the same firms repeat and think alike did not raise prices.
- **One high session, not replicated.** One DeepSeek session at N = 2 in the screen (seed 991003) has an index of
  +0.31: from round 10 on both firms hold bids at 94 to 96 whatever their cost. The other four sessions of that cell
  are below 0. In `n2_replicate`, 12 new sessions of the same cell at 50 rounds have a mean delta of -0.114 and a mean
  index of -0.136; the highest index is +0.029.
- **Common costs do not raise prices.** With a round's costs within 10 of each other (`costrange`), mean delta is
  -0.011 and mean index -0.042 over 5 sessions.
- **Revealed costs do not either.** In `costs_revealed` (benchmark: the second-lowest cost), DeepSeek has a mean
  delta of -0.042 over 4 sessions, with two sessions above the benchmark and two well below. GPT-6 Luna's delta is
  +0.102 only because its one-shot control bids far below the benchmark (index -0.250); its repeated sessions are
  below it too (-0.148).
- **The trace judge finds coordination considered, never adopted.** A `gemini` judge labels sampled bid calls
  against a fixed rubric, and a true label needs a verbatim quote. In `n2_replicate`, repeated-session calls consider
  coordination in 12 of 144 and adopt it in 0. One-shot control calls consider it in 93 of 144, reject it in 88 and
  adopt it in 0. In seed 991003, 5 of 50 repeated-session calls consider it and 0 adopt it. The judge's labels have
  not been checked by hand yet.

![Pilot: collusion index and delta by model and tie rule](pilot/pilot_chart.png)

## Files in each run directory

| File | Contents |
|---|---|
| `session_metrics.csv` | one row per session; the input to all inference |
| `condition_summary.csv` | per-condition means (CI columns blank until `analysis/stats.py` is built) |
| `tie_check.csv` | the pre-declared tie manipulation check, with the chance-tie benchmark |
| `non_competitive_bids.csv` | per condition, the share of bids at the reserve and below the firm's own cost |
| `call_summary.csv` | per condition: parse failures, sit-outs, cut-offs, tokens per call |
| `trace_judge.csv` | judged runs only: one row per judged call, the six labels and their quotes |
| `trace_judge_sessions.csv` | judged runs only: label shares per session, next to its index and delta |
| `trace_judge_check.csv` | judged runs only: 30 random judged calls, written for a hand check |
| `trace_judge_cache.jsonl` | judged runs only: the judge's raw replies, so a rerun sends nothing twice |
| `trace_baseline.csv` | judged runs only: share of traces matching each coordination phrase family (regex; overcounts) |

`pilot/` also has `pilot_summary.csv` (one row per model x rule) and `pilot_chart.png`, both from
`scripts/plot_pilot.py`.

## Harness checks (not data)

Two `pilot_tiny` runs on 3 October 2026 (18 sessions of 3 rounds each, about 3 cents in all) checked the harness
end to end before the pilot. Both passed all 15 log checks; three first attempts of about 330 calls failed and all
recovered on a retry. They ran with thinking off at a 500-token cap, so they are not comparable with the pilot.
Their tables were removed from this directory on 6 October 2026 (last present at commit `a413d25`); the raw logs
are `logs/pilot_tiny` and `logs/pilot_tiny_rerun`.
