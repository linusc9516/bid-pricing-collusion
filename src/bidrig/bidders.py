"""Bidder interface, scripted control bidders (BNE, markup, overbid, rotating cartel, match), and the LLM bidder.

Scripted rules and their expected readings are in PLANNING.md section 2.7. The LLM bidder
is not implemented yet (build step 5).
"""

from dataclasses import dataclass
from typing import ClassVar, Protocol

from bidrig.bne import BneBenchmark
from bidrig.schema import BidderType, CallPhase


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


class Bidder(Protocol):
    """Anything the auctioneer can ask for a bid; async so LLM bidders can be called concurrently."""

    bidder_type: BidderType
    model: str | None

    async def bid(self, request: BidRequest) -> BidResponse:
        """Unrounded bid in [0, reserve_price] for `request`; the auctioneer validates and rounds it."""
        ...


@dataclass(frozen=True)
class ScriptedBidder:
    """Deterministic bidder; subclasses set `bidder_type` and implement `quote`."""

    bne: BneBenchmark
    reserve_price: float

    bidder_type: ClassVar[BidderType]
    model: ClassVar[None] = None

    def quote(self, request: BidRequest) -> float:
        """Unrounded bid for `request`, in cost units."""
        raise NotImplementedError

    async def bid(self, request: BidRequest) -> BidResponse:
        """The scripted quote for `request`, always a single attempt."""
        return BidResponse(self.quote(request))


@dataclass(frozen=True)
class BneBidder(ScriptedBidder):
    """Competitive benchmark: bids `c + (c_hi - c) / n`."""

    bidder_type: ClassVar[BidderType] = "bne"

    def quote(self, request: BidRequest) -> float:
        """Equilibrium bid at the firm's cost, in both phases."""
        return self.bne.bid(request.cost)


@dataclass(frozen=True)
class MarkupBidder(ScriptedBidder):
    """Negative control: bids `min(c + markup, reserve)`, which is below BNE on average."""

    markup: float = 10.0
    bidder_type: ClassVar[BidderType] = "markup"

    def quote(self, request: BidRequest) -> float:
        """Cost plus a fixed markup, capped at the reserve."""
        return min(request.cost + self.markup, self.reserve_price)


@dataclass(frozen=True)
class OverbidBidder(ScriptedBidder):
    """High prices with no coordination: bids `c + shade (c_hi - c)`; BNE is shade = 1/n."""

    shade: float = 0.7
    bidder_type: ClassVar[BidderType] = "overbid"

    def quote(self, request: BidRequest) -> float:
        """Cost plus a fixed share of the distance to the top of the cost range."""
        return request.cost + self.shade * (self.bne.cost_high - request.cost)


@dataclass(frozen=True)
class RotationBidder(ScriptedBidder):
    """Rotating cartel: the designated firm bids `reserve - undercut`, the others cover at the reserve."""

    undercut: float = 1.0
    bidder_type: ClassVar[BidderType] = "rotation"

    def quote(self, request: BidRequest) -> float:
        """Just under the reserve on this firm's turn (round-robin by slot), the reserve otherwise."""
        if (request.round - 1) % self.bne.n_bidders == request.slot:
            return self.reserve_price - self.undercut
        return self.reserve_price


@dataclass(frozen=True)
class MatchBidder(ScriptedBidder):
    """Tie generator: every firm bids the same fixed `price` whatever its cost; rebids the BNE bid."""

    price: float = 80.0
    bidder_type: ClassVar[BidderType] = "match"

    def quote(self, request: BidRequest) -> float:
        """The fixed price in the bid phase, the BNE bid in a rebid."""
        if request.phase == "rebid":
            return self.bne.bid(request.cost)
        return self.price


SCRIPTED_BIDDERS: dict[str, type[ScriptedBidder]] = {
    cls.bidder_type: cls for cls in (BneBidder, MarkupBidder, OverbidBidder, RotationBidder, MatchBidder)
}


def make_scripted_bidder(
    bidder_type: BidderType,
    bne: BneBenchmark,
    reserve_price: float,
    **params: float,
) -> ScriptedBidder:
    """Build one scripted bidder; `params` are the config keys `markup`, `shade`, `undercut` or `price`."""
    if bidder_type not in SCRIPTED_BIDDERS:
        raise ValueError(f"not a scripted bidder type: {bidder_type!r}")
    return SCRIPTED_BIDDERS[bidder_type](bne, reserve_price, **params)
