"""analysis/stats.py: the sign-flip test, Holm, the bootstrap interval, the equivalence labels and the baseline table."""

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from bidrig.analysis.metrics import SESSION_METRIC_COLUMNS
from bidrig.analysis.stats import (
    BASELINE_TEST_COLUMNS,
    baseline_tests,
    bootstrap_mean_ci,
    equivalence_label,
    holm,
    matched_pairs,
    seed_rank_correlation,
    sign_flip_p,
)

PLAN = yaml.safe_load((Path(__file__).parents[1] / "configs" / "analysis.yaml").read_text())["baseline_no_channel"]


def test_sign_flip_is_exact_by_hand() -> None:
    assert sign_flip_p([1, 2, 3]) == pytest.approx(2 / 8)  # only +++ and --- reach |mean| 2
    assert sign_flip_p([1, 2, 3], two_sided=False) == pytest.approx(1.0)
    assert sign_flip_p([-1, -2, -3], two_sided=False) == pytest.approx(1 / 8)
    assert sign_flip_p([-1.0] * 12) == pytest.approx(2 / 4096)  # the smallest two-sided p with 12 pairs
    assert sign_flip_p([1, -1]) == pytest.approx(1.0)
    assert sign_flip_p([0.0, 0.0, 0.0]) == pytest.approx(1.0)
    assert math.isnan(sign_flip_p([]))


def test_sign_flip_samples_above_the_exact_limit() -> None:
    assert sign_flip_p([-1.0] * 25) == pytest.approx(1 / 100_001)
    rng = np.random.default_rng(3)
    assert sign_flip_p(rng.normal(0, 1, 30)) > 0.05


def test_holm_by_hand() -> None:
    assert holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])  # 3 x 0.01; 2 x 0.03; then kept monotone
    assert holm([0.6, 0.7]) == pytest.approx([1.0, 1.0])
    out = holm([0.02, float("nan"), 0.01])
    assert out[0] == pytest.approx(0.02) and math.isnan(out[1]) and out[2] == pytest.approx(0.02)
    assert holm([]) == []


def test_bootstrap_interval_brackets_the_mean_and_is_reproducible() -> None:
    values = np.random.default_rng(1).normal(-0.1, 0.1, 12)
    low, high = bootstrap_mean_ci(values)
    assert low < values.mean() < high and (low, high) == bootstrap_mean_ci(values)
    assert high - low == pytest.approx(2 * 1.96 * values.std(ddof=1) / math.sqrt(12), rel=0.25)
    assert bootstrap_mean_ci([0.3] * 5) == pytest.approx((0.3, 0.3))
    assert all(math.isnan(x) for x in bootstrap_mean_ci([0.3]))


@pytest.mark.parametrize(
    ("low", "high", "label"),
    [
        (-0.04, 0.01, "at_equilibrium"),
        (-0.05, 0.05, "at_equilibrium"),
        (-0.06, 0.01, "near_equilibrium"),
        (-0.01, 0.1, "near_equilibrium"),
        (-0.12, -0.02, "not_at_equilibrium"),
        (0.2, 0.3, "not_at_equilibrium"),
        (float("nan"), 0.0, "undetermined"),
    ],
)
def test_equivalence_labels(low: float, high: float, label: str) -> None:
    assert equivalence_label(low, high, 0.05, 0.1) == label


def table(cells: dict[str, tuple[list[float], list[float]]], invalid: dict[tuple[str, int], float] | None = None) -> pd.DataFrame:
    """A session-metrics table from {model: (history indices, one-shot indices)}; the secondary metrics are 1 in the control and 1 + index in the history session."""
    rows = []
    for model, (history, controls) in cells.items():
        for k, (h, c) in enumerate(zip(history, controls, strict=True)):
            for is_control, index in ((False, h), (True, c)):
                row = dict.fromkeys(SESSION_METRIC_COLUMNS, float("nan"))
                row |= {"lineup_id": model, "n_bidders": 2, "tie_break_rule": "random", "seed": 996000 + k, "cost_spread": 0.0,
                        "reveal_costs": False, "is_control": is_control, "collusion_index": index,
                        "session_id": f"{model}-{k}-{is_control}", "invalid_bid_rate": (invalid or {}).get((model, k), 0.0)}  # fmt: skip
                row |= dict.fromkeys(PLAN["secondary"], 1.0 if is_control else 1.0 + index)
                rows.append(row)
    return pd.DataFrame(rows)


def test_baseline_table_tests_each_model_and_adjusts_h1_over_models() -> None:
    drop = [-0.2, -0.1, -0.15, -0.05, -0.3, -0.12, -0.08, -0.2, -0.1, -0.25, -0.02, -0.18]
    flat = [0.02, -0.03, 0.01, -0.01, 0.04, -0.02, 0.03, -0.04, 0.0, 0.01, -0.01, 0.02]
    out = baseline_tests(table({"a": (drop, [0.0] * 12), "b": ([x - 0.2 for x in flat], [-0.2] * 12)}), PLAN, "exploratory")
    assert list(out.columns) == BASELINE_TEST_COLUMNS and set(out["status"]) == {"exploratory"}
    assert sorted(out["family"].unique()) == ["confirmatory", "secondary"]  # no pair dropped, so no sensitivity rows
    h1 = out[out["test_id"] == "H1_history_lowers_price"].set_index("model")
    assert h1.loc["a", "n"] == 12 and h1.loc["a", "n_negative"] == 12 and h1.loc["a", "mean"] == pytest.approx(np.mean(drop))
    assert h1.loc["a", "p_raw"] == pytest.approx(2 / 4096) and h1.loc["a", "p_holm"] == pytest.approx(4 / 4096)
    assert h1.loc["a", "supported"] and not h1.loc["b", "supported"]
    assert h1.loc["b", "p_holm"] == pytest.approx(h1.loc["b", "p_raw"])  # the larger p of two is not multiplied
    assert h1.loc["b", "mean"] == pytest.approx(np.mean(flat))  # history minus its own control, both near -0.2
    h2 = out[out["test_id"] == "H2_one_shot_at_equilibrium"].set_index("model")
    assert h2.loc["a", "label"] == "at_equilibrium" and h2.loc["a", "supported"]
    assert h2.loc["b", "label"] == "not_at_equilibrium" and not h2.loc["b", "supported"]
    secondary = out[(out["family"] == "secondary") & (out["model"] == "a")]
    assert list(secondary["outcome"]) == PLAN["secondary"] and list(secondary["p_holm"]) == pytest.approx([5 * 2 / 4096] * 5)


def test_baseline_table_keeps_only_complete_pairs_and_adds_the_invalid_bid_sensitivity() -> None:
    full = table({"a": ([-0.1, -0.2, -0.3, -0.1], [0.0, 0.01, -0.01, 0.0])}, invalid={("a", 3): 0.2})
    lone = full[~((full["seed"] == 996001) & full["is_control"])]  # seed 996001 loses its control
    assert len(matched_pairs(full)) == 4 and len(matched_pairs(lone)) == 3
    out = baseline_tests(lone, PLAN, "confirmatory")
    h1 = out[out["test_id"] == "H1_history_lowers_price"].set_index("family")
    assert h1.loc["confirmatory", "n"] == 3 and h1.loc["sensitivity", "n"] == 2  # then the pair with 20% invalid bids goes
    assert h1.loc["confirmatory", "mean"] == pytest.approx(np.mean([-0.1, -0.29, -0.1]))
    assert h1.loc["sensitivity", "mean"] == pytest.approx(np.mean([-0.1, -0.29]))


def test_seed_rank_correlation_across_models() -> None:
    rising = [0.1 * k for k in range(6)]
    out = seed_rank_correlation(table({"a": (rising, [0.0] * 6), "b": ([2 * x for x in rising], [0.0] * 6), "c": (rising[::-1], [0.0] * 6)}), "collusion_index")
    by_pair = {(r.model_a, r.model_b): r.rho for r in out.itertuples()}
    assert set(out["n_seeds"]) == {6} and len(out) == 3
    # The controls sit at 0 on every seed, so the mean per seed keeps each model's order over seeds.
    assert by_pair[("a", "b")] == pytest.approx(1.0) and by_pair[("a", "c")] == pytest.approx(-1.0)
