"""Session builders and hand-controlled bidders shared by the tests."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from bidrig.auction import run_session_sync
from bidrig.bidders import Bidder, BidRequest, BidResponse, make_scripted_bidder
from bidrig.bne import BneBenchmark
from bidrig.schema import BidRow, LineupEntry, SessionMeta, firm_ids


def make_meta(
    bidder_types: Sequence[str],
    rule: str = "random",
    seed: int = 1,
    n_rounds: int = 50,
    history_window: int | None = None,
    lineup_id: str = "test",
) -> SessionMeta:
    """Baseline-parameter session (U[0, 100], reserve 100, increment 0.01) for the given slots."""
    n = len(bidder_types)
    prefix = "oneshot__" if history_window == 0 else ""
    return SessionMeta(
        run_id="test",
        condition_id=f"{prefix}tie-{rule}__info-full__lineup-{lineup_id}__n{n}",
        session_id=f"{lineup_id}-{rule}-n{n}-s{seed}-w{history_window}",
        seed=seed,
        n_bidders=n,
        info_condition="full",
        tie_break_rule=rule,
        lineup_id=lineup_id,
        lineup=[LineupEntry(f, t) for f, t in zip(firm_ids(n), bidder_types, strict=True)],
        cost_low=0,
        cost_high=100,
        reserve_price=100,
        bid_increment=0.01,
        n_rounds=n_rounds,
        history_window=history_window,
    )


def scripted_session(
    bidder_type: str,
    n: int = 3,
    rule: str = "random",
    seed: int = 1,
    n_rounds: int = 50,
    history_window: int | None = None,
    **params: float,
) -> tuple[SessionMeta, list[BidRow]]:
    """Run one same-type scripted session and return its meta and rows."""
    meta = make_meta([bidder_type] * n, rule, seed, n_rounds, history_window, lineup_id=f"dummy-{bidder_type}")
    bne = BneBenchmark(n, meta.cost_low, meta.cost_high)
    bidders = [make_scripted_bidder(bidder_type, bne, meta.reserve_price, **params) for _ in range(n)]
    return meta, run_session_sync(meta, bidders)


def custom_session(
    bidders: Sequence[Bidder],
    rule: str = "random",
    seed: int = 1,
    n_rounds: int = 50,
) -> tuple[SessionMeta, list[BidRow]]:
    """Run one session with hand-built bidders."""
    meta = make_meta([b.bidder_type for b in bidders], rule, seed, n_rounds)
    return meta, run_session_sync(meta, bidders)


@dataclass
class FnBidder:
    """Bidder driven by a function of the request; records every request it receives."""

    fn: Callable[[BidRequest], float | None]
    requests: list[BidRequest] = field(default_factory=list)
    bidder_type: str = "llm"
    model: str | None = "fake-model"

    async def bid(self, request: BidRequest) -> BidResponse:
        self.requests.append(request)
        return BidResponse(self.fn(request))


def fixed(bid: float | None, rebid: float | None = None) -> FnBidder:
    """Bidder with one constant bid and one constant rebid."""
    return FnBidder(lambda r: rebid if r.phase == "rebid" else bid)


def by_round(rows: Sequence[BidRow]) -> dict[int, list[BidRow]]:
    """Rows grouped by round, in slot order."""
    grouped: dict[int, list[BidRow]] = {}
    for row in rows:
        grouped.setdefault(row.round, []).append(row)
    return grouped


def winners(rows: Sequence[BidRow]) -> list[str]:
    """Winning firm id per round, in round order (rounds without a winner are skipped)."""
    return [row.firm_id for row in rows if row.is_winner]
