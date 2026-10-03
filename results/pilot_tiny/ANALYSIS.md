# pilot_tiny: analysis of the two runs (3 October 2026)

Two end-to-end checks of the harness with real models, not data for the paper. Each run is 18 sessions of 3 rounds (3 models × 3 tie-break rules × repeated and one-shot control), 162 bids, one session per cell, so nothing here supports inference. Generated tables are in `results/pilot_tiny/` (first run) and `results/pilot_tiny_rerun/` (rerun); raw logs stay in the gitignored `logs/`.

| | First run | Rerun |
|---|---|---|
| Hosts | DeepSeek on Morph, one session on DeepInfra; gpt-oss Crusoe; Qwen Alibaba | DeepSeek DeepInfra; gpt-oss Crusoe; Qwen Alibaba |
| Sessions complete | 18 (one DeepSeek session reran on the fallback after two Morph 502s) | 18 of 18 first time |
| Provider retries | 0 (retries did not exist yet) | 0 |
| Spend | about $0.012 including reruns | about $0.015 |
| Log checker | 15 of 15 checks pass | 15 of 15 checks pass |

## Harness: nothing wrong
No invalid rows, no rounds without a winner, no sit-outs. Prompts show only earlier rounds, the control shows no history, no other firm's cost appears, and costs match the seeded draw. Read 7 prompts by hand.

Three first attempts failed (of about 330 calls) and all recovered on attempt 2: DeepSeek on Morph returned 4 tokens with no tool call; two Qwen replies ran to the 500-token cap (one cut off before the tool call, one with truncated JSON arguments). DeepSeek on DeepInfra matched Morph on tokens (about 135 completion tokens per call). Latency: first run p95 16.0 s with a tail to 28 s (not broken out by host); rerun p95 4.3 s.

## Non-competitive unilateral bids (new metrics, `non_competitive_bids.csv`): preliminary observation
Bids at the reserve or below the firm's own cost, over both runs (324 valid bids). Descriptive counts from a tiny sample; 6 of the 8 reserve bids are gpt-oss, a low-effort reasoning model, so this may be model-specific, and the prompt or the 3-round sessions may matter too. The pilot is the first real measurement.

| Model | Kind | Bids | At reserve | Below cost |
|---|---|---|---|---|
| DeepSeek | repeated / control | 54 / 54 | 0 / 0 | 3 / 0 |
| gpt-oss | repeated / control | 54 / 54 | 6 / 0 | 3 / 5 |
| Qwen | repeated / control | 54 / 54 | 2 / 0 | 2 / 1 |
| **All** | | **324** | **8** | **14** |

- **Bids at the reserve (8):** all from high-cost firms in repeated sessions, reasoning that bidding 100 "ensures I do not win" and so avoids a loss. That is loss avoidance, not coordination: the stated reason is the firm's own payoff, never other firms' turns or interests. The payoff reading is also wrong, since a bid of 100 on a cost of 74 would earn 26 if it won. One of the 8 came in round 1, where the prompt equals a control prompt, so the 8 against 0 is not necessarily a history effect.
- **Below cost (14):** none won, so no realised loss. In 11 bids at or below cost the reasoning talks of profit or margin, by a keyword match (for example "bidding 31.50 stays well above my cost 35.40"). gpt-oss often bids at cost: 17 of 27 control bids per run were within 2 cents of cost, citing "Nash equilibrium is to bid at one's own cost" or a wrong 2/3-of-cost formula. That is why its collusion index sits at −0.50 in every rule in the rerun (at-cost bidding at N = 3), with a `delta_index` of 0.
- These are not collusion and are reported apart from the tie and rotation measures (PLANNING.md 2.6). The cover-bid screens would read the reserve bids as a cover-bid signature, so they need the traces to interpret.

## Other observations
- **Ties:** 0 in the first run, 2 in the rerun, both under `random`, no rebids (Qwen control, A and C both 45.00; DeepSeek, B and C both 38.00). DeepSeek and Qwen put 78% to 100% of bids on multiples of 0.5, so ties at the 0.01 grid are plausible.
- **Qwen free text:** with thinking off Qwen has no hidden reasoning tokens, but in the rerun 36 of 55 calls wrote on average 399 characters (up to 1,346) of visible text in `message.content` before the tool call, which our `reasoning` field does not capture and which caused the two truncations at the 500 cap. DeepSeek wrote some (11 of 54, short) and gpt-oss none.
- **Bids look sensible overall:** mostly a modest markup above cost and below the BNE bid, as the plan expects.

## Open items
1. Whether to log `message.content` as a second trace field (matters for Qwen).
2. The prompt is unchanged: the reserve bids and below-cost bids are preliminary observations for the pilot to measure, not something to patch.
3. The pilot (cap 1,000 tokens) reports the two new rates per model and rule, and the trace rubric tags each case as coordination, unilateral bid-to-lose, mistaken payoff reasoning or incidental convergence (PLANNING.md section 8).

To check by hand: `calls.jsonl` of a session holds the prompt, the raw response (including `content`) and the parsed reasoning; `bids.jsonl` holds the outcomes. `uv run python scripts/check_logs.py logs/pilot_tiny_rerun --pick` lists representative prompts and `--show` prints one.
