"""Channel-arm analysis (analysis/channel.py): arms, reflection endings, the paired H3, H4 and H5 tests, channel use, labels by arm."""

import dataclasses
import json

import numpy as np
import pandas as pd
import pytest
from helpers import make_meta

from bidrig.analysis.channel import (
    arm_of,
    cell_label,
    channel_tests,
    judge_arm,
    labels_by_arm,
    message_use,
    reflection_endings,
)
from bidrig.schema import CallRow

PLAN = {
    "confirmatory": [{"id": "H3_x", "outcome": "collusion_index", "alpha": 0.05}, {"id": "H4_x", "outcome": "collusion_index", "alpha": 0.05}],
    "secondary": ["markup_ratio"],
}


def reflect(round_number: int, firm: str, attempt: int, tools: list[str], error: str | None = None) -> CallRow:
    reasoning = json.dumps([{"name": t, "arguments": {}} for t in tools])
    return CallRow("s", round_number, firm, attempt, "reflect", "m", "p", "[]", None, reasoning, None, error, 1, 1, 1.0)


def test_arms_follow_the_session_settings() -> None:
    meta = make_meta(["llm"] * 2)
    assert arm_of(meta) == "B0"
    meta.workspace = True
    assert arm_of(meta) == "M2"
    meta.workspace_shared = False
    assert arm_of(meta) == "M1"
    assert arm_of(make_meta(["llm"] * 2, history_window=0)) is None
    talking = make_meta(["llm"] * 2)
    talking.channel = True
    assert arm_of(talking) == "C1"


def test_reflection_steps_are_counted_by_how_they_end() -> None:
    calls = [
        reflect(1, "A", 1, ["read_workspace"]), reflect(1, "A", 2, ["end_reflection"]),
        *(reflect(1, "B", k, ["read_workspace"]) for k in range(1, 5)),
        reflect(2, "A", 1, [], error="no tool call"),
    ]  # fmt: skip
    assert reflection_endings(calls) == {"steps": 3, "end_reflection": 1, "step_cap": 1, "no_tool_call": 1}


def _table(m1_minus_b0: list[float], m2_minus_m1: list[float], cap_m1: list[float] | None = None) -> pd.DataFrame:
    rows = []
    for seed, (a, b) in enumerate(zip(m1_minus_b0, m2_minus_m1, strict=True)):
        base = 0.1 * seed
        caps = {"B0": 0.0, "M1": (cap_m1 or [0.0] * len(m1_minus_b0))[seed], "M2": 0.0}
        for arm, index in (("B0", base), ("M1", base + a), ("M2", base + a + b)):
            rows.append({"model": "luna", "seed": seed, "arm": arm, "collusion_index": index, "markup_ratio": 1 + index,
                         "cap_share": caps[arm], "invalid_bid_rate": 0.0})  # fmt: skip
    return pd.DataFrame(rows)


def test_paired_tests_give_the_contrasts_and_holm_over_the_two() -> None:
    out = channel_tests(_table([0.1] * 8, [-0.1] * 8), PLAN, "confirmatory")
    main = out[out["family"] == "confirmatory"].set_index("test_id")
    assert main.loc["H3_x", "mean"] == pytest.approx(0.1) and main.loc["H3_x", "n_positive"] == 8
    assert main.loc["H3_x", "p_raw"] == pytest.approx(2 / 256)  # only the all-plus and all-minus patterns are as extreme
    assert main.loc["H3_x", "p_holm"] == pytest.approx(4 / 256)
    assert bool(main.loc["H3_x", "supported"]) and not bool(main.loc["H4_x", "supported"])  # H4 needs a rise
    assert set(out.loc[out["family"] == "secondary", "test_id"]) == {"markup_ratio_H3", "markup_ratio_H4"}


def test_sessions_mostly_ended_at_the_step_cap_leave_the_tests_and_return_as_a_sensitivity() -> None:
    caps = [0.5] + [0.0] * 7
    out = channel_tests(_table(list(np.linspace(0.05, 0.4, 8)), [0.0] * 8, caps), PLAN, "confirmatory")
    h3 = out[out["test_id"] == "H3_x"].set_index("family")
    assert h3.loc["confirmatory", "n"] == 7 and h3.loc["with_capped", "n"] == 8


def test_labels_are_split_by_arm_and_session() -> None:
    judged = pd.DataFrame({
        "session_id": ["a", "a", "b", "c"], "condition_id": ["x__pn", "x__pn", "x__ws", "x__ws"],
        "parse_ok": [True, True, True, False], "uses_rival_notes": [False, False, True, True],
    })  # fmt: skip
    out = labels_by_arm(judged, ["uses_rival_notes"]).set_index("arm")
    assert out.loc["M1", "share_of_judged"] == 0 and out.loc["M2", "judged"] == 1 and out.loc["M2", "share_of_sessions"] == 1


PLAN_H5 = {"confirmatory": [{"id": "H5_x", "outcome": "collusion_index", "alpha": 0.05}], "secondary": ["markup_ratio"]}


def _table_h5(rises: dict[str, list[float]]) -> pd.DataFrame:
    rows = []
    for model, diffs in rises.items():
        for seed, d in enumerate(diffs):
            for arm, index in (("B0", 0.1 * seed), ("C1", 0.1 * seed + d), ("M1", 0.1 * seed), ("M2", 0.1 * seed)):
                if arm in ("M1", "M2") and model != "luna":
                    continue
                rows.append({"model": model, "seed": seed, "arm": arm, "collusion_index": index, "markup_ratio": 1 + index,
                             "cap_share": 0.0, "invalid_bid_rate": 0.0})  # fmt: skip
    return pd.DataFrame(rows)


def test_h5_is_c1_minus_b0_with_holm_over_the_models() -> None:
    out = channel_tests(_table_h5({"deepseek": [0.5] * 8, "luna": [-0.1] * 8}), PLAN_H5, "confirmatory")
    main = out[out["family"] == "confirmatory"].set_index("model")
    assert list(main["contrast"]) == ["C1 - B0", "C1 - B0"]
    assert main.loc["deepseek", "p_raw"] == pytest.approx(2 / 256) and main.loc["deepseek", "p_holm"] == pytest.approx(4 / 256)
    assert bool(main.loc["deepseek", "supported"]) and not bool(main.loc["luna", "supported"])  # H5 needs a rise
    extra = out[out["family"] == "secondary_contrast"]
    assert set(extra["contrast"]) == {"C1 - M2", "C1 - M1"} and set(extra["model"]) == {"luna"}


def test_message_use_counts_steps_messages_and_failed_requests() -> None:
    meta = make_meta(["llm"] * 2)
    meta.channel = True
    meta.lineup = [dataclasses.replace(entry, model="m") for entry in meta.lineup]
    calls = [
        CallRow("s", 1, "A", 1, "message", "m", "p", "[]", None, None, None, None, 1, 1, 1.0),
        CallRow("s", 1, "B", 1, "message", "m", "p", "[]", None, None, None, "no tool call", 1, 1, 1.0),
        CallRow("s", 2, "A", 1, "message", "m", "p", "[]", None, None, None, None, 1, 1, 1.0),
        CallRow("s", 2, "B", 1, "message", "m", "p", "[]", None, None, None, None, 1, 1, 1.0),
    ]  # fmt: skip
    events = [{"round": 2, "firm_id": "A", "op": "write", "text": "abcd", "truncated": False}]
    row = message_use([(meta, events, calls)]).iloc[0]
    assert row["steps"] == 4 and row["share_steps_sent"] == 0.25 and row["first_message_round"] == 2
    assert row["mean_message_chars"] == 4 and row["share_requests_failed"] == 0.25
    assert message_use([(make_meta(["llm"] * 2), events, calls)]).empty


def test_channel_sessions_are_labelled_c1() -> None:
    judged = pd.DataFrame({"session_id": ["a"], "condition_id": ["x__msg"], "parse_ok": [True], "proposes_coordination": [True]})
    assert labels_by_arm(judged, ["proposes_coordination"]).iloc[0]["arm"] == "C1"


def test_h9_and_h10_compare_each_notes_arm_with_b0_and_add_the_declared_secondary_contrasts() -> None:
    rows = []
    for seed in range(8):
        for arm, index in (("B0", 0.0), ("M1", 0.05), ("M2", 0.3), ("C1", 0.9)):
            rows.append({"model": "deepseek", "seed": seed, "arm": arm, "collusion_index": index + 0.01 * seed, "markup_ratio": 1.0,
                         "cap_share": 0.0, "invalid_bid_rate": 0.0})  # fmt: skip
    plan = {"confirmatory": [{"id": "H9_x", "outcome": "collusion_index", "alpha": 0.05}, {"id": "H10_x", "outcome": "collusion_index", "alpha": 0.05}],
            "secondary": []}  # fmt: skip
    out = channel_tests(pd.DataFrame(rows), plan, "confirmatory")
    main = out[out["family"] == "confirmatory"].set_index("test_id")
    assert main.loc["H9_x", "contrast"] == "M2 - B0" and main.loc["H10_x", "contrast"] == "M1 - B0"
    assert main.loc["H9_x", "mean"] == pytest.approx(0.3) and bool(main.loc["H9_x", "supported"])
    assert set(out.loc[out["family"] == "secondary_contrast", "contrast"]) == {"M2 - M1", "C1 - M2"}


def test_narrow_cost_sessions_are_their_own_arms_and_never_b0() -> None:
    meta = make_meta(["llm"] * 2)
    meta.cost_low, meta.cost_high, meta.reserve_price = 40, 60, 60
    assert arm_of(meta) == "S2C"
    meta.reserve_price = 100
    assert arm_of(meta) == "S2A"
    meta.cost_high = 70
    assert arm_of(meta) is None
    meta.cost_high, meta.workspace = 60, True
    assert arm_of(meta) is None


def test_restricted_channels_are_their_own_arms_and_cells_pair_mixed_lineups_and_n3_apart() -> None:
    meta = make_meta(["llm"] * 2)
    meta.channel, meta.channel_max_chars = True, 50
    assert arm_of(meta) == "C1cap"
    meta.channel_notice = True
    assert arm_of(meta) is None
    meta.channel_max_chars = 500
    assert arm_of(meta) == "C1notice"
    meta.lineup = [dataclasses.replace(e, model=m) for e, m in zip(meta.lineup, ["haiku", "deepseek"], strict=True)]
    assert cell_label(meta) == "deepseek x haiku"
    three = make_meta(["llm"] * 3)
    three.lineup = [dataclasses.replace(e, model="deepseek") for e in three.lineup]
    assert cell_label(three) == "deepseek n3"
    ids = pd.Series(["x__msg-cap50", "x__msg-notice", "x__msg", "x"])
    assert list(judge_arm(ids)) == ["C1cap", "C1notice", "C1", "B0"]


def test_cell_scoped_hypotheses_use_their_declared_holm_families_and_a_restriction_needs_a_fall() -> None:
    rows = []
    for seed in range(8):
        for model, arm, index in (("deepseek", "B0", 0.0), ("deepseek", "C1", 0.9), ("deepseek", "C1cap", 0.2), ("deepseek", "C1notice", 0.95),
                                  ("haiku", "B0", 0.0), ("haiku", "C1", 0.5)):  # fmt: skip
            rows.append({"model": model, "seed": seed, "arm": arm, "collusion_index": index + 0.01 * seed, "markup_ratio": 1.0,
                         "cap_share": 0.0, "invalid_bid_rate": 0.0})  # fmt: skip
    plan = {"confirmatory": [
        {"id": "H13_x", "cell": "haiku", "holm": "h13", "outcome": "collusion_index", "alpha": 0.05},
        {"id": "H14_x", "cell": "deepseek", "holm": "restrictions", "outcome": "collusion_index", "alpha": 0.05},
        {"id": "H15_x", "cell": "deepseek", "holm": "restrictions", "outcome": "collusion_index", "alpha": 0.05},
    ], "secondary": []}  # fmt: skip
    out = channel_tests(pd.DataFrame(rows), plan, "confirmatory")
    main = out[out["family"] == "confirmatory"].set_index("test_id")
    assert list(main.index) == ["H14_x", "H15_x", "H13_x"]  # each in its own cell only
    assert main.loc["H14_x", "contrast"] == "C1cap - C1" and main.loc["H13_x", "model"] == "haiku"
    assert main.loc["H13_x", "p_holm"] == pytest.approx(2 / 256)  # alone in its family
    assert main.loc["H14_x", "p_holm"] == pytest.approx(4 / 256) == main.loc["H15_x", "p_holm"]
    assert bool(main.loc["H14_x", "supported"]) and not bool(main.loc["H15_x", "supported"])  # H15 rose: no support
    assert set(out.loc[out["family"] == "secondary_contrast", "contrast"]) == {"C1cap - B0", "C1notice - B0"}
