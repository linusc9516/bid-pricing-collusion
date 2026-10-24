"""Open message channel: prompts, one message per step, the runner, the toggle, and the log checks; mocked client only."""

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from helpers import make_meta
from test_checks import COST_LINE, HOSTS
from test_llm import HOST, SPEC, FakeOpenAI, completion
from test_workspace import tool_reply

from bidrig.auction import run_session
from bidrig.bidders import LLMBidder
from bidrig.checks import check_run, load_logs
from bidrig.llm import LLMSettings, OpenRouterClient, SpendTracker
from bidrig.prompts import CHANNEL_DIGITS, CHANNEL_PARAGRAPH, WORKSPACE_PARAGRAPH, system_prompt
from bidrig.runner import plan_sessions, prepare, run_plan
from bidrig.schema import MESSAGES_FILE, read_workspace_events
from bidrig.workspace import Workspace

CONFIGS = Path(__file__).parents[1] / "configs"


def talking_model(text: str = "Firm {firm} here.", provider: Any = "Morph", twice: bool = False) -> Any:
    """Bids cost + 20; in a communication step sends one message (two if `twice`)."""

    def reply(kwargs: dict[str, Any]) -> Any:
        host = provider(kwargs) if callable(provider) else provider
        system, user = kwargs["messages"][0]["content"], kwargs["messages"][1]["content"]
        if "communication step, not a bid" not in user:
            cost = float(COST_LINE.search(user).group(1))
            return completion({"reasoning": "r", "bid": min(cost + 20, 100)}, provider=host)
        message = ("send_message", {"text": text.format(firm=system.split("Firm ")[1][0])})
        return tool_reply(*([message] * (2 if twice else 1)), provider=host)

    return reply


def test_system_prompt_discloses_the_channel() -> None:
    meta = make_meta(["llm"] * 2, n_rounds=3)
    meta.channel = True
    text = system_prompt(meta, "A", "short", 400)
    assert text.endswith(CHANNEL_PARAGRAPH) and WORKSPACE_PARAGRAPH not in text
    assert "Every firm reads every message" in CHANNEL_PARAGRAPH
    assert not any(word in CHANNEL_PARAGRAPH.lower() for word in ("coordinat", "cooperat", "collu", "agree"))


def run_channel(twice: bool = False, delivered: bool = True, strip_digits: bool = False, text: str = "Firm {firm} here.") -> tuple[FakeOpenAI, list, Workspace]:
    fake = FakeOpenAI(fn=talking_model(text, twice=twice))
    meta = make_meta(["llm"] * 2, n_rounds=3)
    meta.channel, meta.channel_delivered, meta.channel_strip_digits = True, delivered, strip_digits
    client = OpenRouterClient(fake, LLMSettings(), SpendTracker(1.0))
    log: list = []
    channel = Workspace(max_chars=500, strip_digits=strip_digits)
    bidders = [LLMBidder(SPEC, HOST, client, meta, log, channel=channel) for _ in range(2)]

    async def between(round_number: int) -> None:
        await asyncio.gather(*(b.communicate(round_number, slot) for slot, b in enumerate(bidders)))

    asyncio.run(run_session(meta, bidders, log, between_rounds=between))
    return fake, [c for b in bidders for c in b.calls], channel


def test_messages_reach_every_firm_at_the_next_step_and_bid() -> None:
    fake, calls, channel = run_channel()
    steps = [c for c in calls if c.phase == "message"]
    assert sorted((c.round, c.firm_id, c.attempt) for c in steps) == [(1, "A", 1), (1, "B", 1), (2, "A", 1), (2, "B", 1)]
    assert sorted((e.round, e.firm_id) for e in channel.events) == [(1, "A"), (1, "B"), (2, "A"), (2, "B")]
    users = [r["messages"][1]["content"] for r in fake.requests]
    step2 = [u for u in users if "Round 2 is over" in u]
    assert step2 and all("[after round 1, Firm B" in u and "[after round 2" not in u for u in step2)  # never this step's
    bid3 = [u for u in users if "communication step" not in u and "Round 2:" in u]
    assert bid3 and all("[after round 2, Firm A" in u and "[after round 2, Firm B" in u for u in bid3)
    assert all("No messages have been sent." in u for u in users if "No earlier rounds" in u)


def test_only_one_message_per_step() -> None:
    _, _, channel = run_channel(twice=True)
    assert len(channel.events) == 4


def test_workspace_and_channel_are_exclusive_toggles() -> None:
    config, models, plan = prepare(CONFIGS / "channel_screen_n2.yaml", "x")
    assert all(p.meta.channel and not p.meta.workspace and p.meta.condition_id.endswith("__msg") for p in plan)
    assert plan[0].n_llm_calls == (25 + 24) * 2
    assert {p.meta.seed for p in plan} == {p.meta.seed for p in prepare(CONFIGS / "workspace_screen_n2.yaml", "x")[2]}
    config["workspace"] = {"enabled": True}
    with pytest.raises(ValueError, match="at most one"):
        plan_sessions(config, "x", models)
    config["workspace"] = {"enabled": False}
    config["sweep"] = {"history_window": [None, 0]}
    with pytest.raises(ValueError, match="channel needs"):
        plan_sessions(config, "x", models)


def test_runner_writes_messages_and_the_checks_pass(tmp_path: Path) -> None:
    config, models, plan = prepare(CONFIGS / "channel_tiny.yaml")
    route = lambda kw: HOSTS[kw["extra_body"].get("provider", {"only": [None]})["only"][0]]
    fake = FakeOpenAI(fn=talking_model("My cost was 12.34.", provider=route))
    result = asyncio.run(run_plan(plan, config, models, tmp_path, lambda: fake))
    assert not result.failed and len(result.completed) == 2
    logs, _ = load_logs(tmp_path / "channel_tiny")
    report = check_run(logs)
    assert report.passed, report.findings[:3]
    assert report.items["channel"] == 2 and report.items["workspace"] == 0
    assert len(read_workspace_events(logs[0].path, MESSAGES_FILE)) == 4
    assert not (logs[0].path / "workspace.jsonl").exists()
    phases = [c.phase for c in logs[0].calls]
    assert phases.count("bid") == 6 and phases.count("message") == 4


def test_cells_switch_the_channel_cap_and_notice_on_for_themselves_only() -> None:
    _, _, plan = prepare(CONFIGS / "ext_tiny.yaml", "x")
    by_cell = {p.meta.lineup_id: p.meta for p in plan}
    assert not by_cell["b0-haiku"].channel and by_cell["b0-haiku"].condition_id.endswith("__n2")
    assert by_cell["c1-haiku"].condition_id.endswith("__msg") and by_cell["c1-haiku"].channel_max_chars == 500
    assert by_cell["cap-deepseek"].condition_id.endswith("__msg-cap50") and by_cell["cap-deepseek"].channel_max_chars == 50
    assert by_cell["notice-deepseek"].condition_id.endswith("__msg-notice") and by_cell["notice-deepseek"].channel_notice
    mixed = [p for p in plan if p.meta.lineup_id.endswith("deepseek-luna")]
    assert mixed[0].models == mixed[1].models  # same seed, same firm-to-model assignment in B0 and C1


def test_undelivered_messages_reach_only_their_sender_under_the_same_prompt() -> None:
    fake, _, channel = run_channel(delivered=False)
    assert len(channel.events) == 4
    for request in fake.requests:
        system, user = request["messages"][0]["content"], request["messages"][1]["content"]
        firm = system.split("Firm ")[1][0]
        assert f"Firm {'B' if firm == 'A' else 'A'} here." not in user
        assert system.endswith(CHANNEL_PARAGRAPH)
    later = [r["messages"][1]["content"] for r in fake.requests if "Round 2 is over" in r["messages"][1]["content"]]
    assert later and all("(you)] Firm " in u for u in later)


def test_runner_undelivered_session_passes_the_checks_and_a_delivered_one_would_not(tmp_path: Path) -> None:
    config, models, _ = prepare(CONFIGS / "channel_tiny.yaml")
    config["channel"] = {**config["channel"], "delivered": False}
    plan = plan_sessions(config, "undelivered", models)
    assert all(p.meta.condition_id.endswith("__msg-undelivered") and not p.meta.channel_delivered for p in plan)
    route = lambda kw: HOSTS[kw["extra_body"].get("provider", {"only": [None]})["only"][0]]
    make_fake = lambda: FakeOpenAI(fn=talking_model("Firm {firm}: bid 99.", provider=route))
    assert not asyncio.run(run_plan(plan, config, models, tmp_path, make_fake)).failed
    logs, _ = load_logs(tmp_path / "undelivered")
    report = check_run(logs)
    assert report.passed, report.findings[:3]

    delivered = prepare(CONFIGS / "channel_tiny.yaml")[2]
    asyncio.run(run_plan(delivered, config | {"channel": {**config["channel"], "delivered": True}}, models, tmp_path, make_fake))
    delivered_logs, _ = load_logs(tmp_path / "channel_tiny")
    relabelled = [replace(log, meta=replace(log.meta, channel_delivered=False)) for log in delivered_logs]
    assert any("by another firm" in f.detail for f in check_run(relabelled).failures("channel"))


def test_digit_filter_removes_every_digit_before_any_firm_sees_the_message_and_keeps_the_text_as_written() -> None:
    fake, _, channel = run_channel(strip_digits=True, text="Firm {firm}: both bid 99.50, then 100 in round 3.")
    assert [e.text for e in channel.events if e.firm_id == "A"] == ["Firm A: both bid ., then  in round ."] * 2
    assert all(e.written == f"Firm {e.firm_id}: both bid 99.50, then 100 in round 3." for e in channel.events)
    for request in fake.requests:
        shown = "\n".join(str(m.get("content") or "") for m in request["messages"] if m["role"] in ("user", "tool"))
        assert "99.50" not in shown and "then 100" not in shown
        assert request["messages"][0]["content"].endswith(f"{CHANNEL_PARAGRAPH} {CHANNEL_DIGITS}")


def test_runner_digit_filter_session_passes_the_checks_and_an_unfiltered_one_would_not(tmp_path: Path) -> None:
    config, models, _ = prepare(CONFIGS / "channel_tiny.yaml")
    config["channel"] = {**config["channel"], "strip_digits": True}
    plan = plan_sessions(config, "nodigits", models)
    assert all(p.meta.condition_id.endswith("__msg-nodigits") and p.meta.channel_strip_digits for p in plan)
    route = lambda kw: HOSTS[kw["extra_body"].get("provider", {"only": [None]})["only"][0]]
    make_fake = lambda: FakeOpenAI(fn=talking_model("Firm {firm}: bid 99.", provider=route))
    assert not asyncio.run(run_plan(plan, config, models, tmp_path, make_fake)).failed
    logs, _ = load_logs(tmp_path / "nodigits")
    report = check_run(logs)
    assert report.passed, report.findings[:3]

    unfiltered = prepare(CONFIGS / "channel_tiny.yaml")[2]
    asyncio.run(run_plan(unfiltered, config | {"channel": {**config["channel"], "strip_digits": False}}, models, tmp_path, make_fake))
    unfiltered_logs, _ = load_logs(tmp_path / "channel_tiny")
    relabelled = [replace(log, meta=replace(log.meta, channel_strip_digits=True)) for log in unfiltered_logs]
    assert any("has a digit" in f.detail for f in check_run(relabelled).failures("channel"))


def test_log_checks_rebuild_a_reworded_prompt_run(tmp_path: Path) -> None:
    """The checks once missed the reworded prompt's token cap and so skipped its exact rebuild."""
    config, models, _ = prepare(CONFIGS / "channel_tiny.yaml")
    config["prompt"] = {"template": "prompts/bidder_system_v2.md", "version": "v2-reworded"}
    plan = plan_sessions(config, "reworded", models)
    route = lambda kw: HOSTS[kw["extra_body"].get("provider", {"only": [None]})["only"][0]]
    assert not asyncio.run(run_plan(plan, config, models, tmp_path, lambda: FakeOpenAI(fn=talking_model(provider=route)))).failed
    logs, _ = load_logs(tmp_path / "reworded")
    report = check_run(logs)
    assert report.passed, report.findings[:3]
    assert report.items["system_prompt"] > 0 and sum(report.caps.values()) == report.items["tokens"]
