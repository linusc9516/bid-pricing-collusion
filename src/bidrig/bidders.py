"""Bidder interface, scripted control bidders (BNE, markup, overbid, rotating cartel, match), and the LLM bidder.

Scripted rules and their expected readings are in PLANNING.md section 2.7. `BidRequest` and
`BidResponse` live in schema.py and are re-exported here.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Protocol

from bidrig.bne import BneBenchmark
from bidrig.llm import Host, ModelSpec, OpenRouterClient, ProviderStats
from bidrig.prompts import DEFAULT_TEMPLATE, build_messages
from bidrig.schema import (
    BidderType,
    BidRequest,
    BidResponse,
    BidRow,
    CallRow,
    SessionMeta,
)


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


@dataclass
class LLMBidder:
    """One firm played by a model; it reads the shared session log only through the prompt builder."""

    spec: ModelSpec
    host: Host | None
    client: OpenRouterClient
    meta: SessionMeta
    log: list[BidRow]  # the auctioneer's log, appended once per finished round
    calls: list[CallRow] = field(default_factory=list)
    reasoning_length: str = "short"
    max_output_tokens: int = 400  # stated in the prompt; keep equal to llm.max_output_tokens
    template: Path = DEFAULT_TEMPLATE
    stats: ProviderStats = field(default_factory=ProviderStats)  # shared by the session's firms

    bidder_type: ClassVar[BidderType] = "llm"

    @property
    def model(self) -> str:
        """The model alias from configs/models.yaml."""
        return self.spec.alias

    async def bid(self, request: BidRequest) -> BidResponse:
        """The model's bid for `request` (None after every retry failed); attempts go to `calls`."""
        messages = build_messages(self.meta, self.log, request, self.reasoning_length, self.max_output_tokens, self.template)
        bid, rows = await self.client.request_bid(
            self.spec,
            self.host,
            messages,
            self.meta.reserve_price,
            session_id=self.meta.session_id,
            session_seed=self.meta.seed,
            round_number=request.round,
            firm_id=request.firm_id,
            slot=request.slot,
            phase=request.phase,
            stats=self.stats,
        )
        self.calls.extend(rows)
        return BidResponse(bid, len(rows))
