"""Replay-rival placebo: the replay bidder, the lineup and its plan, an end-to-end run with a fake model, and the analysis."""

import asyncio
import json
import math
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest
import yaml
from helpers import make_meta
from test_llm import FakeOpenAI
from test_metrics import hand_rows
from test_runner import bid_from_prompt, small

from bidrig.analysis.placebo import (
    PLACEBO_COLUMNS,
    PLACEBO_TEST_COLUMNS,
    placebo_table,
    placebo_tests,
)
from bidrig.bidders import ReplayBidder
from bidrig.bne import BneBenchmark
from bidrig.checks import check_run, load_logs
from bidrig.runner import load_config, prepare, replay_source, run_plan
from bidrig.schema import BidRequest, read_calls, read_session, session_dir

CONFIGS = Path(__file__).parents[1] / "configs"
PLAN = yaml.safe_load((CONFIGS / "analysis.yaml").read_text())["placebo_replay"]
REPLAY = json.loads((CONFIGS / "replay" / "baseline_no_channel_luna_B.json").read_text())


def test_replay_bidder_bids_its_list_whatever_its_cost() -> None:
    bidder = ReplayBidder(BneBenchmark(2, 0, 100), 100, bids=(70.0, 99.99, 12.5))
    assert [bidder.quote(BidRequest("B", 1, n, cost)) for n, cost in ((1, 5.0), (2, 95.0), (3, 60.0))] == [70.0, 99.99, 12.5]
    assert bidder.bidder_type == "replay" and bidder.model is None
    with pytest.raises(ValueError, match="round 4"):
        bidder.quote(BidRequest("B", 1, 4, 10.0))


def test_replay_sources_rotate_and_never_reuse_the_sessions_own_seed() -> None:
    replay = {"high": [103, 104, 102, 108], "low": [101, 110, 100, 109]}
    assert [replay_source(replay, "high", 100 + k, 100) for k in range(6)] == [103, 104, 108, 108, 103, 104]  # seed 102 skips itself
    assert [replay_source(replay, "low", 100 + k, 100) for k in range(4)] == [101, 110, 100, 109]
    assert replay_source(replay, "low", 101, 100) == 110 and replay_source(replay, "low", 100, 100) == 101


def test_replay_file_holds_fifty_bids_per_source_and_the_two_levels_differ() -> None:
    sessions = REPLAY["sessions"]
    assert len(sessions) == 8 and all(len(s["bids"]) == 50 for s in sessions.values())
    high = [s["mean_bid"] for s in sessions.values() if s["level"] == "high"]
    low = [s["mean_bid"] for s in sessions.values() if s["level"] == "low"]
    assert len(high) == len(low) == 4 and min(high) > max(low) + 5


def test_placebo_plan_matches_the_declared_design() -> None:
    config = load_config(CONFIGS / "placebo_replay.yaml")
    _, _, plan = prepare(CONFIGS / "placebo_replay.yaml", host_role=config["llm"]["host"])
    design = PLAN["design"]
    assert len(plan) == 48 and sum(p.n_llm_calls for p in plan) == 2400  # the replayed firm makes no call
    assert {p.meta.run_id for p in plan} == {PLAN["run_id"]} and not any(p.meta.is_control for p in plan)
    low_seed, high_seed = (int(x) for x in design["seeds"].split("-"))
    for level in ("high", "low"):
        declared = [int(x) for x in design["arms"][level].replace("sources", "").split(",")]
        assert config["replay"][level] == declared and all(REPLAY["sessions"][str(s)]["level"] == level for s in declared)
        for model in ("deepseek", "gpt-luna"):
            cell = [p.meta for p in plan if p.models[0] == model and p.meta.replay["level"] == level]
            assert sorted(m.seed for m in cell) == list(range(low_seed, high_seed + 1)) and len(cell) == design["n_pairs_per_model"]
            assert all(m.replay["source_seed"] in declared and m.replay["source_seed"] != m.seed for m in cell)
            assert all([(e.firm_id, e.bidder_type, e.model) for e in m.lineup] == [("A", "llm", model), ("B", "replay", None)] for m in cell)
            assert {m.providers[model]["name"] for m in cell} == {design["cells"][model]["host"]}
            assert {(m.n_rounds, m.tie_break_rule, m.prompt_version, m.history_window) for m in cell} == {(50, "random", "v1", None)}
    assert config["replay"]["file"] == design["replay_file"]


def test_placebo_session_runs_end_to_end_and_firm_b_replays_the_recorded_bids(tmp_path: Path) -> None:
    config, models, plan = small("placebo_replay.yaml", n_rounds=3)
    fake = FakeOpenAI(fn=bid_from_prompt)
    result = asyncio.run(run_plan(plan, config, models, tmp_path, lambda: fake))
    assert len(result.completed) == 4 and not result.failed and len(fake.requests) == 4 * 3  # one model call per round
    for p in plan:
        meta, rows = read_session(session_dir(tmp_path, p.meta))
        recorded = REPLAY["sessions"][str(meta.replay["source_seed"])]["bids"][:3]
        assert [r.bid for r in rows if r.firm_id == "B"] == recorded
        assert [r.bid for r in rows if r.firm_id == "A"] == [min(round(r.cost + 25, 2), 100) for r in rows if r.firm_id == "A"]
        assert {c.firm_id for c in read_calls(session_dir(tmp_path, p.meta))} == {"A"}
    logs, skipped = load_logs(tmp_path / "t")
    report = check_run(logs, Path(config["_root"]) / config["prompt"]["template"])
    # The fake model reports no serving host, which is the one check that cannot pass here. Every other check does:
    # structure, costs, auction, prompts, rounds shown, cost leak.
    assert not skipped and {f.check for f in report.findings} <= {"provider"}, [f for f in report.findings if f.check != "provider"][:3]


def replay_session(level: str, seed: int, a_bids: list[float]) -> tuple:
    """Three rounds: firm A has costs 10, 20, 40 (benchmark bids 55, 60, 70) and bids `a_bids`; firm B replays 90, 90, 90."""
    rows = hand_rows(2, [[(c, b, b < 90), (50, 90, b >= 90)] for c, b in zip((10, 20, 40), a_bids, strict=True)])
    meta = make_meta(["llm", "replay"], seed=seed, n_rounds=3, lineup_id=f"cell-{level}")
    lineup = [replace(meta.lineup[0], model="m"), meta.lineup[1]]
    return replace(meta, lineup=lineup, replay={"file": "f", "level": level, "source_seed": 7, "firm_id": "B"}), rows


def test_placebo_table_uses_the_model_firms_rows_only() -> None:
    table = placebo_table([replay_session("high", 1, [65.0, 70.0, 80.0]), replay_session("low", 1, [55.0, 60.0, 70.0]), (make_meta(["llm"] * 2), [])][:2])
    assert list(table.columns) == PLACEBO_COLUMNS and list(table["level"]) == ["high", "low"] and set(table["model"]) == {"m"}
    high, low = table.iloc[0], table.iloc[1]
    assert high["markup_ratio"] == pytest.approx((55 + 50 + 40) / (45 + 40 + 30)) and low["markup_ratio"] == pytest.approx(1.0)
    assert high["bid_minus_benchmark"] == pytest.approx(10.0) and high["bid_gap"] == pytest.approx(10.0) and low["bid_gap"] == pytest.approx(0.0)
    assert high["replayed_mean_bid"] == pytest.approx(90.0) and high["win_share"] == pytest.approx(1.0) and high["n_valid"] == 3
    assert low["bid_slope"] == pytest.approx(0.5) and math.isnan(high["markup_ratio_late"])  # no round 11 in three rounds


def test_placebo_tests_pair_by_seed_and_adjust_over_models() -> None:
    rows = []
    for model, shift in (("a", 0.3), ("b", 0.0)):
        for k in range(12):
            noise = 0.01 * ((k * 7) % 5 - 2)
            for level, value in (("high", 1.0 + shift + noise), ("low", 1.0 - noise)):
                rows.append({**dict.fromkeys(PLACEBO_COLUMNS, 0.5), "model": model, "level": level, "seed": k, "n_valid": 50 if (model, k) != ("a", 0) else 40, "markup_ratio": value})
    out = placebo_tests(pd.DataFrame(rows), PLAN, "exploratory")
    assert list(out.columns) == PLACEBO_TEST_COLUMNS and set(out["status"]) == {"exploratory"}
    main = out[out["family"] == "confirmatory"].set_index("model")
    assert main.loc["a", "n"] == 12 and main.loc["a", "n_positive"] == 12 and main.loc["a", "mean_diff"] == pytest.approx(0.3, abs=0.01)
    assert main.loc["a", "p_raw"] == pytest.approx(2 / 4096) and main.loc["a", "p_holm"] == pytest.approx(4 / 4096) and main.loc["a", "supported"]
    assert not main.loc["b", "supported"] and main.loc["b", "p_holm"] == pytest.approx(main.loc["b", "p_raw"])
    assert list(out[(out["family"] == "secondary") & (out["model"] == "a")]["outcome"]) == PLAN["secondary"]
    sensitivity = out[out["family"] == "sensitivity"]
    assert list(sensitivity["model"]) == ["a"] and sensitivity.iloc[0]["n"] == 11  # the pair with 40 valid bids is dropped
