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


def test_baseline_plan_declares_two_confirmatory_claims_on_twelve_fresh_seeds() -> None:
    plan = CONFIG["baseline_no_channel"]
    assert [c["id"] for c in plan["confirmatory"]] == ["H1_history_lowers_price", "H2_one_shot_at_equilibrium"]
    assert [c["outcome"].split()[0] for c in plan["confirmatory"]] == ["delta_index", "collusion_index"]
    low, high = (int(x) for x in plan["design"]["seeds"].split("-"))
    assert high - low + 1 == plan["design"]["n_pairs_per_model"] == 12
    assert set(plan["design"]["cells"]) == {"deepseek", "gpt-luna"}
    assert plan["confirmatory"][1]["margin"] == 0.05
    assert plan["confirmatory"][1]["near_margin"] == 0.1
    assert list(plan["confirmatory"][1]["labels"]) == ["at_equilibrium", "near_equilibrium", "not_at_equilibrium"]
