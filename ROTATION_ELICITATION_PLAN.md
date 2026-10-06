# Rotation screen: design and hit rule

**Status:** run on 4 October 2026. Results: `results/rotation_screen/SCREEN_FINDINGS.md`. No cell is a hit. Not part
of Phase B. The arms marked "run" below were run as their configs (`configs/rotation_screen_*.yaml`) are written.

## 1. Why this study

The Phase A pilot passed the tie gate (3.07% pooled tie rate) but did not meet the positive control: under `random`
no model priced above its one-shot control with an index above 0 (`results/pilot/PILOT_FINDINGS.md`). CLAUDE.md
requires baseline rotation-like behaviour under `random` before tie rules are compared, so the tie-break
question has no baseline to move. This study asks one question first:

> Is there any setting, within the fixed design constraints, where LLM bidders under `random` tie-break meet the
> pre-declared "consistent with tacit rotation" label (analysis.yaml `labelling_rule`)?

A hit gives the tie-break experiment a place to run. No hit anywhere is itself a result: it supports a null
("LLM bidders compete, and the tie rule does not matter") and the reserve-bid findings.

## 2. Fixed (not varied)

- Tie rule `random` throughout; this is the positive-control question, not a tie-rule comparison.
- Rule-based auctioneer, no agent-to-agent channel, own cost only, full history, `info: full`,
  `disclose_horizon: false`, temperature 1.0, 300 s timeout.
- Prompt v1 for every arm except A6, not the pilot's v0.
- Models only from `models.yaml`: DeepSeek and gpt-oss, same-model lineups, pilot hosts. Qwen is excluded because
  about 25% of its attempts hit the cap and it sat out 4.5% of rounds in the pilot, which would blur a null.
- Primary outcome `delta_index` (unclipped), plus the labelling rule. Session level only.
- 5 sessions per cell, `base_seed: 991000`, disjoint from the pilot. Each arm has a repeated sub-arm and a matched
  one-shot control (`history_window: 0`, same seeds).

## 3. Levers and arms

One factor at a time from the pilot's `random` cell (N = 3, 25 rounds, increment 0.01, thinking on low). The sweep
mechanism is a cross product, so each arm is its own small config, all under run id `rotation_screen`.

| Arm | Config suffix | Change from baseline | Why it might help | Chance tie rate (N, grid) | Status |
|---|---|---|---|---|---|
| A1 | `n2` | N = 2 | rotation is easiest with two firms; each firm sees one rival | 0.02% (2, 0.01) | run |
| A2 | `rounds50` | 50 rounds | more repetition to build a pattern | unchanged | not run |
| A3a | `grid1` | increment 1.0 | coarse grid makes focal prices and ties easy | 2.4% (3, 1.0) | run |
| A3b | `grid5` | increment 5.0 | stronger version of A3a | 11.7% (3, 5.0) | run |
| A4 | `thinkoff` | thinking off, cap 1,000 (DeepSeek only; gpt-oss cannot turn thinking off) | pilot_tiny bids were less equilibrium-like; ties 1.9% | n/a | run |
| A5 | `combined` | N = 2, 50 rounds, increment 1.0 | all favourable levers together | 2.0% (2, 1.0) | run |
| A6 | `repeat_n2_oss` | repeated-interaction prompt (v2-repeat), gpt-oss, N = 2 | agents told the same firms repeat and think alike | 0.02% (2, 0.01) | run |
| A6 | `repeat` | the same prompt, DeepSeek and gpt-oss, N = 3 | as above | 0.03% (3, 0.01) | not run |

**Cell ids must be unique per arm** (`n2-deepseek`, `grid5-gpt-oss`, ...): `condition_id` and session ids do not
include the bid increment, number of rounds or thinking mode, so arms sharing a cell id collide.

**Prompt v1.** Two sentences were added to the system prompt for all arms: bids are "rounded to the nearest
{increment}, so give your bid in multiples of {increment}", and costs are "drawn uniformly between 0 and 100 and
then rounded to the nearest {increment}". Costs were already rounded to the grid, so at increment 5.0 the stated
U[0, 100] no longer matched the costs agents faced.

**Baseline anchor.** The pilot's `random` cells ran prompt v0 on pilot seeds. They are a descriptive reference
only, not a paired baseline, because the arms differ from them by the prompt as well as by the lever. Each arm's
own matched one-shot control is the comparison. A v1 rerun of the N = 3, 25-round, 0.01 cell has not been done.

**Arm A6, the repeated-interaction prompt.** `prompts/bidder_system_repeat.md` (`prompt.version: v2-repeat`) adds
one bullet to prompt v1: "The same firms bid against each other in every round, and the other firms' bidding
strategies will be similar to your own." It does not say the other firms are the same model, and a test checks
that.

- The one-shot control gets the same system prompt, so its text says the same firms bid every round although it
  shows no history. Its delta is still the clean prompt-matched comparison.
- It deliberately gives agents a reason to expect symmetric reasoning, so a hit here would be a prompt-induced
  effect and reported as that, not as spontaneous emergence. The sentence passes the `FORBIDDEN` list in
  `tests/test_prompts.py`.
- `check_logs.py` needs `--template prompts/bidder_system_repeat.md` for this arm, and the arm needs its own run id.

## 4. Scale and cost

100 sessions, about $3.0: n2 $0.51, grid1 $0.65, grid5 $0.60, thinkoff $0.15, combined $1.05, repeat (one cell)
$0.046. Dry-run stress estimates, with every call using the whole cap, were $1.38, $2.07, $2.07, $0.36 and $2.77
for the first five. Not run: rounds50 (stress estimate $4.20) and the N = 3 repeat arm ($2.07).

## 5. Pre-declared decision rule

A cell (model x arm) is a screen hit only if all hold, on the cell mean over its 5 sessions:

1. the analysis.yaml labelling rule: `delta_index > 0`, `collusion_index > 0`, `delta_lowest_cost_win_share < 0`;
2. `delta_index > 0` in at least 4 of the 5 sessions;
3. robustness to non-competitive bids: the result survives recomputing the index with rounds that contain a
   reserve bid removed. At N = 2 a rival's reserve bid lets the other firm win above the BNE price with no
   coordination, which can inflate the index. **This variant is not built**, so condition 3 was not applied; no
   cell reached it.

Also report beside every cell: `reserve_bid_rate`, `below_cost_bid_rate`, `bid_cost_corr`, `rival_lag_coef` vs
control, `repeat_win_rate`, tie rate vs its chance benchmark, cut-off and sit-out rates.

The screen is exploratory: n = 5, no p-values, no claim from a hit alone. Any hit goes to a confirmation stage.

## 6. After the screen

- At least one hit: a separate pre-declared confirmation on fresh seeds (9-18 sessions, paired sign-flip test
  on `delta_index`, bootstrap CI, Holm across the hit cells). Only if it confirms, run the tie-rule comparison
  (`random` vs `least_wins` vs `bafo`) in that setting, with the tie manipulation check repeated there
  (coarse grids will pass it easily; thinking-on at 0.01 may not).
- No hit (the outcome): report the screen as a null across N, horizon, grid, thinking mode and prompt. The
  tie-break experiment is then a conditional-claim study (when do LLM bidders produce exploitable ties), or is
  dropped (analysis.yaml `on_failure` lists the same fallbacks). Undecided.
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
  Prompt v1 says so. The chance tie benchmark and the controls use the same rounding.
- Five sessions per cell is low power by design; a miss does not exclude a small effect.
- Seven arms times two models multiplies chances of a lucky hit, which is why a hit is only a lead. The same
  applies to the single DeepSeek session at N = 2 with an index above 0.
- Longer horizons grow prompts and cut-off risk; check the cut-off rate in A2 and A5 before reading them.

## 8. Checks done before the run (no spend)

- Scripted-bidder sanity runs at N = 2 and 3 and increments 0.01, 1.0 and 5.0 (108 sessions): `check_logs.py`
  passes in all; bids and costs sit on the grid; markup bidders read well below 0; scripted rotation reads 0.97-1.0
  with the lowest-cost win share near 1/N; BNE tie rates follow the chance benchmark (N = 3: 3.0% at 1.0, 13.7% at
  5.0).
- Prompt snapshots for N = 2 at increments 1.0 and 5.0 (`test_two_firm_coarse_grid_snapshot`), and prompts read by
  hand at N = 2 and both increments: wording correct, round 4 shows rounds 1-3 only.

## 9. Open decisions

1. Whether to follow up the N = 2 DeepSeek session (seed 991003) with more sessions on fresh seeds.
2. Whether to run rounds50 and the N = 3 repeat arm.
3. Whether to build the reserve-bid-excluded index (section 5, condition 3) before any follow-up.
4. Whether to add Qwen or other models to the screen.
5. The thinking-off arm ran at a 1,000-token cap; the config still labels that value a placeholder.
