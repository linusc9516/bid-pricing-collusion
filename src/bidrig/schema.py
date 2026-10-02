"""Dataclasses for session metadata, per-firm bid rows, and per-attempt LLM call rows.

Field definitions and agent visibility are in PLANNING.md section 3.
"""

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
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
    history_window: int | None = None  # None = whole session; 0 = one-shot control
    temperature: float | None = None
    prompt_version: str | None = None
    providers: dict[str, dict[str, str]] = field(default_factory=dict)
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

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready dict with the field names of PLANNING.md section 3."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CallRow":
        """Inverse of `to_dict`."""
        return cls(**data)


def firm_ids(n_bidders: int) -> list[str]:
    """Firm ids `A`, `B`, ... in slot order; n_bidders in 1..26."""
    if not 1 <= n_bidders <= 26:
        raise ValueError(f"n_bidders must be in 1..26, got {n_bidders}")
    return [chr(ord("A") + slot) for slot in range(n_bidders)]


def session_dir(log_dir: Path, meta: SessionMeta) -> Path:
    """Directory `<log_dir>/<run_id>/<condition_id>/<session_id>/` for one session."""
    return Path(log_dir) / meta.run_id / meta.condition_id / meta.session_id


def write_session(log_dir: Path, meta: SessionMeta, rows: Iterable[BidRow]) -> Path:
    """Write session.json and bids.jsonl for one session; returns the session directory."""
    out = session_dir(log_dir, meta)
    out.mkdir(parents=True, exist_ok=True)
    (out / SESSION_FILE).write_text(json.dumps(meta.to_dict(), indent=2) + "\n")
    with (out / BIDS_FILE).open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row.to_dict()) + "\n")
    return out


def read_session(path: Path) -> tuple[SessionMeta, list[BidRow]]:
    """Load one session directory written by `write_session`."""
    path = Path(path)
    meta = SessionMeta.from_dict(json.loads((path / SESSION_FILE).read_text()))
    with (path / BIDS_FILE).open() as handle:
        rows = [BidRow.from_dict(json.loads(line)) for line in handle if line.strip()]
    return meta, rows
