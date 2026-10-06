# Phase A pilot findings (2026-10-03)

n = 5 sessions per cell, directional only; no tests or intervals. Config `configs/pilot.yaml`, run id `pilot`,
thinking on at low effort, 4,000-token cap, prompt v0. Generated tables are the CSVs in this directory;
`pilot_summary.csv` and `pilot_chart.png` (one row and one group per model x rule) come from `scripts/plot_pilot.py`.

![Collusion index and delta by model and tie rule](pilot_chart.png)

## Run
90 of 90 sessions completed, 0 failed, 1 provider retry (one session). All on the primary hosts (DeepInfra,
Crusoe, Alibaba); no fallback used. Spend $3.11 (cap $8). Wall clock about 3 h 20 min (17:17 to 20:38).
`check_logs.py`: 15 of 15 checks pass on 7,611 call rows. One prompt read by hand (round 25 shows rounds 1-24
only; the own cost is the only cost shown).

## Gate
MANIPULATION CHECK: pooled random + least_wins tie rate 3.07% [1.95%, 4.57%] over 750 rounds against a chance
benchmark of 0.03% -> **PROCEED** (>= 1%). By model: gpt-oss 4-7%, Qwen 1.6-3.2%, DeepSeek 0.8-1.6%. One-shot
controls: about 0-1.6%.

## Call health
Cut off at the cap: 800 of 7,611 attempts. Qwen 21-30% of attempts (mean 2,150-2,670 tokens, p95 at the cap),
DeepSeek 0-1.6%, gpt-oss 0. Sit-outs: Qwen 4.5% of rounds in repeated cells (1-2% one-shot), DeepSeek and
gpt-oss 0. Free text outside the tool call: 152 of 7,611 attempts (about 2%), so the Qwen content note recurs
with thinking on.

## Positive control (random tie-break)
No cell shows rotation-like behaviour. collusion_index vs one-shot control, delta_index: DeepSeek -0.078 vs
-0.011 (-0.067); gpt-oss -0.458 vs -0.468 (+0.009, index below 0); Qwen -0.366 vs -0.269 (-0.097). The index is
below 0 everywhere and delta is not positive except for gpt-oss, which is essentially zero. Lowest-cost win share
falls in repeated vs control (DeepSeek .88 vs .98, gpt-oss .90 vs .93, Qwen .78 vs .86), but with a negative
index that is noisier or more aggressive pricing, not rotation. By the pre-declared label, none is tacit rotation.
The same pattern holds under least_wins and bafo (delta -0.12 to -0.03, gpt-oss +0.03 under least_wins).

## BAFO rebid delta (rebid minus tied bid; few ties, so tiny n)
DeepSeek +5.7 (2 rebid calls), gpt-oss -32.2 (27 calls), Qwen -23.8 (14 calls). Rebids mostly undercut.

## Non-competitive bids (reserve / below cost, repeated vs one-shot)
gpt-oss reserve 27-34% vs 14-18%; below cost 5-8% vs 2-9%. Qwen reserve 11-12% vs about 1%; below cost 1-5%.
DeepSeek reserve 3-5% vs 0.3%; below cost about 0%. Repeated play raises reserve bids for every model.

## bid_cost_corr and rival_lag_coef (mean over sessions, repeated / control)
bid_cost_corr: DeepSeek 0.96 / 0.99, gpt-oss 0.86 / 0.91, Qwen 0.84 / 0.93 (bids track costs; no sign of cover
bids). rival_lag_coef: DeepSeek 0.016 / 0.003, gpt-oss -0.015 / -0.018, Qwen -0.019 / 0.007; all near 0 and
indistinguishable from the placebo, so no reward-punishment response to rivals' last bids is visible.
Versus BNE: DeepSeek's one-shot index is about 0 (near the benchmark bid); gpt-oss (-0.47) and Qwen (-0.27)
bid well below it, gpt-oss often at cost.

## Caveats and open questions
- Thinking-on, effort-low settings; not comparable to the thinking-off `pilot_tiny` harness checks.
- Qwen's cut-off rate (about 25%) and sit-outs are a data-quality issue for Phase B's cap decision.
- The ties come mostly from gpt-oss bidding at cost or at the reserve, not from coordination; the gate passes on
  tie frequency, not on collusion. Whether the tie lever matters when there is no baseline rotation is an open
  design question; the rotation screen (`../rotation_screen/SCREEN_FINDINGS.md`) looked for a baseline and found none.
- Phase B thinking mode, cap, reasoning length, budget and tie grid are undecided.
