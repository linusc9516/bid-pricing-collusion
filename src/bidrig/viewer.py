"""Export of logged sessions to the JSON bundles read by the static example viewer (site/)."""

import json
import math
from collections.abc import Sequence
from typing import Any

from bidrig.schema import BidRow, CallRow, SessionMeta

MAX_THINKING_CHARS = 2500  # hidden thinking text is cut to this many characters; the full length is kept
METRIC_KEYS = [
    "collusion_index", "control_index", "delta_index", "lowest_cost_win_share", "delta_lowest_cost_win_share",
    "repeat_win_rate", "tie_rate", "tie_price_index", "reserve_bid_rate", "below_cost_bid_rate", "bid_cost_corr",
    "rival_lag_coef", "mean_rebid_delta", "invalid_bid_rate",
]  # fmt: skip


def _clean(value: Any) -> Any:
    """JSON-safe value: NaN and infinity become None, numpy scalars become Python numbers."""
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _messages(call: CallRow) -> dict[str, str]:
    """`{system, user}` text of a logged call; the prompt is stored as a JSON list of chat messages."""
    messages = json.loads(call.prompt)
    out = {"system": "", "user": ""}
    for message in messages:
        if message["role"] in out:
            out[message["role"]] = message["content"]
    return out


def _call_bundle(call: CallRow, max_thinking: int) -> dict[str, Any]:
    """One LLM attempt: reasoning field, hidden thinking (truncated), free text, error, tokens and the user message."""
    thinking = call.thinking or ""
    return {
        "phase": call.phase,
        "attempt": call.attempt,
        "reasoning": call.reasoning,
        "thinking": thinking[:max_thinking] or None,
        "thinking_chars": len(thinking),
        "content": call.content,
        "bid": _clean(call.parsed_bid),
        "error": call.error,
        "finish": call.finish_reason,
        "tokens": [call.prompt_tokens, call.completion_tokens, call.reasoning_tokens],
        "user": _messages(call)["user"],
    }


def session_bundle(
    meta: SessionMeta,
    rows: Sequence[BidRow],
    calls: Sequence[CallRow],
    metrics: dict[str, Any] | None = None,
    max_thinking: int = MAX_THINKING_CHARS,
) -> dict[str, Any]:
    """Everything the viewer shows for one session: settings, metrics, rounds, per-firm calls and system prompts."""
    models = {entry.firm_id: entry.model or entry.bidder_type for entry in meta.lineup}
    by_key: dict[tuple[int, str], list[CallRow]] = {}
    systems: dict[str, str] = {}
    for call in calls:
        by_key.setdefault((call.round, call.firm_id), []).append(call)
        systems.setdefault(call.firm_id, _messages(call)["system"])
    rounds = []
    for number in sorted({row.round for row in rows}):
        in_round = [row for row in rows if row.round == number]
        winner = next((row for row in in_round if row.is_winner), None)
        rounds.append(
            {
                "n": number,
                "winner": winner.firm_id if winner else None,
                "price": _clean(winner.winning_bid) if winner else None,
                "tie": in_round[0].tie_resolution,
                "firms": [
                    {
                        "id": row.firm_id,
                        "cost": _clean(row.cost),
                        "bid": _clean(row.bid),
                        "rebid": _clean(row.rebid),
                        "bne": round(float(row.bne_bid), 4),
                        "profit": _clean(row.profit),
                        "won": row.is_winner,
                        "tied": row.tied,
                        "valid": row.valid,
                        "min_cost": row.is_min_cost,
                        "calls": [_call_bundle(c, max_thinking) for c in by_key.get((number, row.firm_id), [])],
                    }
                    for row in sorted(in_round, key=lambda r: r.firm_id)
                ],
            }
        )
    return {
        "id": meta.session_id,
        "condition": meta.condition_id,
        "control": meta.is_control,
        "meta": {
            "seed": meta.seed,
            "n_bidders": meta.n_bidders,
            "tie_break_rule": meta.tie_break_rule,
            "info": meta.info_condition,
            "models": models,
            "cost_range": [meta.cost_low, meta.cost_high],
            "reserve": meta.reserve_price,
            "increment": meta.bid_increment,
            "n_rounds": meta.n_rounds,
            "history_window": meta.history_window,
            "prompt_version": meta.prompt_version,
            "providers": {k: f"{v.get('name', '')}".strip() for k, v in meta.providers.items()},
        },
        "metrics": {k: _clean((metrics or {}).get(k)) for k in METRIC_KEYS},
        "system": systems,
        "rounds": rounds,
    }
