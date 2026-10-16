"""Notes-arm analysis (analysis/channel.py): arms, reflection endings, the paired H3 and H4 tests, labels by arm."""

import json

import numpy as np
import pandas as pd
import pytest
from helpers import make_meta

from bidrig.analysis.channel import (
    arm_of,
    channel_tests,
    labels_by_arm,
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
