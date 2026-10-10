"""Session-level inference for the plans declared in configs/analysis.yaml: exact paired sign-flip tests, Holm
correction, percentile bootstrap intervals over whole sessions, and the equivalence labels of the baseline plan.
A round is never an observation: every function here takes one value per session or per matched pair.
"""

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from bidrig.analysis.metrics import CONTROL_MATCH_KEYS

N_BOOTSTRAP = 10_000  # resamples, as declared
CI_LEVEL = 0.95
EXACT_MAX_PAIRS = 20  # 2**20 sign patterns; above this the sign-flip test samples patterns
N_PERMUTATIONS = 100_000
RNG_SEED = 20261010  # fixed, so a table can be reproduced from the logs
INVALID_RATE_LIMIT = 0.05  # sensitivity: pairs with a session above this are dropped

BASELINE_TEST_COLUMNS = [
    "status", "model", "family", "test_id", "outcome", "n", "mean", "median", "sd", "min", "max",
    "ci_low", "ci_high", "n_negative", "p_raw", "p_holm", "wilcoxon_p", "label", "supported",
]  # fmt: skip


def sign_flip_p(differences: Sequence[float], two_sided: bool = True) -> float:
    """P-value of the paired sign-flip test on the mean of `differences`, in (0, 1]; NaN with no pairs.

    Exact over all 2**n sign patterns up to `EXACT_MAX_PAIRS` pairs, else from `N_PERMUTATIONS` random patterns.
    One-sided tests the lower tail (a mean below 0).
    """
    d = np.asarray(differences, dtype=float)
    n = len(d)
    if n == 0:
        return float("nan")
    if n <= EXACT_MAX_PAIRS:
        signs = 1 - 2 * ((np.arange(2**n)[:, None] >> np.arange(n)) & 1)
    else:
        signs = np.random.default_rng(RNG_SEED).choice([-1, 1], size=(N_PERMUTATIONS, n))
    means = signs @ d / n
    observed = d.mean()
    tolerance = 1e-12 * max(1.0, float(np.abs(d).max()))
    hits = np.abs(means) >= abs(observed) - tolerance if two_sided else means <= observed + tolerance
    return float(hits.mean()) if n <= EXACT_MAX_PAIRS else float((hits.sum() + 1) / (N_PERMUTATIONS + 1))


def holm(p_values: Sequence[float]) -> list[float]:
    """Holm-adjusted p-values in the input order, each in [0, 1]; NaN entries stay NaN and are left out of the family."""
    p = np.asarray(p_values, dtype=float)
    out = np.full(len(p), np.nan)
    known = np.flatnonzero(~np.isnan(p))
    running = 0.0
    for rank, i in enumerate(known[np.argsort(p[known], kind="stable")]):
        running = max(running, min(1.0, (len(known) - rank) * p[i]))
        out[i] = running
    return out.tolist()


def bootstrap_mean_ci(values: Sequence[float], level: float = CI_LEVEL, n_resamples: int = N_BOOTSTRAP) -> tuple[float, float]:
    """Percentile bootstrap interval (low, high) of the mean, resampling whole sessions; NaN with fewer than 2 values."""
    v = np.asarray(values, dtype=float)
    if len(v) < 2:
        return float("nan"), float("nan")
    draws = np.random.default_rng(RNG_SEED).integers(0, len(v), size=(n_resamples, len(v)))
    low, high = np.quantile(v[draws].mean(axis=1), [(1 - level) / 2, (1 + level) / 2])
    return float(low), float(high)


def equivalence_label(ci_low: float, ci_high: float, margin: float, near_margin: float) -> str:
    """`at_equilibrium` if the interval lies wholly inside +-margin, `near_equilibrium` if wholly inside +-near_margin, else `not_at_equilibrium`."""
    if np.isnan(ci_low) or np.isnan(ci_high):
        return "undetermined"
    if -margin <= ci_low and ci_high <= margin:
        return "at_equilibrium"
    if -near_margin <= ci_low and ci_high <= near_margin:
        return "near_equilibrium"
    return "not_at_equilibrium"


def matched_pairs(table: pd.DataFrame) -> pd.DataFrame:
    """One row per history session with a matched one-shot control: every metric twice, the control's suffixed `_control`."""
    history, controls = table[~table["is_control"]], table[table["is_control"]]
    return history.merge(controls, on=CONTROL_MATCH_KEYS, suffixes=("", "_control"), validate="one_to_one")


def _summary(values: np.ndarray) -> dict[str, Any]:
    low, high = bootstrap_mean_ci(values)
    return {
        "n": len(values), "mean": float(values.mean()), "median": float(np.median(values)),
        "sd": float(values.std(ddof=1)) if len(values) > 1 else float("nan"),
        "min": float(values.min()), "max": float(values.max()), "ci_low": low, "ci_high": high,
    }  # fmt: skip


def _paired_row(differences: np.ndarray) -> dict[str, Any]:
    """Summary of paired differences with the sign-flip p and, as a sensitivity check, the Wilcoxon signed-rank p."""
    nonzero = differences[differences != 0]
    wilcoxon = float(scipy_stats.wilcoxon(nonzero).pvalue) if len(nonzero) else float("nan")
    return _summary(differences) | {"n_negative": int((differences < 0).sum()), "p_raw": sign_flip_p(differences), "wilcoxon_p": wilcoxon}


def baseline_tests(table: pd.DataFrame, plan: Mapping[str, Any], status: str) -> pd.DataFrame:
    """The declared baseline tests on a session-metrics table, one row per model and test; columns `BASELINE_TEST_COLUMNS`.

    `plan` is the `baseline_no_channel` section of configs/analysis.yaml; `status` is `confirmatory` for the run the
    plan names and `exploratory` for any other run. A model is a `lineup_id`. Only pairs with both sessions present
    enter. H1 is Holm-adjusted over the models; the secondary family is Holm-adjusted within each model.
    """
    h1, h2 = plan["confirmatory"]
    alpha = float(h1["alpha"])
    pairs = matched_pairs(table)
    rows: list[dict[str, Any]] = []
    for model, cell in pairs.groupby("lineup_id", sort=True):
        clean = cell[(cell["invalid_bid_rate"] <= INVALID_RATE_LIMIT) & (cell["invalid_bid_rate_control"] <= INVALID_RATE_LIMIT)]
        for family, frame in (("confirmatory", cell), ("sensitivity", clean)):
            if family == "sensitivity" and len(clean) in (0, len(cell)):
                continue  # nothing was dropped, or nothing is left
            delta = (frame["collusion_index"] - frame["collusion_index_control"]).to_numpy(float)
            rows.append({"model": model, "family": family, "test_id": h1["id"], "outcome": "delta_index"} | _paired_row(delta))
            one_shot = _summary(frame["collusion_index_control"].to_numpy(float))
            label = equivalence_label(one_shot["ci_low"], one_shot["ci_high"], float(h2["margin"]), float(h2["near_margin"]))
            rows.append({"model": model, "family": family, "test_id": h2["id"], "outcome": "collusion_index (one-shot)",
                         "label": label, "supported": label == "at_equilibrium"} | one_shot)  # fmt: skip
        secondary = []
        for metric in plan["secondary"]:
            both = cell[[metric, f"{metric}_control"]].dropna()
            if len(both):
                diff = (both[metric] - both[f"{metric}_control"]).to_numpy(float)
                secondary.append({"model": model, "family": "secondary", "test_id": f"{metric}_history_minus_one_shot", "outcome": metric} | _paired_row(diff))
        for row, adjusted in zip(secondary, holm([r["p_raw"] for r in secondary]), strict=True):
            row["p_holm"] = adjusted
        rows.extend(secondary)
    out = pd.DataFrame(rows, columns=BASELINE_TEST_COLUMNS[1:])
    for family in ("confirmatory", "sensitivity"):
        mask = (out["family"] == family) & (out["test_id"] == h1["id"])
        out.loc[mask, "p_holm"] = holm(out.loc[mask, "p_raw"].tolist())
        out.loc[mask, "supported"] = (out.loc[mask, "p_holm"] < alpha) & (out.loc[mask, "mean"] < 0)
    out.insert(0, "status", status)
    return out[BASELINE_TEST_COLUMNS]


def seed_rank_correlation(table: pd.DataFrame, metric: str = "delta_index") -> pd.DataFrame:
    """Spearman correlation of `metric` across seeds for every pair of models (`lineup_id`), history sessions only for a delta.

    One row per pair: model_a, model_b, n_seeds, rho, p. A high value means the cost sequence, which the models share
    per seed, moves the metric for both. Exploratory: no correction, and seeds are few.
    """
    wide = table.dropna(subset=[metric]).pivot_table(index="seed", columns="lineup_id", values=metric, aggfunc="mean")
    rows = []
    for i, a in enumerate(wide.columns):
        for b in wide.columns[i + 1 :]:
            both = wide[[a, b]].dropna()
            if len(both) >= 3:
                result = scipy_stats.spearmanr(both[a], both[b])
                rows.append({"model_a": a, "model_b": b, "n_seeds": len(both), "rho": float(result.statistic), "p": float(result.pvalue)})
    return pd.DataFrame(rows, columns=["model_a", "model_b", "n_seeds", "rho", "p"])
