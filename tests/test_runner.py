"""Runner: config expansion, dry-run estimate, resume, spend cap and host failures; mocked client only."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from test_llm import FakeOpenAI, completion

from bidrig.analysis.metrics import call_summary, condition_means, session_metrics_table
from bidrig.runner import (
    estimate,
    is_complete,
    load_config,
    plan_sessions,
    prepare,
    run_plan,
)
from bidrig.schema import read_calls, read_meta, read_session, session_dir

CONFIGS = Path(__file__).parents[1] / "configs"


def bid_from_prompt(kwargs: dict[str, Any]) -> Any:
    """A fake model that bids its cost plus 25, capped at the reserve."""
    user = kwargs["messages"][1]["content"]
    cost = float(user.split("Your cost for this round is ")[1].split(".\n")[0])
    return completion({"reasoning": "Cost plus a margin.", "bid": min(cost + 25, 100)}, provider=None)


def small(config_name: str, **overrides: Any) -> tuple[dict, dict, list]:
    """A config planned with fewer sessions and rounds, for fast end-to-end runs."""
    config, models, _ = prepare(CONFIGS / config_name, "t")
    config["session"]["n_sessions"] = overrides.get("n_sessions", 1)
    config["auction"]["n_rounds"] = overrides.get("n_rounds", 3)
    if "cap" in overrides:
        config["budget"]["max_cost_usd"] = overrides["cap"]
    plan = plan_sessions(config, "t", models, overrides.get("host", "primary"))
    return config, models, plan


# --- config expansion ---


def test_inheritance() -> None:
    config = load_config(CONFIGS / "pilot.yaml")
    assert config["auction"]["n_rounds"] == 25 and config["auction"]["n_bidders"] == 3
    assert config["session"]["base_seed"] == 990000 and config["session"]["n_sessions"] == 5
    assert config["llm"]["temperature"] == 1.0 and config["budget"]["max_cost_usd"] == 2
    assert "inherits" not in config


def test_pilot_plan() -> None:
    _, _, plan = prepare(CONFIGS / "pilot.yaml")
    assert len(plan) == 60 and len({p.meta.condition_id for p in plan}) == 12
    assert sum(p.n_llm_calls for p in plan) == 4500
    assert {p.meta.seed for p in plan} == set(range(990000, 990005))
    controls = [p for p in plan if p.meta.is_control]
    assert len(controls) == 30 and all(p.meta.condition_id.startswith("oneshot__") for p in controls)
    meta = plan[0].meta
    assert meta.run_id == "pilot" and meta.n_rounds == 25 and meta.temperature == 1.0 and meta.prompt_version
    assert meta.providers == {"deepseek": {"name": "Morph", "quantization": "fp8", "role": "primary"}}
    assert meta.condition_id == "tie-random__info-full__lineup-pilot-deepseek__n3"
    assert [e.model for e in meta.lineup] == ["deepseek"] * 3
    assert len({p.meta.session_id for p in plan}) == 60


def test_every_repeated_pilot_session_has_a_control_on_the_same_seed() -> None:
    _, _, plan = prepare(CONFIGS / "pilot.yaml")
    key = lambda m: (m.lineup_id, m.n_bidders, m.tie_break_rule, m.seed)
    controls = {key(p.meta) for p in plan if p.meta.is_control}
    assert {key(p.meta) for p in plan if not p.meta.is_control} == controls


@pytest.mark.parametrize(
    ("name", "sessions", "calls"),
    [
        ("main_tiebreak.yaml", 432, 64800),
        ("supporting_info.yaml", 18, 2700),
        ("supporting_n.yaml", 36, 6300),
        ("supporting_lineup.yaml", 18, 2700),
        ("sanity_dummy.yaml", 216, 0),
        ("sanity_tiebreak.yaml", 108, 0),
        ("pilot_tiny.yaml", 4, 36),
    ],
)
def test_call_counts_match_the_plan(name: str, sessions: int, calls: int) -> None:
    _, _, plan = prepare(CONFIGS / name, "x")
    assert len(plan) == sessions and sum(p.n_llm_calls for p in plan) == calls


def test_supporting_ablations_reuse_the_main_seeds_and_baseline_control() -> None:
    main = prepare(CONFIGS / "main_tiebreak.yaml", "x")[2]
    info = prepare(CONFIGS / "supporting_info.yaml", "x")[2]
    main_seeds = sorted({p.meta.seed for p in main})
    assert sorted({p.meta.seed for p in info}) == main_seeds[:9]
    baseline_controls = {
        (p.meta.lineup_id, p.meta.n_bidders, p.meta.tie_break_rule, p.meta.seed)
        for p in main
        if p.meta.is_control and p.meta.lineup_id == "homog-deepseek" and p.meta.tie_break_rule == "random"
    }
    assert {(p.meta.lineup_id, p.meta.n_bidders, p.meta.tie_break_rule, p.meta.seed) for p in info} <= baseline_controls


def test_heterogeneous_slots_are_seeded_and_shared_with_the_control() -> None:
    _, _, plan = prepare(CONFIGS / "supporting_lineup.yaml", "x")
    by_seed: dict[int, set] = {}
    for p in plan:
        assert sorted(p.models) == ["deepseek", "glm", "gpt-oss"]
        by_seed.setdefault(p.meta.seed, set()).add(tuple(p.models))
    assert all(len(orders) == 1 for orders in by_seed.values())
    assert len({next(iter(o)) for o in by_seed.values()}) > 1
    assert set(plan[0].meta.providers) == {"deepseek", "gpt-oss"}  # glm has no pinned host yet


def test_unknown_model_or_sweep_key_is_rejected() -> None:
    config, models, _ = prepare(CONFIGS / "pilot.yaml")
    config["cells"] = [{"id": "x", "lineup": {"type": "homogeneous", "model": "gpt-5"}}]
    with pytest.raises(ValueError, match="gpt-5"):
        plan_sessions(config, "t", models)
    config["cells"] = [{"id": "x", "lineup": {"type": "homogeneous", "model": "deepseek"}}]
    config["sweep"] = {"temperature": [0.5, 1.0]}
    with pytest.raises(ValueError, match="temperature"):
        plan_sessions(config, "t", models)


# --- dry-run estimate ---


def test_pilot_estimate_matches_planning() -> None:
    config, models, plan = prepare(CONFIGS / "pilot.yaml")
    est = estimate(plan, config, models, "primary")
    assert est.output_tokens_per_call == 1000
    assert est.cost_usd == pytest.approx(1.49, abs=0.01)
    assert est.cost_by_model["deepseek"] == pytest.approx(0.88, abs=0.01)
    assert est.cost_by_model["gpt-oss"] == pytest.approx(0.61, abs=0.01)
    assert est.cost_usd < config["budget"]["max_cost_usd"]


def test_fallback_hosts_change_the_estimate_and_providers() -> None:
    config, models, plan = prepare(CONFIGS / "pilot.yaml", host_role="fallback")
    assert plan[0].meta.providers["deepseek"]["name"] == "DeepInfra"
    assert estimate(plan, config, models, "fallback").cost_usd > 1.49


# --- running ---


def test_scripted_config_runs_and_resumes(tmp_path: Path) -> None:
    config, models, plan = prepare(CONFIGS / "sanity_tiebreak.yaml", "t")
    first = asyncio.run(run_plan(plan, config, models, tmp_path))
    assert len(first.completed) == 108 and not first.failed and first.spent_usd == 0
    second = asyncio.run(run_plan(plan, config, models, tmp_path))
    assert not second.completed and len(second.skipped) == 108
    meta, rows = read_session(session_dir(tmp_path, plan[0].meta))
    assert meta.status == "complete" and meta.started_at and meta.finished_at and len(rows) == 150
    assert read_calls(session_dir(tmp_path, plan[0].meta)) == []


def test_unfinished_session_is_rerun_from_scratch(tmp_path: Path) -> None:
    config, models, plan = prepare(CONFIGS / "sanity_tiebreak.yaml", "t")
    asyncio.run(run_plan(plan, config, models, tmp_path))
    path = session_dir(tmp_path, plan[3].meta)
    meta = json.loads((path / "session.json").read_text())
    meta["status"] = "failed"
    (path / "session.json").write_text(json.dumps(meta))
    (path / "bids.jsonl").write_text("")
    result = asyncio.run(run_plan(plan, config, models, tmp_path))
    assert result.completed == [plan[3].meta.session_id]
    assert len(read_session(path)[1]) == 150


def test_llm_config_runs_end_to_end_with_a_fake_client(tmp_path: Path) -> None:
    config, models, plan = small("pilot.yaml", n_rounds=4)
    fake = FakeOpenAI(fn=bid_from_prompt)
    result = asyncio.run(run_plan(plan, config, models, tmp_path, lambda: fake))
    assert len(result.completed) == 12 and not result.failed
    assert len(fake.requests) == 12 * 4 * 3
    assert {r["extra_body"]["provider"]["only"][0] for r in fake.requests} == {"morph", "crusoe"}
    assert result.spent_usd > 0
    loaded = []
    for p in plan:
        path = session_dir(tmp_path, p.meta)
        meta, rows = read_session(path)
        calls = read_calls(path)
        assert meta.status == "complete" and len(rows) == 12 and len(calls) == 12
        assert all(c.model == meta.lineup[0].model for c in calls)
        loaded.append((meta, rows, calls))
    table = session_metrics_table((m, r) for m, r, _ in loaded)
    assert table.loc[~table["is_control"], "delta_index"].notna().all()
    assert (condition_means(table)["n_sessions"] <= 1).all()
    summary = call_summary(loaded)
    assert (summary["n_calls"] == 12).all() and (summary["attempt_error_rate"] == 0).all()


def test_one_shot_control_prompts_carry_no_history(tmp_path: Path) -> None:
    config, models, plan = small("pilot.yaml", n_rounds=4)
    plan = [p for p in plan if p.meta.is_control][:1]
    fake = FakeOpenAI(fn=bid_from_prompt)
    asyncio.run(run_plan(plan, config, models, tmp_path, lambda: fake))
    assert all("No earlier rounds are shown." in r["messages"][1]["content"] for r in fake.requests)


def test_spend_cap_stops_the_sweep(tmp_path: Path) -> None:
    config, models, plan = small("pilot.yaml", n_rounds=4, cap=0.0005)
    config["llm"]["max_concurrency"] = 1
    fake = FakeOpenAI(fn=lambda kw: completion({"reasoning": "r", "bid": 60}, provider=None, tokens=(1000, 1000)))
    result = asyncio.run(run_plan(plan, config, models, tmp_path, lambda: fake))
    assert result.budget_exceeded and len(result.failed) == 1
    assert result.spent_usd == pytest.approx(0.0005, abs=0.0005)
    assert len(fake.requests) < 4
    statuses = [read_meta(session_dir(tmp_path, p.meta)).status for p in plan if session_dir(tmp_path, p.meta).exists()]
    assert statuses == ["failed"]


def test_host_failure_fails_only_that_session_and_reruns_on_fallback(tmp_path: Path) -> None:
    config, models, plan = small("pilot.yaml", n_rounds=2)

    def flaky(kwargs: dict[str, Any]) -> Any:
        if kwargs["extra_body"]["provider"]["only"] == ["morph"]:
            return RuntimeError("503 from Morph")
        return bid_from_prompt(kwargs)

    first = asyncio.run(run_plan(plan, config, models, tmp_path, lambda: FakeOpenAI(fn=flaky)))
    deepseek = {p.meta.session_id for p in plan if p.models[0] == "deepseek"}
    assert set(first.failed) == deepseek and len(first.completed) == 6

    _, _, fallback_plan = small("pilot.yaml", n_rounds=2, host="fallback")
    pending = [p for p in fallback_plan if not is_complete(tmp_path, p.meta)]
    fake = FakeOpenAI(fn=flaky)
    second = asyncio.run(run_plan(pending, config, models, tmp_path, lambda: fake, "fallback"))
    assert set(second.completed) == deepseek
    assert {r["extra_body"]["provider"]["only"][0] for r in fake.requests} == {"deepinfra"}
    meta = read_meta(session_dir(tmp_path, pending[0].meta))
    assert meta.providers["deepseek"]["role"] == "fallback" and meta.status == "complete"


def test_condition_means_table_shape(tmp_path: Path) -> None:
    config, models, plan = prepare(CONFIGS / "sanity_tiebreak.yaml", "t")
    asyncio.run(run_plan(plan, config, models, tmp_path))
    table = session_metrics_table(read_session(session_dir(tmp_path, p.meta)) for p in plan)
    summary = condition_means(table)
    assert list(summary.columns) == ["condition_id", "metric", "n_sessions", "mean", "ci_low", "ci_high"]
    wide = summary.pivot(index="condition_id", columns="metric", values="mean")
    match_lw = wide.loc["tie-least_wins__info-full__lineup-dummy-match__n3"]
    assert match_lw["tie_rate"] == 1.0 and match_lw["chi2_stat"] < 0.1
    assert pd.isna(summary["ci_low"]).all()


def test_pilot_tiny_is_small_and_on_its_own_seeds() -> None:
    config, models, plan = prepare(CONFIGS / "pilot_tiny.yaml")
    assert plan[0].meta.run_id == "pilot_tiny"
    assert {p.meta.tie_break_rule for p in plan} == {"bafo"} and {p.meta.n_rounds for p in plan} == {3}
    other_seeds = {p.meta.seed for name in ["pilot.yaml", "main_tiebreak.yaml"] for p in prepare(CONFIGS / name, "x")[2]}
    assert not {p.meta.seed for p in plan} & other_seeds
    assert estimate(plan, config, models, "primary").cost_usd < config["budget"]["max_cost_usd"] / 2
