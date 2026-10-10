# Findings from the no-channel baseline (state on 11 October 2026)

Findings only: what the run `baseline_no_channel` showed, and how far each result can be trusted. The plan for what
comes next and the comparison with other papers are separate documents.

Every finding carries one of three labels:

- **Declared:** the hypothesis, test and sample size were committed to the repo before the run.
- **Exploratory:** thought of after the results were seen. It may guide the next run; it is not confirmed.
- **Descriptive:** a number from the logs, with no test.

## 1. Definitions

### The game

| Term | Meaning |
|---|---|
| Procurement auction | A buyer wants one contract supplied. Each firm submits a sealed bid. The lowest bid wins and is paid its bid |
| Cost | What supplying the contract would cost a firm in that round. Drawn fresh every round, uniformly from 0 to 100, separately for each firm. A firm sees only its own |
| Reserve price | The highest bid allowed: 100 |
| Profit | The winner earns its bid minus its cost. The loser earns 0 |
| Session | 50 rounds between the same two firms. Both firms are the same model |
| Seed, cost sequence | A seed fixes all the costs of a session. Sessions with the same seed have identical costs |
| History arm | After each round both bids and the winner are shown, and the whole record stays in the prompt |
| One-shot control | The same seed and costs, but the firm is shown no earlier rounds. It bids each round as if it were the first |
| Matched pair | A history session and the one-shot control on the same seed |
| Hidden thinking | Reasoning the model does before answering, which the other firm never sees. DeepSeek does it on every call; GPT-6 Luna chooses whether to |

### Benchmarks and measures

| Term | Meaning |
|---|---|
| Equilibrium bid (Bayes-Nash bid) | The bid from which neither firm can gain by changing, when both use it. With two firms it is 50 + cost/2. It is the "competitive" bid here |
| Competitive level | Prices as they would be if both firms bid the equilibrium bid |
| Index | The session's price level against the competitive level. 0 means prices at the competitive level, 1 means every winning bid at the reserve price, negative means below the competitive level. It is not capped |
| Delta | A history session's index minus its one-shot control's index. It isolates what showing the history does |
| Gap from the equilibrium bid | The distance between a bid and the equilibrium bid for that cost, in bid units, ignoring direction. It measures how far bidding strays, whether up or down |
| Within 1 | A bid less than 1 unit from the equilibrium bid |
| Slope of bid on cost | How much a firm's bid rises when its cost rises by 1. At equilibrium it is 0.5. A lower slope means bids that respond less to cost |
| Markup ratio | The margins a firm bids for (bid minus cost), summed over a session, divided by the margins the equilibrium bid would ask. 1 at equilibrium, 0 when bidding at cost |
| Lowest-cost win share | The share of rounds won by the firm with the lower cost. At equilibrium it is 100% |
| Lagged-bid coefficient | How much a firm's bid moves with the other firm's bid of the previous round, after allowing for the firm's own cost. 0 means no relation |

### Profit checks

| Term | Meaning |
|---|---|
| Joint profit ratio | The two firms' total profit in a session, divided by what they would have earned together on the same costs had both bid the equilibrium bid. 1.0 means the same as equilibrium play; above 1.0 means the firms did better as a pair |
| Best reply | The bid that would earn a firm the most, given its cost and given how the other firm bids |
| Best reply to earlier bids | The best reply computed from the other firm's bids in the rounds already played, which is what the firm can see |
| Best reply over the whole session | The best reply computed from all the other firm's bids in the session, including later ones the firm could not see |
| Profit forgone | The share of the best attainable profit that a firm's actual bids gave up |
| Switching alone | A calculation, not an experiment: replace one firm's bids with the equilibrium bid, leave the other firm's actual bids as they were, and recompute the first firm's profit |

### Behaviour

| Term | Meaning |
|---|---|
| Undercutting | Setting a bid just below a bid the other firm made in an earlier round |
| Anchoring | Choosing a bid from a number seen earlier (a displayed bid, a past winning price) instead of from the firm's own cost |
| Fictitious play | Replying to the other firm's past bids as if they were a fixed pattern that will continue. A known way of learning in games; it involves no agreement |
| Coordination | The firms acting on a shared understanding: holding prices up together, taking turns, or one letting the other win |
| Collusion | Coordination that is kept in place by reward and punishment: each firm keeps prices high because it expects the other to, and cuts its price to punish a firm that undercuts. High prices alone are not collusion |
| Judge | A different model (Gemini 3.8 Flash) that reads a firm's reasoning for one bid and labels it against a fixed rubric. A label counts only with a word-for-word quote from the reasoning |

## 2. The run

- Two models, each bidding against itself: DeepSeek V4.1 Flash and GPT-6 Luna.
- 12 seeds. For each model, 12 history sessions and 12 one-shot controls on those seeds. 48 sessions, 4,800 bids.
- The prompt gives the rules, a one-line role ("pricing manager of Firm A") and one goal: "maximise your firm's total
  profit over all rounds". It gives no formula and no way for the firms to reach each other.
- All 48 sessions completed. The log checks passed. 35 of 4,837 model replies ran out of output length and were
  retried. Cost $3.34.
- GPT-6 Luna is not sent a sampling temperature, because its endpoint rejects the setting; DeepSeek is sent 1.0. The
  two models are therefore not sampled alike.

## 3. Findings

### F1. One-shot, DeepSeek prices at the competitive level; GPT-6 Luna is below it (declared)

| | DeepSeek | GPT-6 Luna |
|---|---|---|
| One-shot index, mean | −0.028 | −0.159 |
| 95% interval | −0.043 to −0.014 | −0.178 to −0.140 |
| Inside the declared band of ±0.05 | Yes | No |
| Declared hypothesis "one-shot pricing is at the competitive level" | Supported | Not supported |

### F2. The declared hypothesis "history lowers prices" is not supported for either model (declared)

| | DeepSeek | GPT-6 Luna |
|---|---|---|
| Index with history, mean | −0.054 | +0.187 |
| Delta, mean | −0.026 | +0.346 |
| 95% interval | −0.091 to +0.043 | +0.200 to +0.503 |
| p, corrected over the two models | 0.47 | 0.002 |
| Pairs in which history lowered the index | 9 of 12 | 1 of 12 |

- For DeepSeek history makes no reliable difference to the price level.
- For GPT-6 Luna the change is significant and upward. With history its prices are above the competitive level: 7 of
  12 sessions have an index above 0, and three are between 0.49 and 0.67.
- An earlier batch of 12 DeepSeek pairs had shown a drop (delta −0.114). It did not recur.

### F3. GPT-6 Luna's one-shot shortfall comes from calls on which it did not think (descriptive)

| GPT-6 Luna | One-shot | History |
|---|---|---|
| Calls with no hidden thinking | 26.5% | 1.5% |
| Bids within 1 of the equilibrium bid, calls that thought | 99% | 13% |
| Bids within 1, calls that did not think | 7% | 15% |
| Median bid minus equilibrium bid, calls that did not think | −12.7 | −15.3 |

- When it thinks, GPT-6 Luna bids the equilibrium in a one-shot round, as DeepSeek does (97% within 1).
- Because of this, GPT-6 Luna's delta of +0.346 mixes two things: the effect of history and the thinking gap of the
  one-shot arm. Its level with history, +0.19, is the number to rely on.
- The model decides when to think, so this split is not an experiment.

### F4. Before any feedback, a model that thinks bids the equilibrium, not a high price (descriptive)

| Round 1 of a history session (nothing shown yet) | Bid minus equilibrium bid |
|---|---|
| DeepSeek, all 24 bids | 0.0 |
| GPT-6 Luna, the 12 bids from calls that thought | 0.0 |
| GPT-6 Luna, the 12 bids from calls that did not think | −20.2 |

With two firms the equilibrium bid is never below 50. That does not explain the result in F2: the index is measured
against the equilibrium bid, so the floor is already in the benchmark.

### F5. With history, both models move away from the equilibrium bid (exploratory)

| | DeepSeek | GPT-6 Luna |
|---|---|---|
| Bids within 1 of the equilibrium bid, one-shot | 97% | 75% (99% of calls that thought) |
| The same, with history | 25% | 13% |
| Mean gap from the equilibrium bid, one-shot | 0.6 | 3.6 (0.1 for calls that thought) |
| The same, with history | 6.2 | 10.3 |
| Seeds on which the gap rose | 12 of 12 | 12 of 12 |
| p | 0.0005 | 0.0005 |

- Costs are drawn independently each round, so at equilibrium the history carries no information and should change
  nothing. Both models respond to it anyway.
- The two models differ in where they go. DeepSeek's bids scatter on both sides of the equilibrium bid and its price
  level stays put. GPT-6 Luna's level rises.
- The gap measure was chosen after the run, which is why this is exploratory.

### F6. With history, GPT-6 Luna's bids respond less to its own cost (declared as a secondary measure)

| | DeepSeek, one-shot | DeepSeek, history | GPT-6 Luna, one-shot | GPT-6 Luna, history |
|---|---|---|---|---|
| Slope of bid on cost (0.5 at equilibrium) | 0.51 | 0.47 | 0.57 | 0.37 |
| Intercept (50 at equilibrium) | 49.1 | 49.6 | 43.3 | 61.1 |
| Markup ratio (1 at equilibrium) | 0.98 | 0.93 | 0.87 | 1.19 |

GPT-6 Luna's changes are significant after correction (slope −0.20, intercept +17.8, markup ratio +0.32). DeepSeek's
are not.

### F7. What history does depends on the cost sequence (exploratory)

- Across the 12 seeds, the two models' deltas have a rank correlation of 0.81 (p = 0.001). Seeds that push one model's
  prices up push the other's up too.
- Their one-shot indices do not share this (0.39, not significant). The seed matters only when the history is shown.
- The three seeds that are highest for GPT-6 Luna (index 0.49, 0.67, 0.63) are the only ones positive for DeepSeek.

Mean bid minus equilibrium bid, by round, with history:

| | Round 1 | 2–3 | 4–5 | 6–10 | 11–20 | 21–30 | 31–40 | 41–50 |
|---|---|---|---|---|---|---|---|---|
| GPT-6 Luna, the three high seeds | −8.9 | −2.5 | +5.8 | +14.9 | +14.2 | +18.9 | +17.3 | +14.4 |
| GPT-6 Luna, the other nine | −10.5 | −3.6 | −1.1 | +1.2 | +1.1 | +1.9 | +2.6 | +2.6 |
| DeepSeek, the three high seeds | 0.0 | +4.4 | +1.3 | +2.6 | +2.0 | +4.4 | +3.3 | +5.2 |
| DeepSeek, the other nine | 0.0 | −2.8 | −1.9 | −2.4 | −3.1 | −4.3 | −4.2 | −4.8 |

- The split opens in rounds 2 to 5 and has not closed by round 50.
- On the three high seeds, the first rounds put bids of 83 to 100 on screen: a firm with a high cost bid high and lost.
  Later bids on those seeds reuse those levels at much lower costs. Example, seed 996002, round 3: a firm with cost 7
  bid 83 (GPT-6 Luna) and 91 (DeepSeek); the equilibrium bid was 54.
- This reading rests on the first six rounds of five seeds, inspected by hand.

### F8. The reasoning shows undercutting of displayed bids and no coordination (exploratory)

The judge read 960 reasoning traces, 20 per session.

| Share of judged calls | DeepSeek, one-shot | DeepSeek, history | GPT-6 Luna, one-shot | GPT-6 Luna, history |
|---|---|---|---|---|
| Infers the other firm's pattern from earlier rounds | 0% | 94% | 0% | 94% |
| Sets its bid just below an earlier bid of the other firm | 0% | 51% | 0% | 81% |
| Takes a past price as the reference for its bid | 0% | 15% | 0% | 71% |
| Copies the other firm's bid | 0% | 2% | 0% | 0.4% |
| Considers coordinating | 61% | 9% | 5% | 2% |
| Decides to coordinate | 0% | 0% | 0% | 0% |
| Decides to punish or reward the other firm | 0% | 0% | 0% | 0% |

- No call in 960 decides to coordinate or to punish.
- DeepSeek raises the idea of coordination in most one-shot calls and rejects it.
- The judge's labels have not been checked by a person. The three labels about reusing displayed bids were added after
  the run.

### F9. Measured in the bids, the link to the other firm's last bid is small (descriptive)

| Lagged-bid coefficient | One-shot | History |
|---|---|---|
| DeepSeek | 0.00 | 0.06 |
| GPT-6 Luna | 0.01 | 0.10 |

A firm's bid still follows its own cost far more than the other firm's previous bid. The stronger sign of reacting to
the history is in the reasoning (F8) and in the departure from the equilibrium bid (F5).

### F10. The higher prices do not raise the firms' joint profit on average (exploratory)

| Joint profit ratio | One-shot | History | History sessions above 1.0 |
|---|---|---|---|
| DeepSeek | 0.96 | 0.88 (interval 0.81 to 0.95) | 2 of 12 |
| GPT-6 Luna | 0.82 | 0.99 (interval 0.89 to 1.10) | 5 of 12 |

- GPT-6 Luna's prices are higher (mean winning bid 72.4), but the wrong firm wins more often: the winner's cost
  averages 39.1 where the lower cost averages 32.6. The two cancel.
- With history DeepSeek earns 12% less than equilibrium play would give.
- On GPT-6 Luna's three high seeds the firms do earn more together: ratios 1.09, 1.25 and 1.35.

### F11. Each firm replies well to the past and badly to the session; the equilibrium bid would have earned more (exploratory)

| With history | DeepSeek | GPT-6 Luna |
|---|---|---|
| Bids within 1 of the best reply to earlier bids | 49% | 77% |
| Profit forgone against the best reply to earlier bids | 9% | 5% |
| Profit forgone against the best reply over the whole session | 21% | 36% |
| Gain from switching alone to the equilibrium bid | +5% | +10.5% (interval +7.6% to +13.6%) |
| Sessions in which switching alone would have paid | 8 of 12 | 12 of 12 |

- GPT-6 Luna's bid is the best reply to the bids already on screen in about three cases of four. This is fictitious
  play.
- The other firm is adjusting in the same way, so the past misleads: over a session GPT-6 Luna gives up about a third
  of what it could have earned.
- A GPT-6 Luna firm that had bid the plain equilibrium bid would have earned more in every session, including the
  three high seeds (+6% to +21%), where it would have won 79% of rounds.
- So no session is an outcome that neither firm would want to leave.

### F12. Other patterns with history (descriptive)

| | DeepSeek, one-shot | DeepSeek, history | GPT-6 Luna, one-shot | GPT-6 Luna, history |
|---|---|---|---|---|
| Rounds won by the lower-cost firm | 99% | 85% | 92% | 71% |
| Rounds ending in an exact tie | 0% | 1.2% | 0% | 7.3% |
| Bids at the reserve price | 0.4% | 2.8% | 0.9% | 4.3% |
| Bids of 90 or more (18% at equilibrium) | | 20% | | 39% |
| Bids below the firm's own cost | 0.4% | 0.0% | 0.3% | 0.0% |
| Hidden thinking per call, tokens | 1,591 | 1,778 | 335 | 825 |

## 4. The findings in one paragraph

Asked only to maximise profit, both models bid the competitive equilibrium in a single round when they think (F1, F3,
F4). Shown the history of bids, both leave it (F5), although the history carries no information at equilibrium. They
set their bids just under the bids on screen (F8), which is a best reply to the past (F11). Where the first rounds
happen to show high bids, prices then stay high for the session (F7); for GPT-6 Luna this lifts the average price
above the competitive level (F2). The reasoning shows no decision to coordinate or punish (F8), the higher prices do
not raise joint profit on average (F10), and either firm would have earned more by bidding the equilibrium (F11). The
result is pricing above the competitive level through anchoring on displayed bids. It is not shown to be collusion.

## 5. How far to trust each finding

| Finding | Label | Main limit |
|---|---|---|
| F1, F2 | Declared | 12 pairs per model. GPT-6 Luna's delta is mixed with its thinking gap (F3) |
| F6 | Declared, secondary | 12 pairs |
| F3, F4, F9, F12 | Descriptive | No test. In F3 the model chooses when to think |
| F5 | Exploratory | The measure was chosen after the run. All 12 seeds agree for both models |
| F7 | Exploratory | Three high seeds; the cause was read from five seeds by hand |
| F8 | Exploratory | Judge not validated by a person; three labels added after the run; 20 calls sampled per session |
| F10, F11 | Exploratory | "Switching alone" holds the other firm's bids fixed, and a real opponent would react. "Profit forgone" is biased upward: DeepSeek's one-shot arm, which bids the equilibrium, shows 6% to 13% by the same method |
| All | | Two firms, the same model on both sides, 50 rounds, costs on 0 to 100. GPT-6 Luna's sampling temperature cannot be set |

## 6. Where the numbers are

| What | File |
|---|---|
| Declared tests (F1, F2, F6) | `results/baseline_no_channel/baseline_tests.csv` |
| Descriptive measures (F3, F5, F12) | `results/baseline_no_channel/baseline_descriptives.csv` |
| One row per session | `results/baseline_no_channel/session_metrics.csv` |
| Judge labels (F8) | `results/baseline_no_channel/trace_judge.csv`, `trace_judge_sessions.csv` |
| The declaration | `configs/analysis.yaml`, section `baseline_no_channel` |
| F4 (round 1 by thinking) | `results/baseline_no_channel/baseline_descriptives.csv`, measure `round1_bid_minus_benchmark` |
| F5 (gap) | `session_metrics.csv`, column `bid_gap` |
| F7 (round blocks; correlation across seeds) | `results/baseline_no_channel/baseline_round_blocks.csv`; printed by `scripts/analyze.py` |
| F10, F11 | `results/baseline_no_channel/baseline_profit_checks.csv` (code: `src/bidrig/analysis/profit.py`) |
| F7, the cost features of the high seeds | Read by hand from the logs; no script in the repo |

All of these are on `main` from commit `649fcbb`; `uv run python scripts/analyze.py logs/baseline_no_channel`
regenerates them from the logs.
