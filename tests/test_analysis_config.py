"""configs/analysis.yaml: the pre-declared pilot decision rule is well formed and points at real metrics."""

from pathlib import Path

import yaml

from bidrig.analysis.metrics import SESSION_METRIC_COLUMNS, manipulation_verdict

CONFIG = yaml.safe_load((Path(__file__).parents[1] / "configs" / "analysis.yaml").read_text())


def test_decision_thresholds_are_ordered_and_drive_the_verdict() -> None:
    decision = CONFIG["manipulation_check"]["decision"]
    assert 0 < decision["failed_below"] < decision["proceed_at"] < 1
    assert decision == {"min_rounds": 300, "proceed_at": 0.01, "failed_below": 0.003}  # the values declared before the pilot
    args = (decision["proceed_at"], decision["failed_below"])
    assert manipulation_verdict(0.0, 0.0, *args) == "failed"
    assert manipulation_verdict(0.005, 0.005, *args) == "borderline"
    assert manipulation_verdict(0.05, 0.05, *args) == "proceed"


def test_supporting_metrics_exist_as_session_columns() -> None:
    assert set(CONFIG["supporting_metrics"]) <= set(SESSION_METRIC_COLUMNS)


def test_labelling_rule_requires_the_index_above_the_benchmark() -> None:
    rule = CONFIG["labelling_rule"]
    assert any(line.startswith("collusion_index > 0") for line in rule)
    assert any(line.startswith("delta_index > 0") for line in rule) and any("delta_lowest_cost_win_share" in line for line in rule)


def test_pre_existing_plan_is_unchanged() -> None:
    assert CONFIG["primary_outcome"] == "delta_index" and CONFIG["unit"] == "session"
    assert [c["id"] for c in CONFIG["confirmatory"]] == ["least_wins_vs_random", "bafo_vs_random"]
