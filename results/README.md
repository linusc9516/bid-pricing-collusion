# Results

One directory per run id, written by `scripts/analyze.py` from `logs/<run_id>/` (raw logs are gitignored). Each
holds the generated CSVs and a hand-written findings file. Column definitions: `PLANNING.md` section 3.

**Every run so far has 5 sessions per cell. All numbers are descriptive: no tests, no intervals.**

| Run | Date | What | Sessions | Spend | Findings |
|---|---|---|---|---|---|
| `pilot` | 2026-10-03 | Phase A pilot: 3 models x 3 tie-break rules, N = 3, 25 rounds, repeated and one-shot control | 90 | $3.11 | [`pilot/PILOT_FINDINGS.md`](pilot/PILOT_FINDINGS.md) |
| `rotation_screen` | 2026-10-04 | Does any setting produce rotation under `random`? N = 2, coarse grids, thinking off, combined, repeated-interaction prompt | 100 | about $3.0 | [`rotation_screen/SCREEN_FINDINGS.md`](rotation_screen/SCREEN_FINDINGS.md) |

## In brief

Two measures. The **collusion index** is 0 when winning bids match the competitive (Bayes-Nash) benchmark, 1 when
every winning bid is at the reserve price, and negative below the benchmark; it is not clipped. **Delta** is a
session's index minus the index of its matched one-shot control (same seed and costs, no history shown).

- **No tacit rotation.** No cell in either run has a mean index above 0. Under `random` in the pilot, delta is
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
- **One lead.** One DeepSeek session at N = 2 (seed 991003) has an index of +0.31: from round 10 on both firms hold
  bids at 94 to 96 whatever their cost. The other four sessions of that cell are below 0. One of five, found by
  looking at the outlier.

![Pilot: collusion index and delta by model and tie rule](pilot/pilot_chart.png)

## Files in each run directory

| File | Contents |
|---|---|
| `session_metrics.csv` | one row per session; the input to all inference |
| `condition_summary.csv` | per-condition means (CI columns blank until `analysis/stats.py` is built) |
| `tie_check.csv` | the pre-declared tie manipulation check, with the chance-tie benchmark |
| `non_competitive_bids.csv` | per condition, the share of bids at the reserve and below the firm's own cost |
| `call_summary.csv` | per condition: parse failures, sit-outs, cut-offs, tokens per call |

`pilot/` also has `pilot_summary.csv` (one row per model x rule) and `pilot_chart.png`, both from
`scripts/plot_pilot.py`.

## Harness checks (not data)

Two `pilot_tiny` runs on 3 October 2026 (18 sessions of 3 rounds each, about 3 cents in all) checked the harness
end to end before the pilot. Both passed all 15 log checks; three first attempts of about 330 calls failed and all
recovered on a retry. They ran with thinking off at a 500-token cap, so they are not comparable with the pilot.
Their tables were removed from this directory on 6 October 2026 (last present at commit `a413d25`); the raw logs
are `logs/pilot_tiny` and `logs/pilot_tiny_rerun`.
