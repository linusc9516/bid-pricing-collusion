# Rotation-elicitation screen: plan (draft, nothing run)

Status: planning plus the no-spend checks (section 10), updated 2026-10-03. Draft arm configs exist and have been
dry-run; no model has been called for this study. Not part of Phase B; it needs its own go-ahead and budget
from the user.

## 1. Why this study

The Phase A pilot passed the tie gate (3.07% pooled tie rate) but the positive control failed: under `random`
no model priced above its one-shot control with an index above 0 (`results/pilot/PILOT_FINDINGS.md`). CLAUDE.md
requires baseline rotation-like behaviour under `random` before tie rules are compared, so the tie-break
question has no baseline to move. This study asks one question first:

> Is there any setting, within the fixed design constraints, where LLM bidders under `random` tie-break meet the
> pre-declared "consistent with tacit rotation" label (analysis.yaml `labelling_rule`)?

A hit gives the tie-break experiment a place to run. No hit anywhere is itself a result: it supports a
well-powered null ("LLM bidders compete, and the tie rule does not matter") and the reserve-bid findings.

## 2. Fixed (not varied)

- Tie rule `random` throughout; this is the positive-control question, not a tie-rule comparison.
- Rule-based auctioneer, no agent-to-agent channel, own cost only, full history, `info: full`,
  `disclose_horizon: false`, temperature 1.0, 300 s timeout.
- Prompt v1 for every arm (see below), not the pilot's v0.
- Models only from `models.yaml`. Hosts as in the pilot.
- Primary outcome `delta_index` (unclipped), plus the labelling rule. Session level only.

## 3. Levers and arms

The sweep mechanism is a cross product, so a one-factor design needs one small config per arm, all under one run
id (`rotation_screen`). Cell ids must be unique per arm (`n2-deepseek`, `grid5-gpt-oss`, ...): `condition_id` and
session ids do not include the bid increment, number of rounds or thinking mode, so arms sharing a cell id collide. Each arm has a repeated sub-arm and a matched one-shot control (`history_window: 0`, same
seeds), as in the pilot.

Prompt v1: two sentences were added to the system prompt for all arms (2026-10-03). Bids are "rounded to the
nearest {increment}, so give your bid in multiples of {increment}", and costs are "drawn uniformly between 0 and
100 and then rounded to the nearest {increment}". Reason: costs are rounded to the grid, so at increment 5.0 the
stated U[0, 100] no longer matched the costs agents faced. The change applies to every condition, including 0.01.

Baseline anchor: the pilot's `random` cells (N = 3, 25 rounds, increment 0.01, thinking on low) ran prompt v0, with
pilot seeds. They are a descriptive reference only, not a paired baseline and not a clean comparator, because
the arms differ from them by the prompt as well as by the lever. Each arm's own matched one-shot control (same
prompt, same seeds) is the comparison. Optional: rerun the N = 3, 25-round, 0.01 cell under v1 (about
750 calls per model) as a v1 anchor, which also shows what the prompt change alone does; the user's call.

| Arm | Change from baseline | Why it might help | Chance tie rate (N, grid) |
|---|---|---|---|
| A1 | N = 2 | rotation is easiest with two firms; each firm sees one rival | 0.02% (2, 0.01) |
| A2 | 50 rounds | more repetition to build a pattern | unchanged |
| A3a | increment 1.0 | coarse grid makes focal prices and ties easy | 2.4% (3, 1.0) |
| A3b | increment 5.0 | stronger version of A3a | 11.7% (3, 5.0) |
| A4 | thinking off (DeepSeek only) | pilot_tiny bids were less equilibrium-like; ties 1.9% | n/a |
| A5 | N = 2, 50 rounds, increment 1.0 | all favourable levers together | compute with `chance_tie_rate` |

A4 is DeepSeek only because gpt-oss cannot turn thinking off. Output cap for A4 is open (500 at pilot_tiny, 1,000
is the other value used so far); needs the user's decision.

Models: DeepSeek and gpt-oss. Qwen is excluded from the screen because about 25% of its attempts hit the cap and
it sat out 4.5% of rounds, which would blur a null; it can be added if budget allows. Cells share a lineup
(homogeneous), as in the pilot.

Not included, needs a user decision: a prompt that states the interaction repeats with the same rivals (prompt
v1, snapshot regeneration) as arm A6. It is probably the strongest lever and also the most contestable one,
since it changes what agents are told. The decision belongs to the user.

## 4. Scale and cost (rough)

5 sessions per cell, new seeds (proposed base_seed 991000, disjoint from the pilot).

- Calls per model: A1 500, A2 1,500, A3a 750, A3b 750, A5 1,000 = about 4,500; plus A4 750 for DeepSeek.
  About 9,750 calls in all; no rebids, since the tie rule is `random`.
- Cost: dry runs (stress case, every call uses the whole cap): n2 $1.38, rounds50 $4.20, grid1 $2.07,
  grid5 $2.07, thinkoff $0.36, combined $2.77, in all $12.85 for 9,750 calls. The pilot's actual spend was about 42%
  of its stress estimate ($3.11 of $7.41), which gives roughly $5-6 here. The drafts carry a placeholder $3 tripwire
  per arm (rounds50's stress estimate already exceeds it); set the real caps with the user.
- Wall clock: the pilot took 3 h 20 min for 6,750 calls at concurrency 8, so about 5 h.
- Staging option: run A1 and A3a/A3b first (cheapest, most plausible levers), review, then A2, A4, A5.

## 5. Pre-declared decision rule (to be committed before any run)

A cell (model x arm) is a screen hit only if all hold, on the cell mean over its 5 sessions:

1. the analysis.yaml labelling rule: `delta_index > 0`, `collusion_index > 0`, `delta_lowest_cost_win_share < 0`;
2. `delta_index > 0` in at least 4 of the 5 sessions;
3. robustness to non-competitive bids: the result survives recomputing the index with rounds that contain a
   reserve bid removed. At N = 2 a rival's reserve bid lets the other firm win above the BNE price with no
   coordination, which can inflate the index. This variant is not built yet (small addition to
   `analysis/metrics.py`; decide whether to build it before the run).

Also report beside every cell: `reserve_bid_rate`, `below_cost_bid_rate`, `bid_cost_corr`, `rival_lag_coef` vs
control, `repeat_win_rate`, tie rate vs its chance benchmark, cut-off and sit-out rates.

The screen is exploratory: n = 5, no p-values, no claim from a hit alone. Any hit goes to a confirmation stage.

## 6. After the screen

- At least one hit: a separate pre-declared confirmation on fresh seeds (9-18 sessions, paired sign-flip test
  on `delta_index`, bootstrap CI, Holm across the hit cells). Only if it confirms, run the tie-rule comparison
  (`random` vs `least_wins` vs `bafo`) in that setting, with the tie manipulation check repeated there
  (coarse grids will pass it easily; thinking-on at 0.01 may not).
- No hit: report the screen as a null across N, horizon, grid, and thinking mode. The tie-break experiment is
  then a conditional-claim study (when do LLM bidders produce exploitable ties), or is dropped, the user's call
  (analysis.yaml `on_failure` lists the same fallbacks).
- A partial result (index rises but stays below 0, "moving toward competitive pricing") is reported as that,
  not as collusion.

## 7. Risks

- Floor effect: gpt-oss and Qwen bid far below BNE (index about -0.3 to -0.5), so the index cannot reach above 0
  without a large shift. DeepSeek, which sits at about 0, is the most likely to produce a hit.
- A coarse grid raises the index mechanically through rounding: a scripted BNE bidder reads +0.04 at N = 2 and
  increment 5.0 (about 0 at 0.01). The matched one-shot control uses the same grid, so `delta_index` cancels it.
  Judge the grid arms on `delta_index` and the labelling rule, never on the raw index, and use each arm's own
  control, not the pilot baseline.
- With a coarse grid the costs are discrete (multiples of 5 at increment 5.0) and the endpoints get half weight.
  Prompt v1 now says so. The chance tie benchmark and the controls use the same rounding.
- Five sessions per cell is low power by design; a miss does not exclude a small effect.
- Seven arms times two models multiplies chances of a lucky hit, which is why a hit is only a lead.
- Longer horizons grow prompts and cut-off risk; check the cut-off rate in A2 and A5 before reading them.

## 8. Build and file list

- Done (drafts, uncommitted until the user approves): `configs/rotation_screen_{n2,rounds50,grid1,grid5,thinkoff,combined}.yaml`,
  `base_seed: 991000`, inheriting `base.yaml` with the pilot's llm settings restated; the prompt v1 edit in
  `prompts/bidder_system.md` (`prompt.version: v1` in `base.yaml`), regenerated system snapshots and four new
  N = 2 / coarse-grid snapshots with a test (`test_two_firm_coarse_grid_snapshot`).
- `configs/analysis.yaml` addition (or a separate declared file) with section 5, committed before the run.
- Still to do: the reserve-bid-excluded index variant in `analysis/metrics.py`, with tests.
- Results to `results/rotation_screen/` with a findings file, same format as `PILOT_FINDINGS.md`.
- Run order: `--dry-run` for each config, user approval of budget, then run under `--run-id rotation_screen`.

## 9. Open decisions for the user

1. Go-ahead and budget for the screen (proposed tripwire $7, about 5 h).
2. Whether to include the prompt-v1 arm (A6).
3. Output cap for the thinking-off arm; whether to add Qwen.
4. Whether to build the reserve-bid-excluded index before the run.
5. Whether a screen hit is enough to trigger the confirmation stage, or the user wants a second look first.

## 10. No-spend checks done (2026-10-03)

1. Dry runs of all six arm configs: section 4.
2. Scripted-bidder sanity runs at N = 2 and 3 and increments 0.01, 1.0 and 5.0 (108 sessions, no API calls):
   `check_logs.py` passes in all three; bids and costs sit on the grid; BNE index about 0 at 0.01 and +0.04 at
   N = 2 with increment 5.0 (rounding); markup bidders well below 0; scripted rotation reads 0.97-1.0 with the
   lowest-cost win share near 1/N; BNE tie rates follow the chance benchmark (N = 3: 3.0% at 1.0, 13.7% at 5.0).
3. Chance tie rates for the combined arm: 2.0% (N = 2, 1.0) and 9.7% (N = 2, 5.0).
4. Prompt snapshots for N = 2 at increments 1.0 and 5.0, plus the v1 wording on the existing snapshots.
5. Prompts read by hand at N = 2 and both increments: wording correct, round 4 shows rounds 1-3 only.
The cheap live checks (smoke test of the thinking-off config, a 3-round combined-arm run) are not done.
