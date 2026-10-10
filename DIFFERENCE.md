# How this study differs from prior work (10 October 2026)

Ten papers, each read by a separate agent against its source. A reviewing agent then checked this file against the
sources, and its corrections are applied (section 9 lists what was read, what was re-checked and what was not). "Mine" is the no-channel baseline `baseline_no_channel` and the plan in
`PLANNING_NEW.md`. Page numbers are those of the source named in section 9. Statements marked *(inference)* are a
reader's inference or arithmetic, not something the paper says.

## 1. The short version

- **Prices above the competitive level without communication are not new.** Heo et al. (2026), Fish et al. and Tolety
  (2025) report them for LLMs, and Calvano et al. (2020), Banchio and Skrzypacz (2022) and Heo et al. (2024, 2025) for
  learning algorithms. Do not claim to be first on that.
- **None of the four LLM studies reviewed here has a control without history, or a test that separates coordination
  from tracking displayed prices.** None has private costs either, so none has a benchmark for them (Fish et al.
  compute static Nash and monopoly prices for their game; Tolety defines a competitive equilibrium without reporting
  its value). These are what this study adds.
- **Three of the four give their agents a written private memory in every multi-agent arm and never vary it there**
  (Heo 2026, Fish et al., Agrawal et al.). Tolety has no notes file but keeps a per-agent conversation history
  (p.22). Their "no channel" condition is this study's planned private-notes arm, not its baseline.
- **Prompts differ.** In Heo (2026) the high price appears only with a profit-seeking sentence. Fish et al. have no
  duopoly arm without an added exploration sentence. Tolety uses a plain profit goal with a driver role. This study's
  result arises under a one-line role and one goal line, in one of two models.
- **The same behaviour is read differently.** Heo (2026) and Fish et al. regress a price on the other firm's previous
  price and read a positive coefficient as reward and punishment. Here the behaviour is read as undercutting or
  anchoring on displayed bids. Neither they nor this study has run the test that decides between the two. Calvano
  et al. ran it for Q-learners (a forced deviation).
- **There is a precedent for a mechanism without punishment.** Banchio and Skrzypacz's learners keep no state, so they
  cannot run a reward and punishment scheme, yet first-price bids settle far from the competitive level through
  outbidding "by just one bid increment" (abstract).

## 2. Claims side by side

| Paper | Agents and game | The paper's headline claim | Relation to my claim |
|---|---|---|---|
| **Mine** | 2 LLM firms (DeepSeek V4.1 Flash; GPT-6 Luna), repeated first-price procurement auction, private costs redrawn each round | Shown the bidding history, GPT-6 Luna prices above the competitive level with no channel (index +0.19); DeepSeek stays at it. The reasoning shows undercutting of displayed bids and no coordination | |
| Heo, Ahn & Park 2026 (J. Manage. Eng.) | 2 GPT-4o bidders, repeated lowest-bid procurement, common known cost | GPT-4o agents "frequently adopt reward–punishment mechanisms" and "often converge to supracompetitive prices" without collusive intent (p.1); the outcome is "one sentence away" in the prompt (pp.12-13) | Closest paper. Same market type, same finding in outline, different game and no control. They call it reward and punishment; I do not |
| Fish, Gonczarowski & Shorrer (arXiv 2404.00806 v6) | 2 GPT-4 agents, repeated price-setting duopoly; appendix A.6: first-price auction, common fixed value | LLM pricing agents "quickly and consistently arrive at supracompetitive pricing levels" with no instruction to collude (p.4); prompt wording shifts the level; behaviour "is consistent with a reward-punishment scheme" (p.6) | Same phenomenon in pricing. Defines algorithmic collusion by outcome, so no mechanism needs to be shown (p.2, fn.4) |
| Tolety 2025 (NeurIPS workshop) | 1 to 7 LLM drivers, repeated ascending payout clock, common fixed cost | Reports "systematic supra-competitive prices in small auction settings" without communication, collapsing at 5 or more bidders (abstract, p.1; p.5) | Claims "first evidence of bidder side tacit collusion by LLMs" (p.1), and calls his format "strategically equivalent to a first-price sealed-bid auction" (p.2), so in his own terms the claim covers my format. Common fixed cost; no control |
| Agrawal et al. 2025 (ICML workshop) | 5 LLM sellers and 5 LLM buyers, double auction, fixed common cost | Sellers "collude significantly more when they are allowed to communicate" (p.2); without messages they "do not price supracompetitively after the first 10 rounds" (p.6) | The precedent for my channel arms |
| Calvano et al. 2020 (AER) | 2 Q-learners, repeated price-setting, fixed cost | Q-learners "consistently learn to charge supracompetitive prices, without communicating", sustained by punishment "followed by a gradual return to cooperation" (p.3267) | Sets the standard for what counts as collusion. Not LLMs, not an auction |
| Banchio & Skrzypacz 2022 (arXiv 2202.05947) | 2 stateless Q-learners, repeated first-price and second-price auctions, common fixed value | First-price auctions with no extra feedback give "tacit-collusive outcomes"; showing the bid needed to win restores competition (abstract; pp.10, 18) | Closest auction paper for algorithms. Fixed values; outcome-only definition |
| Heo et al. 2025 (J. Manage. Eng.) | 2 or 4 Q-learning and DQN bidders, repeated construction tender, common cost estimate | RL bidders "can converge to collusive strategies, consistently leading to supracompetitive prices" (p.1) | Same market framing, learning algorithms, no benchmark derived |
| Heo, Park & Ahn 2024 (J. Comput. Civ. Eng.) | 2 to 5 Q-learning bidders, same setting | AI bidders "tend to develop cooperative strategies over time, leading to higher bids" (p.1) | Earliest of the Heo line; benchmark is a human average |
| Sherstyuk 1999 (Exp. Econ.) | 3 human buyers, 2 units, common known value | Collusion without communication in ascending auctions where bids may be matched; sealed-bid auctions "converged to the competitive equilibrium" (p.59) | Human reference with no channel |
| Davis & Wilson 2002 (Econ. Inquiry) | 4 human sellers, repeated procurement, identical cost schedules not disclosed to sellers | Given the chance to talk, sellers "often raise prices considerably" (p.213); organising it "is not a trivial matter" (p.224) | Human reference for a channel |

## 3. Setups side by side

### 3a. LLM studies

| | **Mine** | Heo 2026 | Fish et al. (pricing; auction A.6) | Tolety 2025 | Agrawal 2025 |
|---|---|---|---|---|---|
| Format | First-price sealed-bid procurement; lowest bid wins | Lowest-bid procurement (p.3) | Bertrand duopoly, logit demand (pp.8-9); A.6 forward first-price auction (p.38) | Ascending payout clock; first to accept wins (pp.2-3) | Double auction in rounds (p.2) |
| Agents | 2 | 2 (p.5) | 2 | 1 to 7 (p.4) | 5 sellers, 5 buyers (p.2) |
| Cost or value | Private, i.i.d. uniform 0 to 100, redrawn each round | Common and known: estimate 1.0, estimation error 0, realised cost ±0.5% (pp.3, 5) | Fixed marginal cost 1; A.6 common fixed value (pp.9, 38) | Common fixed reservation wage $10 (p.3) | Fixed: cost $80, value $100 (p.2) |
| What is shown | Every bid and the winner, whole session | Last 20 rounds: own bid, the other firm's bid, win, cost, profit (p.4) | Last 100 periods: all prices, own quantity and profit (p.10). A.6: own bid, win or loss, and the bid that would have sufficed to win (p.38) | Past winners, winning price and round (pp.14-15) | Order book, last 5 rounds, past trades (p.3; prompt p.11) |
| Private memory | None | "Insights" and "strategy" text from the previous round, in every arm (p.4) | Plans and insights files, rewritten each period, in every arm (p.10) | No notes file; a per-agent conversation history (p.22) | Memory log and strategy scratchpad, in every arm (p.3) |
| Horizon | 50 rounds, not announced | 150 rounds, not in the prompt (pp.4-5) | 300 periods, not in the prompt (p.8) | 40 auctions, expected length stated (p.14) | 30 rounds, announced (prompt, p.11) |
| Models | DeepSeek V4.1 Flash; GPT-6 Luna | GPT-4o, January 2025; temperature not stated (p.5) | GPT-4-0613, temperature 1; GPT-5.2 in A.5 (pp.12, 37, 41) | Four OpenAI models, temperature 0.2 (p.4) | GPT-4.1; Claude 3.7 Sonnet (p.3) |
| Goal and steering | A one-line role ("pricing manager of Firm A") and one goal line: "maximise your firm's total profit over all rounds". No "competitor", no exploration or steering sentence | "TOP PRIORITY" long-term profit; "experiment with ... risky or aggressive approaches"; plus a win-seeking or profit-seeking sentence; no arm without one (p.4) | "TOP PRIORITY ... profit in the long run"; exploration instruction; P1 or P2 sentence; the word "Competitor" (pp.11-12, 49) | Uber-driver persona; "maximize your profit. You can employ any strategy you wish" (pp.14-15) | "expert negotiator"; "maximum profitability"; "high profit margins" (pp.11-12) |
| Communication | None (channels planned) | None | None | None | Sellers broadcast one message per round; varied on and off (p.3) |
| Competitive benchmark | Closed-form Bayes-Nash bid function | None derived (cost 1.0 implicit) | Static Nash 1.47 and monopoly 1.92 (p.37; lines in the figure on p.13) | Reservation wage and large-group behaviour; not computed (pp.3, 19) | $90, the midpoint, asserted (p.3) |
| Measure | Index: 0 at the benchmark price, 1 at the reserve, not clipped; minus the matched one-shot control | Mean bid as a multiple of cost; lagged-bid regression (pp.7, 10) | Mean price and profit, periods 251-300 (p.13) | Mean accepted payout, small against large groups (p.5) | Trade price; judge-scored coordination (pp.3-4) |
| Sessions per cell | 12 matched pairs | 30 runs; 25 to 29 valid (Tables 1, 6) | 21 per prefix; 12 per prefix in A.6, 4 per value (pp.12, 39) | Not stated | 10, stated for one experiment (p.4) |
| Unit and test | Session; exact paired sign-flip; Holm | Welch t-test, unit not stated; regressions pool agent-rounds (pp.7, 10) | Run-level Welch test; regressions on period pairs with firm-run fixed effects (pp.12, 18-19) | Auctions within a trial, it appears; Mann-Whitney (pp.5, 20) | Bootstrap intervals, no test (p.5) |
| No-history control | Matched one-shot, same seed and costs | None | None in the duopoly (monopoly memory ablation only, p.44) | None | None |
| Deviation or placebo test | None yet (planned) | None | None; text "implantation" instead (pp.16-17) | None | None |
| Declared in advance | Yes, in the repo before the run | Not stated | Not stated | Not stated | Not stated |

### 3b. Learning-algorithm studies

| | Calvano 2020 | Banchio & Skrzypacz 2022 | Heo 2025 | Heo 2024 |
|---|---|---|---|---|
| Format | Repeated price-setting, logit demand (p.3273) | First-price and second-price auctions, highest bid wins (p.6) | Lowest bid; also second-lowest and mean-bid rules (pp.6-7) | Lowest markup wins (p.4) |
| Agents | 2; 3 and 4 in robustness | 2; 3 in an extension | 2; 4 for award rules | 2 to 5 (p.7) |
| Cost or value | Fixed marginal cost 1 | Fixed common value 1 (p.6) | Common estimate; cost drawn after the bid (p.3) | Same (pp.4-6) |
| Agent | Tabular Q-learning, memory of 1 period | Stateless tabular Q-learning | Tabular Q and DQN | Tabular Q, memory of 1 |
| Horizon | To convergence, about 850,000 periods at the middle of the parameter grid (p.3276) | 1,000,000 periods (p.10) | 700,000 steps (tabular), 5,000 (DQN) | About 5,000 episodes (p.7) |
| Benchmark | Static Nash and monopoly, computed (p.3274) | Static Nash, the top grid bid (p.7) | Lines at the grid ends, not derived | Human average markup 0.943 (p.6) |
| Measure | Profit gain Δ, 0 to 1 (p.3277) | Revenue against static Nash | Share reaching the cap | Final markup |
| Sessions | 1,000 per cell | 1,000 per cell; 500 or fewer for some figures | 100 per condition | Not stated |
| Test | None; means and SDs | None | None | None |
| Controls | Memoryless arm; discount factor to 0; forced deviation; best-response check; rematching (pp.3278-85, 3293-94) | Payment-rule family; initialisation; exploration; synchronous updating (pp.12-18) | Re-pairing converged agents (pp.6-7) | Hyperparameter sweep |

### 3c. Human studies

| | Sherstyuk 1999 | Davis & Wilson 2002 |
|---|---|---|
| Format | Ascending oral auction against sealed bid; 3 buyers, 2 units (pp.61-63) | Sealed posted offers; 4 sellers, buyer wants 4 units (pp.215, 219) |
| Cost or value | Common known value 100 (pp.61-63) | Identical cost schedules in the set-cost design, not disclosed to sellers; seller-specific costs in the endogenous-cost design (pp.215-219) |
| Feedback | All bids posted after each period (p.63) | All bid prices announced (pp.219-220) |
| Horizon | 15 to 21 periods, end not announced | 40 periods, end not announced |
| Communication | None | Face to face, all sellers, every fourth period; costs may not be discussed (p.220) |
| Benchmark | All bid 100; collusive price 5 | Competitive price P_c; monopoly price 65 cents above it |
| Measure | Mean price; efficiency index 0 to 1 (p.64) | Price minus P_c; index M, 0 to 1 and unclipped (p.223) |
| Sessions | 4 per treatment | 4 per cell |
| Unit and test | Session; permutation test | Session mean per 10 periods; Mann-Whitney |

## 4. Results side by side

| Paper | Level reached with no communication | Scale | What moves it |
|---|---|---|---|
| **Mine** | DeepSeek: index −0.05 with history, −0.03 without. GPT-6 Luna: +0.19 with history, −0.16 without (the one-shot figure is pulled down by calls with no hidden thinking) | 0 = Bayes-Nash price, 1 = reserve | The history; the cost sequence (the per-seed effect has a rank correlation of 0.81 across the two models) |
| Heo 2026 | 1.001 under the win-seeking sentence, 1.107 under the profit-seeking one, 1.040 with both, 1.018 for a mixed pair, as multiples of cost (Table 2, p.7; p.12) | No ceiling stated | One prompt sentence |
| Fish et al. | Above static Nash under both prompts; under P2 mean price 1.689, about halfway between Nash 1.47 and monopoly 1.92 *(inference on the scaling)*; 1.685 with a discounting instruction (pp.12, 36) | Nash and monopoly lines | Prompt prefix |
| Fish et al., A.6 | Under one sentence bids "well below" value, although bidders are shown the bid that would have won; under the other about full value (pp.38-39) | Value | Prompt sentence |
| Tolety | GPT-4.1-mini: $12.40 at 2 bidders against $10.28 to $10.29 at 5 to 7 (Table 4, p.19) | $10 reservation, $13.75 maximum | Number of bidders; model |
| Agrawal | Without messages 87.71; with messages 90.52; intervals overlap (Table 1, p.5) | Asserted benchmark 90 | Urgency message (+5.7); oversight (−4.3) |
| Calvano | Δ = 0.85 in the representative case; 0.64 and 0.56 with 3 and 4 firms (pp.3277, 3288) | Profit, Nash to monopoly | Memory; patience |
| Banchio & Skrzypacz | First-price revenue 0.24 against a Nash of 0.95; second-price 0.95 (p.10) | Value 1 | Payment rule; feedback |
| Heo 2025 | Both learners at the cap of 1.2 with two agents; "slightly below, yet close to" it with four under the lowest-bid rule (pp.7-8) | Grid 0.7 to 1.2 | Award rule changes speed and stability |
| Heo 2024 | 1.198 under a profit reward; 1.05 under a win-count reward (p.8) | Human average 0.943 | Objective; number of bidders |
| Sherstyuk | Sealed bid: session means 40.3, 50.9, 78.2, 88.7 against a competitive 100, where low is collusive (p.65) | 5 to 100 | Auction format |
| Davis & Wilson | Without talk: within about 5 cents of P_c (set-cost design); M never above 0.08. With talk: 46.3 and 60.0 cents above P_c in the last 10 periods, of a possible 65 (45.3 and 52.5 above the no-talk sessions) (Tables 2-3; p.223) | P_c to monopoly | Talk; time |

**These levels cannot be compared across papers.** They use different games, different benchmarks, and price or profit
scales. In particular, do not set +0.19 beside Calvano's 0.85: that is a profit index after about a million periods
for Q-learners with fixed costs.

**The one like-for-like number: how much a bid follows the other firm's previous bid.**

| Study | Coefficient on the other firm's previous price or bid | Specification |
|---|---|---|
| Heo 2026 | 0.615 (win-seeking prompt), 0.954 (profit-seeking) | Pooled over runs and rounds; no cost term, no run effects (Table 5, p.10) |
| Fish et al. | 0.103 (P1), 0.022 (P2) | Own lag included; firm-run fixed effects (Table 1, p.19) |
| **Mine** | 0.10 (GPT-6 Luna), 0.06 (DeepSeek) with history; 0.01 and 0.00 in the one-shot controls | Own cost and own lag included; firm fixed effects; one value per session, then the mean |

With a cost control and a control arm, the coefficient here is small, close to Fish et al.'s and far from Heo's pooled
value. The stronger sign of tracking in this study is in the reasoning: the judge finds a bid set just under an
earlier displayed bid in 81% of sampled GPT-6 Luna calls and 51% of DeepSeek's.

## 5. Does prior work already report my findings?

| Finding | Heo 2026 | Fish | Tolety | Agrawal | Calvano | Banchio | Heo 2025 | Heo 2024 | Sherstyuk | Davis & Wilson |
|---|---|---|---|---|---|---|---|---|---|---|
| (a) Prices above the competitive level without communication | Yes, under a profit-seeking sentence | Yes | Yes, small groups | No | Yes | Yes | Yes | Yes, against a human average | Yes in the oral auction; one of four sealed-bid sessions | Mostly no |
| (b) Dependence on early rounds or the cost sequence | Partly: asserted, not tested (p.12) | No | No | Partly: the first round is seeded by the experimenters because it shapes the session (p.2) | Partly: "history dependent" (p.3292) | No | No | No | Partly, not analysed | No |
| (c) Prices tracking or undercutting displayed prices | Yes: lagged-bid regression; cluster labels (pp.9-10) | Yes: lagged-price regression; implanted undercutting plans (pp.19-21) | Partly: anecdotes (pp.16-17) | No analysis | Partly: the other firm cuts its price after a forced cut (p.3285) | Partly: the one-increment step is their mechanism | Partly | Partly | Partly, oral auction only | No |
| (d) A test separating tracking or anchoring from a reward and punishment scheme | No | No | No | No | Yes, for Q-learners: forced deviation, memoryless and impatient arms, best-response check (pp.3278-85) | No | No | No | No | No |
| (e) Effect of a channel, private memory or shared notes | No: memory in every arm | Partly: memory ablation in monopoly only | No | Partly: messages, no test reported | No | No | No | No | No | Yes: face-to-face talk |

What follows from the table:

- **Row (a) is taken.** Claim it only with the qualifiers of section 7.
- **Row (b) is new as a measured result.** Others mention it; none has random costs to measure it with.
- **Row (c) is shared, and it is where the readings differ.** Heo and Fish et al. measure it with a regression; this
  study measures it with a regression and with labels on the reasoning.
- **Row (d) is empty for every LLM study, including this one so far.** Calvano et al. fill it for Q-learners. Filling
  it for LLM bidders is the largest contribution available.
- **Row (e):** no study reviewed here has a shared or unintended channel, and none varies private memory in a
  multi-agent market.

## 6. Where each side is stronger

| | Prior work is stronger | This study is stronger |
|---|---|---|
| Sample | Heo 2026: 30 runs per cell. Fish: 21. Heo 2025: 100. Calvano and Banchio: 1,000 | 12 matched pairs per model |
| Horizon | 150 rounds (Heo 2026) and 300 (Fish), with a convergence test in Heo (mean break points at rounds 59 to 79) | 50 rounds, no convergence test |
| Causal levers | Prompt sentence (Heo, Fish); payment rule (Banchio); award rule (Heo 2025); number of bidders (Tolety, Heo 2024); communication, oversight, urgency (Agrawal) | History on or off, so far |
| Mechanism tests | Calvano: forced deviation, best-response check, memoryless arm, rematching. Fish: implanting plan text. Banchio: four agent manipulations | A judge over the reasoning; nothing causal yet |
| Reasoning data | Heo and Fish: a written strategy every round, clustered and linked to bids | Hidden thinking and a 2 to 3 sentence field |
| Benchmark | With a common known cost, anything above cost is above the competitive level; this needs only the one-shot Nash prediction | A closed-form benchmark for private costs, giving a scale with a defined zero and one; needs risk-neutral equilibrium bidding as the reference |
| Control | | A matched one-shot control on the same seed and costs, which none of the four LLM studies has |
| Inference | | Session as unit; hypotheses, tests and sample size committed before the run; exact test; correction over models |
| Prompt | | A one-line role and one goal line; each of the four LLM studies carries a steering sentence, a persona or an exploration instruction |
| Baseline purity | | No private memory in the baseline; in Heo, Fish et al. and Agrawal et al. it is in every arm |
| Cost structure | Closer to real tenders (shared cost, small noise) | Private redrawn costs make the history uninformative at equilibrium, so any response to it is a clear departure |

### Weaknesses of the prior papers that are fair to state

| Paper | Weakness | Source |
|---|---|---|
| Heo 2026 | The lagged-bid regression pools agent-rounds with no run effects, and is significant even where prices sit at cost (β = 0.615 under the win-seeking prompt), so it cannot separate collusion from competition. The paper accepts that high stable prices "do not necessarily indicate algorithmic collusion" (p.7) and hedges ("may be consistent with", p.10), but also states that "agents continued to exhibit reward–punishment behavior across all conditions" (p.12) | pp.7, 10, 12; the pooling critique is *(inference)* |
| Heo 2026 | No benchmark, ceiling or normalised index; no control without history; no arm without a steering sentence | whole paper; p.4 |
| Heo 2026 | Transparency is proposed as the policy lever but never varied | pp.12-13 |
| Fish et al. | No control without history in the duopoly; no forced deviation (v6; not found in v1 or v5). The lagged-price regression has firm-run fixed effects and robust errors but is not clustered by run, and the implantation test counts agent-periods | pp.13, 17-19 |
| Fish et al. | Defines algorithmic collusion by outcome, so the mechanism is not required | p.2, fn.4 |
| Tolety | Runs per cell not stated; the tests appear to treat auctions inside one trial as independent. Table 4 does not fit "collapses at 5 or more" for GPT-4o-mini (11.06 at six bidders against 10.25 at five). The paper concedes low power | pp.5-6, 19-20; the independence point is *(inference)* |
| Agrawal | No test is reported; the trade-price intervals of the message and no-message arms overlap ("significantly" in the text refers to coordination scores). The $90 benchmark is asserted. The judge's repeatability is tested, its validity is not, as the paper says | pp.3, 5, 19 |
| Heo 2024, 2025 | As printed, the cost model draws the winner's margin independently of its markup, which leaves unclear why high bids are rewarded; no tie rule is stated although the end point is a tie at the cap | 2025 pp.3-4; 2024 p.5; the conflict is *(inference)* |
| Heo 2024 | "Collusion" is judged against a human average markup, not an equilibrium | pp.6, 9 |
| Calvano | No inferential statistics. Convergence takes about a million periods, though gains begin early (p.3293). Half the sessions are an exact equilibrium on path; the rest are close to one (loss 0.2%) | pp.3276-79, 3292-93 |
| Banchio & Skrzypacz | Fixed common values only; the feedback result changes the learner's update rule, it does not display information to an agent with memory, which the authors flag as untested | pp.6, 17, 23 |
| Sherstyuk | The abstract says sealed-bid auctions converged to the competitive outcome; two of four did | pp.59, 64 |
| Davis & Wilson | Four sessions per cell. The talk arm also differs from its control in tie and disclosure rules; the authors justify this (p.221) and find the rules unimportant (pp.225-226) | pp.220-226 |

## 7. How to frame the hypothesis and the claim

**The definition to adopt.** Calvano et al. (p.3269), quoting Harrington: "collusion is not simply a synonym of high
prices but crucially involves 'a reward-punishment scheme designed to provide the incentives for firms to consistently
price above the competitive level'". By that definition the baseline result is not collusion, and the paper should
say so first. Fish et al. use the looser outcome definition; name both and state which one is used.

| Do claim | Do not claim |
|---|---|
| With private costs redrawn each round, a closed-form benchmark and a matched no-history control, GPT-6 Luna prices above the competitive level when shown the bidding history, and DeepSeek V4.1 Flash does not | That this is the first evidence of LLM bidders pricing above the competitive level without communication (Heo 2026, Fish et al. and Tolety precede it) |
| The effect appears under a one-line role and one goal line; in Heo (2026) the high price needed a profit-seeking sentence | That the models collude, tacitly or otherwise |
| The effect of history depends on the cost sequence, and the gap opens in the first five rounds | That the cost-sequence result is confirmatory: it was found after the run |
| The sampled reasoning shows undercutting of displayed bids and no adopted coordination (coordination is considered in 2% of sampled GPT-6 Luna calls and 9% of DeepSeek's), by an LLM judge whose labels are not yet hand-checked | That the judge shows the absence of coordination; it shows none was written |
| The pattern others read as reward and punishment has a second reading, tracking displayed bids, which no study has tested against the first | That prior work is wrong; say the alternative is untested there and here |
| Any channel effect must be measured against this baseline on the same seeds | That a high price in a channel arm is evidence of collusion by itself |

**How undercutting can go with high prices (a hypothesis, not a result).** In Fish et al. the prompt that produces
more undercutting gives the lower prices, though still above static Nash. In Banchio and Skrzypacz, outbidding by one
increment is what keeps first-price bids away from the competitive level, and it leads to competitive bids only when
the learner is also given the bid that would have won. Here undercutting goes with prices that stay high. A possible
reason is the cost structure. With a fixed common cost, the other firm's last price is close to the price to beat next
round. With costs redrawn each round, the last displayed bid carries no information about the other firm's next cost,
only about how it marks up, so undercutting it by a cent tracks the old price level and not the new costs. This is
untested; the placebo-history and narrow-cost arms bear on it. Cite Banchio and Skrzypacz as a precedent for a
non-competitive outcome with no punishment scheme, not as a contrast.

**Suggested wording of the baseline claim.** "In a repeated first-price procurement auction with private costs redrawn
each round, GPT-6 Luna bidders shown the full bidding history price above the Bayes-Nash level (index +0.19, against
−0.03 to −0.05 for DeepSeek V4.1 Flash), with no communication, no steering instruction and no adopted coordination in
their sampled reasoning. Their bids respond less to their own cost than in the one-shot control (slope 0.37 against
0.57), and their reasoning sets the bid just under an earlier displayed bid in 81% of sampled calls. We read this as
anchoring on the displayed history; we do not show a reward and punishment scheme, and so do not call it collusion."

**The fallback claim, which stands even if every channel arm is null.** "Shown the bidding history, both models move
away from the Bayes-Nash bid, although costs are redrawn independently each round, so the history carries no
information at equilibrium. The mean gap between a bid and the Bayes-Nash bid rises on every one of 12 cost sequences
for both models (from 0.6 to 6.2 bid units for DeepSeek V4.1 Flash; from 0.1 to 10.2 for GPT-6 Luna, counting calls
that thought)." This is exploratory as it stands, because the gap measure was chosen after the run; it becomes
confirmatory if declared before the 150-round baseline. None of the four LLM studies can make this claim: with a fixed
common cost the other firm's last price is informative, so responding to it is not a departure from equilibrium.

**On intent.** Do not write that the models "aim" for high prices. Before any feedback, a model that thinks bids the
Bayes-Nash bid almost exactly, in a one-shot round and in round 1 of a session. The high bids appear only after
feedback, and only on cost sequences that put high bids on screen early (`PLANNING_NEW.md`, section 1.2). Tolety reads
similar behaviour as agents having "developed a theory of mind about their competitors" (p.6); the data here do not
need that.

**Hypotheses for the channel study** (drafts; `PLANNING_NEW.md` section 6 has the table): private notes change the
price level against no channel (H3); sharing the notes raises it against private notes (H4); direct messages raise it
against no channel (H5); with a replayed rival, bids follow the replayed price level (H6). Each is two-sided, per
model, paired by seed.

## 8. What could still be improved

Ranked by how much a reviewer who knows this literature would care.

| # | Gap | Who does it better | What to do | In the plan? |
|---|---|---|---|---|
| 1 | No test separating anchoring from a reward and punishment scheme | Calvano (forced deviation, for Q-learners); none of the four LLM studies | Placebo or replayed history; a forced undercut with a twin session on the same seed | Placebo yes (S1); forced undercut is a candidate |
| 2 | 50 rounds, no convergence test | Heo 2026 (150 rounds, break points); Fish (300) | Rerun the no-channel arm at 100 rounds; report the index by 10-round block; test for a trend | Yes (B0 long) |
| 3 | 12 seeds, with a large cost-sequence effect | Heo 2026 (30); Fish (21) | A second block of 12 seeds, declared separately; repeats of one seed to split cost sequence from sampling noise | Open decision |
| 4 | GPT-6 Luna's one-shot arm mixes "no history" with "often no thinking" | | Report levels, compare history arms with history arms, and show bids split by whether the call thought | Yes |
| 5 | Private memory never isolated | Fish (monopoly only) | The private-notes arm | Yes (M1) |
| 6 | Judge labels unvalidated | Agrawal reports judge repeatability; nobody reports human agreement | Hand-code a sample; report agreement; judge reasoning and channel text separately | Step 1 of the order of work |
| 7 | Only price is reported | Heo, Fish, Calvano, Davis & Wilson report profit | Add joint profit against the equilibrium profit; report the lagged-bid coefficient (0.10 and 0.06, against 0.01 and 0.00 one-shot) beside Heo's and Fish et al.'s | Yes (`PLANNING_NEW.md` 2.1) |
| 8 | The best-response question: are the high bids a mistake or a best reply to the other firm's actual bids | Calvano (Q-loss check) | Compute each firm's best reply to the other firm's empirical bid distribution per session | Yes (`PLANNING_NEW.md` 2.1) |
| 9 | Two firms only, same model on both sides | Tolety (1 to 7); Heo 2024 (2 to 5); Agrawal (mixed models); Heo 2026 (mixed prompts) | A three-firm cell; a mixed pair | Candidates |
| 10 | Wide cost range is unrealistic and seeds the effect | Heo 2024 and 2025 (markup range calibrated to tender data) | The narrow-cost arm; state the limit | Yes (S2) |
| 11 | No bridge to the nearest prior result | | One cell with Heo's common known cost, this prompt and these models | Candidate |
| 12 | The two models are not sampled alike (temperature not accepted by GPT-6 Luna's endpoint) | | Cannot be fixed; state it with every result | Stated |

## 9. Sources and how much was read

| Paper | Source read | Extent |
|---|---|---|
| Heo, Ahn & Park (2026), J. Manage. Eng. 42(2): 04025063 | `heo_tacit_collusion.pdf` | All 15 pages as text; pages 4-7 and 11 also as images |
| Heo, Park & Ahn (2025), Proc. 42nd ISARC, pp.1332-1339 (precursor of the above: 3 runs per condition, no regression) | iaarc.org | All 8 pages as text |
| Fish, Gonczarowski & Shorrer, arXiv 2404.00806 v6 (31 Aug 2026) | arXiv PDF | Main text and appendices A-H; appendix I sampled; figures not read |
| Tolety (2025), arXiv 2511.21802 v1, NeurIPS 2025 workshop | arXiv PDF | All 22 pages as text |
| Agrawal et al. (2025), arXiv 2507.01413 v1, ICML 2025 workshop | arXiv PDF | All 19 pages as text; figures not read |
| Calvano, Calzolari, Denicolò & Pastorello (2020), AER 110(10): 3267-3297 | Archived copy of the published PDF | All 31 pages as text; online appendix not read |
| Banchio & Skrzypacz (2022), arXiv 2202.05947 v1 | arXiv PDF | All 30 pages as text; figures not read |
| Heo, Ahn, Oh & Park (2025), J. Manage. Eng. 41(5): 04025045 | `heo_rl_collusion_2025.pdf` | All 13 pages as images |
| Heo, Park & Ahn (2024), J. Comput. Civ. Eng. 38(4): 04024016 | `heo_potential_ai_alg_collusion.pdf` | All 12 pages as images |
| Sherstyuk (1999), Exp. Econ. 2: 59-75 | `Sherstyuk_Collusion_Without_Conspiracy.pdf` | All 17 pages as images |
| Davis & Wilson (2002), Econ. Inquiry 40(2): 213-230 | `Davis_Collusion_in_procurement.pdf` | All 18 pages as images |

**Re-check by the reviewing agent.** Heo (2026) and this study's result files were verified in full. The other nine
papers were verified in part: the pages behind each quotation, number and table cell that was checked, not every page.
The ISARC precursor and the figures of the text-only sources were not re-checked. Three items remain unverified:
whether any of the four LLM studies was pre-registered (none says so in the parts read), whether Heo (2024, 2025)
state a tie rule on their last pages, and whether version 2 of Fish et al. contains a deviation test.

"The four LLM studies" means Heo (2026), Fish et al., Tolety and Agrawal et al. Other LLM market studies exist and were
not read (for example the follow-up Fish et al. cite, and the works Agrawal et al. cite), so no statement here is about
the whole literature.

Not covered: Puzzello (2008), Athey et al. and Comanor and Schankerman, which bear on the shelved tie-break study;
Lotfi et al. (2026) and Mazur (2025), which the earlier literature report lists with only an abstract or a blog post
read.
