"""Shared notes workspace: locking, the reflection tool loop, prompts, the runner and the log checks; mocked client only."""

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from helpers import make_meta
from test_checks import COST_LINE, HOSTS
from test_llm import HOST, SPEC, FakeOpenAI, completion

from bidrig.auction import run_session
from bidrig.bidders import LLMBidder
from bidrig.checks import check_run, load_logs
from bidrig.llm import LLMSettings, OpenRouterClient, SpendTracker
from bidrig.prompts import WORKSPACE_PARAGRAPH, system_prompt
from bidrig.runner import plan_sessions, prepare, run_plan
from bidrig.schema import read_workspace_events
from bidrig.workspace import Workspace, notes_before

CONFIGS = Path(__file__).parents[1] / "configs"


def tool_reply(*calls: tuple[str, dict[str, Any]], provider: str | None = "Morph") -> SimpleNamespace:
    """A completion that makes the given tool calls."""
    reply = completion(None, provider=provider)
    reply.choices[0].message.tool_calls = [
        SimpleNamespace(id=f"t{i}", function=SimpleNamespace(name=name, arguments=json.dumps(args)))
        for i, (name, args) in enumerate(calls)
    ]
    return reply


def reflecting_model(note: str = "Firm {firm} plans to bid high.", provider: Any = "Morph") -> Any:
    """Bids cost + 20; in a reflection reads, then writes one note, then ends."""

    def reply(kwargs: dict[str, Any]) -> Any:
        host = provider(kwargs) if callable(provider) else provider
        messages = kwargs["messages"]
        user = messages[1]["content"]
        if "reflection step" not in user:
            cost = float(COST_LINE.search(user).group(1))
            return completion({"reasoning": "r", "bid": min(cost + 20, 100)}, provider=host)
        done = {m["tool_calls"][0]["function"]["name"] for m in messages if m.get("role") == "assistant"}
        firm = messages[0]["content"].split("Firm ")[1][0]
        if "read_workspace" not in done:
            return tool_reply(("read_workspace", {}), provider=host)
        if "write_workspace" not in done:
            return tool_reply(("write_workspace", {"text": note.format(firm=firm)}), provider=host)
        return tool_reply(("end_reflection", {}), provider=host)

    return reply


def test_concurrent_writes_are_all_kept_in_order() -> None:
    workspace = Workspace(max_chars=5)

    async def go() -> None:
        await asyncio.gather(*(workspace.write(f, 1, f"{f} note") for f in "ABCDEF"))
        assert await workspace.read("A", 1) and (await workspace.write("A", 2, "short")).truncated is False

    asyncio.run(go())
    writes = [e for e in workspace.events if e.op == "write"]
    assert [e.seq for e in workspace.events] == list(range(1, 9))
    assert {e.firm_id for e in writes} == set("ABCDEF") and all(e.truncated for e in writes[:6])
    read = next(e for e in workspace.events if e.op == "read")
    assert (read.n_notes, read.n_foreign) == (6, 5)


def test_system_prompt_mentions_the_workspace_but_not_who_reads_it() -> None:
    meta = make_meta(["llm"] * 2, n_rounds=3)
    assert WORKSPACE_PARAGRAPH not in system_prompt(meta, "A", "short", 400)
    meta.workspace = True
    text = system_prompt(meta, "A", "short", 400)
    assert text.endswith(WORKSPACE_PARAGRAPH)
    assert not any(word in WORKSPACE_PARAGRAPH.lower() for word in ("other firm", "shared", "private", "communicat"))


def test_reflection_reaches_the_other_firms_next_bid() -> None:
    fake = FakeOpenAI(fn=reflecting_model())
    meta = make_meta(["llm"] * 2, n_rounds=3)
    meta.workspace = True
    client = OpenRouterClient(fake, LLMSettings(), SpendTracker(1.0))
    log: list = []
    workspace = Workspace()
    bidders = [LLMBidder(SPEC, HOST, client, meta, log, workspace=workspace) for _ in range(2)]

    async def between(round_number: int) -> None:
        await asyncio.gather(*(b.reflect(round_number, slot) for slot, b in enumerate(bidders)))

    asyncio.run(run_session(meta, bidders, log, between_rounds=between))
    reflect = [c for b in bidders for c in b.calls if c.phase == "reflect"]
    assert sorted({c.round for c in reflect}) == [1, 2]  # none after the last round
    assert sorted(c.attempt for c in reflect if (c.round, c.firm_id) == (1, "A")) == [1, 2, 3]
    writes = [e for e in workspace.events if e.op == "write"]
    assert sorted((e.round, e.firm_id) for e in writes) == [(1, "A"), (1, "B"), (2, "A"), (2, "B")]
    round3_bid_a = next(r for r in fake.requests if "reflection step" not in r["messages"][1]["content"] and "Round 2:" in r["messages"][1]["content"] and "Firm A" in r["messages"][0]["content"])
    user = round3_bid_a["messages"][1]["content"]
    assert "[after round 1, Firm B] Firm B plans to bid high." in user and "[after round 2, Firm A (you)]" in user
    round1 = [r for r in fake.requests if "No earlier rounds" in r["messages"][1]["content"] and "reflection" not in r["messages"][1]["content"]]
    assert all("The notes workspace is empty." in r["messages"][1]["content"] for r in round1)


def test_reflection_stops_at_the_step_cap_and_without_tool_calls() -> None:
    fake = FakeOpenAI([tool_reply(("read_workspace", {}))] * 5 + [completion(None)])
    meta = make_meta(["llm"] * 2, n_rounds=2)
    meta.workspace = True
    client = OpenRouterClient(fake, LLMSettings(), SpendTracker(1.0))
    bidder = LLMBidder(SPEC, HOST, client, meta, [], workspace=Workspace(), reflection_steps=4)
    asyncio.run(bidder.reflect(1, 0))
    assert [c.attempt for c in bidder.calls] == [1, 2, 3, 4]
    assert fake.requests[1]["messages"][-1]["role"] == "tool" and fake.requests[1]["tool_choice"] == "auto"
    bidder.calls.clear()
    asyncio.run(bidder.reflect(1, 0))  # one more read, then a reply with no tool call ends the step
    assert [c.error for c in bidder.calls] == [None, "no tool call"]


def test_workspace_config_plans_and_refuses_a_one_shot_control() -> None:
    config, models, plan = prepare(CONFIGS / "workspace_screen_n2.yaml", "x")
    assert len(plan) == 10 and all(p.meta.workspace and p.meta.condition_id.endswith("__ws") for p in plan)
    assert plan[0].n_llm_calls == (25 + 24) * 2
    twin = prepare(CONFIGS / "rotation_screen_n2.yaml", "x")[2]
    assert {p.meta.seed for p in plan} == {p.meta.seed for p in twin}
    config["sweep"] = {"history_window": [None, 0]}
    with pytest.raises(ValueError, match="one-shot"):
        plan_sessions(config, "x", models)


def test_runner_writes_the_workspace_and_the_checks_pass(tmp_path: Path) -> None:
    config, models, plan = prepare(CONFIGS / "workspace_tiny.yaml")
    route = lambda kw: HOSTS[kw["extra_body"].get("provider", {"only": [None]})["only"][0]]
    fake = FakeOpenAI(fn=reflecting_model("Cost was 12.34; bid {firm}.", provider=route))
    result = asyncio.run(run_plan(plan, config, models, tmp_path, lambda: fake))
    assert not result.failed and len(result.completed) == 2
    logs, _ = load_logs(tmp_path / "workspace_tiny")
    report = check_run(logs)
    assert report.passed, report.findings[:3]
    assert report.items["workspace"] == 2
    events = read_workspace_events(logs[0].path)
    assert [e["op"] for e in events].count("write") == 4
    phases = [c.phase for c in logs[0].calls]
    assert phases.count("bid") == 6 and phases.count("reflect") == 12


def test_private_workspace_reads_and_shows_only_the_firms_own_notes() -> None:
    workspace = Workspace(shared=False)

    async def go() -> tuple[str, list]:
        await workspace.write("A", 1, "A note")
        await workspace.write("B", 1, "B note")
        return await workspace.read("A", 1), await workspace.notes_before(2, "A")

    text, shown = asyncio.run(go())
    assert "A note" in text and "B note" not in text and [n.text for n in shown] == ["A note"]
    read = next(e for e in workspace.events if e.op == "read")
    assert (read.n_notes, read.n_foreign) == (1, 0)
    assert [n.text for n in notes_before(workspace.events, 2)] == ["A note", "B note"]  # the log keeps both


def test_private_notes_never_reach_the_other_firm() -> None:
    fake = FakeOpenAI(fn=reflecting_model())
    meta = make_meta(["llm"] * 2, n_rounds=3)
    meta.workspace, meta.workspace_shared = True, False
    client = OpenRouterClient(fake, LLMSettings(), SpendTracker(1.0))
    log: list = []
    workspace = Workspace(shared=False)
    bidders = [LLMBidder(SPEC, HOST, client, meta, log, workspace=workspace) for _ in range(2)]

    async def between(round_number: int) -> None:
        await asyncio.gather(*(b.reflect(round_number, slot) for slot, b in enumerate(bidders)))

    asyncio.run(run_session(meta, bidders, log, between_rounds=between))
    assert len([e for e in workspace.events if e.op == "write"]) == 4
    for request in fake.requests:
        firm = request["messages"][0]["content"].split("Firm ")[1][0]
        other = "B" if firm == "A" else "A"
        shown = "\n".join(str(m.get("content") or "") for m in request["messages"])
        assert f"Firm {other} plans to bid high." not in shown
    assert system_prompt(meta, "A", "short", 400).endswith(WORKSPACE_PARAGRAPH)  # same prompt as the shared arm


def test_runner_private_notes_session_passes_the_checks_and_a_shared_one_would_not(tmp_path: Path) -> None:
    config, models, _ = prepare(CONFIGS / "workspace_tiny.yaml")
    config["workspace"] = {**config["workspace"], "shared": False}
    plan = plan_sessions(config, "private", models)
    assert all(p.meta.condition_id.endswith("__pn") and not p.meta.workspace_shared for p in plan)
    route = lambda kw: HOSTS[kw["extra_body"].get("provider", {"only": [None]})["only"][0]]
    make_fake = lambda: FakeOpenAI(fn=reflecting_model("Cost was 12.34; firm {firm} bids high.", provider=route))
    result = asyncio.run(run_plan(plan, config, models, tmp_path, make_fake))
    assert not result.failed
    logs, _ = load_logs(tmp_path / "private")
    report = check_run(logs)
    assert report.passed, report.findings[:3]
    assert report.items["private_notes"] == 2 and report.items["workspace"] == 2
    reads = [e for e in read_workspace_events(logs[0].path) if e["op"] == "read"]
    assert reads and all(e["n_foreign"] == 0 for e in reads)

    shared = prepare(CONFIGS / "workspace_tiny.yaml")[2]
    asyncio.run(run_plan(shared, config | {"workspace": {**config["workspace"], "shared": True}}, models, tmp_path, make_fake))
    shared_logs, _ = load_logs(tmp_path / "workspace_tiny")
    assert check_run(shared_logs).passed
    relabelled = [replace(log, meta=replace(log.meta, workspace_shared=False)) for log in shared_logs]
    failures = check_run(relabelled).failures("private_notes")
    assert any("foreign" in f.detail for f in failures) and any("by another firm" in f.detail for f in failures)
