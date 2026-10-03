"""OpenRouter wrapper: structured bid extraction via tool call, retries, usage and cost tracking.

Behaviour is specified in PLANNING.md section 2.3; host pinning and routing rules in 5.5.
"""

import json
import math
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from bidrig.schema import CallPhase, CallRow

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
TOOL_NAME = "submit_bid"


class BudgetExceeded(RuntimeError):
    """The config's spending cap is reached; the sweep stops."""


class ProviderError(RuntimeError):
    """The pinned host failed or a different host served the call; the session is abandoned."""


@dataclass(frozen=True)
class Host:
    """One OpenRouter provider endpoint; prices in USD per million tokens."""

    name: str
    quantization: str
    price_in: float
    price_out: float
    role: str = "primary"  # primary | fallback


@dataclass(frozen=True)
class ModelSpec:
    """One alias from configs/models.yaml; prices in USD per million tokens (headline listing)."""

    alias: str
    slug: str
    price_in: float
    price_out: float
    hosts: dict[str, Host] = field(default_factory=dict)

    def host(self, role: str) -> Host | None:
        """The pinned host for `role` (primary | fallback); None if no host is chosen for this model."""
        if not self.hosts:
            return None
        if role not in self.hosts:
            raise ValueError(f"model {self.alias!r} has no {role} host")
        return self.hosts[role]


def load_models(path: Path) -> dict[str, ModelSpec]:
    """Model aliases from a models.yaml file."""
    raw = yaml.safe_load(Path(path).read_text())["models"]
    specs = {}
    for alias, entry in raw.items():
        hosts = {role: Host(role=role, **host) for role, host in (entry.get("providers") or {}).items()}
        specs[alias] = ModelSpec(alias, entry["slug"], entry["price_in"], entry["price_out"], hosts)
    return specs


@dataclass
class SpendTracker:
    """Cumulative spend in USD against a cap; shared by every call of one sweep."""

    cap_usd: float
    spent_usd: float = 0.0

    def check(self) -> None:
        """Raise `BudgetExceeded` once spend has reached the cap."""
        if self.spent_usd >= self.cap_usd:
            raise BudgetExceeded(f"spent ${self.spent_usd:.4f} of a ${self.cap_usd:.2f} cap")

    def add(self, usd: float) -> None:
        """Record one call's cost in USD."""
        self.spent_usd += usd


@dataclass(frozen=True)
class LLMSettings:
    """Per-config call settings; `max_retries` is corrective retries after the first attempt."""

    temperature: float = 1.0
    max_output_tokens: int = 400
    max_retries: int = 2
    reasoning_effort: str | None = "low"


def bid_tool(reserve_price: float) -> dict[str, Any]:
    """The forced tool: a short reasoning string and a bid in [0, reserve_price]."""
    return {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": "Submit your sealed bid for this round.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reasoning": {"type": "string", "description": "Why you chose this bid."},
                    "bid": {"type": "number", "description": f"Your bid, between 0 and {reserve_price:g}."},
                },
                "required": ["reasoning", "bid"],
                "additionalProperties": False,
            },
        },
    }


def call_seed(session_seed: int, round_number: int, slot: int, phase: CallPhase, attempt: int) -> int:
    """Deterministic per-call sampling seed in [0, 2**31)."""
    key = (session_seed, round_number, slot, 1 if phase == "rebid" else 0, attempt)
    value = 0
    for part in key:
        value = (value * 1_000_003 + part) % (2**31 - 1)
    return value


def parse_bid(response: Any, reserve_price: float) -> tuple[float | None, str | None, str | None]:
    """(bid, tool reasoning, error) from a chat completion; bid is None with an error message if unusable."""
    message = response.choices[0].message
    calls = [c for c in (message.tool_calls or []) if c.function.name == TOOL_NAME]
    if not calls:
        return None, None, "no submit_bid tool call"
    try:
        args = json.loads(calls[0].function.arguments)
    except (json.JSONDecodeError, TypeError):
        return None, None, "tool arguments are not valid JSON"
    if not isinstance(args, dict):
        return None, None, "tool arguments are not an object"
    reasoning = args.get("reasoning")
    reasoning = reasoning if isinstance(reasoning, str) else None
    raw_bid = args.get("bid")
    try:
        bid = float(raw_bid) if not isinstance(raw_bid, bool) else math.nan
    except (TypeError, ValueError):
        return None, reasoning, f"bid {raw_bid!r} is not a number"
    if not math.isfinite(bid) or not 0 <= bid <= reserve_price:
        return None, reasoning, f"bid {raw_bid!r} is outside 0 to {reserve_price:g}"
    return bid, reasoning, None


def _corrective(error: str, reserve_price: float) -> dict[str, str]:
    return {
        "role": "user",
        "content": f"Your reply was not accepted ({error}). Call the submit_bid tool with a bid between 0 and "
        f"{reserve_price:g}.",
    }


def _extra(obj: Any, name: str) -> Any:
    """An OpenRouter-specific response field the openai SDK keeps as an extra attribute."""
    return getattr(obj, name, None)


class OpenRouterClient:
    """Forced-tool-call bid requests against one OpenAI-compatible client, with spend tracking."""

    def __init__(self, client: Any, settings: LLMSettings, spend: SpendTracker) -> None:
        self.client = client
        self.settings = settings
        self.spend = spend

    def request_kwargs(
        self, spec: ModelSpec, host: Host | None, messages: Sequence[dict[str, str]], seed: int, reserve_price: float
    ) -> dict[str, Any]:
        """Keyword arguments for `chat.completions.create`, including OpenRouter routing."""
        extra: dict[str, Any] = {"usage": {"include": True}}
        if self.settings.reasoning_effort:
            extra["reasoning"] = {"effort": self.settings.reasoning_effort}
        if host is not None:
            # Never fall back to another host mid-session (PLANNING.md 5.5).
            extra["provider"] = {
                "only": [host.name.lower()],
                "quantizations": [host.quantization],
                "allow_fallbacks": False,
                "require_parameters": True,
            }
        return {
            "model": spec.slug,
            "messages": list(messages),
            "tools": [bid_tool(reserve_price)],
            "tool_choice": {"type": "function", "function": {"name": TOOL_NAME}},
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_output_tokens,
            "seed": seed,
            "extra_body": extra,
        }

    async def request_bid(
        self,
        spec: ModelSpec,
        host: Host | None,
        messages: Sequence[dict[str, str]],
        reserve_price: float,
        *,
        session_id: str,
        session_seed: int,
        round_number: int,
        firm_id: str,
        slot: int,
        phase: CallPhase,
    ) -> tuple[float | None, list[CallRow]]:
        """Ask for one bid, retrying with a corrective message; returns (bid or None, one row per attempt).

        Raises `ProviderError` when the API call itself fails or another host served it, and
        `BudgetExceeded` before an attempt once the cap is reached.
        """
        price_in, price_out = (host.price_in, host.price_out) if host else (spec.price_in, spec.price_out)
        conversation = list(messages)
        rows: list[CallRow] = []
        for attempt in range(1, self.settings.max_retries + 2):
            self.spend.check()
            kwargs = self.request_kwargs(
                spec, host, conversation, call_seed(session_seed, round_number, slot, phase, attempt), reserve_price
            )
            started = time.perf_counter()
            try:
                response = await self.client.chat.completions.create(**kwargs)
            except Exception as exc:  # the SDK has already retried transient errors
                raise ProviderError(f"{spec.alias} call failed: {exc}") from exc
            latency_ms = (time.perf_counter() - started) * 1000
            if not getattr(response, "choices", None):
                raise ProviderError(f"{spec.alias} returned no choices: {response!r}")
            provider = _extra(response, "provider")
            if host is not None and provider is not None and provider.lower() != host.name.lower():
                raise ProviderError(f"{spec.alias} was served by {provider}, not the pinned {host.name}")

            usage = getattr(response, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", None)
            completion_tokens = getattr(usage, "completion_tokens", None)
            self.spend.add(((prompt_tokens or 0) * price_in + (completion_tokens or 0) * price_out) / 1e6)

            bid, reasoning, error = parse_bid(response, reserve_price)
            dump = response.model_dump_json() if hasattr(response, "model_dump_json") else repr(response)
            rows.append(
                CallRow(
                    session_id=session_id,
                    round=round_number,
                    firm_id=firm_id,
                    attempt=attempt,
                    phase=phase,
                    model=spec.alias,
                    provider=provider,
                    prompt=json.dumps(conversation),
                    raw_response=dump,
                    reasoning=reasoning,
                    parsed_bid=bid,
                    error=error,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    latency_ms=latency_ms,
                )
            )
            if error is None:
                return bid, rows
            conversation = [*messages, _corrective(error, reserve_price)]
        return None, rows


def make_openai_client(api_key: str, base_url: str | None = None, max_retries: int = 3) -> Any:
    """Async OpenAI SDK client pointed at OpenRouter; the SDK retries 429, 5xx and timeouts itself."""
    from openai import AsyncOpenAI

    return AsyncOpenAI(api_key=api_key, base_url=base_url or DEFAULT_BASE_URL, max_retries=max_retries, timeout=120)
