"""Bidder interface, scripted control bidders (BNE, markup, overbid, rotating cartel, match), and the LLM bidder.

Scripted rules and their expected readings are in PLANNING.md section 2.7. `BidRequest` and
`BidResponse` live in schema.py and are re-exported here.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Protocol

from bidrig.bne import Benchmark
from bidrig.channel import SEND_TOOL, SKIP_TOOL, channel_tools
from bidrig.llm import Host, ModelSpec, OpenRouterClient, ProviderStats
from bidrig.prompts import (
    DEFAULT_TEMPLATE,
    build_communication_messages,
    build_messages,
    build_reflection_messages,
)
from bidrig.schema import (
    BidderType,
    BidRequest,
    BidResponse,
    BidRow,
    CallRow,
    SessionMeta,
)
from bidrig.workspace import END_TOOL, READ_TOOL, WRITE_TOOL, Workspace, workspace_tools


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

    bne: Benchmark
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


@dataclass(frozen=True)
class ReplayBidder(ScriptedBidder):
    """Bids a fixed list, one entry per round, whatever its cost and whatever the other firms do.

    Used as a placebo rival: its bids come from a recorded session, so nothing the other firm does is answered.
    Its logged cost, benchmark bid and profit carry no meaning.
    """

    bids: tuple[float, ...] = ()  # bid for round 1, 2, ...; needs one per round of the session
    bidder_type: ClassVar[BidderType] = "replay"

    def quote(self, request: BidRequest) -> float:
        if not 1 <= request.round <= len(self.bids):
            raise ValueError(f"replay has {len(self.bids)} bids, asked for round {request.round}")
        return self.bids[request.round - 1]


SCRIPTED_BIDDERS: dict[str, type[ScriptedBidder]] = {
    cls.bidder_type: cls for cls in (BneBidder, MarkupBidder, OverbidBidder, RotationBidder, MatchBidder)
}


def make_scripted_bidder(
    bidder_type: BidderType,
    bne: Benchmark,
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
    workspace: Workspace | None = None  # shared by the session's firms; set exactly when meta.workspace
    reflection_steps: int = 4  # most requests in one reflection step
    channel: Workspace | None = None  # the session's message log; set exactly when meta.channel

    bidder_type: ClassVar[BidderType] = "llm"

    @property
    def model(self) -> str:
        """The model alias from configs/models.yaml."""
        return self.spec.alias

    async def bid(self, request: BidRequest) -> BidResponse:
        """The model's bid for `request` (None after every retry failed); attempts go to `calls`."""
        store = self.workspace or self.channel
        notes = await store.notes_before(request.round, request.firm_id) if store else ()
        messages = build_messages(
            self.meta, self.log, request, self.reasoning_length, self.max_output_tokens, self.template, notes
        )
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

    async def reflect(self, round_number: int, slot: int) -> None:
        """The reflection step after `round_number`: read and write the workspace (shared or private); calls go to `calls`."""
        if self.workspace is None:
            raise ValueError("reflection needs a workspace")
        workspace = self.workspace
        firm_id = self.meta.lineup[slot].firm_id

        async def handle(name: str, args: dict) -> str:
            if name == READ_TOOL:
                return await workspace.read(firm_id, round_number)
            if name == WRITE_TOOL:
                text = args.get("text")
                if not isinstance(text, str) or not text.strip():
                    return "Not accepted: give the note as a non-empty text."
                note = await workspace.write(firm_id, round_number, text)
                return f"Note saved (cut to {workspace.max_chars} characters)." if note.truncated else "Note saved."
            return f"Unknown tool {name!r}."

        messages = build_reflection_messages(
            self.meta, self.log, firm_id, round_number, self.reasoning_length, self.max_output_tokens, self.template
        )
        rows = await self.client.run_tools(
            self.spec,
            self.host,
            messages,
            workspace_tools(workspace.max_chars),
            handle,
            END_TOOL,
            self.reflection_steps,
            session_id=self.meta.session_id,
            session_seed=self.meta.seed,
            round_number=round_number,
            firm_id=firm_id,
            slot=slot,
            stats=self.stats,
        )
        self.calls.extend(rows)

    async def communicate(self, round_number: int, slot: int) -> None:
        """The communication step after `round_number`: one request, at most one message; calls go to `calls`."""
        if self.channel is None:
            raise ValueError("communication needs a channel")
        channel = self.channel
        firm_id = self.meta.lineup[slot].firm_id
        # Firms write concurrently, so each sees only messages from earlier rounds, never this round's.
        earlier = await channel.notes_before(round_number, firm_id)
        sent = False

        async def handle(name: str, args: dict) -> str:
            nonlocal sent
            if name != SEND_TOOL:
                return f"Unknown tool {name!r}."
            if sent:
                return "Not accepted: one message per communication step."
            text = args.get("text")
            if not isinstance(text, str) or not text.strip():
                return "Not accepted: give the message as a non-empty text."
            sent = True
            message = await channel.write(firm_id, round_number, text)
            return f"Message sent (cut to {channel.max_chars} characters)." if message.truncated else "Message sent."

        messages = build_communication_messages(
            self.meta, self.log, firm_id, round_number, earlier, self.reasoning_length, self.max_output_tokens, self.template
        )
        rows = await self.client.run_tools(
            self.spec,
            self.host,
            messages,
            channel_tools(channel.max_chars),
            handle,
            SKIP_TOOL,
            1,
            session_id=self.meta.session_id,
            session_seed=self.meta.seed,
            round_number=round_number,
            firm_id=firm_id,
            slot=slot,
            stats=self.stats,
            phase="message",
        )
        self.calls.extend(rows)
