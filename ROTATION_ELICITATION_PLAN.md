# Rotation-elicitation screen: plan (draft, nothing run)

Status: planning only, written 2026-10-03 after the Phase A pilot. No configs, code or API calls yet. The
numbers below are back-of-envelope and must be replaced by `--dry-run` output before anything is approved.
Not part of Phase B; it needs its own go-ahead and budget from the user.

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
  `disclose_horizon: false`, prompt v0 unchanged, temperature 1.0, 300 s timeout.
- Models only from `models.yaml`. Hosts as in the pilot.
- Primary outcome `delta_index` (unclipped), plus the labelling rule. Session level only.

## 3. Levers and arms

The sweep mechanism is a cross product, so a one-factor design needs one small config per arm, all under one run
id (`rotation_screen`). Each arm has a repeated sub-arm and a matched one-shot control (`history_window: 0`, same
seeds), as in the pilot.

Baseline anchor: the pilot's `random` cells (N = 3, 25 rounds, increment 0.01, thinking on low). They are reused
descriptively, not rerun. They use pilot seeds, so they are not a paired baseline for the new arms.

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
- Cost: the pilot cost $3.11 for 6,750 calls (about $0.0005 per call), which gives roughly $4-5 here; longer
  histories add input tokens. Proposed tripwire $7, to be set from the dry run.
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
- A coarse grid can raise the index mechanically through rounding to the grid, not through coordination. The
  chance benchmark handles ties but not price; compare each coarse-grid arm's own one-shot control, not the
  pilot baseline.
- Five sessions per cell is low power by design; a miss does not exclude a small effect.
- Seven arms times two models multiplies chances of a lucky hit, which is why a hit is only a lead.
- Longer horizons grow prompts and cut-off risk; check the cut-off rate in A2 and A5 before reading them.

## 8. Build and file list (nothing created yet)

- `configs/rotation_screen_<arm>.yaml`, one per arm, inheriting `pilot.yaml` settings, `base_seed: 991000`.
- `configs/analysis.yaml` addition (or a separate declared file) with section 5, committed before the run.
- Optional: the reserve-bid-excluded index variant in `analysis/metrics.py`, with tests.
- Results to `results/rotation_screen/` with a findings file, same format as `PILOT_FINDINGS.md`.
- Run order: `--dry-run` for each config, user approval of budget, then run under `--run-id rotation_screen`.

## 9. Open decisions for the user

1. Go-ahead and budget for the screen (proposed tripwire $7, about 5 h).
2. Whether to include the prompt-v1 arm (A6).
3. Output cap for the thinking-off arm; whether to add Qwen.
4. Whether to build the reserve-bid-excluded index before the run.
5. Whether a screen hit is enough to trigger the confirmation stage, or the user wants a second look first.
