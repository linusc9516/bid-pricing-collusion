"""Trace judge: trace building, sampling, quote verification, parsing, the regex baseline and a mocked judge run."""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from bidrig.analysis.trace_judge import (
    LABELS,
    MIN_QUOTE_CHARS,
    Trace,
    baseline_flags,
    build_trace,
    cache_key,
    estimate_cost,
    judge_messages,
    parse_judgement,
    quote_found,
    sample_traces,
    traces_from_calls,
)
from bidrig.llm import LLMSettings, ModelSpec, OpenRouterClient, SpendTracker
from bidrig.schema import CallRow

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def call(sid: str, rnd: int, firm: str, *, thinking: str | None = "think text", reasoning: str | None = "stated", error: str | None = None, attempt: int = 1, phase: str = "bid") -> CallRow:
    return CallRow(
        session_id=sid, round=rnd, firm_id=firm, attempt=attempt, phase=phase, model="m", provider="P", prompt="[]",
        raw_response=None, reasoning=reasoning, parsed_bid=1.0, error=error, prompt_tokens=1, completion_tokens=1,
        latency_ms=1.0, thinking=thinking,
    )  # fmt: skip


def test_trace_combines_thinking_and_reasoning_and_trims_long_text() -> None:
    assert build_trace("a", "b") == "[thinking]\na\n\n[stated reasoning]\nb"
    assert build_trace(None, None) == ""
    long = build_trace("x" * 20_000, "end")
    assert len(long) < 8_100 and "middle omitted" in long and long.endswith("end")


def test_traces_use_last_accepted_attempt_and_skip_empty() -> None:
    calls = [
        call("s", 1, "A", attempt=1, error="bad", thinking="first"),
        call("s", 1, "A", attempt=2, thinking="second"),
        call("s", 1, "B", thinking=None, reasoning=None),
        call("s", 1, "A", phase="rebid", thinking="rebid text"),
    ]
    traces = traces_from_calls(calls)
    assert [(t.round, t.firm_id) for t in traces] == [(1, "A")]
    assert "second" in traces[0].text and "first" not in traces[0].text


def test_sample_is_evenly_spaced_per_session() -> None:
    traces = [Trace("a", r, "A", "m", "t") for r in range(1, 51)] + [Trace("b", r, "A", "m", "t") for r in range(1, 4)]
    sampled = sample_traces(traces, 5)
    assert [t.round for t in sampled if t.session_id == "a"] == [1, 11, 21, 31, 41]
    assert len([t for t in sampled if t.session_id == "b"]) == 3
    assert len(sample_traces(traces, None)) == len(traces)


def test_quote_must_be_verbatim_and_long_enough() -> None:
    text = "We could\ntake turns   winning the contract here."
    assert quote_found("take turns winning the contract", text)
    assert quote_found("TAKE TURNS WINNING", text)  # case is ignored
    assert not quote_found("take turns", text)  # present, but shorter than the minimum
    assert not quote_found("keep prices high together", text)
    assert not quote_found(None, text)
    assert MIN_QUOTE_CHARS > 5


def test_parse_keeps_only_labels_with_a_found_quote() -> None:
    text = "The rival bid low last round, so I think they will undercut again. Maybe keep prices high together."
    reply = json.dumps({
        "rival_modeling": {"present": True, "quote": "they will undercut again"},
        "history_inference": {"present": True, "quote": "this phrase is not in the text"},
        "adopts_coordination": {"present": False, "quote": None},
    })
    out = parse_judgement(f"```json\n{reply}\n```", text)
    assert out["parse_ok"] and out["rival_modeling"] and not out["history_inference"]
    assert out["quote_ok"] is False and out["claimed"] == ["rival_modeling", "history_inference"]
    assert out["rival_modeling_quote"] == "they will undercut again"
    assert not any(out[n] for n in LABELS if n != "rival_modeling")


def test_parse_failure_returns_all_false() -> None:
    out = parse_judgement("no json here", "text")
    assert out["parse_ok"] is False and not any(out[n] for n in LABELS)


def test_baseline_ignores_alternatively_but_finds_rotation() -> None:
    assert not baseline_flags("Alternatively, I could bid 50. The reward is small.")["take_turns"]
    assert baseline_flags("We could take turns winning.")["take_turns"]
    assert baseline_flags("Tacit collusion is possible.")["collude"]


def test_judge_prompt_hides_arm_and_session() -> None:
    messages = judge_messages(Trace("oneshot__tie-random__seed1", 7, "A", "deepseek", "I bid 60."))
    blob = json.dumps(messages)
    assert "oneshot" not in blob and "deepseek" not in blob and "tie-random" not in blob and "I bid 60." in blob


def test_cache_key_depends_on_model_rubric_and_call() -> None:
    a = Trace("s", 1, "A", "m", "t")
    assert cache_key("gemini", a) != cache_key("glm", a)
    assert cache_key("gemini", a) != cache_key("gemini", Trace("s", 2, "A", "m", "t"))
    assert estimate_cost([a], 1.0, 1.0) > 0


def test_judge_all_with_a_fake_client_caches_replies_and_tracks_spend(tmp_path: Path) -> None:
    from judge_traces import judge_all

    reply = json.dumps({n: {"present": False, "quote": None} for n in LABELS})
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=reply))], usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=100)
    )
    sent = []

    async def create(**kwargs):
        sent.append(kwargs)
        return response

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    spend = SpendTracker(10.0)
    client = OpenRouterClient(fake, LLMSettings(), spend)
    spec = ModelSpec(alias="gemini", slug="google/x", price_in=1.0, price_out=2.0)
    traces = [Trace("s", r, "A", "m", f"text {r}") for r in (1, 2, 3)]
    cache: dict = {}
    path = tmp_path / "cache.jsonl"
    asyncio.run(judge_all(client, spec, traces, 2, cache, path))
    assert len(sent) == 3 and all("tools" not in k and k["temperature"] == 0.0 for k in sent)
    assert spend.spent_usd == pytest.approx(3 * (1000 * 1.0 + 100 * 2.0) / 1e6)
    assert len(path.read_text().splitlines()) == 3 and len(cache) == 3
    asyncio.run(judge_all(client, spec, traces, 2, cache, path))
    assert len(sent) == 3  # cached calls are not sent again
