"""Profit checks on a session's bids: joint profit against benchmark play, each firm's bids against the best reply
to the other firms' actual bids, and the gain from switching alone to the benchmark bid. Also the bid's gap from the
benchmark by round block. All are exploratory measures (PLANNING_NEW.md 2.1); none enters a declared test.

Profits are in bid units; ratios and shares are unitless and not clipped. NaN means not defined for the session.
"""

from collections.abc import Iterable, Sequence
from itertools import pairwise

import numpy as np
import pandas as pd

from bidrig.schema import BidRow, SessionMeta

MIN_EARLIER_ROUNDS = 5  # a best reply to earlier bids needs at least this many earlier rounds with a rival bid
CLOSE = 1.0  # a bid this near the best reply counts as close to it, in bid units; a coarser grid widens it to one increment
PROFIT_CHECK_COLUMNS = [
    "session_id", "lineup_id", "is_control", "seed", "joint_profit_ratio", "switch_gain", "firms_gaining_by_switch",
    "best_reply_share", "forgone_vs_earlier", "forgone_vs_session",
]  # fmt: skip


def _frame(rows: Sequence[BidRow]) -> pd.DataFrame:
    frame = pd.DataFrame([row.to_dict() for row in rows])
    frame["bid"] = frame["bid"].astype(float)
    return frame


def joint_profit_ratio(rows: Sequence[BidRow]) -> float:
    """The firms' total profit over the profit under benchmark play on the same costs: 1 means equal, above 1 more.

    Under benchmark play every firm bids its `bne_bid`, so each round the firm with the lowest benchmark bid (the
    lowest cost, on ties) wins and earns that bid minus its cost.
    """
    frame = _frame(rows)
    winners = frame.sort_values(["round", "bne_bid", "cost"]).groupby("round").head(1)
    benchmark = float((winners["bne_bid"] - winners["cost"]).sum())
    return float(frame["profit"].sum()) / benchmark if benchmark > 0 else float("nan")


def _bid_to_beat(frame: pd.DataFrame, firm_id: str) -> pd.Series:
    """Per round, the lowest valid bid among the other firms (NaN if none bid): the bid `firm_id` has to beat."""
    others = frame[(frame["firm_id"] != firm_id) & frame["valid"]]
    return others.groupby("round")["bid"].min().reindex(sorted(frame["round"].unique()))


def _expected_profit(bids: np.ndarray, cost: float, to_beat: np.ndarray) -> np.ndarray:
    """(bid - cost) times the share of `to_beat` values the bid wins against; an equal bid counts as half a win."""
    wins = (to_beat[None, :] > bids[:, None] + 1e-9).mean(axis=1)
    ties = (np.abs(to_beat[None, :] - bids[:, None]) <= 1e-9).mean(axis=1)
    return (bids - cost) * (wins + 0.5 * ties)


def switch_profits(rows: Sequence[BidRow]) -> list[tuple[float, float]]:
    """Per firm: (its actual profit, its profit had it bid `bne_bid` in every round against the other firms' actual bids).

    The other firms' bids are held fixed, so this is a calculation and not what would happen: a real opponent would
    react. An equal bid counts as half a win, whatever the session's tie rule.
    """
    frame = _frame(rows)
    out = []
    for firm_id, own in frame.groupby("firm_id", sort=True):
        own = own.sort_values("round")
        to_beat = _bid_to_beat(frame, firm_id).to_numpy()
        benchmark_bid, cost = own["bne_bid"].to_numpy(), own["cost"].to_numpy()
        alone = np.isnan(to_beat)
        win = np.where(alone, 1.0, (benchmark_bid < to_beat - 1e-9) + 0.5 * (np.abs(benchmark_bid - to_beat) <= 1e-9))
        out.append((float(own["profit"].sum()), float(((benchmark_bid - cost) * win).sum())))
    return out


def switch_gain(rows: Sequence[BidRow]) -> float:
    """Gain from switching alone to the benchmark bid: the firms' counterfactual profits summed, over their actual profits summed, minus 1.

    Each firm's counterfactual is computed separately (`switch_profits`), so this is the profit-weighted mean of the
    firms' own gains, not the result of both switching. NaN when the actual profits do not sum to a positive number.
    """
    pairs = switch_profits(rows)
    actual = sum(a for a, _ in pairs)
    return sum(c for _, c in pairs) / actual - 1 if actual > 0 else float("nan")


def best_reply(meta: SessionMeta, rows: Sequence[BidRow]) -> dict[str, float]:
    """How a session's bids compare with the best reply to the other firms' actual bids; means over firms.

    `best_reply_share`: share of bids within `CLOSE` of the best reply to the bids to beat in earlier rounds, which is
    what the firm could see. `forgone_vs_earlier`: 1 minus the firm's expected profit over the best attainable, both
    against those earlier bids. `forgone_vs_session`: the same against the bids to beat in all other rounds of the
    session, later ones included. The best reply is found and scored on one sample, so both `forgone` values are
    biased upward; read them against a session that bids the benchmark, not against 0.
    """
    frame = _frame(rows)
    close = max(CLOSE, meta.bid_increment)
    per_firm = []
    for firm_id, own in frame[frame["valid"]].groupby("firm_id", sort=True):
        to_beat = _bid_to_beat(frame, firm_id)
        totals = {"earlier": [0.0, 0.0], "session": [0.0, 0.0]}  # [actual, best]
        near = counted = 0
        for row in own.itertuples():
            samples = {"earlier": to_beat[to_beat.index < row.round].dropna().to_numpy(), "session": to_beat[to_beat.index != row.round].dropna().to_numpy()}
            for name, sample in samples.items():
                if len(sample) < MIN_EARLIER_ROUNDS:
                    continue
                candidates = np.unique(np.concatenate([sample - meta.bid_increment, sample, [meta.reserve_price, row.cost]]))
                candidates = candidates[(candidates >= row.cost - 1e-9) & (candidates <= meta.reserve_price + 1e-9)]
                if not len(candidates):
                    continue  # a cost above the reserve price leaves no bid that does not lose money
                expected = _expected_profit(candidates, row.cost, sample)
                totals[name][0] += float(_expected_profit(np.array([row.bid]), row.cost, sample)[0])
                totals[name][1] += float(expected.max())
                if name == "earlier":
                    counted += 1
                    near += abs(row.bid - candidates[expected.argmax()]) <= close + 1e-9
        per_firm.append({
            "best_reply_share": near / counted if counted else float("nan"),
            "forgone_vs_earlier": 1 - totals["earlier"][0] / totals["earlier"][1] if totals["earlier"][1] > 0 else float("nan"),
            "forgone_vs_session": 1 - totals["session"][0] / totals["session"][1] if totals["session"][1] > 0 else float("nan"),
        })  # fmt: skip
    out = {}
    for key in ("best_reply_share", "forgone_vs_earlier", "forgone_vs_session"):
        defined = [f[key] for f in per_firm if not np.isnan(f[key])]
        out[key] = float(np.mean(defined)) if defined else float("nan")
    return out


def profit_checks_table(sessions: Iterable[tuple[SessionMeta, Sequence[BidRow]]]) -> pd.DataFrame:
    """One row per session with the profit checks; columns `PROFIT_CHECK_COLUMNS`.

    `firms_gaining_by_switch` is the number of firms whose own profit would have been higher at the benchmark bid.
    """
    records = []
    for meta, rows in sessions:
        records.append({
            "session_id": meta.session_id, "lineup_id": meta.lineup_id, "is_control": meta.is_control, "seed": meta.seed,
            "joint_profit_ratio": joint_profit_ratio(rows),
            "switch_gain": switch_gain(rows),
            "firms_gaining_by_switch": sum(c > a for a, c in switch_profits(rows)),
            **best_reply(meta, rows),
        })  # fmt: skip
    return pd.DataFrame(records, columns=PROFIT_CHECK_COLUMNS)


def round_block_gaps(sessions: Iterable[tuple[SessionMeta, Sequence[BidRow]]], edges: Sequence[int] = (1, 3, 5, 10, 20, 30, 40, 50)) -> pd.DataFrame:
    """Mean of (bid - benchmark bid) over valid bids per session and round block; a block ends at each value of `edges`.

    Columns: lineup_id, is_control, seed, block (for example `6-10`), n_bids, mean_bid_minus_benchmark. Rounds past
    the last edge form one further block.
    """
    records = []
    for meta, rows in sessions:
        frame = _frame(rows)
        frame = frame[frame["valid"]]
        bounds = [0, *[e for e in edges if e < meta.n_rounds], meta.n_rounds]
        for low, high in pairwise(bounds):
            block = frame[(frame["round"] > low) & (frame["round"] <= high)]
            if len(block):
                records.append({
                    "lineup_id": meta.lineup_id, "is_control": meta.is_control, "seed": meta.seed,
                    "block": str(high) if high == low + 1 else f"{low + 1}-{high}", "n_bids": len(block),
                    "mean_bid_minus_benchmark": float((block["bid"] - block["bne_bid"]).mean()),
                })  # fmt: skip
    return pd.DataFrame(records, columns=["lineup_id", "is_control", "seed", "block", "n_bids", "mean_bid_minus_benchmark"])
