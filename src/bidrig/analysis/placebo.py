"""Replay-rival placebo (configs/placebo_replay.yaml): measures on the model firm's own bids, and the declared test.

In a replay session one firm is a model and the other replays recorded bids, so the session-level metrics, which mix
both firms, are not meaningful. Everything here uses the model firm's rows only. The plan is the section
`placebo_replay` of configs/analysis.yaml.
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from bidrig.analysis.stats import bootstrap_mean_ci, holm, sign_flip_p
from bidrig.schema import BidRow, SessionMeta

MIN_VALID_BIDS = 48  # sensitivity: pairs in which the model firm has fewer valid bids than this in either session are dropped
LATE_FROM_ROUND = 11  # `*_late` measures use rounds from this one on, when ten rounds of replayed bids are on screen
PLACEBO_COLUMNS = [
    "session_id", "model", "level", "seed", "source_seed", "n_valid", "markup_ratio", "markup_ratio_late",
    "bid_minus_benchmark", "bid_minus_benchmark_late", "bid_gap", "bid_slope", "win_share", "replayed_mean_bid",
]  # fmt: skip
PLACEBO_TEST_COLUMNS = ["status", "model", "family", "outcome", "n", "mean_high", "mean_low", "mean_diff", "ci_low", "ci_high", "n_positive", "p_raw", "p_holm", "supported"]


def _markup_ratio(rows: pd.DataFrame) -> float:
    room = float((rows["bne_bid"] - rows["cost"]).sum())
    return float((rows["bid"] - rows["cost"]).sum()) / room if room > 0 else float("nan")


def placebo_table(sessions: Iterable[tuple[SessionMeta, Sequence[BidRow]]]) -> pd.DataFrame:
    """One row per replay session, from the model firm's valid bids; columns `PLACEBO_COLUMNS`. Sessions without a replayed firm are skipped.

    `markup_ratio` is the sum of (bid - cost) over the sum of (benchmark bid - cost): 1 at the benchmark, 0 at cost.
    `bid_minus_benchmark` is the mean signed distance and `bid_gap` the mean absolute one, in bid units. `win_share`
    is the share of rounds the model firm won. `replayed_mean_bid` is the mean of the bids it was shown.
    """
    records = []
    for meta, rows in sessions:
        if not meta.replay:
            continue
        frame = pd.DataFrame([row.to_dict() for row in rows])
        frame["bid"] = frame["bid"].astype(float)
        replayed = frame[frame["firm_id"] == meta.replay["firm_id"]]
        own = frame[(frame["firm_id"] != meta.replay["firm_id"]) & frame["valid"]]
        late = own[own["round"] >= LATE_FROM_ROUND]
        slope = float(np.polyfit(own["cost"], own["bid"], 1)[0]) if len(own) >= 3 and own["cost"].nunique() > 1 else float("nan")
        records.append({
            "session_id": meta.session_id, "model": next(e.model for e in meta.lineup if e.model), "level": meta.replay["level"],
            "seed": meta.seed, "source_seed": meta.replay["source_seed"], "n_valid": len(own),
            "markup_ratio": _markup_ratio(own), "markup_ratio_late": _markup_ratio(late),
            "bid_minus_benchmark": float((own["bid"] - own["bne_bid"]).mean()), "bid_minus_benchmark_late": float((late["bid"] - late["bne_bid"]).mean()),
            "bid_gap": float((own["bid"] - own["bne_bid"]).abs().mean()), "bid_slope": slope,
            "win_share": float(own["is_winner"].mean()), "replayed_mean_bid": float(replayed["bid"].mean()),
        })  # fmt: skip
    return pd.DataFrame(records, columns=PLACEBO_COLUMNS)


def placebo_tests(table: pd.DataFrame, plan: Mapping[str, Any], status: str) -> pd.DataFrame:
    """The declared placebo tests: per model and outcome, the high-replay value minus the low-replay value, paired by seed.

    Exact sign-flip test, two-sided. The confirmatory outcome is Holm-adjusted over the models; the secondary
    outcomes are Holm-adjusted within each model. Only seeds with both arms enter. A `sensitivity` row repeats the
    confirmatory test without pairs short of `MIN_VALID_BIDS`, when that drops any. Columns `PLACEBO_TEST_COLUMNS`.
    """
    primary = plan["confirmatory"][0]
    alpha = float(primary["alpha"])
    rows: list[dict[str, Any]] = []
    for model, cell in table.groupby("model", sort=True):
        wide = cell.pivot(index="seed", columns="level")
        secondary = []
        full = wide["n_valid"].min(axis=1) >= MIN_VALID_BIDS  # seeds whose two sessions both have nearly every bid
        families = [("confirmatory", [primary["outcome"]], wide), ("secondary", list(plan["secondary"]), wide)]
        if 0 < full.sum() < len(wide):
            families.append(("sensitivity", [primary["outcome"]], wide[full]))
        for family, outcomes, frame in families:
            for outcome in outcomes:
                both = frame[outcome].dropna()
                if not {"high", "low"} <= set(both.columns) or both.empty:
                    continue
                diff = (both["high"] - both["low"]).to_numpy(float)
                low, high = bootstrap_mean_ci(diff)
                row = {
                    "model": model, "family": family, "outcome": outcome, "n": len(diff), "mean_high": float(both["high"].mean()),
                    "mean_low": float(both["low"].mean()), "mean_diff": float(diff.mean()), "ci_low": low, "ci_high": high,
                    "n_positive": int((diff > 0).sum()), "p_raw": sign_flip_p(diff),
                }  # fmt: skip
                (secondary if family == "secondary" else rows).append(row)
        for row, adjusted in zip(secondary, holm([r["p_raw"] for r in secondary]), strict=True):
            row["p_holm"] = adjusted
        rows.extend(secondary)
    out = pd.DataFrame(rows, columns=PLACEBO_TEST_COLUMNS[1:]).astype({"supported": object})
    for family in ("confirmatory", "sensitivity"):
        mask = out["family"] == family
        out.loc[mask, "p_holm"] = holm(out.loc[mask, "p_raw"].tolist())
        out.loc[mask, "supported"] = (out.loc[mask, "p_holm"] < alpha) & (out.loc[mask, "mean_diff"] > 0)
    out.insert(0, "status", status)
    return out[PLACEBO_TEST_COLUMNS]
