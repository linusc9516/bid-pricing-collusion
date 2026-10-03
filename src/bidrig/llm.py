"""OpenRouter wrapper: structured bid extraction via tool call, retries, usage and cost tracking.

Behaviour is specified in PLANNING.md section 2.3; host pinning and routing rules in 5.5.
"""

import asyncio
import json
import math
import random
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from bidrig.schema import CallPhase, CallRow, trace_fields

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
TOOL_NAME = "submit_bid"
HOST_TIERS = ("primary", "fallback", "backup")  # order a failed session moves down; never switch inside a session
ERROR_LOG_LIMIT = 20  # provider errors kept per session in session.json


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
    role: str = "primary"  # one of HOST_TIERS


@dataclass(frozen=True)
class ModelSpec:
    """One alias from configs/models.yaml; prices in USD per million tokens (headline listing)."""

    alias: str
    slug: str
    price_in: float
    price_out: float
    hosts: dict[str, Host] = field(default_factory=dict)
    reasoning: dict[str, Any] | None = None  # OpenRouter `reasoning` object; None = use the config default

    def host(self, role: str) -> Host | None:
        """The pinned host for `role`; a model with fewer tiers uses its last tier below `role`, None if none is pinned."""
        if not self.hosts:
            return None
        if role not in HOST_TIERS:
            raise ValueError(f"host role must be one of {HOST_TIERS}, got {role!r}")
        for tier in reversed(HOST_TIERS[: HOST_TIERS.index(role) + 1]):
            if tier in self.hosts:
                return self.hosts[tier]
        raise ValueError(f"model {self.alias!r} has no host at or below {role}")


def load_models(path: Path) -> dict[str, ModelSpec]:
    """Model aliases from a models.yaml file."""
    raw = yaml.safe_load(Path(path).read_text())["models"]
    specs = {}
    for alias, entry in raw.items():
        hosts = {role: Host(role=role, **host) for role, host in (entry.get("providers") or {}).items()}
        specs[alias] = ModelSpec(alias, entry["slug"], entry["price_in"], entry["price_out"], hosts, entry.get("reasoning"))
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


@dataclass
class ProviderStats:
    """Transient provider errors met by one session; `retries` counts retried requests, `errors` the first few failures."""

    retries: int = 0
    errors: list[str] = field(default_factory=list)

    def record(self, message: str) -> None:
        """Keep the first `ERROR_LOG_LIMIT` failures, each cut to 300 characters."""
        if len(self.errors) < ERROR_LOG_LIMIT:
            self.errors.append(message[:300])


@dataclass(frozen=True)
class LLMSettings:
    """Per-config call settings; `max_retries` is corrective retries after the first attempt, `provider_retries` repeats of a failed request."""

    temperature: float = 1.0
    max_output_tokens: int = 400
    max_retries: int = 2
    reasoning_effort: str | None = "low"  # default for models without their own `reasoning` setting
    tool_choice: str = "auto"  # auto | required | forced; most pinned hosts reject required and forced
    provider_retries: int = 4  # retries of a request that fails with a transient provider error, per request
    retry_base_s: float = 2.0  # wait before retry k is retry_base_s * 2**k seconds, with jitter
    retry_cap_s: float = 30.0  # longest single wait, also the cap on a Retry-After
    session_retry_cap: int = 20  # abandon the session after this many provider retries in total
    request_timeout_s: float = 120.0  # per request; a long thinking reply at a large cap needs more
    reasoning_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)  # per model alias, beats models.yaml

    @classmethod
    def from_config(cls, llm: dict[str, Any]) -> "LLMSettings":
        """Settings from a config's `llm` block; absent keys keep the defaults above."""
        names = ["temperature", "max_output_tokens", "max_retries", "reasoning_effort", "tool_choice",
                 "provider_retries", "retry_base_s", "retry_cap_s", "session_retry_cap", "request_timeout_s",
                 "reasoning_overrides"]
        return cls(**{name: llm[name] for name in names if name in llm})


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


def tool_choice_value(setting: str) -> str | dict[str, Any]:
    """The request's `tool_choice` for a config setting: auto, required, or forced (the named function)."""
    if setting == "forced":
        return {"type": "function", "function": {"name": TOOL_NAME}}
    if setting not in ("auto", "required"):
        raise ValueError(f"tool_choice must be auto, required or forced, got {setting!r}")
    return setting


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


def _retry_after(failure: Any) -> float | None:
    """Seconds from a Retry-After header on an SDK exception's response, None if absent or not a number."""
    headers = getattr(getattr(failure, "response", None), "headers", None)
    try:
        return float(headers.get("retry-after")) if headers is not None and headers.get("retry-after") is not None else None
    except (TypeError, ValueError):
        return None


def transient_failure(failure: Any) -> tuple[bool, str, float | None]:
    """(worth retrying, description, Retry-After seconds) for an SDK exception or a response with no choices.

    Retried: connection errors and timeouts, HTTP 408, 429 and 5xx, and an error body in a 200 response
    with such a code or `provider_unavailable`. Never retried: other 4xx and anything unrecognised.
    """
    if isinstance(failure, BaseException):
        status = getattr(failure, "status_code", None)
        network = any(cls.__name__ in ("APIConnectionError", "APITimeoutError") for cls in type(failure).__mro__)
        retryable = network or (isinstance(status, int) and (status in (408, 429) or 500 <= status < 600))
        return retryable, f"{type(failure).__name__}: {failure}", _retry_after(failure)
    error = getattr(failure, "error", None)
    if not isinstance(error, dict):
        return False, f"no choices in the response: {failure!r}", None
    code = error.get("code")
    kind = (error.get("metadata") or {}).get("error_type")
    retryable = (isinstance(code, int) and (code in (408, 429) or 500 <= code < 600)) or kind == "provider_unavailable"
    return retryable, f"HTTP {code}: {error.get('message')}", None


def _extra(obj: Any, name: str) -> Any:
    """An OpenRouter-specific response field the openai SDK keeps as an extra attribute."""
    return getattr(obj, name, None)


class OpenRouterClient:
    """Forced-tool-call bid requests against one OpenAI-compatible client, with spend tracking."""

    def __init__(
        self,
        client: Any,
        settings: LLMSettings,
        spend: SpendTracker,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self.client = client
        self.settings = settings
        self.spend = spend
        self.sleep = sleep
        self.rng = rng or random.Random()

    def retry_delay(self, retry: int, retry_after: float | None) -> float:
        """Seconds to wait before retry number `retry` (0-based): a Retry-After as given, else exponential with +-25% jitter."""
        if retry_after is not None:
            return min(self.settings.retry_cap_s, retry_after)
        base = min(self.settings.retry_cap_s, self.settings.retry_base_s * 2**retry)
        return base * (0.75 + 0.5 * self.rng.random())

    async def _create(self, kwargs: dict[str, Any], alias: str, stats: ProviderStats, where: str) -> tuple[Any, float]:
        """One request, repeated on transient provider errors; returns (response, latency in ms of the successful try).

        Raises `ProviderError` for a non-transient failure, when retries run out, or at the session's retry cap.
        The retry reuses the same seed: a failed request produced no output, so nothing about the data changes.
        """
        for retry in range(self.settings.provider_retries + 1):
            started = time.perf_counter()
            cause: BaseException | None = None
            try:
                response = await self.client.chat.completions.create(**kwargs)
            except Exception as exc:  # noqa: BLE001  classified below; a non-transient one is raised as ProviderError
                transient, reason, retry_after = transient_failure(exc)
                cause = exc
            else:
                if getattr(response, "choices", None):
                    return response, (time.perf_counter() - started) * 1000
                transient, reason, retry_after = transient_failure(response)
            stats.record(f"{where}: {reason}")
            if not transient:
                raise ProviderError(f"{alias} call failed: {reason}") from cause
            if retry == self.settings.provider_retries:
                raise ProviderError(f"{alias} still failing after {retry} retries: {reason}") from cause
            if stats.retries >= self.settings.session_retry_cap:
                raise ProviderError(f"{alias} session retry cap of {self.settings.session_retry_cap} reached: {reason}") from cause
            stats.retries += 1
            await self.sleep(self.retry_delay(retry, retry_after))
        raise AssertionError("unreachable")

    def request_kwargs(
        self, spec: ModelSpec, host: Host | None, messages: Sequence[dict[str, str]], seed: int, reserve_price: float
    ) -> dict[str, Any]:
        """Keyword arguments for `chat.completions.create`, including OpenRouter routing."""
        extra: dict[str, Any] = {"usage": {"include": True}}
        reasoning = self.settings.reasoning_overrides.get(spec.alias, spec.reasoning)
        if reasoning is None and self.settings.reasoning_effort:
            reasoning = {"effort": self.settings.reasoning_effort}
        if reasoning is not None:
            extra["reasoning"] = reasoning
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
            "tool_choice": tool_choice_value(self.settings.tool_choice),
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
        stats: ProviderStats | None = None,
    ) -> tuple[float | None, list[CallRow]]:
        """Ask for one bid, retrying with a corrective message; returns (bid or None, one row per attempt).

        Raises `ProviderError` when the API call keeps failing, fails for good, or another host served it,
        and `BudgetExceeded` before an attempt once the cap is reached. Provider retries are counted in `stats`.
        """
        stats = stats if stats is not None else ProviderStats()
        price_in, price_out = (host.price_in, host.price_out) if host else (spec.price_in, spec.price_out)
        conversation = list(messages)
        rows: list[CallRow] = []
        for attempt in range(1, self.settings.max_retries + 2):
            self.spend.check()
            kwargs = self.request_kwargs(
                spec, host, conversation, call_seed(session_seed, round_number, slot, phase, attempt), reserve_price
            )
            response, latency_ms = await self._create(
                kwargs, spec.alias, stats, f"round {round_number} firm {firm_id} {phase} attempt {attempt}"
            )
            provider = _extra(response, "provider")
            if host is not None and provider is not None and provider.lower() != host.name.lower():
                raise ProviderError(f"{spec.alias} was served by {provider}, not the pinned {host.name}")

            usage = getattr(response, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", None)
            completion_tokens = getattr(usage, "completion_tokens", None)
            self.spend.add(((prompt_tokens or 0) * price_in + (completion_tokens or 0) * price_out) / 1e6)

            bid, reasoning, error = parse_bid(response, reserve_price)
            dump = response.model_dump_json() if hasattr(response, "model_dump_json") else repr(response)
            trace = trace_fields(json.loads(dump)) if dump.startswith("{") else {}
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
                    **trace,
                )
            )
            if error is None:
                return bid, rows
            conversation = [*messages, _corrective(error, reserve_price)]
        return None, rows


def make_openai_client(api_key: str, base_url: str | None = None, max_retries: int = 3, timeout: float = 120.0) -> Any:
    """Async OpenAI SDK client pointed at OpenRouter; the SDK retries 429, 5xx and timeouts itself."""
    from openai import AsyncOpenAI

    return AsyncOpenAI(api_key=api_key, base_url=base_url or DEFAULT_BASE_URL, max_retries=max_retries, timeout=timeout)
