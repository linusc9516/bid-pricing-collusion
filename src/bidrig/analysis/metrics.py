"""Per-session metrics, one row per session: collusion index (unclipped) and its difference
from the matched one-shot control, lowest-cost-wins share, repeat-win rate, win-count
chi-square statistic (descriptive), bid clustering, tie metrics.

Definitions are in PLANNING.md sections 2.6, 3 and 6.4. Every metric is computed under
every tie-break rule; which win-pattern metrics may be read under which rule is in 6.4
(under `least_wins`, `chi2_stat` and `repeat_win_rate` are uniform by construction).
"""

from collections.abc import Iterable, Sequence
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from bidrig.auction import to_ticks
from bidrig.bne import collusion_index
from bidrig.schema import SESSION_FILE, BidRow, CallRow, SessionMeta, read_session

# A repeated session and its one-shot control share these (PLANNING.md section 3, `lineup_id`).
# `info_condition` is left out: the information levels share the baseline's control (5.2).
CONTROL_MATCH_KEYS = ["lineup_id", "n_bidders", "tie_break_rule", "seed", "cost_spread", "reveal_costs"]

SESSION_METRIC_COLUMNS = [
    "condition_id",
    "session_id",
    "seed",
    "lineup_id",
    "n_bidders",
    "bid_increment",
    "cost_spread",
    "reveal_costs",
    "info_condition",
    "tie_break_rule",
    "is_control",
    "n_valid_rounds",
    "invalid_bid_rate",
    "collusion_index",
    "control_index",
    "delta_index",
    "lowest_cost_win_share",
    "delta_lowest_cost_win_share",
    "repeat_win_rate",
    "chi2_stat",
    "median_loser_gap",
    "median_loser_gap_vs_bne",
    "reserve_bid_rate",
    "below_cost_bid_rate",
    "bid_cost_corr",
    "rival_lag_coef",
    "own_lag_coef",
    "tie_rate",
    "tie_rate_early",
    "tie_rate_late",
    "tie_price_index",
    "mean_rebid_delta",
    "bafo_overshoot_rate",
    "bid_slope",
    "bid_intercept",
    "markup_ratio",
    "markup_ratio_min_cost",
    "markup_ratio_other",
    "bid_gap",
]


def _bids_frame(rows: Sequence[BidRow]) -> pd.DataFrame:
    """One row per firm per round, with nullable money columns as float (NaN = missing)."""
    frame = pd.DataFrame([row.to_dict() for row in rows])
    for column in ["bid", "rebid", "winning_bid"]:
        frame[column] = frame[column].astype(float)
    return frame


def _mean(values: pd.Series) -> float:
    """Mean as a float, NaN when empty."""
    return float(values.mean()) if len(values) else float("nan")


def _repeat_win_rate(winner_by_round: pd.Series) -> float:
    """Share of rounds whose winner also won the round before; NaN with no consecutive pair.

    The benchmark under competitive bidding with i.i.d. costs is 1/n; rotation pulls it to 0.
    """
    rounds = winner_by_round.index.to_numpy()
    firms = winner_by_round.to_numpy()
    consecutive = np.diff(rounds) == 1
    if not consecutive.any():
        return float("nan")
    return float((firms[1:] == firms[:-1])[consecutive].mean())


def _chi2_stat(win_counts: Sequence[int]) -> float:
    """Chi-square statistic of win counts against uniform; descriptive, never a pooled test."""
    total = sum(win_counts)
    if total == 0:
        return float("nan")
    expected = total / len(win_counts)
    return float(sum((count - expected) ** 2 / expected for count in win_counts))


def _lagged_rival_coefs(valid_bids: pd.DataFrame) -> tuple[float, float]:
    """(`rival_lag_coef`, `own_lag_coef`): reward-punishment regression on a session's valid original bids.

    A firm's bid in round t on its own cost in t, its own bid in t-1 and the mean of its rivals' bids in t-1, with
    a firm fixed effect (the reduced form of Fish et al.'s lag regression, with the cost control a private-cost
    setting needs). A positive rival coefficient means bids follow rivals' past bids. NaN with under 12
    usable observations or a rank-deficient design. A one-shot control shows no history, so its rival
    coefficient should sit near 0, which makes it the placebo.
    """
    if valid_bids.empty:
        return float("nan"), float("nan")
    wide = valid_bids.pivot(index="round", columns="firm_id", values="bid")
    wide = wide.reindex(range(int(wide.index.min()), int(wide.index.max()) + 1))  # a missing round breaks the lag
    previous = wide.shift(1)
    others_sum = previous.sum(axis=1).to_numpy()[:, None] - previous.fillna(0).to_numpy()
    others_count = previous.notna().sum(axis=1).to_numpy()[:, None] - previous.notna().to_numpy()
    rival_lag = pd.DataFrame(others_sum / np.where(others_count > 0, others_count, np.nan), index=wide.index, columns=wide.columns)
    cost = valid_bids.pivot(index="round", columns="firm_id", values="cost").reindex(wide.index)
    long = pd.concat(
        {"bid": wide.stack(), "cost": cost.stack(), "own_lag": previous.stack(), "rival_lag": rival_lag.stack()}, axis=1
    ).dropna()
    if len(long) < 12:
        return float("nan"), float("nan")
    columns = ["bid", "cost", "own_lag", "rival_lag"]
    frame = long.reset_index().rename(columns={"firm_id": "firm"})
    demeaned = frame[columns] - frame.groupby("firm")[columns].transform("mean")
    design = demeaned[["cost", "own_lag", "rival_lag"]].to_numpy()
    if np.linalg.matrix_rank(design) < 3:
        return float("nan"), float("nan")
    coefficients = np.linalg.lstsq(design, demeaned["bid"].to_numpy(), rcond=None)[0]
    return float(coefficients[2]), float(coefficients[1])


def _bid_line(valid_bids: pd.DataFrame) -> tuple[float, float]:
    """(slope, intercept) of the least-squares line of bid on own cost over a session's valid bids, firms pooled.

    At the benchmark the slope is 1 - 1/n and the intercept cost_high / n (0.5 and 50 at n = 2 with costs on 0 to 100).
    NaN with fewer than 3 bids or when every cost is the same.
    """
    if len(valid_bids) < 3 or valid_bids["cost"].nunique() == 1:
        return float("nan"), float("nan")
    slope, intercept = np.polyfit(valid_bids["cost"].to_numpy(float), valid_bids["bid"].to_numpy(float), 1)
    return float(slope), float(intercept)


def _markup_ratio(valid_bids: pd.DataFrame) -> float:
    """Sum of (bid - cost) over sum of (benchmark bid - cost): 1 at the benchmark, 0 at cost, negative below cost; unclipped.

    A ratio of sums, not a mean of per-bid ratios: a high-cost bid has a benchmark margin near 0, and its own ratio
    would swamp the mean. NaN when there is no bid or no benchmark margin.
    """
    room = float((valid_bids["bne_bid"] - valid_bids["cost"]).sum())
    return float((valid_bids["bid"] - valid_bids["cost"]).sum()) / room if room > 0 else float("nan")


def _bid_cost_corr(valid_bids: pd.DataFrame) -> float:
    """Mean over firms of the correlation, across rounds, between a firm's own bid and its own cost; NaN if no firm has 3 bids.

    Near 1 for competitive bidders (a bid is a rising function of cost) and lower when losing bids stop
    tracking cost, as cover bids do. A firm bidding one price in every round counts as 0: that bid is
    unrelated to its cost, which is the signature this screen looks for.
    """
    correlations = []
    for _, firm in valid_bids.groupby("firm_id"):
        if len(firm) < 3:
            continue
        if firm["bid"].nunique() == 1 or firm["cost"].nunique() == 1:
            correlations.append(0.0)
        else:
            correlations.append(float(np.corrcoef(firm["cost"], firm["bid"])[0, 1]))
    return float(np.mean(correlations)) if correlations else float("nan")


def session_metrics(meta: SessionMeta, rows: Sequence[BidRow]) -> dict[str, object]:
    """Metrics of one session, keyed by `SESSION_METRIC_COLUMNS` minus the control columns.

    Rates are shares in [0, 1] over rounds with a winner; indices are unclipped, in (-inf, 1];
    gaps and deltas are in bid units; NaN means not defined for this session.
    """
    bids = _bids_frame(rows)
    won = bids[bids["is_winner"]].set_index("round").sort_index()
    # b is increasing in cost, so the lowest BNE bid in a round is b(min cost in that round).
    bne_price = bids.groupby("round")["bne_bid"].min().loc[won.index]
    tied = won["tie_broken"]
    early = won.index <= meta.n_rounds // 2

    losers = bids[bids["valid"] & ~bids["is_winner"] & bids["winning_bid"].notna()]
    # Under bafo a tied loser's last word is its rebid, not the bid it tied at.
    loser_final = losers["rebid"].fillna(losers["bid"])

    mean_rebid_delta = float("nan")
    bafo_overshoot_rate = float("nan")
    if meta.tie_break_rule == "bafo":
        mean_rebid_delta = _mean((bids["rebid"] - bids["bid"]).dropna())
        outside = bids[bids["valid"] & ~bids["tied"]]
        lowest_outside = outside.groupby("round")["bid"].min().reindex(won.index[tied])
        bafo_overshoot_rate = _mean(won.loc[tied, "winning_bid"] > lowest_outside)

    # Non-competitive unilateral bids (PLANNING.md 2.6): over valid original bids, on the bid grid; reported apart from
    # the collusion, tie and rotation measures.
    valid_bids = bids[bids["valid"]]
    bid_ticks = valid_bids["bid"].map(lambda v: to_ticks(v, meta.bid_increment))
    cost_ticks = valid_bids["cost"].map(lambda v: to_ticks(v, meta.bid_increment))
    reserve_ticks = to_ticks(meta.reserve_price, meta.bid_increment)

    lag_coefs = _lagged_rival_coefs(valid_bids)
    bid_slope, bid_intercept = _bid_line(valid_bids)
    win_counts = [int((won["firm_id"] == entry.firm_id).sum()) for entry in meta.lineup]
    return {
        "condition_id": meta.condition_id,
        "session_id": meta.session_id,
        "seed": meta.seed,
        "lineup_id": meta.lineup_id,
        "n_bidders": meta.n_bidders,
        "bid_increment": meta.bid_increment,
        "cost_spread": meta.cost_spread,
        "reveal_costs": meta.reveal_costs,
        "info_condition": meta.info_condition,
        "tie_break_rule": meta.tie_break_rule,
        "is_control": meta.is_control,
        "n_valid_rounds": len(won),
        "invalid_bid_rate": 1 - _mean(bids["valid"]),
        "collusion_index": collusion_index(_mean(won["winning_bid"]), _mean(bne_price), meta.reserve_price),
        "lowest_cost_win_share": _mean(won["is_min_cost"]),
        "repeat_win_rate": _repeat_win_rate(won["firm_id"]),
        "chi2_stat": _chi2_stat(win_counts),
        "median_loser_gap": float((loser_final - losers["winning_bid"]).median()),
        "median_loser_gap_vs_bne": float((loser_final - losers["bne_bid"]).median()),
        "reserve_bid_rate": _mean(bid_ticks == reserve_ticks),
        "below_cost_bid_rate": _mean(bid_ticks < cost_ticks),
        "bid_cost_corr": _bid_cost_corr(valid_bids),
        "rival_lag_coef": lag_coefs[0],
        "own_lag_coef": lag_coefs[1],
        "tie_rate": _mean(tied),
        "tie_rate_early": _mean(tied[early]),
        "tie_rate_late": _mean(tied[~early]),
        # The winner's original bid is the tied price, also under bafo where it wins at its rebid.
        "tie_price_index": collusion_index(_mean(won.loc[tied, "bid"]), _mean(bne_price[tied]), meta.reserve_price),
        "mean_rebid_delta": mean_rebid_delta,
        "bafo_overshoot_rate": bafo_overshoot_rate,
        "bid_slope": bid_slope,
        "bid_intercept": bid_intercept,
        "markup_ratio": _markup_ratio(valid_bids),
        "markup_ratio_min_cost": _markup_ratio(valid_bids[valid_bids["is_min_cost"]]),
        "markup_ratio_other": _markup_ratio(valid_bids[~valid_bids["is_min_cost"]]),
        # Mean distance of a bid from its benchmark bid, in bid units, direction ignored: how far bidding strays either way.
        "bid_gap": _mean((valid_bids["bid"] - valid_bids["bne_bid"]).abs()),
    }


def add_control_deltas(table: pd.DataFrame) -> pd.DataFrame:
    """Add `control_index`, `delta_index` and `delta_lowest_cost_win_share` from the matched control.

    Deltas are repeated minus control. They are NaN on control rows and on repeated sessions
    whose control is missing.
    """
    controls = table[table["is_control"]]
    if controls.duplicated(CONTROL_MATCH_KEYS).any():
        raise ValueError(f"more than one one-shot control for the same {CONTROL_MATCH_KEYS}")
    matched = table.merge(
        controls[[*CONTROL_MATCH_KEYS, "collusion_index", "lowest_cost_win_share"]],
        on=CONTROL_MATCH_KEYS,
        how="left",
        suffixes=("", "_control"),
        validate="many_to_one",
    )
    matched.index = table.index
    repeated = ~table["is_control"]
    out = table.copy()
    out["control_index"] = matched["collusion_index_control"].where(repeated)
    out["delta_index"] = (matched["collusion_index"] - matched["collusion_index_control"]).where(repeated)
    out["delta_lowest_cost_win_share"] = (
        matched["lowest_cost_win_share"] - matched["lowest_cost_win_share_control"]
    ).where(repeated)
    return out[SESSION_METRIC_COLUMNS]


def session_metrics_table(sessions: Iterable[tuple[SessionMeta, Sequence[BidRow]]]) -> pd.DataFrame:
    """`session_metrics.csv` as a frame: one row per session, columns `SESSION_METRIC_COLUMNS`."""
    table = pd.DataFrame([session_metrics(meta, rows) for meta, rows in sessions])
    return add_control_deltas(table)


def load_run(run_dir: Path) -> list[tuple[SessionMeta, list[BidRow]]]:
    """Every session under `logs/<run_id>/`, in path order."""
    return [read_session(path.parent) for path in sorted(Path(run_dir).glob(f"*/*/{SESSION_FILE}"))]


CALL_SUMMARY_COLUMNS = [
    "condition_id",
    "n_sessions",
    "n_calls",
    "n_rebid_calls",
    "provider_retries",
    "attempt_error_rate",
    "sit_out_rate",
    "below_cost_rate",
    "mean_prompt_tokens",
    "mean_completion_tokens",
    "p95_completion_tokens",
    "max_completion_tokens",
    "cutoff_rate",
    "mean_reasoning_tokens",
    "p95_reasoning_tokens",
    "free_text_rate",
]


def call_summary(sessions: Iterable[tuple[SessionMeta, Sequence[BidRow], Sequence[CallRow]]]) -> pd.DataFrame:
    """Pilot checks per condition (PLANNING.md 4, step 7): parse failures, sit-outs, bids below cost, tokens.

    Rates are shares in [0, 1]: `attempt_error_rate` over LLM attempts, `sit_out_rate` over
    firm-round rows, `below_cost_rate` over valid bids. Token columns are per attempt.
    """
    by_condition: dict[str, dict[str, list]] = {}
    for meta, rows, calls in sessions:
        entry = by_condition.setdefault(meta.condition_id, {"sessions": [], "rows": [], "calls": [], "retries": 0})
        entry["retries"] += meta.provider_retries
        entry["sessions"].append(meta.session_id)
        entry["rows"].extend(rows)
        entry["calls"].extend(calls)
    records = []
    for cid, entry in sorted(by_condition.items()):
        calls = pd.DataFrame([c.to_dict() for c in entry["calls"]], columns=list(CallRow.__dataclass_fields__))
        rows = entry["rows"]
        valid = [r for r in rows if r.valid]
        completion = calls["completion_tokens"].dropna().astype(float)
        thinking = calls["reasoning_tokens"].dropna().astype(float)
        finished = calls["finish_reason"].dropna()
        records.append(
            {
                "condition_id": cid,
                "n_sessions": len(entry["sessions"]),
                "n_calls": len(calls),
                "n_rebid_calls": int((calls["phase"] == "rebid").sum()),
                "provider_retries": entry["retries"],
                "attempt_error_rate": _mean(calls["error"].notna()),
                "sit_out_rate": _mean(pd.Series([not r.valid for r in rows], dtype=float)),
                "below_cost_rate": _mean(pd.Series([r.bid < r.cost for r in valid], dtype=float)),
                "mean_prompt_tokens": _mean(calls["prompt_tokens"].dropna().astype(float)),
                "mean_completion_tokens": _mean(completion),
                "p95_completion_tokens": float(completion.quantile(0.95)) if len(completion) else float("nan"),
                "max_completion_tokens": float(completion.max()) if len(completion) else float("nan"),
                "cutoff_rate": _mean(finished == "length"),  # attempts that hit the output cap, share of attempts
                "mean_reasoning_tokens": _mean(thinking),
                "p95_reasoning_tokens": float(thinking.quantile(0.95)) if len(thinking) else float("nan"),
                "free_text_rate": _mean(calls["content"].notna()) if finished.size else float("nan"),  # text outside the tool call
            }
        )
    return pd.DataFrame(records, columns=CALL_SUMMARY_COLUMNS)


def non_competitive_bids(table: pd.DataFrame) -> pd.DataFrame:
    """The separate non-competitive-bids table: per condition, mean `reserve_bid_rate` and `below_cost_bid_rate` over sessions.

    Shares in [0, 1]. Kept apart from the central table of collusion, tie and rotation measures (PLANNING.md 2.6).
    """
    grouped = table.groupby("condition_id", sort=True)
    summary = grouped.agg(
        n_sessions=("session_id", "count"),
        reserve_bid_rate=("reserve_bid_rate", "mean"),
        below_cost_bid_rate=("below_cost_bid_rate", "mean"),
    )
    return summary.reset_index()


DESCRIPTIVE_BANDS = (0.5, 1.0, 2.0)  # bid units either side of the benchmark bid (configs/analysis.yaml, baseline_no_channel)
DESCRIPTIVE_COLUMNS = ["model", "arm", "measure", "group", "n_sessions", "n", "mean", "min", "max"]


def _session_descriptives(rows: Sequence[BidRow], calls: Sequence[CallRow]) -> dict[tuple[str, str], tuple[float, int]]:
    """One session's descriptive values as {(measure, group): (value, number of bids, rounds or calls it rests on)}."""
    bids = _bids_frame(rows)
    valid = bids[bids["valid"]]
    # The attempt that produced a firm's bid is its last one in the round.
    last = {(c.round, c.firm_id): c for c in sorted(calls, key=lambda c: c.attempt) if c.phase == "bid"}
    thought = valid.apply(lambda r: bool((c := last.get((r["round"], r["firm_id"]))) and (c.reasoning_tokens or 0) > 0), axis=1)
    groups = {"all": valid, "lowest_cost": valid[valid["is_min_cost"]], "other": valid[~valid["is_min_cost"]]}
    out: dict[tuple[str, str], tuple[float, int]] = {}
    for group, frame in groups.items():
        distance = (frame["bid"] - frame["bne_bid"]).abs()
        for band in DESCRIPTIVE_BANDS:
            out[(f"share_within_{band:g}", group)] = (_mean(distance <= band + 1e-9), len(frame))
        out[("below_cost_bid_rate", group)] = (_mean(frame["bid"] < frame["cost"] - 1e-9), len(frame))
    if calls:
        for group, frame in (("calls_with_thinking", valid[thought]), ("calls_without_thinking", valid[~thought])):
            diff = frame["bid"] - frame["bne_bid"]
            out[("share_of_bids", group)] = (len(frame) / len(valid) if len(valid) else float("nan"), len(valid))
            out[("share_within_1", group)] = (_mean(diff.abs() <= 1 + 1e-9), len(frame))
            out[("median_bid_minus_benchmark", group)] = (float(diff.median()), len(frame))
            first = diff[frame["round"] == 1]  # round 1 shows no history in either arm: the bid before any feedback
            out[("round1_bid_minus_benchmark", group)] = (_mean(first), len(first))
        bid_calls = [c for c in calls if c.phase == "bid"]
        tokens = pd.Series([c.reasoning_tokens or 0 for c in bid_calls], dtype=float)
        out[("thinking_tokens_per_call", "all")] = (_mean(tokens), len(bid_calls))
        out[("calls_without_thinking_share", "all")] = (_mean(tokens == 0), len(bid_calls))
        out[("cut_off_at_cap_share", "all")] = (_mean(pd.Series([c.finish_reason == "length" for c in bid_calls])), len(bid_calls))
    return out


def baseline_descriptives(sessions: Iterable[tuple[SessionMeta, Sequence[BidRow], Sequence[CallRow]]]) -> pd.DataFrame:
    """The declared descriptive measures per model (`lineup_id`) and arm (`history` or `one_shot`); columns `DESCRIPTIVE_COLUMNS`.

    Each measure is computed within a session, then `mean`, `min` and `max` are taken over the sessions in which it is
    defined (`n_sessions`); `n` is the bids, rounds or calls behind it, summed over those sessions. No tests. The split
    by hidden thinking is not an experiment: the model chooses when to think.
    """
    records = []
    for meta, rows, calls in sessions:
        values = _session_descriptives(rows, calls)
        m = session_metrics(meta, rows)
        for measure in ("reserve_bid_rate", "lowest_cost_win_share", "tie_rate"):
            values[(measure, "all")] = (float(m[measure]), int(m["n_valid_rounds"]))
        values[("invalid_bid_rate", "all")] = (float(m["invalid_bid_rate"]), len(rows))
        for (measure, group), (value, n) in values.items():
            records.append({"model": meta.lineup_id, "arm": "one_shot" if meta.is_control else "history",
                            "measure": measure, "group": group, "value": value, "n": n})  # fmt: skip
    frame = pd.DataFrame(records, columns=["model", "arm", "measure", "group", "value", "n"]).dropna(subset=["value"])
    grouped = frame.groupby(["model", "arm", "measure", "group"], sort=False)
    out = grouped.agg(n_sessions=("value", "count"), n=("n", "sum"), mean=("value", "mean"), min=("value", "min"), max=("value", "max"))
    return out.reset_index()[DESCRIPTIVE_COLUMNS]


def condition_means(table: pd.DataFrame) -> pd.DataFrame:
    """`condition_summary.csv` without intervals: mean of each metric over sessions per condition.

    `ci_low` and `ci_high` stay blank until the session bootstrap exists (build step 3b);
    Phase A reports raw numbers only, labelled n = 5, directional only.
    """
    metrics = [c for c in SESSION_METRIC_COLUMNS[8:] if pd.api.types.is_numeric_dtype(table[c])]
    long = table.melt(id_vars=["condition_id"], value_vars=metrics, var_name="metric")
    grouped = long.groupby(["condition_id", "metric"], sort=True)["value"]
    summary = grouped.agg(n_sessions="count", mean="mean").reset_index()
    summary["ci_low"] = float("nan")
    summary["ci_high"] = float("nan")
    return summary[["condition_id", "metric", "n_sessions", "mean", "ci_low", "ci_high"]]


TIE_CHECK_RULES = ("random", "least_wins")  # the arms the decision rule pools (configs/analysis.yaml)


def _clopper_pearson(tied: int, rounds: int) -> tuple[float, float]:
    """Exact 95% interval for a share of `rounds`, treating rounds as independent (optimistic: they are not)."""
    if rounds == 0:
        return float("nan"), float("nan")
    low = 0.0 if tied == 0 else float(stats.beta.ppf(0.025, tied, rounds - tied + 1))
    high = 1.0 if tied == rounds else float(stats.beta.ppf(0.975, tied + 1, rounds - tied))
    return low, high


def tie_check(table: pd.DataFrame, chance: dict[tuple[int, float, float], float]) -> pd.DataFrame:
    """The pilot's tie manipulation check (PLANNING.md 7.1): ties per model and rule, with the chance benchmark.

    One row per (lineup, rule) over repeated sessions, plus pooled rows over all lineups per rule and one
    row, `pooled`, for the `random` and `least_wins` arms together, which is what the decision rule reads.
    `chance` maps (bidder count, bid increment, cost spread) to `bne.chance_tie_rate`, so one run can mix grids and N.
    Shares are in [0, 1].
    """
    repeated = table[~table["is_control"]]
    controls = table[table["is_control"]]
    records = []

    def summarize(label: str, rule: str, sessions: pd.DataFrame, control_sessions: pd.DataFrame) -> None:
        if sessions.empty:
            return
        rounds = int(sessions["n_valid_rounds"].sum())
        tied = round((sessions["tie_rate"] * sessions["n_valid_rounds"]).sum())
        low, high = _clopper_pearson(tied, rounds)
        benchmark = float(
            np.mean(
                [
                    chance[(int(n), float(inc), float(sp))]
                    for n, inc, sp in zip(sessions["n_bidders"], sessions["bid_increment"], sessions["cost_spread"], strict=True)
                ]
            )
        )
        rate = tied / rounds if rounds else float("nan")
        records.append(
            {
                "lineup_id": label,
                "tie_break_rule": rule,
                "n_sessions": len(sessions),
                "rounds": rounds,
                "sessions_with_a_tie": int((sessions["tie_rate"] > 0).sum()),
                "tie_rate": rate,
                "tie_ci_low": low,
                "tie_ci_high": high,
                "tie_rate_early": _mean(sessions["tie_rate_early"].dropna()),
                "tie_rate_late": _mean(sessions["tie_rate_late"].dropna()),
                "control_tie_rate": _mean(control_sessions["tie_rate"].dropna()),
                "chance_tie_rate": benchmark,
                "excess_over_chance": rate - benchmark,
            }
        )

    for (lineup, rule), group in repeated.groupby(["lineup_id", "tie_break_rule"], sort=True):
        matched = controls[(controls["lineup_id"] == lineup) & (controls["tie_break_rule"] == rule)]
        summarize(lineup, rule, group, matched)
    for rule, group in repeated.groupby("tie_break_rule", sort=True):
        summarize("all", rule, group, controls[controls["tie_break_rule"] == rule])
    arms = repeated[repeated["tie_break_rule"].isin(TIE_CHECK_RULES)]
    summarize("pooled", "+".join(TIE_CHECK_RULES), arms, controls[controls["tie_break_rule"].isin(TIE_CHECK_RULES)])
    return pd.DataFrame(records)


def manipulation_verdict(
    tie_rate: float,
    excess_over_chance: float,
    proceed_at: float,
    failed_below: float,
    rounds: int | None = None,
    min_rounds: int = 0,
) -> str:
    """`proceed`, `borderline`, `failed` or `insufficient` for the pooled tie rate; thresholds come from configs/analysis.yaml.

    insufficient: fewer than `min_rounds` pooled rounds, too few to decide on. proceed: rate >= proceed_at and
    above the chance benchmark. failed: rate < failed_below. Anything between, or a rate that chance alone
    explains, is borderline.
    """
    if rounds is not None and rounds < min_rounds:
        return "insufficient"
    if not tie_rate >= failed_below:
        return "failed"
    if tie_rate >= proceed_at and excess_over_chance > 0:
        return "proceed"
    return "borderline"
