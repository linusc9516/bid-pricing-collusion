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

from bidrig.auction import to_ticks
from bidrig.bne import collusion_index
from bidrig.schema import SESSION_FILE, BidRow, CallRow, SessionMeta, read_session

# A repeated session and its one-shot control share these (PLANNING.md section 3, `lineup_id`).
# `info_condition` is left out: the information levels share the baseline's control (5.2).
CONTROL_MATCH_KEYS = ["lineup_id", "n_bidders", "tie_break_rule", "seed"]

SESSION_METRIC_COLUMNS = [
    "condition_id",
    "session_id",
    "seed",
    "lineup_id",
    "n_bidders",
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
    "tie_rate",
    "tie_rate_early",
    "tie_rate_late",
    "tie_price_index",
    "mean_rebid_delta",
    "bafo_overshoot_rate",
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

    win_counts = [int((won["firm_id"] == entry.firm_id).sum()) for entry in meta.lineup]
    return {
        "condition_id": meta.condition_id,
        "session_id": meta.session_id,
        "seed": meta.seed,
        "lineup_id": meta.lineup_id,
        "n_bidders": meta.n_bidders,
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
        "tie_rate": _mean(tied),
        "tie_rate_early": _mean(tied[early]),
        "tie_rate_late": _mean(tied[~early]),
        # The winner's original bid is the tied price, also under bafo where it wins at its rebid.
        "tie_price_index": collusion_index(_mean(won.loc[tied, "bid"]), _mean(bne_price[tied]), meta.reserve_price),
        "mean_rebid_delta": mean_rebid_delta,
        "bafo_overshoot_rate": bafo_overshoot_rate,
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
