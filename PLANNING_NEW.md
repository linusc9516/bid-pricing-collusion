# Plan: the channel study (written 10 October 2026)

This file is the plan for the work after the no-channel baseline. It replaces the run plan in `PLANNING.md`, which
describes the shelved tie-break study; the data schema and harness notes there still apply. Nothing in this file is a
declared analysis. Each arm's hypothesis and test go into `configs/analysis.yaml` in their own commit before that arm
runs, as was done for the baseline.

Companion file: `DIFFERENCE.md` compares this design and its results with prior work and gives the wording to use for
the claims.

## 1. Question and claim

**Question.** Two LLM firms bid against each other in a repeated sealed-bid procurement auction. Does giving them a way
to reach each other raise prices beyond what they already reach with no channel?

**Why "beyond".** The baseline showed that one of the two models prices above the competitive level with no channel at
all, and that the reasoning shows undercutting of displayed bids, not coordination. A channel result therefore cannot
be read from the price level alone. It needs two things: a price difference against the no-channel arm on the same
seeds, and evidence of agreement in what the firms write.

**Working claim, to be tested.** "Shown the bidding history, some current LLM bidders price above the competitive level
with no channel and no coordination in their reasoning. A private notes file does not change this; a channel between
the firms does, and the agreement is visible in the channel." Each half can fail independently, and either failure is
a result.

**Words.** Following Calvano et al. (2020) and Harrington, "collusion" needs a reward and punishment scheme, not only
high prices. Until a test shows one, the baseline result is called "pricing above the competitive level" or
"anchoring on displayed bids". See `DIFFERENCE.md`, section 7.

### 1.1 Three claims, from the safest to the one still to be tested

| Tier | Claim | Evidence now | What it still needs |
|---|---|---|---|
| **Fallback (the worst case)** | Showing the bidding history changes how the models bid, although costs are independent each round and the history carries no information at equilibrium | Both models, all 12 seeds each: the mean gap between a bid and the Bayes-Nash bid rises from 0.6 to 6.2 bid units for DeepSeek and from 3.6 to 10.3 for GPT-6 Luna (0.1 to 10.2 counting only calls that thought). The judge finds inference from earlier rounds in 94% of history calls | The gap measure was chosen after the run, so this is exploratory. Declare it before the 150-round baseline and test it there on fresh sessions |
| **Baseline** | With history, GPT-6 Luna prices above the competitive level; DeepSeek does not | Index +0.19 against −0.05; 7 of 12 GPT-6 Luna sessions above 0 | It does not pay on average (section 2.1). Still open: whether it persists past round 50, and whether it survives a narrow cost range |
| **Channel** | A channel between the firms raises prices beyond the baseline, and the agreement is visible in the channel; private notes alone do not | None yet | The main arms |

The fallback claim holds even if every later arm is null. It is a statement about behaviour, not about collusion: the
models treat past bids as informative when, at equilibrium, they are not. The two models differ in what follows from
it. DeepSeek's bids scatter around the Bayes-Nash bid and its price level stays put; GPT-6 Luna's level rises.

### 1.2 The intent question

**The concern (Linus, 10 October).** With two firms the Bayes-Nash bid is 50 + cost/2, so it is never below 50. A
capable model may know this and bid near the maximum to gain profit. Is a high bid its intent before it has seen any
feedback, or do the profits and the other firm's high bids push it there?

**What the baseline says.**

| Evidence | DeepSeek | GPT-6 Luna |
|---|---|---|
| One-shot bids within 1 of the Bayes-Nash bid | 97% | 99% of calls that thought; 7% of calls that did not |
| Round 1 of a history session (no history yet), bid minus Bayes-Nash bid | 0.0 | 0.0 for calls that thought; −20 for the half that did not |
| Bid minus Bayes-Nash bid, rounds 6 to 10, on the three high seeds | +2.6 | +14.9 |
| The same, on the other nine seeds | −2.4 | +1.2 |
| History bids of 90 or more (the Bayes-Nash bid is 90 or more in 18% of cases) | 20% | 39% |
| History bids at the reserve price | 3% | 4% |

- **Before any feedback the intent is the equilibrium bid, not a high bid.** A model that thinks bids the Bayes-Nash
  bid almost exactly, in a one-shot round and in the first round of a session.
- **The floor of 50 is not the cause.** The index is measured against the Bayes-Nash bid, which already contains the
  floor, so "equilibrium bids are high" cannot give a positive index.
- **The move to high bids comes after feedback, and only where high bids were on screen early.** It opens in rounds 2
  to 5 on the three seeds whose first rounds showed bids of 83 to 100, and stays small on the other nine.
- **There is something to the concern for GPT-6 Luna:** with history it bids 90 or more about twice as often as
  equilibrium play would. Few of those bids are at the maximum itself.
- **Settled by section 2.1:** bidding high in reply to a high-bidding opponent is a sound reply to the bids already on
  screen and an error over the session. A firm that bid the Bayes-Nash bid throughout would have earned more.

## 2. What exists

| Item | State |
|---|---|
| No-channel baseline, 50 rounds (`baseline_no_channel`) | Done, 10 October. 12 matched pairs per model, declared tests. DeepSeek at the competitive level with and without history. GPT-6 Luna above it with history (index +0.19) |
| Trace judge, rubric v3 | Done on 960 baseline traces. Labels not hand-checked |
| Harness for notes, shared workspace, messages, placebo history | Not built. A collaborator's fork has a first shared-workspace implementation; its logs are not in this repo |
| Narrow-cost draw (`cost_spread`) with a numeric equilibrium benchmark | Built (`bne.CommonCostBenchmark`), used once in `costrange` |
| History window as a config value, coarse bid grids | Built |

### 2.1 Two checks on the existing baseline (free, exploratory)

The baseline shows GPT-6 Luna pricing above the competitive level with history. Two checks on the existing logs say
whether that pays, and so which description of the result is right. Neither needs a new run. Both are exploratory:
they were thought of after the results were seen.

**Joint-profit check: do the two firms together earn more than at equilibrium?**

- **Compute, per session:** the two firms' actual total profit over the session, and the total they would have earned
  on the same costs if both had bid the Bayes-Nash bid in every round. Report the ratio and the difference, per model
  and arm, with the session as the unit.
- **Why it is needed.** The index looks only at the price paid. A high price with the higher-cost firm winning can
  leave the firms no better off: with history the lowest-cost firm wins 71% of GPT-6 Luna's rounds, against 92%
  one-shot.
- **Data:** `bids.jsonl` (`profit`, `cost`, `bne_bid`, `is_winner`, `is_min_cost`).

| Result | Reading |
|---|---|
| Actual profit above the equilibrium profit | The high prices pay the firms as a pair. That is the outcome collusion aims for, however they got there |
| About equal | The higher price is offset by the wrong firm winning |
| Below | The firms lose money against equilibrium play. It is a mistake, not a strategy |

**Best-response check: is each firm's bid a good reply to how the other firm actually bids?**

- **Compute, per firm and round:** take the other firm's actual bids in that session as its bid distribution. Given the
  firm's own cost, find the bid that maximises expected profit against that distribution, (bid − cost) × the chance
  that the other firm bids higher. Compare it with the bid the firm made. Report the profit given up as a share of the
  best attainable, and whether the bid was above or below the best reply.
- **Example.** A firm has cost 20, and the other firm has bid between 80 and 95 all session. The Bayes-Nash bid is 60,
  earning 40 when it wins. The best reply is just under 80: it still wins almost every round and earns about 60. A bid
  near 79 there is a sensible reply to this opponent, not a failure to bid competitively.
- **This is the analogue of the check in Calvano et al. (2020)**, who show that their algorithms' high prices are close
  to a best reply to each other and so are not a failure to optimise.

| Result | Reading |
|---|---|
| Little profit given up | Each firm bids well given the other. The high prices confirm themselves: neither firm gains by returning to the Bayes-Nash bid alone |
| Much given up, by bidding too high | The firm loses rounds it should win. Anchoring as a mistake |
| Much given up, by bidding too low | The firm undercuts by more than it needs to |

**The two together sort the baseline result into one of three descriptions.**

| Joint profit | Bids against the best reply | Description |
|---|---|---|
| Above equilibrium | Close | A stable high-price outcome that neither firm wants to leave. The nearest to tacit collusion in outcome, still with no reward and punishment scheme shown |
| Above equilibrium | Far | High prices by the luck of the start; a firm that replied better would undercut more |
| Not above | Far | An anchoring error from which nobody gains |

**Limits.**

- The best-response check uses about 50 bids per session as the other firm's distribution, so it is rough.
- It treats that distribution as fixed, although it shifts over the session, and it ignores that the other firm's bid
  depends on its own cost. A version that conditions on the round block is a refinement.
- Neither check shows a reward and punishment scheme. They separate "pays" from "does not pay"; the forced deviation
  (section 10) and the replayed rival (S1) are what separate anchoring from coordination.

The same two checks are computed for every later arm, so that a channel effect on price can be read beside its effect
on profit.

**Results on `baseline_no_channel` (run 11 October; exploratory; 12 sessions per cell).**

Joint profit as a ratio to the profit under equilibrium play on the same costs:

| | One-shot | History | History sessions above 1.0 |
|---|---|---|---|
| DeepSeek | 0.96 | 0.88 (interval 0.81 to 0.95) | 2 of 12 |
| GPT-6 Luna | 0.82 | 0.99 (interval 0.89 to 1.10) | 5 of 12 |

- GPT-6 Luna's higher prices leave the firms where equilibrium play would: the mean price is 72.4, but the winner's
  mean cost is 39.1 where the lowest cost averages 32.6.
- With history DeepSeek earns 12% less than under equilibrium play.
- On the three high seeds the ratio is 1.09, 1.25 and 1.35. Across seeds the ratio and the index have a rank
  correlation of 0.95.

Best reply, with history:

| | DeepSeek | GPT-6 Luna |
|---|---|---|
| Bids within 1 of the best reply to the other firm's earlier bids | 49% | 77% |
| Profit forgone against that best reply | 9% | 5% |
| Profit forgone against the other firm's bids over the whole session | 21% | 36% |
| Gain if one firm switches alone to the Bayes-Nash bid, the other firm's bids held fixed | +5% (8 of 12 sessions) | +10.5% (12 of 12; interval +7.6% to +13.6%) |

- Each firm replies well to the bids already on screen and badly to what the other firm goes on to do, because the
  other firm is adjusting too. This is the pattern called fictitious play.
- A GPT-6 Luna firm would have earned more with the plain Bayes-Nash bid in every session, the three high seeds
  included (+6% to +21% there, winning 79% of rounds).

**Which description fits.** Not the first: no session is an outcome that neither firm wants to leave. On average the
third: an anchoring error from which nobody gains. On the three high seeds the second: joint profit above equilibrium
by the luck of the start, with deviation still paying.

**Limits of these results.** The switching test holds the other firm's bids fixed, and a real opponent would react;
fear of that reaction is what a collusive outcome rests on, and the judge finds no such reasoning. The "forgone"
figures are biased upward, because the best reply is found and scored on the same sample: DeepSeek's one-shot arm,
which bids the equilibrium, shows 6% to 13% by this method, so that is the noise floor. Scripts: not yet in the repo.

### 2.2 Observations and current explanations (state on 10 October)

Kept apart on purpose: the first table is what the logs show, the second is what is believed about why.

**Observations**

| # | Observation | Status |
|---|---|---|
| O1 | One-shot, a model that thinks bids the Bayes-Nash bid: DeepSeek 97% within 1, GPT-6 Luna 99% of thinking calls. No formula is given | Declared test H2 supported for DeepSeek. For GPT-6 Luna the split by thinking is descriptive |
| O2 | GPT-6 Luna skips hidden thinking on 26.5% of one-shot calls and 1.5% of history calls; without thinking it bids a median 12.7 below the Bayes-Nash bid. This pulls its one-shot index to −0.16 | Descriptive. The model chooses when to think, so this is not an experiment |
| O3 | With history both models leave the Bayes-Nash bid: within 1 of it falls from 97% to 25% (DeepSeek) and 99% to 13% (GPT-6 Luna, thinking calls); the mean gap rises on all 12 seeds for both | Exploratory (the gap measure was not declared) |
| O4 | Price level: DeepSeek −0.05 with history, GPT-6 Luna +0.19 | Declared test H1 not supported for either; GPT-6 Luna's change is upward (Holm p 0.002), mixed with O2 |
| O5 | The drop found for DeepSeek in the earlier batch `n2_replicate` (delta −0.114) did not recur (−0.026) | Declared |
| O6 | GPT-6 Luna's bids react less to its cost with history: slope 0.57 to 0.37, intercept 43 to 61 | Secondary, significant after correction |
| O7 | The effect of history depends on the cost sequence: per-seed deltas have a rank correlation of 0.81 between the two models; the one-shot indices do not (0.39) | Exploratory |
| O8 | The gap between high and low seeds opens in rounds 2 to 5 and does not close by round 50. One-shot controls show no such split | Exploratory |
| O9 | The three high seeds are those whose first rounds put bids of 83 to 100 on screen, from a firm with a high cost that lost | Exploratory; read from five seeds |
| O10 | Judge, 960 traces: no call adopts coordination or punishes. Considered in 61% of DeepSeek's one-shot calls (and rejected), 9% and 2% of history calls | Exploratory; labels not hand-checked |
| O11 | Judge, history calls: a bid set just under an earlier displayed bid in 81% (GPT-6 Luna) and 51% (DeepSeek); a past price taken as the reference in 71% and 15%; copying a bid in under 2% | Exploratory; labels added after the run |
| O12 | With a cost control, the coefficient of a bid on the other firm's previous bid is small: 0.10 and 0.06, against 0.01 and 0.00 one-shot | Descriptive |
| O13 | GPT-6 Luna with history: ties in 7.3% of rounds (DeepSeek 1.2%); the lowest-cost firm wins 71% (92% one-shot) | Descriptive |
| O14 | Earlier coarse-grid data (DeepSeek, three firms, 25 rounds): coarser grids fall faster in rounds 2 to 15 and end at the same level | Weak: 5 sessions, other seeds |
| O16 | Joint profit with history is 0.99 of the equilibrium profit for GPT-6 Luna and 0.88 for DeepSeek; above it on GPT-6 Luna's three high seeds (1.09 to 1.35) | Exploratory |
| O17 | With history, 77% of GPT-6 Luna's bids and 49% of DeepSeek's are within 1 of the best reply to the other firm's earlier bids | Exploratory |
| O18 | One firm switching alone to the Bayes-Nash bid would gain 10.5% (GPT-6 Luna, 12 of 12 sessions) and 5% (DeepSeek, 8 of 12), the other firm's bids held fixed | Exploratory |
| O15 | On seven faster hosts DeepSeek ran into the output cap on 19% to 44% of replies; on DeepInfra, 0 of 32 in the test | Operational |

**Explanations (hypotheses, with what would test each)**

| # | Explanation | Rests on | Test |
|---|---|---|---|
| E1 | Each firm sets its bid just under the bids on screen, whatever its own cost: a best reply to the past as if it were fixed (fictitious play). Both do it, so the price falls by small steps from wherever the first rounds put it, and a high start stays high | O6, O8, O9, O11, O17 | Replayed rival (S1); history window (X1); bid grid (X2) |
| E2 | The wide cost range supplies the high starts by chance: a firm that draws 90 must bid above 90 | O9 | A narrow independent cost range |
| E3 | This is anchoring on displayed bids, not coordination | O10, O11; no reward and punishment shown | Forced deviation (section 10); the judge hand-check |
| E4 | Intent before feedback is the equilibrium bid; the high bids are made by the feedback | Section 1.2 | Already shown descriptively; the replayed rival would show it causally |
| E5 | GPT-6 Luna's one-shot shortfall is a thinking effect, not a strategy | O2 | None possible by assignment; report the split |
| E6 | The high bids are an error over the session, not a stable outcome: neither joint profit nor a firm's own profit is served by them on average | O16, O18 | Done (section 2.1). A forced deviation would show whether the other firm reacts |
| E7 | Unexplained: why GPT-6 Luna's level rises and DeepSeek's does not. Candidates: DeepSeek thinks about twice as long per call (1,800 tokens against 800) and infers a floor from many rounds, where GPT-6 Luna reacts to the latest level; GPT-6 Luna runs at a sampling setting that cannot be set | O4, O11 | A mixed pair; none for the sampling setting |
| E8 | The two DeepSeek batches differ (O5) because the mean over 12 seeds depends on which cost sequences were drawn | O7 | More seeds; repeats of one seed |

## 3. Arms, by rank

The ranking was proposed by Linus and checked on 10 October. Four points were changed after that check and agreed:
direct messages is a required control, not a side arm; the no-channel arm is rerun at the long session length;
placebo history stays a supporting arm but runs first; the narrow-cost arm includes a channel cell.

| Rank | Arm | What the firm gets, beyond the baseline | Compared with | Role |
|---|---|---|---|---|
| 0 | **B0 long: no-channel baseline, long sessions** | Nothing | Its own one-shot control (already run for 50 rounds; rerun at the long length) | The comparison arm for every channel arm |
| 1 | **M1: private notes** | A notes tool. Each firm reads and writes its own file | B0 long | Main arm, and the control for M2: it holds "having notes" fixed |
| 1 | **M2: shared workspace** | The same notes tool, but both firms read and write one file, and are not told | M1 (effect of sharing) and B0 long (total effect) | Main arm: an unintended channel |
| 1c | **C1: direct messages** | A message to the other firm before each bid | B0 long and M2 | Required control: the upper bound. Without it a null in M2 cannot be read |
| 2 | **S1: placebo history** | No channel. The displayed history is made independent of the firm's own play | B0 (50 rounds) | Supporting, runs first: separates anchoring from coordination in the baseline |
| 2 | **S2: narrow costs** | Costs drawn in a narrow band around a common level | B0 and M2 under the same narrow costs | Supporting: is the baseline effect, and the channel effect, an artefact of costs on 0 to 100 |
| 3 | **X1: history window of 20 rounds** | No channel; only the last 20 rounds are shown | B0 long | Mechanism check, exploratory |
| 3 | **X2: bid grid of 1 and of 5** | No channel; coarser bids | B0 (50 rounds) | Mechanism check, exploratory |

**Why this order holds.**

- **M1 before M2.** Three of the four LLM studies reviewed give their agents a private memory in every multi-agent
  arm (Heo 2026: "insights" and "strategy" text; Fish et al.: plans and insights files; Agrawal et al.: memory and
  scratchpad) and none varies it there.
  Fish et al. show in a monopoly that removing it changes behaviour. So "shared notes against no notes" would mix two
  things. M1 isolates the first; M2 minus M1 isolates sharing.
- **C1 is required.** If M2 shows nothing, the reader must know whether these models can hold a high price at all when
  they can plainly talk. Davis and Wilson (2002) found that even humans with face-to-face talk needed about 30 periods
  to raise prices and one group of eight never managed. C1 is that reference for the models.
- **S1 runs first.** It decides how the baseline is described, and every later arm is read against the baseline.
- **X1 and X2 are mechanism checks, not supporting evidence for the channel claim.** They test how the baseline effect
  works (how long a starting price persists, and how fast undercutting brings it down). Both readings of the baseline,
  anchoring and coordination, predict the same direction for them, so they cannot support either. They are reported as
  exploratory.

## 4. Design shared by all arms

| Setting | Value | Reason |
|---|---|---|
| Firms | 2, the same model on both sides | As in the baseline. Tolety (2025) finds prices fall with more bidders, so 2 is the most favourable case; say so as a limit |
| Models | DeepSeek V4.1 Flash (low effort, DeepInfra) and GPT-6 Luna (high effort, OpenAI) | As declared for the baseline |
| Costs | Private, i.i.d. uniform 0 to 100 each round, except in S2 | Keeps the closed-form benchmark |
| Seeds | 996000 to 996011, the baseline's, in every arm | The effect of history depends strongly on the cost sequence (0.81 between models). Arms are only comparable on the same seeds |
| Pairing | Each channel session is paired by seed with the B0 long session | Removes the seed effect from every comparison |
| Prompt | `prompts/bidder_system.md` (v1), plus the fewest lines needed to describe the tool of that arm | A one-line role and one goal line. No "competitor", no exploration or steering sentence |
| Rounds | 50 for S1, S2, X2. A long length for B0 long, M1, M2, C1, X1 (section 8) | Heo's sessions converge after round 59 to 73 on average, beyond 50 |
| Round count | Not announced | As in the baseline; avoids end-game effects |
| Unit of analysis | The session | A round is never an observation |
| Comparisons | History arm against history arm | GPT-6 Luna skips hidden thinking on 26.5% of one-shot calls and 1.5% of history calls, so its one-shot arm is not a clean reference |

Three rules carried over from the harness:

- **The auctioneer stays rule-based.** No arm uses an LLM auctioneer. That idea is future work.
- **The harness never shows a firm another firm's cost.** A firm may choose to write its own cost into a note or a
  message. That is the firm's act, it is logged, and the judge labels it. Whether to forbid it in the prompt is an
  open decision (section 9).
- **One parameter per arm.** `communication: none | private_notes | shared_notes | messages` is one session setting,
  not separate code paths.

## 5. The arms in detail

### B0 long: no-channel baseline at the long length

The baseline config with only `n_rounds` changed, history arm and one-shot control, same seeds. It answers two
questions on its own: whether GPT-6 Luna's high prices persist or decay after round 50, and whether DeepSeek stays at
the competitive level. The first 50 rounds should reproduce `baseline_no_channel` up to sampling noise, because the
round count is not announced; report that check.

### M1: private notes

Each firm has a notes tool with one file. Before it bids, it sees its file and may rewrite it. The file persists over
the session. The other firm never sees it.

- **Compared with B0 long**, paired by seed.
- **What it tests.** Whether a private memory alone moves prices. Prior work suggests it may: the supra-competitive
  results of Heo (2026) and Fish et al. were all obtained with such a memory present.
- **To decide.** File size limit; whether the file replaces part of the displayed history or adds to it. The history
  must stay identical to B0 long, so the notes are added, never substituted.

### M2: shared workspace

The same tool and the same prompt text as M1. The only difference is in the harness: both firms' tool calls read and
write one file.

- **Compared with M1** (the effect of sharing) and with B0 long (the total effect).
- **What to record.** `messages.jsonl` per session: every read and write, with round, firm and text. From it: the
  round in which a firm first reacts to text it did not write; whether a price or a turn-taking rule is proposed;
  whether the other firm follows; whether a firm writes its cost.
- **Attribution.** Entries are not labelled with their author in the first version. A firm has to notice foreign text
  by itself. A labelled version is a possible second cell.
- **Honesty of the prompt.** The prompt says the tool is the firm's notes. It does not say the file is private. This is
  deliberate and is stated in the paper.

### C1: direct messages

Before each bid, each firm may send one short message to the other firm; both messages are delivered before the bids.
The prompt says so plainly. Nothing in the prompt encourages or forbids agreement.

- **Compared with B0 long and with M2.**
- **A second cell, if budget allows:** firms are told to agree on prices. It shows whether the models can hold a high
  price when asked to, which bounds every other arm from above.
- **Read the result by segment and by session**, not only as a session mean. Human collusion with talk formed late and
  broke down in places (Davis and Wilson).

### S1: placebo history (runs first)

The aim is to break the link between what a firm does and what it later sees, while keeping numbers on the screen.

Two versions; choose one before building (section 9):

- **Replay rival.** One LLM firm plays a scripted firm that replays, unchanged, the bids of a recorded
  baseline session from another seed. The LLM firm cannot influence it. Run it with a replay from a high-price session
  and from a low-price session. Anchoring predicts the LLM firm's bids follow the replayed level in both. Coordination
  predicts nothing here, because there is nobody to coordinate with and nothing the firm does is answered.
- **Relabelled history.** Two LLM firms as in the baseline, but the displayed history is said to come from an earlier,
  unrelated market. If prices still follow the displayed numbers, the numbers alone are doing the work.

The replay version is the stronger design: it varies the displayed price level as a treatment, on the same costs, and
the harness already has scripted bidders.

### S2: narrow costs

**Open point (found on 10 October, after this section was written):** `cost_spread` keeps the two firms' costs close
within a round, but the round's level still ranges over 5 to 95, so high numbers still reach the screen. The direct
test of the artefact is a narrow independent range, for example costs on 40 to 60, where the closed-form benchmark
still holds. `PRE_SPRINT_TODO.md`, task 6, sets out both options and recommends the narrow range first. The text below
describes the `cost_spread` version.

`cost_spread` set so that a round's costs lie within a narrow band around a common level, with the numeric equilibrium
benchmark already in `bne.py`. Two cells: no channel, and the shared workspace (M2). 50 rounds, same seeds.

- **What it tests.** With costs on 0 to 100, a firm that draws a cost of 90 must bid above 90, which puts high bids on
  screen by chance. Narrow costs remove that source. If the no-channel effect disappears, it was an artefact of the
  wide range; if the channel effect also disappears, the same holds for it.
- **Before running:** check what `CommonCostBenchmark` assumes about what a firm knows of the common level, and state
  it in the prompt in the same words.

### X1 and X2: mechanism checks

- **X1, `history_window: 20`**, long sessions, no channel. If the starting price persists because early bids stay on
  screen, a window of 20 should let it fade after round 20. This is also Heo's (2026) setting.
- **X2, grid 1 and grid 5**, 50 rounds, no channel, history arm only. If prices stay high because each undercut is one
  cent, a coarser grid should bring them down faster. Coarse grids also create ties and round-number bids; report the
  tie rate beside the index. Banchio and Skrzypacz (2022, footnote 16) note that the grid step bounds how close
  step-by-step outbidding gets to the competitive price.

## 6. Hypotheses to declare (drafts)

Each is written into `configs/analysis.yaml` before its arm runs. All are per model, paired by seed, session as unit,
exact sign-flip test, Holm within a family.

| Id | Statement | Outcome | Family |
|---|---|---|---|
| H3 | Private notes change the price level against no channel | index(M1) minus index(B0 long) | Main |
| H4 | Sharing the workspace raises the price level against private notes | index(M2) minus index(M1) | Main |
| H5 | Direct messages raise the price level against no channel | index(C1) minus index(B0 long) | Main (control) |
| H6 | With a replayed rival, the firm's bids follow the replayed price level | markup ratio under the high replay minus under the low replay, same seeds | Supporting |
| H7 | Under narrow costs the no-channel history arm is at the competitive level | index inside a declared band, as H2 | Supporting |
| H8 | The fallback claim: history moves bids away from the Bayes-Nash bid | mean absolute gap between bid and Bayes-Nash bid per session, history minus one-shot, tested on the 150-round baseline | Baseline |

Evidence from the text is declared with them: the share of sessions in which the judge finds a proposed and an
accepted price or turn-taking rule in the channel, with the judge run on the reasoning and on the channel text
separately, and a hand-coded sample to validate it. A price effect without that evidence is reported as a price
effect, not as collusion.

Not hypotheses: X1 and X2 (exploratory), and anything about rounds beyond 50 in B0 long that is thought of after
seeing it.

## 7. Order of work

Before the sprint (to 22 October):

0. Run the joint-profit and best-response checks of section 2.1 on the baseline logs. Free.
1. Hand-check the judge on the 30 calls in `results/baseline_no_channel/trace_judge_check.csv`, and on a second sample
   of the three new labels. Fix the rubric if needed.
2. Build S1 (replay rival), declare H6, run it. About $3.
3. Build `communication` as one session setting with the three channel values and `messages.jsonl`; extend
   `check_logs.py` (the notes of M1 never reach the other firm; the workspace of M2 is one file; no cost appears in a
   harness-written line) and the judge (labels for the channel text).
4. Run X2 and S2 at 50 rounds. About $6.
5. Tiny end-to-end checks of M1, M2 and C1 (3 rounds), read by hand.
6. Decide the long length and the session count (section 8), then declare H3 to H5.

During the sprint (23 to 25 October): B0 long, M1, M2, C1, then X1, in that order, then analysis and the write-up.

After each run: `check_logs.py` first, then `analyze.py`, then the judge.

## 8. Session length, session count and cost

Cost per 12 history sessions, from the baseline's measured token use. The prompt grows with every round, so input cost
grows with the square of the session length.

| Length | DeepSeek | GPT-6 Luna | Both, one arm |
|---|---|---|---|
| 50 rounds | $1.3 | $0.7 | $2.0 |
| 100 rounds | about $3.2 | about $1.8 | about $5.0 |
| 150 rounds | about $5.7 | about $3.3 | about $9.0 |

Notes and message calls add to this; allow 30% to 50% for M1, M2 and C1.

| Plan | Arms | Rough total |
|---|---|---|
| Long arms at 100 rounds (B0 long, M1, M2, C1, X1), 12 seeds, both models | 5 | about $30 |
| The same at 150 rounds | 5 | about $55 |
| Short arms (S1, S2 two cells, X2 two grids), 12 seeds, both models | 5 cells | about $10 to $12 |

With a $50 credit, 100 rounds fits and 150 does not. 100 rounds covers Heo's mean convergence points (rounds 59 to
79). Wall time on DeepInfra is about 50 minutes per 100-round DeepSeek session, all sessions in parallel.

Session count: 12 pairs detected GPT-6 Luna's effect but leave DeepSeek's interval wide (about ±0.07). 24 seeds would
halve the cost headroom. Keep 12 for the first pass and add a second block of 12 new seeds, declared separately, if
credit remains.

## 9. Open decisions

| Decision | Options | Leaning |
|---|---|---|
| Long session length | 100 or 150 rounds | 100, for cost |
| Placebo design (S1) | Replay rival, or relabelled history | Replay rival |
| May firms state their costs in a channel | Allowed and logged; or forbidden in the prompt, as in Davis and Wilson | Allowed and logged, since a prohibition is itself a steer |
| Workspace attribution in M2 | Unlabelled; labelled; both | Unlabelled first |
| Instructed-agreement cell in C1 | Run or skip | Run if credit allows |
| Models in S2 and X2 | Both, or GPT-6 Luna only | Both |
| Seeds beyond 12 | A second block of 12, declared separately | After the first pass |

## 10. Candidates not in the ranking

Suggested by the comparison with prior work; none is agreed.

- **Forced deviation.** Override one firm's bid with a deep undercut in one round and compare the other firm's later
  bids with a twin session on the same seed. A lasting shift fits anchoring; a short drop and a return fits punishment.
  This is the test Calvano et al. use, and no LLM study has run it.
- **Mixed pair** (DeepSeek against GPT-6 Luna), no channel: do Luna's high prices need two Lunas?
- **Three firms**, no channel: Tolety and Heo (2024) both find prices fall with more bidders.
- **A bridging cell:** Heo's common known cost with this prompt and these models, to show whether the difference from
  their result comes from the game or from the prompt.

## 11. Risks

| Risk | What it would look like | Response |
|---|---|---|
| The channel harness changes the no-channel prompt | B0 long and the baseline differ in the first 50 rounds | Snapshot tests on the prompt; report the first-50 comparison |
| The notes tool makes replies run past the output cap | More cut-off replies than in the baseline (0.7% to 2.2% for DeepSeek) | Measure in the tiny checks; keep the cap, limit the file size |
| Firms never notice the shared file | No foreign text is ever referred to | It is a result; the labelled-attribution cell tests whether noticing is the barrier |
| Models refuse to agree on prices in C1 | Messages state a refusal | It is a result; the instructed cell shows whether they can |
| The judge mislabels channel text | Hand-coded sample disagrees | Report agreement; fall back to hand coding of the sessions that matter |
| Seed effect swamps arm effects | Paired differences vary as much as the baseline's deltas | Same seeds in every arm; a second block of seeds |
| Luna's sampling cannot be set | Temperature is not accepted by its endpoint | State it with every result |
