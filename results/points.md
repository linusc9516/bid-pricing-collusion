# Talking points: pilots and rotation screen (3 to 5 minutes)

Sources: `results/pilot_tiny/ANALYSIS.md` (both runs), `results/pilot/PILOT_FINDINGS.md`, `results/rotation_screen/SCREEN_FINDINGS.md`. Every figure below comes from those files. Open `site/index.html` in a browser before you start; the example buttons along the top are named in quotes below. Direct links use the form `site/index.html#/<example>/<0 = repeated, 1 = control>/<round>`.

Say once, early: every result here has 5 sessions per cell, so it is descriptive only. No tests, no intervals.

## 0:00 to 0:30. The question

We run a sealed-bid procurement auction with LLM bidders. The lowest bid wins and is paid its bid. Each firm sees only its own cost, and there is no way for firms to talk. The question is whether bidders drift into taking turns winning at high prices without ever communicating, and whether the tie-break rule (random, least-wins-first, or a best-and-final rebid) changes that.

Two measures to define, once:
- **Collusion index.** 0 means prices at the competitive benchmark, 1 means every winning bid at the maximum allowed price, below 0 means under the benchmark. It is not clipped.
- **Delta.** The session's index minus the index of its one-shot control: same seed and costs, but the firm is shown no history. Delta isolates what repeated play adds.

**Show:** "What rotation would look like", round 3 (`#/scripted-rotation/0/3`). Point at the winner strip alternating blue, orange, blue, orange, and at the chart where both firms bid 99 and 100 whatever their cost. Say: this is the pattern we are looking for, and it is a scripted bidder, not a model.

## 0:30 to 1:00. The two pilot_tiny runs: the harness works

Two end-to-end checks, 18 sessions of 3 rounds each with real models, about 3 cents each. They are not data. Both passed all 15 log checks. No prompt leaked another firm's cost, and the control showed no history. Three first attempts failed out of about 330 calls and all recovered on a retry. The first run switched DeepSeek's host after a provider error; the rerun ran clean on the new hosts.

Two things first showed up here and shaped everything after:
- gpt-oss often bids at its own cost or at the 100 maximum.
- Qwen writes visible free text outside the tool call, which caused cutoffs at a 500-token cap.

No graph for this part.

## 1:00 to 2:20. The Phase A pilot: 90 sessions, three models, $3.11

Three models, three tie rules, repeated and control, 25 rounds, thinking on at low effort. All 90 sessions completed, all log checks pass.

**The tie check passed.** Ties happen in 3.1% of rounds, against a chance rate of 0.03%. So the tie rule has something to act on.

**There is no rotation.** Under random tie-break, no model prices above its own control and above the benchmark. Delta is -0.07 for DeepSeek, +0.01 for gpt-oss (with an index of -0.46) and -0.10 for Qwen. The lowest-cost firm wins slightly less often than in the control, but at below-benchmark prices that is noise, not turn-taking. `rival_lag_coef` is within 0.02 of its control: firms do not react to a rival's last bid.

Four things we saw instead, each with a graph:
1. **DeepSeek bids the equilibrium price.** **Show:** "DeepSeek prices at the competitive benchmark", round 5 (`#/deepseek-equilibrium/0/5`). Turn on "Show equilibrium bids", dots sit on the diamonds. Open the thinking text for a firm and read the derivation of `c + (100 - c)/3`.
2. **gpt-oss bids 100 to avoid winning, which is not collusion.** Reserve bids went up from 14-18% in the control to 27-34% in repeated play. **Show:** "gpt-oss bids at the reserve to lose on purpose", round 4 (`#/gpt-oss-reserve/0/4`). Three firms at 100, and the reasoning says it is avoiding a loss.
3. **A rebid mostly undercuts.** Under the rebid rule, gpt-oss and Qwen rebids undercut the tied bid by 32 and 24 on average (few ties, so small n; DeepSeek had only 2 rebids). **Show:** "A tie and its best-and-final rebid", round 4 (`#/bafo-rebid/0/4`). Three firms tie at 100, one rebids 95.83, two stay at 100. Open the rebid card to show the notice the firm got.
4. **Qwen is the messy one.** About a quarter of its attempts hit the 4,000-token cap and 4.5% of rounds are sit-outs. **Show:** "A model that sometimes fails to bid", round 3 (`#/qwen-invalid/0/3`). Firm B shows three cut-off attempts and no bid. This matters for how we set the output cap later.

## 2:20 to 3:30. The rotation screen: 100 sessions, about $3.00

Because there was no baseline rotation, we asked whether any setting produces it. One lever at a time, random tie-break, DeepSeek and gpt-oss:
- two bidders instead of three
- a coarse price grid (steps of 1 and of 5)
- thinking off (DeepSeek)
- all favourable levers together (two bidders, 50 rounds, step 1)
- a prompt line saying the same firms bid every round and that their strategies will be similar to yours, with no mention that they are the same model

We pre-declared what counts as a hit: delta and index both above 0, the lowest-cost win share falling, and delta positive in at least 4 of 5 sessions.

**No cell is a hit.** No cell has a mean index above 0.
- The closest cell is gpt-oss with two bidders and 50 rounds: delta +0.135 in 5 of 5 sessions, but its index is -0.82, and its reserve-bid share rose from 16% to 24%. That is moving toward competitive pricing, not collusion.
- Thinking off pushes DeepSeek further below the benchmark (index -0.42). Less reasoning made it more competitive, not less.
- The repeated-interaction prompt did not raise prices: delta -0.12 for gpt-oss at two bidders. **Show:** "The prompt that says the rivals repeat" (`#/repeat-prompt/0/1`). Open "System prompt" and point at the added line, then compare the winner strips of the repeated and control sessions.
- On the coarse grids, ties sit at the chance rate, so ties there tell us nothing about coordination.

## 3:30 to 4:15. The one exception worth showing

In one DeepSeek session with two bidders (seed 991003), the index is +0.31. The other four sessions of that cell average below zero. **Show:** "The one session above the benchmark", round 15 (`#/deepseek-outlier/0/15`), then switch to the control with "View this session" (`#/deepseek-outlier/1/15`).

What to point at, all visible in the chart and the table:
- From round 11 on, both firms bid 94 to 96 whatever their cost, including costs of 2, 17 and 26. The control bids on the benchmark line.
- The winning price creeps down by cents (95.9, 95.5, 95.49, ... 93.99) with a drop to about 50 every few rounds.
- The firm's reasoning describes the rival's alternating "high mode" and "low mode" and chooses to undercut only slightly.

Say plainly: this is one session out of five, found by looking at the outlier, so it is a lead and not a result. It is the closest thing to the behaviour we are after.

## 4:15 to 4:45. What this means and what is next

- Harness and measures work. The tie manipulation check passes, but the tie lever has no baseline rotation to move.
- For these models and settings, bidders compete, and the tie rule is not a lever on collusion. This is a null result at n = 5.
- Findings that stand on their own: reserve bidding rises under repeated play, rebids undercut, thinking-on DeepSeek reaches equilibrium while gpt-oss and Qwen bid well below it, and a cheap prompt change does not move prices.
- Open decisions: whether to follow up the outlier session with more sessions at two bidders and DeepSeek, whether to run the main tie-break experiment at all, and the Phase B settings (thinking mode, output cap, reasoning length, budget).

## Numbers cheat sheet

| Run | Sessions | Spend | Result in one line |
|---|---|---|---|
| pilot_tiny, first run | 18 | about $0.012 | Harness check passed |
| pilot_tiny, rerun | 18 | about $0.015 | Harness check passed on new hosts |
| pilot | 90 | $3.11 | Tie gate passes at 3.1%, no rotation |
| rotation screen | 100 | about $3.00 | No cell meets the hit rule |

## If asked

- **Why no statistics?** Five sessions per cell is a pilot. Everything is per-session means with no tests, and the pre-declared analysis waits for the full run.
- **Is the control fair?** Same seed and costs, no history shown. For the repeated-interaction prompt the control gets the same system prompt, so the added line also says the firms repeat.
- **Does the repeated-interaction prompt count as spontaneous?** No. It gives the model a reason to expect symmetric reasoning, so a hit there would be reported as prompt-induced.
- **Why gpt-oss bids at cost or the maximum?** Its reasoning cites a wrong equilibrium formula or loss avoidance. Both are mistakes about payoffs, not coordination.
- **Not run:** a 50-round arm on its own, and the repeated-interaction prompt for DeepSeek or at three bidders.
