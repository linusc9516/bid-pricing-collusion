"""Open message channel: prompts, one message per step, the runner, the toggle, and the log checks; mocked client only."""

import asyncio
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
from bidrig.prompts import CHANNEL_PARAGRAPH, WORKSPACE_PARAGRAPH, system_prompt
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


def run_channel(twice: bool = False) -> tuple[FakeOpenAI, list, Workspace]:
    fake = FakeOpenAI(fn=talking_model(twice=twice))
    meta = make_meta(["llm"] * 2, n_rounds=3)
    meta.channel = True
    client = OpenRouterClient(fake, LLMSettings(), SpendTracker(1.0))
    log: list = []
    channel = Workspace(max_chars=500)
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
