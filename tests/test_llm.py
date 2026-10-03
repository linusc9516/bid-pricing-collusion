"""OpenRouter wrapper and LLM bidder against a mocked client; no network."""

import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from helpers import make_meta

from bidrig.auction import run_session
from bidrig.bidders import LLMBidder
from bidrig.llm import (
    BudgetExceeded,
    Host,
    LLMSettings,
    ModelSpec,
    OpenRouterClient,
    ProviderError,
    SpendTracker,
    call_seed,
    load_models,
    parse_bid,
)
from bidrig.schema import BidRequest

MODELS = Path(__file__).parents[1] / "configs" / "models.yaml"
SPEC = ModelSpec("deepseek", "deepseek/deepseek-v4.1-flash", 0.021, 0.383)
HOST = Host("Morph", "fp8", 0.021, 0.383)


def completion(
    args: dict[str, Any] | str | None, provider: str | None = "Morph", tokens: tuple[int, int] = (500, 100)
) -> SimpleNamespace:
    """A chat completion shaped like the openai SDK's, with OpenRouter's `provider` field."""
    tool_calls = None
    if args is not None:
        arguments = args if isinstance(args, str) else json.dumps(args)
        tool_calls = [SimpleNamespace(function=SimpleNamespace(name="submit_bid", arguments=arguments))]
    message = SimpleNamespace(content=None, tool_calls=tool_calls, reasoning="hidden thoughts")
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        provider=provider,
        usage=SimpleNamespace(prompt_tokens=tokens[0], completion_tokens=tokens[1]),
    )


class FakeOpenAI:
    """Returns queued responses (or calls a function of the request) and records every request."""

    def __init__(self, responses: list[Any] | None = None, fn: Any = None) -> None:
        self.responses = list(responses or [])
        self.fn = fn
        self.requests: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        item = self.fn(kwargs) if self.fn else self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def ask(fake: FakeOpenAI, host: Host | None = HOST, cap: float = 10.0, **settings: Any) -> tuple:
    client = OpenRouterClient(fake, LLMSettings(**settings), SpendTracker(cap))
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    result = asyncio.run(
        client.request_bid(
            SPEC, host, messages, 100, session_id="s", session_seed=5, round_number=3, firm_id="B", slot=1, phase="bid"
        )
    )
    return (*result, client)


def test_valid_tool_call_is_parsed() -> None:
    fake = FakeOpenAI([completion({"reasoning": "Bid above cost.", "bid": 61.237})])
    bid, rows, client = ask(fake)
    assert bid == 61.237
    (row,) = rows
    assert (row.attempt, row.phase, row.model, row.provider, row.error) == (1, "bid", "deepseek", "Morph", None)
    assert (row.reasoning, row.parsed_bid, row.prompt_tokens, row.completion_tokens) == ("Bid above cost.", 61.237, 500, 100)
    assert "hidden thoughts" in row.raw_response
    assert json.loads(row.prompt)[1]["content"] == "u"
    assert client.spend.spent_usd == pytest.approx((500 * 0.021 + 100 * 0.383) / 1e6)


def test_request_forces_the_tool_and_pins_the_host() -> None:
    fake = FakeOpenAI([completion({"reasoning": "r", "bid": 50})])
    ask(fake, temperature=1.0, max_output_tokens=400, reasoning_effort="low")
    (kw,) = fake.requests
    assert kw["model"] == "deepseek/deepseek-v4.1-flash"
    assert kw["tool_choice"] == {"type": "function", "function": {"name": "submit_bid"}}
    assert kw["tools"][0]["function"]["parameters"]["required"] == ["reasoning", "bid"]
    assert (kw["temperature"], kw["max_tokens"]) == (1.0, 400)
    assert kw["seed"] == call_seed(5, 3, 1, "bid", 1)
    provider = kw["extra_body"]["provider"]
    assert provider == {"only": ["morph"], "quantizations": ["fp8"], "allow_fallbacks": False, "require_parameters": True}
    assert kw["extra_body"]["reasoning"] == {"effort": "low"}


def test_unpinned_model_has_no_provider_block() -> None:
    fake = FakeOpenAI([completion({"reasoning": "r", "bid": 50}, provider="Alibaba")])
    bid, _, client = ask(fake, host=None, reasoning_effort=None)
    assert bid == 50
    assert "provider" not in fake.requests[0]["extra_body"] and "reasoning" not in fake.requests[0]["extra_body"]
    assert client.spend.spent_usd == pytest.approx((500 * 0.021 + 100 * 0.383) / 1e6)


@pytest.mark.parametrize(
    ("bad", "error"),
    [
        (None, "no submit_bid tool call"),
        ("{not json", "not valid JSON"),
        ({"reasoning": "r", "bid": 140}, "outside"),
        ({"reasoning": "r", "bid": -1}, "outside"),
        ({"reasoning": "r", "bid": "cheap"}, "not a number"),
        ({"reasoning": "r", "bid": True}, "outside"),
        ({"reasoning": "r"}, "not a number"),
    ],
)
def test_bad_reply_is_retried_with_a_correction(bad: Any, error: str) -> None:
    fake = FakeOpenAI([completion(bad), completion({"reasoning": "r", "bid": 70})])
    bid, rows, _ = ask(fake)
    assert bid == 70
    assert [r.attempt for r in rows] == [1, 2]
    assert error in rows[0].error and rows[1].error is None
    retry_messages = fake.requests[1]["messages"]
    assert len(retry_messages) == 3 and "not accepted" in retry_messages[2]["content"]
    assert fake.requests[1]["seed"] != fake.requests[0]["seed"]


def test_numeric_string_bid_is_accepted() -> None:
    bid, _, _ = parse_bid(completion({"reasoning": "r", "bid": "55.5"}), 100)
    assert bid == 55.5


def test_firm_sits_out_after_max_retries() -> None:
    fake = FakeOpenAI([completion(None)] * 3)
    bid, rows, client = ask(fake, max_retries=2)
    assert bid is None and len(rows) == 3 and len(fake.requests) == 3
    assert client.spend.spent_usd == pytest.approx(3 * (500 * 0.021 + 100 * 0.383) / 1e6)
    # Each retry carries one correction, not a growing pile of them.
    assert all(len(r["messages"]) == 3 for r in fake.requests[1:])


def test_api_failure_abandons_the_session() -> None:
    with pytest.raises(ProviderError):
        ask(FakeOpenAI([RuntimeError("502 bad gateway")]))
    with pytest.raises(ProviderError):
        ask(FakeOpenAI([SimpleNamespace(choices=[], provider="Morph")]))


def test_a_different_host_abandons_the_session() -> None:
    with pytest.raises(ProviderError, match="DeepInfra"):
        ask(FakeOpenAI([completion({"reasoning": "r", "bid": 50}, provider="DeepInfra")]))
    bid, _, _ = ask(FakeOpenAI([completion({"reasoning": "r", "bid": 50}, provider="morph")]))
    assert bid == 50


def test_budget_cap_stops_before_the_next_call() -> None:
    fake = FakeOpenAI([completion(None, tokens=(1_000_000, 0))] * 3)
    with pytest.raises(BudgetExceeded):
        ask(fake, cap=0.03)
    assert len(fake.requests) == 2  # 0.021 after one call, 0.042 after two, then the cap holds


def test_call_seed_is_deterministic_and_distinct() -> None:
    seeds = {call_seed(7, r, s, p, a) for r in range(1, 51) for s in range(5) for p in ("bid", "rebid") for a in (1, 2, 3)}
    assert len(seeds) == 50 * 5 * 2 * 3
    assert all(0 <= s < 2**31 for s in seeds)
    assert call_seed(7, 1, 0, "bid", 1) == call_seed(7, 1, 0, "bid", 1)


def test_models_yaml_loads() -> None:
    specs = load_models(MODELS)
    assert set(specs) == {"deepseek", "gpt-oss", "glm", "qwen"}
    assert specs["deepseek"].host("primary") == Host("Morph", "fp8", 0.021, 0.383, "primary")
    assert specs["gpt-oss"].host("fallback").name == "AkashML"
    assert specs["glm"].host("primary") is None


# --- the LLM bidder inside a real session ---


def test_llm_bidders_play_a_session_through_the_filter() -> None:
    """Each prompt holds only earlier rounds, and never another firm's cost."""

    def reply(kwargs: dict[str, Any]) -> SimpleNamespace:
        user = kwargs["messages"][1]["content"]
        cost = float(user.split("Your cost for this round is ")[1].split(".\n")[0])
        return completion({"reasoning": "Cost plus a margin.", "bid": min(cost + 20, 100)})

    fake = FakeOpenAI(fn=reply)
    meta = make_meta(["llm"] * 3, rule="bafo", n_rounds=6)
    client = OpenRouterClient(fake, LLMSettings(), SpendTracker(1.0))
    log: list = []
    bidders = [LLMBidder(SPEC, HOST, client, meta, log) for _ in range(3)]
    rows = asyncio.run(run_session(meta, bidders, log))
    assert rows is log and len(rows) == 18
    assert all(r.model == "deepseek" and r.n_attempts == 1 for r in rows)
    calls = [c for b in bidders for c in b.calls]
    assert len(calls) == 18 and len(fake.requests) == 18
    for request in fake.requests:
        user = request["messages"][1]["content"]
        own_cost = float(user.split("Your cost for this round is ")[1].split(".\n")[0])
        current = next(r.round for r in rows if r.cost == own_cost)
        shown_rounds = {int(x) for x in re.findall(r"Round (\d+):", user)}
        assert shown_rounds == set(range(1, current))
        firm = next(r.firm_id for r in rows if r.cost == own_cost and r.round == current)
        numbers = set(re.findall(r"-?\d+\.\d\d", user))
        public = {f"{v:.2f}" for r in rows for v in (r.bid, r.rebid, r.winning_bid) if v is not None}
        own = {f"{v:.2f}" for r in rows if r.firm_id == firm for v in (r.cost, r.profit)}
        others = {f"{r.cost:.2f}" for r in rows if r.firm_id != firm}
        assert not (numbers & others) - public - own


def test_llm_bidder_rebid_call_is_logged_as_rebid() -> None:
    fake = FakeOpenAI(
        fn=lambda kw: completion(
            {"reasoning": "r", "bid": 40 if "tied for lowest:" in kw["messages"][1]["content"] else 60}
        )
    )
    meta = make_meta(["llm"] * 2, rule="bafo", n_rounds=2)
    client = OpenRouterClient(fake, LLMSettings(), SpendTracker(1.0))
    log: list = []
    bidders = [LLMBidder(SPEC, HOST, client, meta, log) for _ in range(2)]
    rows = asyncio.run(run_session(meta, bidders, log))
    assert all(r.tied and r.rebid == 40 for r in rows)
    phases = [c.phase for b in bidders for c in b.calls]
    assert phases.count("rebid") == 4 and phases.count("bid") == 4
    assert all(r.n_attempts == 1 for r in rows)


def test_llm_bidder_satisfies_the_request_shape() -> None:
    fake = FakeOpenAI([completion({"reasoning": "r", "bid": 42})])
    meta = make_meta(["llm"] * 3)
    bidder = LLMBidder(SPEC, HOST, OpenRouterClient(fake, LLMSettings(), SpendTracker(1.0)), meta, [])
    response = asyncio.run(bidder.bid(BidRequest("A", 0, 1, 30.0)))
    assert (response.bid, response.n_attempts) == (42, 1)
    assert bidder.model == "deepseek" and bidder.bidder_type == "llm"
    assert "No earlier rounds are shown." in fake.requests[0]["messages"][1]["content"]
