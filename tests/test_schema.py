"""Schema round-trips through the on-disk session layout."""

import json
from dataclasses import fields
from pathlib import Path

import pytest

from bidrig.schema import (
    BidRow,
    CallRow,
    LineupEntry,
    SessionMeta,
    firm_ids,
    read_session,
    session_dir,
    write_session,
)

# PLANNING.md section 3, in table order.
SESSION_FIELDS = [
    "run_id", "condition_id", "session_id", "seed", "n_bidders", "info_condition",
    "tie_break_rule", "lineup_id", "lineup", "cost_low", "cost_high", "reserve_price",
    "bid_increment", "n_rounds", "cost_spread", "reveal_costs", "history_window", "temperature", "prompt_version",
    "providers", "provider_retries", "provider_errors", "git_sha", "started_at", "finished_at", "status",
]  # fmt: skip
BID_FIELDS = [
    "session_id", "round", "firm_id", "cost", "bid", "is_winner", "winning_bid", "profit",
    "valid", "n_attempts", "tie_broken", "tied", "n_tied", "tie_resolution", "rebid",
    "bne_bid", "is_min_cost", "model",
]  # fmt: skip
CALL_FIELDS = [
    "session_id", "round", "firm_id", "attempt", "phase", "model", "provider", "prompt",
    "raw_response", "reasoning", "parsed_bid", "error", "prompt_tokens", "completion_tokens",
    "latency_ms", "reasoning_tokens", "finish_reason", "thinking", "content",
]  # fmt: skip


def make_meta() -> SessionMeta:
    return SessionMeta(
        run_id="run",
        condition_id="tie-random__info-full__lineup-dummy-bne__n3",
        session_id="s000",
        seed=7,
        n_bidders=3,
        info_condition="full",
        tie_break_rule="random",
        lineup_id="dummy-bne",
        lineup=[LineupEntry(f, "bne") for f in firm_ids(3)],
        cost_low=0,
        cost_high=100,
        reserve_price=100,
        bid_increment=0.01,
        n_rounds=1,
    )


def make_row(firm_id: str, is_winner: bool) -> BidRow:
    return BidRow(
        session_id="s000", round=1, firm_id=firm_id, cost=10.0, bid=40.0, is_winner=is_winner,
        winning_bid=40.0, profit=30.0 if is_winner else 0.0, valid=True, n_attempts=1,
        tie_broken=False, tied=False, n_tied=1, tie_resolution="none", rebid=None,
        bne_bid=40.0, is_min_cost=is_winner, model=None,
    )  # fmt: skip


def test_field_names_match_plan() -> None:
    assert [f.name for f in fields(SessionMeta)] == SESSION_FIELDS
    assert [f.name for f in fields(BidRow)] == BID_FIELDS
    assert [f.name for f in fields(CallRow)] == CALL_FIELDS


def test_firm_ids() -> None:
    assert firm_ids(3) == ["A", "B", "C"]
    with pytest.raises(ValueError):
        firm_ids(27)


def test_is_control_only_for_window_zero() -> None:
    meta = make_meta()
    assert not meta.is_control
    meta.history_window = 0
    assert meta.is_control


def test_session_round_trip(tmp_path: Path) -> None:
    meta = make_meta()
    rows = [make_row("A", True), make_row("B", False), make_row("C", False)]
    out = write_session(tmp_path, meta, rows)
    assert out == session_dir(tmp_path, meta) == tmp_path / "run" / meta.condition_id / "s000"
    loaded_meta, loaded_rows = read_session(out)
    assert loaded_meta == meta
    assert loaded_rows == rows
    assert json.loads((out / "session.json").read_text())["history_window"] is None
    assert len((out / "bids.jsonl").read_text().splitlines()) == 3


def test_call_row_round_trip() -> None:
    call = CallRow(
        session_id="s000", round=1, firm_id="A", attempt=1, phase="rebid", model="deepseek",
        provider="Morph", prompt="p", raw_response="r", reasoning="because", parsed_bid=41.5,
        error=None, prompt_tokens=100, completion_tokens=20, latency_ms=350.0,
    )  # fmt: skip
    assert CallRow.from_dict(json.loads(json.dumps(call.to_dict()))) == call


def test_trace_fields_from_each_response_shape() -> None:
    from bidrig.schema import trace_fields

    thinking_on = {"choices": [{"finish_reason": "tool_calls", "message": {"content": None, "reasoning": "step by step", "reasoning_details": [{"text": "step by step"}]}}],
                   "usage": {"completion_tokens_details": {"reasoning_tokens": 77}}}
    assert trace_fields(thinking_on) == {"reasoning_tokens": 77, "finish_reason": "tool_calls", "thinking": "step by step", "content": None}
    details_only = {"choices": [{"message": {"reasoning_details": [{"text": "a"}, {"summary": "b"}, {"text": ""}]}}]}
    assert trace_fields(details_only)["thinking"] == "a\nb"
    chatty = {"choices": [{"finish_reason": "length", "message": {"content": "Notes before the tool call."}}], "usage": {}}
    assert trace_fields(chatty) == {"reasoning_tokens": None, "finish_reason": "length", "thinking": None, "content": "Notes before the tool call."}
    assert trace_fields({}) == {"reasoning_tokens": None, "finish_reason": None, "thinking": None, "content": None}


def test_old_call_rows_are_filled_from_their_raw_response(tmp_path: Path) -> None:
    from bidrig.schema import read_calls

    raw = json.dumps({"choices": [{"finish_reason": "length", "message": {"content": "hi", "reasoning": "why"}}], "usage": {"completion_tokens_details": {"reasoning_tokens": 5}}})
    old = {k: None for k in CALL_FIELDS[:-4]} | {"session_id": "s", "round": 1, "firm_id": "A", "attempt": 1, "phase": "bid", "model": "m", "prompt": "[]", "raw_response": raw}
    (tmp_path / "calls.jsonl").write_text(json.dumps(old) + "\n")  # a row written before the four fields existed
    (row,) = read_calls(tmp_path)
    assert (row.finish_reason, row.thinking, row.content, row.reasoning_tokens) == ("length", "why", "hi", 5)
    assert read_calls(tmp_path / "missing") == []
