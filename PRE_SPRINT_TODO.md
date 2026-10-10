# To do before the meeting on Tuesday 13 October 2026

Written on Saturday 10 October, 23:45. Everything here concerns the no-channel side of the study, so none of it
depends on what the team decides about the channel arms. The plan it serves is `PLANNING_NEW.md`; the comparison with
prior work is `DIFFERENCE.md`. The sprint is 23 to 25 October.

## Where things stand

- `main` is at `0185801`; the working tree is clean except for three untracked files:
  `PLANNING_NEW.md`, `DIFFERENCE.md` and this file.
- The declared baseline `baseline_no_channel` is run, analysed, judged and committed. Results:
  `results/baseline_no_channel/`.
- About $5.30 is left on the OpenRouter key. New credit takes 2 to 3 hours after it is requested.
- `PLANNING.md` and the project paragraph of `CLAUDE.md` still describe the shelved tie-break study.

## Order

| # | Task | Cost | Blocked by |
|---|---|---|---|
| 1 | Draft PR with `PLANNING_NEW.md` and `DIFFERENCE.md` | Free | Nothing |
| 2 | Request credit (ask for $50) | | Nothing |
| 3 | Hand-check the judge | Free | Nothing |
| 4 | Free analysis on the baseline: joint profit, best-response check | Free | Nothing |
| 5 | Grid 1 and grid 5 | about $7 | Credit |
| 6 | Narrow costs, no-channel cell | about $3 | Credit; one design decision (below) |
| 7 | No-channel baseline at 150 rounds | about $13 | Credit |
| 8 | Replay-rival placebo: build, declare, run | about $3 | Build; credit |
| 9 | Bring the open decisions to the meeting | | |

Total for 5 to 8: about $26.

## 1. Draft PR

- Branch, for example `plan-channel-study`; add `PLANNING_NEW.md`, `DIFFERENCE.md` and this file; open as a draft.
- Do not merge before the meeting. `PLANNING_NEW.md` is a proposal with open decisions (its section 9).
- Send the link to the team so they can read it before Tuesday.

## 2. Request credit

Ask for $50. The plan needs about $26 before the meeting (tasks 5 to 8), about $30 for the long channel arms at 100
rounds during the sprint, and something for retries and judge calls.

## 3. Hand-check the judge (free)

The judge's labels have never been checked by a person, and three findings rest on them: no adopted coordination,
81% and 51% undercutting, 71% and 15% anchoring on a past price.

- File: `results/baseline_no_channel/trace_judge_check.csv`. 30 random judged calls with the judge's quote per label.
- For each row, open the full trace (the session's `calls.jsonl` under `logs/baseline_no_channel/`, fields `thinking`
  and `reasoning`) and mark each of the nine labels agree or disagree.
- The random 30 will hold few positives of the rare labels. Draw a second sample by label from
  `results/baseline_no_channel/trace_judge.csv`: 15 calls labelled `undercuts_rival_bid`, 15 labelled
  `anchors_on_past_price`, 15 with neither, and every call labelled `considers_coordination` or `copies_rival_bid`
  (about 30 in the history arm).
- Record: agreement per label, and for the misses whether the judge over-claimed or missed.
- If `undercuts_rival_bid` and `anchors_on_past_price` turn out to be the same thing in practice, merge them in a
  rubric v4 and re-judge (the cache makes unchanged labels free only if the rubric version is unchanged, so a v4
  costs about $1.20 again).
- Rubric definitions: `src/bidrig/analysis/trace_judge.py`, `LABEL_DEFINITIONS`.

## 4. Free analysis on the baseline

Both are exploratory and both answer a point raised by the comparison with prior work (`DIFFERENCE.md`, section 8).
How to read each outcome, with a worked example and the limits: `PLANNING_NEW.md`, section 2.1.

- **Joint profit.** Per session: the two firms' total profit against the total they would earn if both bid the
  Bayes-Nash bid on the same costs. A price above the benchmark is only a "gain" if profit is above it too. The data
  are in `bids.jsonl` (`profit`, `cost`, `bne_bid`, `is_min_cost`).
- **Best-response check.** For each firm and round in a history session, is the bid close to the best reply to the
  other firm's actual bids in that session? If GPT-6 Luna's high bids are a best reply to an opponent who also bids
  high, the behaviour is self-confirming, not a mistake. This is the analogue of the check in Calvano et al. (2020).
- **Report the lagged-bid coefficient.** Already in `session_metrics.csv` (`rival_lag_coef`): 0.10 for GPT-6 Luna and
  0.06 for DeepSeek with history, 0.01 and 0.00 one-shot. Put it in the results table beside the index.

## 5. Grid 1 and grid 5 (mechanism check, exploratory)

**Question.** If prices stay high because each undercut is one cent, a coarser grid should bring them down faster.

- **Design.** The baseline config with only `auction.bid_increment` changed to 1.0 and to 5.0. Both models, history
  arm and one-shot control, seeds 996000 to 996011, 50 rounds. One config per grid, as in the rotation screen
  (`configs/rotation_screen_grid1.yaml` is a model); one run id for both.
- **Compared with** the history arm of `baseline_no_channel` on the same seeds.
- **Declare** in `configs/analysis.yaml` that this run is exploratory, with the measures to be reported: index and
  markup ratio by 10-round block, tie rate, share of bids at multiples of 5. Commit before running.
- **What the old data showed** (DeepSeek, three firms, 25 rounds, 5 sessions, different seeds): coarser grids fell
  faster in rounds 2 to 15 and ended at the same level. That is weak, and there is no GPT-6 Luna run on a coarse grid.
- **Watch for:** ties and round-number bids. Report them; do not read a tie as coordination.

## 6. Narrow costs, no-channel cell

**Question.** Is the no-channel result an artefact of costs on 0 to 100, where a firm that draws 90 must bid above 90
and so puts a high number on screen by chance?

**Decide first which "narrow" is meant.** The harness offers two different things, and `PLANNING_NEW.md` currently
names only the second:

| Option | What changes | Benchmark | What it tests |
|---|---|---|---|
| A. Narrow i.i.d. range, for example costs on 40 to 60 (`auction.cost_low`, `auction.cost_high`) | Costs stay private and independent, but never extreme | The closed form still holds: b(c) = c + (cost_high − c)/n | Whether extreme displayed bids are needed for the effect. This is the direct test of the artefact |
| B. Common-cost draw (`auction.cost_spread: 5`, prompt `prompts/bidder_system_common.md`) | The two firms' costs are within 10 of each other in a round, but the round's level still ranges over 5 to 95 | Numeric (`bne.CommonCostBenchmark`) | Closer to real tenders. Does not remove high numbers from the screen, and the other firm's last bid now says more about the market |

Option A answers the question as asked. Option B is a realism arm and changes two things at once. Recommended: run A
now; keep B for later.

- **Design (A).** Baseline config with the cost range changed; both models; history and one-shot; same seeds; 50
  rounds. The reserve price stays 100, so the index keeps its scale; state that the benchmark price is now far below
  the reserve.
- **Check before running:** that `BneBenchmark` is built from `cost_low` and `cost_high` (it is passed both), that the
  prompt states the new range (the template uses `{cost_low}` and `{cost_high}`), and that `check_logs.py` passes on a
  3-round trial.
- **Declare** H7 before running: under narrow costs the no-channel history arm is at the competitive level (index
  inside ±0.05, as H2), per model.

## 7. No-channel baseline at 150 rounds

**Questions.** Does GPT-6 Luna's price above the benchmark persist, grow or decay after round 50? Does DeepSeek stay
at the competitive level? Heo's GPT-4o sessions converge at rounds 59 to 79 on average.

- **Design.** The baseline config with `n_rounds: 150`. Both models, history arm and one-shot control, same seeds.
  New run id (for example `baseline_no_channel_long`).
- **Why 150 now.** The round count is not announced, so the first 100 rounds of a 150-round session are a valid
  100-round session. One run serves either length for the channel arms, and the result informs that choice.
- **Sanity check to report.** Rounds 1 to 50 should reproduce `baseline_no_channel` up to sampling noise (same seeds,
  same costs, same prompts). If they do not, find out why before using either run.
- **Declare** before running: the index by 10-round block; a test of trend in the paired difference between rounds 1
  to 50 and rounds 101 to 150, per model; everything else exploratory.
- **Also declare the fallback claim here (H8 in `PLANNING_NEW.md`):** the mean absolute gap between bid and Bayes-Nash
  bid per session, history minus one-shot, paired by seed, per model, exact sign-flip test. On the 50-round baseline
  it was positive on 12 of 12 seeds for both models (5.6 and 6.7 bid units), but the measure was chosen after seeing
  that run, so only this new run can confirm it. It needs adding to `analysis/metrics.py` first (one line: the mean of
  |bid − bne_bid| over valid bids).
- **Cost.** About $9 for the history arms (input cost grows with the square of the length) and about $4 for the
  one-shot controls. Set `budget.max_cost_usd` from the dry run.
- **Time.** About 75 to 90 minutes for the DeepSeek sessions on DeepInfra; all sessions run in parallel.

## 8. Replay-rival placebo

**Question.** Do a firm's bids follow the numbers on screen when nobody is answering it?

- **Design.** One LLM firm against a scripted firm that replays, unchanged, the bids of a recorded
  `baseline_no_channel` session from another seed. Two versions on the same seeds and costs for the LLM firm: a replay
  from a high-price session (seeds 996002 to 996004 for GPT-6 Luna) and from a low-price one (996001, 996010).
- **Prediction.** Anchoring: the LLM firm's markup follows the replayed level, high in one and low in the other.
  Coordination predicts nothing, since nothing the firm does is answered.
- **Build.**
  - A scripted bidder that replays a bid list (the harness has scripted bidders in `src/bidrig/bidders.py`).
  - A mixed lineup of one LLM firm and one scripted firm.
  - The replayed firm's costs: the history shows bids, not costs, so the LLM firm cannot tell. Record in the log that
    the scripted firm's cost and benchmark fields are not meaningful, and compute the LLM firm's measures from its own
    rows only.
  - The index needs care: the winning bid is sometimes the replayed one. Use the LLM firm's markup ratio as the
    outcome, not the session index.
- **Declare** H6 before running: markup ratio under the high replay minus under the low replay, paired by seed, per
  model, exact sign-flip test.
- **Alternative design**, if the team prefers it: two LLM firms, with the displayed history described as coming from an
  earlier unrelated market. Weaker, because it changes the prompt.

## 9. For the meeting

Decisions that are the team's, listed in `PLANNING_NEW.md` section 9:

- Session length for the channel arms (100 or 150 rounds), with the result of task 7 in hand.
- The channel harness: whether to adopt the collaborator's workspace implementation, and how private notes, the shared
  workspace and direct messages become one session setting.
- Whether firms may state their costs in a note or a message.
- Whether entries in the shared workspace are labelled with their author.
- The placebo design, if task 8 has not already run.
- A second block of 12 seeds.
- The four candidates outside the ranking: forced deviation, mixed pair, three firms, a bridging cell with Heo's cost
  setup.

Also to report: the two files' main points. Prices above the competitive level without communication are not new for
LLM bidders; the control, the benchmark and the neutral prompt are. The baseline result is not collusion by the
standard definition. Three prior LLM studies give agents a private memory in every arm, so the private-notes arm is
their baseline.

## How to run things (so it does not have to be rediscovered)

```sh
# Estimate first; the config's llm.host puts deepseek on DeepInfra and gpt-luna on OpenAI without a flag
uv run python scripts/run_experiment.py configs/<name>.yaml --dry-run

# Run (resumes if interrupted: completed sessions are skipped)
uv run python scripts/run_experiment.py configs/<name>.yaml --yes

# Always in this order afterwards
uv run python scripts/check_logs.py logs/<run_id> --expect-cap 4000
uv run python scripts/analyze.py logs/<run_id> --plan baseline_no_channel   # --plan marks the tables exploratory
uv run python scripts/judge_traces.py logs/<run_id> --sample 20             # prints the plan; add --yes to send
uv run python scripts/export_site.py --no-thinking --no-prompts             # all runs, for the viewer
```

- **Copy the baseline config** (`configs/baseline_no_channel.yaml`) for every new run and change one thing. Keep
  `llm.host: deepseek=backup`, the 4,000-token cap, `reasoning_overrides` (DeepSeek low, GPT-6 Luna high) and
  `base_seed: 996000`.
- **Run from a clean checkout of the commit that holds the declaration**, so each `session.json` records a commit made
  before the data. A temporary `git worktree` at that commit, with `--log-dir` pointing at this repo's `logs/`, lets
  the working tree change while the run goes on.
- **Logs are written when a session ends**, so a long run shows nothing for the first half hour or more. That is
  normal.
- **Do not move DeepSeek to a faster host.** Seven faster hosts cut off 19% to 44% of replies at the cap; DeepInfra
  cut off none in the test and about 1% to 2% in the baseline.
- **GPT-6 Luna is not sent a temperature** (its endpoint rejects it). State this with every result.
- **Declare before running**, in `configs/analysis.yaml`, in a commit of its own. Do not add sessions to a declared
  run after seeing a result.

## Costs used above

Measured in `baseline_no_channel`, per 12 sessions of 50 rounds:

| | History | One-shot |
|---|---|---|
| DeepSeek (DeepInfra) | $1.31 | $1.00 |
| GPT-6 Luna (OpenAI) | $0.73 | $0.30 |

History cost grows with the square of the session length; one-shot cost grows in proportion. The judge costs about
$1.20 per 960 traces.
