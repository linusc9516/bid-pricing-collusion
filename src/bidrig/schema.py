"""Dataclasses for session metadata, per-firm bid rows, and per-attempt LLM call rows.

Field definitions and agent visibility are in PLANNING.md section 3.
"""

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

InfoCondition = Literal["full", "winner_price", "winner_only"]
TieBreakRule = Literal["random", "least_wins", "bafo"]
TieResolution = Literal["none", "random", "least_wins", "bafo", "bafo_random"]
BidderType = Literal["llm", "bne", "markup", "overbid", "rotation", "match"]
SessionStatus = Literal["running", "complete", "failed"]
CallPhase = Literal["bid", "rebid"]

SESSION_FILE = "session.json"
BIDS_FILE = "bids.jsonl"
CALLS_FILE = "calls.jsonl"


@dataclass(frozen=True)
class LineupEntry:
    """One firm slot; `model` is the config alias, None for scripted bidders."""

    firm_id: str
    bidder_type: BidderType
    model: str | None = None


@dataclass
class SessionMeta:
    """Contents of session.json; costs, reserve and increment share the bid's currency units."""

    run_id: str
    condition_id: str
    session_id: str
    seed: int
    n_bidders: int
    info_condition: InfoCondition
    tie_break_rule: TieBreakRule
    lineup_id: str
    lineup: list[LineupEntry]
    cost_low: float
    cost_high: float
    reserve_price: float
    bid_increment: float
    n_rounds: int
    cost_spread: float = 0.0  # 0 = i.i.d. costs; s > 0 = common base + U[-s, s] per firm
    history_window: int | None = None  # None = whole session; 0 = one-shot control
    temperature: float | None = None
    prompt_version: str | None = None
    providers: dict[str, dict[str, str]] = field(default_factory=dict)
    provider_retries: int = 0  # requests repeated after a transient provider error
    provider_errors: list[str] = field(default_factory=list)  # first 20 failed requests, as text
    git_sha: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    status: SessionStatus = "running"

    @property
    def is_control(self) -> bool:
        """True for the one-shot control (no history shown)."""
        return self.history_window == 0

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready dict with the field names of PLANNING.md section 3."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionMeta":
        """Inverse of `to_dict`."""
        lineup = [LineupEntry(**entry) for entry in data["lineup"]]
        return cls(**{**data, "lineup": lineup})


@dataclass
class BidRow:
    """One firm in one round of bids.jsonl; `round` is 1-indexed, money fields are on the bid grid."""

    session_id: str
    round: int
    firm_id: str
    cost: float
    bid: float | None  # original bid, also under bafo; None when the firm sat out
    is_winner: bool
    winning_bid: float | None  # price paid (the rebid price under bafo); None if no valid bid
    profit: float
    valid: bool
    n_attempts: int  # bid phase only; rebid attempts are in calls.jsonl
    tie_broken: bool  # round-level: the lowest valid bid was shared
    tied: bool  # firm-level: this firm shared the lowest valid bid
    n_tied: int  # firms sharing the lowest valid bid; 1 = no tie, 0 = no valid bid
    tie_resolution: TieResolution  # round-level
    rebid: float | None  # None outside a rebid, and for an invalid rebid
    bne_bid: float  # unrounded closed form at this firm's cost
    is_min_cost: bool
    model: str | None

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready dict with the field names of PLANNING.md section 3."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BidRow":
        """Inverse of `to_dict`."""
        return cls(**data)


@dataclass
class CallRow:
    """One LLM attempt in calls.jsonl; `attempt` is 1-indexed, `latency_ms` in milliseconds."""

    session_id: str
    round: int
    firm_id: str
    attempt: int
    phase: CallPhase
    model: str
    provider: str | None
    prompt: str
    raw_response: str | None
    reasoning: str | None
    parsed_bid: float | None
    error: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: float | None
    reasoning_tokens: int | None = None  # hidden thinking tokens, counted inside completion_tokens
    finish_reason: str | None = None  # `length` means the reply hit the output cap
    thinking: str | None = None  # the provider's hidden reasoning text, where it returned any
    content: str | None = None  # free text the model wrote outside the tool call, where it wrote any

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready dict with the field names of PLANNING.md section 3."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CallRow":
        """Inverse of `to_dict`."""
        return cls(**data)


@dataclass(frozen=True)
class BidRequest:
    """What the auctioneer hands one firm for one bid; holds that firm's own cost and no other firm's."""

    firm_id: str
    slot: int  # 0-indexed position in the lineup
    round: int  # 1-indexed
    cost: float
    phase: CallPhase = "bid"
    tied_price: float | None = None  # rebid only: the price the firms tied at
    n_tied: int | None = None  # rebid only: how many firms tied, not which


@dataclass(frozen=True)
class BidResponse:
    """A firm's answer; `bid` is None when it sits out, `n_attempts` counts tries (1 for scripted)."""

    bid: float | None
    n_attempts: int = 1


def trace_fields(raw: dict[str, Any]) -> dict[str, Any]:
    """`reasoning_tokens`, `finish_reason`, `thinking` and `content` from a chat-completion dict; absent pieces are None.

    The thinking text is `message.reasoning` (or `reasoning_content`), else the text of `reasoning_details`.
    """
    choice = (raw.get("choices") or [{}])[0] or {}
    message = choice.get("message") or {}
    details = (raw.get("usage") or {}).get("completion_tokens_details") or {}
    thinking = message.get("reasoning") or message.get("reasoning_content")
    if not thinking:
        parts = [d.get("text") or d.get("summary") or "" for d in (message.get("reasoning_details") or []) if isinstance(d, dict)]
        thinking = "\n".join(p for p in parts if p) or None
    return {
        "reasoning_tokens": details.get("reasoning_tokens"),
        "finish_reason": choice.get("finish_reason"),
        "thinking": thinking,
        "content": message.get("content") or None,
    }


def fill_trace(call: CallRow) -> CallRow:
    """A call row from before these fields existed, with them read back out of its raw response; others unchanged."""
    if call.finish_reason is not None or not (call.raw_response or "").startswith("{"):
        return call
    try:
        return replace(call, **trace_fields(json.loads(call.raw_response)))
    except (json.JSONDecodeError, AttributeError, TypeError):
        return call


def firm_ids(n_bidders: int) -> list[str]:
    """Firm ids `A`, `B`, ... in slot order; n_bidders in 1..26."""
    if not 1 <= n_bidders <= 26:
        raise ValueError(f"n_bidders must be in 1..26, got {n_bidders}")
    return [chr(ord("A") + slot) for slot in range(n_bidders)]


def session_dir(log_dir: Path, meta: SessionMeta) -> Path:
    """Directory `<log_dir>/<run_id>/<condition_id>/<session_id>/` for one session."""
    return Path(log_dir) / meta.run_id / meta.condition_id / meta.session_id


def write_meta(log_dir: Path, meta: SessionMeta) -> Path:
    """Write (or overwrite) session.json alone; returns the session directory."""
    out = session_dir(log_dir, meta)
    out.mkdir(parents=True, exist_ok=True)
    (out / SESSION_FILE).write_text(json.dumps(meta.to_dict(), indent=2) + "\n")
    return out


def _write_jsonl(path: Path, rows: Iterable[BidRow | CallRow]) -> None:
    with path.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row.to_dict()) + "\n")


def write_session(
    log_dir: Path, meta: SessionMeta, rows: Iterable[BidRow], calls: Iterable[CallRow] | None = None
) -> Path:
    """Write session.json, bids.jsonl and, if given, calls.jsonl; returns the session directory."""
    out = write_meta(log_dir, meta)
    _write_jsonl(out / BIDS_FILE, rows)
    if calls is not None:
        _write_jsonl(out / CALLS_FILE, calls)
    return out


def read_meta(path: Path) -> SessionMeta:
    """session.json of one session directory."""
    return SessionMeta.from_dict(json.loads((Path(path) / SESSION_FILE).read_text()))


def read_calls(path: Path) -> list[CallRow]:
    """calls.jsonl of one session directory; empty for scripted sessions."""
    calls = Path(path) / CALLS_FILE
    if not calls.exists():
        return []
    with calls.open() as handle:
        return [fill_trace(CallRow.from_dict(json.loads(line))) for line in handle if line.strip()]


def read_session(path: Path) -> tuple[SessionMeta, list[BidRow]]:
    """Load one session directory written by `write_session`."""
    path = Path(path)
    meta = read_meta(path)
    with (path / BIDS_FILE).open() as handle:
        rows = [BidRow.from_dict(json.loads(line)) for line in handle if line.strip()]
    return meta, rows
