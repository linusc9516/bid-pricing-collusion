"""Rule-based auctioneer: cost draws, bid collection, winner determination, logging.

No LLM is involved in any decision here. Mechanics are in PLANNING.md sections 2.1 and 6.3.
"""

import asyncio
import math
from collections.abc import Sequence
from dataclasses import replace
from decimal import ROUND_HALF_UP, Decimal

import numpy as np

from bidrig.bidders import Bidder, BidRequest
from bidrig.bne import Benchmark, make_benchmark
from bidrig.schema import BidRow, SessionMeta, TieResolution

# Separate streams, so the number of tie-break draws a condition uses can never shift the costs.
_COST_STREAM = 0
_TIE_STREAM = 1
_COMMON_COST_STREAM = 3  # 2 is the runner's slot stream


def to_ticks(value: float, increment: float) -> int:
    """`value` as a whole number of increments, rounded half-up."""
    # Decimal on the shortest repr, so 66.665 rounds up as written instead of by its binary expansion.
    ratio = Decimal(repr(float(value))) / Decimal(repr(float(increment)))
    return int(ratio.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def from_ticks(ticks: int, increment: float) -> float:
    """Inverse of `to_ticks`: the currency value of `ticks` increments."""
    return float(ticks * Decimal(repr(float(increment))))


def draw_costs(
    seed: int,
    n_bidders: int,
    n_rounds: int,
    cost_low: float,
    cost_high: float,
    increment: float,
    cost_spread: float = 0.0,
) -> np.ndarray:
    """Private costs rounded to `increment`; shape (n_rounds, n_bidders).

    `cost_spread` 0: i.i.d. U[cost_low, cost_high]. `cost_spread` s > 0: a round-wide base
    ~ U[cost_low + s, cost_high - s], and each firm's cost is the base + U[-s, s], so costs
    stay in range and a round's costs are within 2s of each other (common-cost design; the
    closed-form BNE does not apply). A function of (seed, n_bidders, cost_spread) only: no
    condition enters, and a shorter session is a prefix of a longer one on the same seed.
    """
    rng = np.random.default_rng([seed, n_bidders, _COST_STREAM])
    if cost_spread == 0:
        raw = rng.uniform(cost_low, cost_high, size=(n_rounds, n_bidders))
    else:
        if not 0 < 2 * cost_spread < cost_high - cost_low:
            raise ValueError(f"need 0 <= cost_spread < (cost_high - cost_low) / 2, got {cost_spread}")
        # Own stream: the i.i.d. draw above is untouched, so existing seeds reproduce.
        rng = np.random.default_rng([seed, n_bidders, _COMMON_COST_STREAM])
        base = rng.uniform(cost_low + cost_spread, cost_high - cost_spread, size=(n_rounds, 1))
        raw = base + rng.uniform(-cost_spread, cost_spread, size=(n_rounds, n_bidders))
    return np.array([[from_ticks(to_ticks(c, increment), increment) for c in row] for row in raw])


async def collect_bids(
    bidders: Sequence[Bidder],
    requests: Sequence[BidRequest],
    reserve_price: float,
    increment: float,
) -> list[tuple[int | None, int]]:
    """Ask each bidder for its request concurrently; returns (bid in ticks or None if invalid, attempts)."""
    responses = await asyncio.gather(*(b.bid(r) for b, r in zip(bidders, requests, strict=True)))
    collected: list[tuple[int | None, int]] = []
    for response in responses:
        bid = response.bid
        in_range = bid is not None and math.isfinite(bid) and 0 <= bid <= reserve_price
        collected.append((to_ticks(bid, increment) if in_range else None, response.n_attempts))
    return collected


async def _resolve_tie(
    meta: SessionMeta,
    bidders: Sequence[Bidder],
    requests: Sequence[BidRequest],
    tied: list[int],
    tied_ticks: int,
    wins: Sequence[int],
    rng: np.random.Generator,
) -> tuple[int, int, TieResolution, dict[int, int | None]]:
    """Pick the winner among `tied` slots under `meta.tie_break_rule`.

    Returns (winner slot, price in ticks, resolution, rebids in ticks by slot). The rule only
    narrows the candidates and, under bafo, moves the price; the final draw is shared.
    """
    rule = meta.tie_break_rule
    candidates, price, rebids = tied, tied_ticks, {}
    resolution: TieResolution = rule
    if rule == "least_wins":
        fewest = min(wins[slot] for slot in tied)
        candidates = [slot for slot in tied if wins[slot] == fewest]
    elif rule == "bafo":
        notice = {"phase": "rebid", "tied_price": from_ticks(tied_ticks, meta.bid_increment), "n_tied": len(tied)}
        offers = await collect_bids(
            [bidders[slot] for slot in tied],
            [replace(requests[slot], **notice) for slot in tied],
            meta.reserve_price,
            meta.bid_increment,
        )
        rebids = {slot: ticks for slot, (ticks, _) in zip(tied, offers, strict=True)}
        live = [slot for slot in tied if rebids[slot] is not None]
        # With no valid rebid the contract still goes to one of the tied firms at the tied price.
        if live:
            price = min(rebids[slot] for slot in live)
            candidates = [slot for slot in live if rebids[slot] == price]
        resolution = "bafo" if len(candidates) == 1 else "bafo_random"
    elif rule != "random":
        raise ValueError(f"unknown tie_break_rule: {rule!r}")
    winner = candidates[0] if len(candidates) == 1 else candidates[int(rng.integers(len(candidates)))]
    return winner, price, resolution, rebids


def _round_requests(meta: SessionMeta, round_number: int, costs: Sequence[float]) -> list[BidRequest]:
    """What the auctioneer hands each firm for one round, in slot order."""
    return [
        BidRequest(firm_id=entry.firm_id, slot=slot, round=round_number, cost=costs[slot])
        for slot, entry in enumerate(meta.lineup)
    ]


async def _run_round(
    meta: SessionMeta,
    bidders: Sequence[Bidder],
    bne: Benchmark,
    round_number: int,
    costs: Sequence[float],
    wins: Sequence[int],
    rng: np.random.Generator,
) -> tuple[list[BidRow], int | None]:
    """Run one round; returns its rows in slot order and the winning slot (None if no valid bid)."""
    requests = _round_requests(meta, round_number, costs)
    bids = await collect_bids(bidders, requests, meta.reserve_price, meta.bid_increment)
    return await _settle_round(meta, bidders, bne, round_number, costs, requests, bids, wins, rng)


async def _settle_round(
    meta: SessionMeta,
    bidders: Sequence[Bidder],
    bne: BneBenchmark,
    round_number: int,
    costs: Sequence[float],
    requests: Sequence[BidRequest],
    bids: Sequence[tuple[int | None, int]],
    wins: Sequence[int],
    rng: np.random.Generator,
) -> tuple[list[BidRow], int | None]:
    """Resolve ties (asking bafo rebids) and build the rows of one round from its collected bids."""
    increment = meta.bid_increment
    valid = [slot for slot, (ticks, _) in enumerate(bids) if ticks is not None]

    winner: int | None = None
    price: int | None = None
    tied: list[int] = []
    resolution: TieResolution = "none"
    rebids: dict[int, int | None] = {}
    if valid:
        price = min(bids[slot][0] for slot in valid)
        tied = [slot for slot in valid if bids[slot][0] == price]
        winner = tied[0]
        if len(tied) > 1:
            winner, price, resolution, rebids = await _resolve_tie(meta, bidders, requests, tied, price, wins, rng)

    cost_ticks = [to_ticks(c, increment) for c in costs]
    min_cost = min(cost_ticks)
    rows = []
    for slot, (request, (ticks, n_attempts)) in enumerate(zip(requests, bids, strict=True)):
        is_winner = slot == winner
        rebid = rebids.get(slot)
        rows.append(
            BidRow(
                session_id=meta.session_id,
                round=round_number,
                firm_id=request.firm_id,
                cost=request.cost,
                bid=None if ticks is None else from_ticks(ticks, increment),
                is_winner=is_winner,
                winning_bid=None if price is None else from_ticks(price, increment),
                profit=from_ticks(price - cost_ticks[slot], increment) if is_winner else 0.0,
                valid=ticks is not None,
                n_attempts=n_attempts,
                tie_broken=len(tied) > 1,
                tied=len(tied) > 1 and slot in tied,
                n_tied=len(tied),
                tie_resolution=resolution,
                rebid=None if rebid is None else from_ticks(rebid, increment),
                bne_bid=bne.bid(request.cost),
                is_min_cost=cost_ticks[slot] == min_cost,
                model=bidders[slot].model,
            )
        )
    return rows, winner


async def run_session(
    meta: SessionMeta,
    bidders: Sequence[Bidder],
    log: list[BidRow] | None = None,
    round_concurrency: int = 1,
) -> list[BidRow]:
    """Run every round of one session; returns n_rounds * n_bidders rows in (round, slot) order.

    `bidders` are in the slot order of `meta.lineup`. Wins counted for `least_wins` are the
    contracts awarded earlier in this session, whatever decided them. If `log` is given, each
    round's rows are appended to it once the round is over, so bidders that share the list
    (through the visibility filter) never see a round before it has happened.

    `round_concurrency` above 1 asks for up to that many rounds' bids at once. It applies only to a one-shot
    control (`history_window` 0) played by model bidders: no bid there depends on an earlier round, so only
    the requests overlap. Ties are still resolved in round order, so the winners, prices, tie draws and win
    counts equal those of a sequential run.
    """
    if not len(bidders) == len(meta.lineup) == meta.n_bidders:
        raise ValueError("bidders, meta.lineup and meta.n_bidders must agree")
    bne = make_benchmark(meta.n_bidders, meta.cost_low, meta.cost_high, meta.cost_spread)
    costs = draw_costs(meta.seed, meta.n_bidders, meta.n_rounds, meta.cost_low, meta.cost_high, meta.bid_increment, meta.cost_spread)
    rng = np.random.default_rng([meta.seed, meta.n_bidders, _TIE_STREAM])
    wins = [0] * meta.n_bidders
    rows: list[BidRow] = [] if log is None else log
    collected: dict[int, tuple[list[BidRequest], list[tuple[int | None, int]]]] = {}
    if round_concurrency > 1 and meta.history_window == 0 and all(b.model is not None for b in bidders):
        gate = asyncio.Semaphore(round_concurrency)

        async def collect_round(index: int) -> None:
            async with gate:
                requests = _round_requests(meta, index + 1, costs[index].tolist())
                collected[index] = (requests, await collect_bids(bidders, requests, meta.reserve_price, meta.bid_increment))

        try:
            async with asyncio.TaskGroup() as group:  # one failed round cancels the rest
                for index in range(meta.n_rounds):
                    group.create_task(collect_round(index))
        except ExceptionGroup as failure:  # callers catch the bidder's own error (BudgetExceeded, ProviderError)
            raise failure.exceptions[0] from None
    for index in range(meta.n_rounds):
        if index in collected:
            requests, bids = collected[index]
            round_rows, winner = await _settle_round(meta, bidders, bne, index + 1, costs[index].tolist(), requests, bids, wins, rng)
        else:
            round_rows, winner = await _run_round(meta, bidders, bne, index + 1, costs[index].tolist(), wins, rng)
        rows.extend(round_rows)
        if winner is not None:
            wins[winner] += 1
    return rows


def run_session_sync(meta: SessionMeta, bidders: Sequence[Bidder], log: list[BidRow] | None = None) -> list[BidRow]:
    """Blocking `run_session`, for scripted sessions and tests."""
    return asyncio.run(run_session(meta, bidders, log))
