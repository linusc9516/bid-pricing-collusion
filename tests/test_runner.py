"""Runner: config expansion, dry-run estimate, resume, spend cap and host failures; mocked client only."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from test_llm import FakeOpenAI, completion, error_body

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
    assert config["llm"]["temperature"] == 1.0 and config["budget"]["max_cost_usd"] == 8
    assert "inherits" not in config


def test_pilot_plan() -> None:
    _, _, plan = prepare(CONFIGS / "pilot.yaml")
    assert len(plan) == 90 and len({p.meta.condition_id for p in plan}) == 18
    assert sum(p.n_llm_calls for p in plan) == 6750
    assert {p.models[0] for p in plan} == {"deepseek", "gpt-oss", "qwen"}
    assert {p.meta.seed for p in plan} == set(range(990000, 990005))
    controls = [p for p in plan if p.meta.is_control]
    assert len(controls) == 45 and all(p.meta.condition_id.startswith("oneshot__") for p in controls)
    meta = plan[0].meta
    assert meta.run_id == "pilot" and meta.n_rounds == 25 and meta.temperature == 1.0 and meta.prompt_version
    assert meta.providers == {"deepseek": {"name": "InferenceNet", "quantization": "fp8", "role": "primary"}}
    assert meta.condition_id == "tie-random__info-full__lineup-pilot-deepseek__n3"
    assert [e.model for e in meta.lineup] == ["deepseek"] * 3
    assert len({p.meta.session_id for p in plan}) == 90
    qwen = next(p.meta for p in plan if p.models[0] == "qwen")
    assert qwen.providers == {} and [e.model for e in qwen.lineup] == ["qwen"] * 3  # one provider, nothing to pin


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
        ("pilot.yaml", 90, 6750),
        ("pilot_tiny.yaml", 18, 162),
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
    est = estimate(plan, config, models, "deepseek=backup")  # the pilot ran deepseek on DeepInfra, primary until 2026-10-10
    assert est.output_tokens_per_call == 4000  # stress case: every call uses the whole cap
    assert est.cost_usd == pytest.approx(7.41, abs=0.01)
    assert est.cost_by_model["deepseek"] == pytest.approx(3.92, abs=0.01)
    assert est.cost_by_model["gpt-oss"] == pytest.approx(2.30, abs=0.01)
    assert est.cost_by_model["qwen"] == pytest.approx(1.20, abs=0.01)
    assert est.cost_usd < config["budget"]["max_cost_usd"]


def test_fallback_hosts_change_the_estimate_and_providers() -> None:
    config, models, plan = prepare(CONFIGS / "pilot.yaml", host_role="fallback")
    assert plan[0].meta.providers["deepseek"] == {"name": "CoreWeave", "quantization": "fp8", "role": "fallback"}
    assert estimate(plan, config, models, "deepseek=fallback").cost_usd > estimate(plan, config, models, "primary").cost_usd
    _, _, backup_plan = prepare(CONFIGS / "pilot.yaml", host_role="backup")
    by_model = {p.models[0]: p.meta.providers for p in backup_plan}
    assert by_model["deepseek"]["deepseek"]["name"] == "DeepInfra" and by_model["gpt-oss"]["gpt-oss"] == {"name": "DekaLLM", "quantization": "bf16", "role": "backup"}
    assert by_model["qwen"] == {}


def test_host_spec_moves_one_model() -> None:
    _, _, plan = prepare(CONFIGS / "pilot.yaml", host_role="deepseek=backup")
    by_model = {p.models[0]: p.meta.providers for p in plan}
    assert by_model["deepseek"]["deepseek"] == {"name": "DeepInfra", "quantization": "fp8", "role": "backup"}
    assert by_model["gpt-oss"]["gpt-oss"] == {"name": "Crusoe", "quantization": "bf16", "role": "primary"}
    _, _, mixed = prepare(CONFIGS / "pilot.yaml", host_role="fallback, deepseek=backup")
    by_model = {p.models[0]: p.meta.providers for p in mixed}
    assert by_model["deepseek"]["deepseek"]["name"] == "DeepInfra" and by_model["gpt-oss"]["gpt-oss"]["name"] == "AkashML"
    for bad in ["spare", "deepseek=spare", "nomodel=backup", "qwen=backup"]:
        with pytest.raises(ValueError, match="host"):
            prepare(CONFIGS / "pilot.yaml", host_role=bad)


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
    assert len(result.completed) == 18 and not result.failed
    assert len(fake.requests) == 18 * 4 * 3
    # qwen has one provider and no pinned host, so its requests carry no provider block.
    assert {r["extra_body"].get("provider", {"only": [None]})["only"][0] for r in fake.requests} == {"inference-net", "crusoe", None}
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
        if kwargs["extra_body"].get("provider", {}).get("only") == ["inference-net"]:
            return RuntimeError("503 from InferenceNet")
        return bid_from_prompt(kwargs)

    first = asyncio.run(run_plan(plan, config, models, tmp_path, lambda: FakeOpenAI(fn=flaky)))
    deepseek = {p.meta.session_id for p in plan if p.models[0] == "deepseek"}
    assert set(first.failed) == deepseek and len(first.completed) == 12

    _, _, fallback_plan = small("pilot.yaml", n_rounds=2, host="fallback")
    pending = [p for p in fallback_plan if not is_complete(tmp_path, p.meta)]
    fake = FakeOpenAI(fn=flaky)
    second = asyncio.run(run_plan(pending, config, models, tmp_path, lambda: fake, "fallback"))
    assert set(second.completed) == deepseek
    assert {r["extra_body"]["provider"]["only"][0] for r in fake.requests} == {"coreweave"}
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
    assert {p.meta.tie_break_rule for p in plan} == {"random", "least_wins", "bafo"} and {p.meta.n_rounds for p in plan} == {3}
    cells = {(p.models[0], p.meta.tie_break_rule, p.meta.is_control) for p in plan}
    assert len(cells) == 18  # every model x rule has one repeated session and its one-shot control
    other_seeds = {p.meta.seed for name in ["pilot.yaml", "main_tiebreak.yaml"] for p in prepare(CONFIGS / name, "x")[2]}
    assert not {p.meta.seed for p in plan} & other_seeds
    assert estimate(plan, config, models, "deepseek=backup").cost_usd < config["budget"]["max_cost_usd"] / 2  # as run, on DeepInfra


def test_llm_caps_by_config() -> None:
    caps = {name: load_config(CONFIGS / name)["llm"]["max_output_tokens"] for name in ["base.yaml", "pilot_tiny.yaml", "pilot.yaml"]}
    assert caps == {"base.yaml": 500, "pilot_tiny.yaml": 500, "pilot.yaml": 4000}
    assert load_config(CONFIGS / "pilot.yaml")["llm"]["reasoning_mode"] == "per_model"


@pytest.mark.parametrize("name", ["main_tiebreak.yaml", "supporting_info.yaml", "supporting_n.yaml", "supporting_lineup.yaml"])
def test_phase_b_settings_are_tbd_and_block_model_calls(name: str, tmp_path: Path) -> None:
    from bidrig.runner import tbd_settings

    config, models, plan = prepare(CONFIGS / name, "x")
    assert tbd_settings(config) == ["max_output_tokens", "reasoning_mode"]
    fake = FakeOpenAI(fn=bid_from_prompt)
    with pytest.raises(ValueError, match="TBD"):
        asyncio.run(run_plan(plan[:2], config, models, tmp_path, lambda: fake))
    assert fake.requests == [] and not any(tmp_path.iterdir())
    assert estimate(plan, config, models, "primary").n_llm_calls > 0  # a dry run still works


def test_phase_a_and_scripted_configs_have_nothing_tbd() -> None:
    from bidrig.runner import tbd_settings

    for name in ["pilot.yaml", "pilot_tiny.yaml", "sanity_dummy.yaml", "sanity_tiebreak.yaml"]:
        assert tbd_settings(prepare(CONFIGS / name, "x")[0]) == [], name


def test_unsupported_llm_settings_are_rejected() -> None:
    from bidrig.runner import check_llm_settings

    base = {"llm": {"max_output_tokens": 500, "reasoning_mode": "per_model"}}
    check_llm_settings(base)
    for bad in [{"reasoning_mode": "on"}, {"max_output_tokens": "lots"}, {"max_output_tokens": True}]:
        with pytest.raises((ValueError, TypeError)):
            check_llm_settings({"llm": {**base["llm"], **bad}})


def flaky_then_fine(failures: int) -> Any:
    """A fake model whose first `failures` requests return a Morph-style 502 error body."""
    left = [failures]

    def respond(kwargs: dict[str, Any]) -> Any:
        if left[0] > 0:
            left[0] -= 1
            return error_body()
        return bid_from_prompt(kwargs)

    return respond


def one_session(**llm: Any) -> tuple[dict, dict, list]:
    config, models, plan = small("pilot.yaml", n_rounds=2)
    config["llm"].update({"retry_base_s": 0, **llm})
    return config, models, plan[:1]


def test_transient_provider_errors_are_retried_and_counted_in_session_json(tmp_path: Path) -> None:
    config, models, plan = one_session()
    result = asyncio.run(run_plan(plan, config, models, tmp_path, lambda: FakeOpenAI(fn=flaky_then_fine(3))))
    assert result.completed == [plan[0].meta.session_id] and not result.failed
    path = session_dir(tmp_path, plan[0].meta)
    meta = read_meta(path)
    assert meta.status == "complete" and meta.provider_retries == 3 and len(meta.provider_errors) == 3
    assert "HTTP 502" in meta.provider_errors[0] and "round 1" in meta.provider_errors[0]
    assert len(read_calls(path)) == 6  # provider retries add no rows to calls.jsonl
    summary = call_summary([(meta, read_session(path)[1], read_calls(path))])
    assert summary["provider_retries"].iloc[0] == 3


def test_persistent_provider_errors_abandon_the_session_with_the_counts(tmp_path: Path) -> None:
    config, models, plan = one_session()
    result = asyncio.run(run_plan(plan, config, models, tmp_path, lambda: FakeOpenAI(fn=flaky_then_fine(10**6))))
    assert list(result.failed) == [plan[0].meta.session_id] and "still failing after 4 retries" in next(iter(result.failed.values()))
    meta = read_meta(session_dir(tmp_path, plan[0].meta))
    # The counter is shared by the session's three firms, which fail in step: 4 retries each at most.
    assert meta.status == "failed" and 4 <= meta.provider_retries <= 12 and 1 <= len(meta.provider_errors) <= 20


def test_session_retry_cap_abandons_a_flaky_session(tmp_path: Path) -> None:
    config, models, plan = one_session(session_retry_cap=2, provider_retries=10)
    result = asyncio.run(run_plan(plan, config, models, tmp_path, lambda: FakeOpenAI(fn=flaky_then_fine(10**6))))
    assert "session retry cap of 2" in next(iter(result.failed.values()))
    assert read_meta(session_dir(tmp_path, plan[0].meta)).provider_retries == 2


def reasoning_sent(config_name: str, tmp_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The `reasoning` object each model's requests carried when a config ran against a fake client."""
    config, models, plan = small(config_name, n_rounds=2)
    fake = FakeOpenAI(fn=bid_from_prompt)
    asyncio.run(run_plan(plan, config, models, tmp_path, lambda: fake))
    by_slug = {m.slug: alias for alias, m in models.items()}
    return {by_slug[r["model"]]: r["extra_body"].get("reasoning") for r in fake.requests}, fake.requests


def test_pilot_runs_deepseek_and_qwen_with_thinking_on_at_low_effort(tmp_path: Path) -> None:
    sent, requests = reasoning_sent("pilot.yaml", tmp_path)
    assert sent == {"deepseek": {"effort": "low"}, "gpt-oss": {"effort": "low"}, "qwen": {"effort": "low"}}
    assert {r["max_tokens"] for r in requests} == {4000}
    assert all("limited to 4000 tokens" in r["messages"][0]["content"] for r in requests)


def test_pilot_tiny_and_the_default_keep_thinking_off(tmp_path: Path) -> None:
    sent, requests = reasoning_sent("pilot_tiny.yaml", tmp_path)
    assert sent == {"deepseek": {"enabled": False}, "gpt-oss": {"effort": "low"}, "qwen": {"enabled": False}}
    assert {r["max_tokens"] for r in requests} == {500}


def test_pilot_allows_long_replies_a_long_timeout() -> None:
    from bidrig.llm import LLMSettings

    assert LLMSettings.from_config(load_config(CONFIGS / "pilot.yaml")["llm"]).request_timeout_s == 300
    assert LLMSettings.from_config(load_config(CONFIGS / "pilot_tiny.yaml")["llm"]).request_timeout_s == 120


def test_run_plan_reports_progress_per_session(tmp_path: Path) -> None:
    config, models, plan = small("pilot.yaml", n_rounds=2)
    lines: list[str] = []
    asyncio.run(run_plan(plan[:3], config, models, tmp_path, lambda: FakeOpenAI(fn=bid_from_prompt), progress=lines.append))
    assert [line.split("]")[0] for line in lines] == ["[1/3", "[2/3", "[3/3"]
    assert all("complete" in line and "spent $" in line for line in lines)


def test_progress_marks_failures(tmp_path: Path) -> None:
    config, models, plan = one_session()
    lines: list[str] = []
    asyncio.run(run_plan(plan, config, models, tmp_path, lambda: FakeOpenAI(fn=flaky_then_fine(10**6)), progress=lines.append))
    assert len(lines) == 1 and lines[0].startswith("[1/1] FAILED")
