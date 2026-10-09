"""Auctioneer mechanics: cost draws, validation, winner determination and the three tie-break rules."""

import asyncio
from collections import Counter
from dataclasses import fields, replace
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest
from helpers import (
    FnBidder,
    by_round,
    custom_session,
    fixed,
    make_meta,
    scripted_session,
    winners,
)

from bidrig.auction import (
    draw_costs,
    from_ticks,
    run_session,
    run_session_sync,
    to_ticks,
)
from bidrig.bidders import BidRequest, BidResponse, make_scripted_bidder
from bidrig.bne import BneBenchmark
from bidrig.schema import BidRow, read_session, write_session

RULES = ["random", "least_wins", "bafo"]


def log_of(bidder_type: str, rule: str, **kwargs: int) -> list[BidRow]:
    """A scripted session's rows with the session id blanked, so logs compare across rules."""
    return [replace(r, session_id="") for r in scripted_session(bidder_type, rule=rule, **kwargs)[1]]


# --- rounding and cost draws ---


@pytest.mark.parametrize(
    ("value", "ticks"),
    [(0, 0), (66.664, 6666), (66.665, 6667), (66.675, 6668), (0.005, 1), (99.999, 10000), (100, 10000)],
)
def test_to_ticks_rounds_half_up(value: float, ticks: int) -> None:
    assert to_ticks(value, 0.01) == ticks


def test_from_ticks_gives_clean_decimals() -> None:
    assert from_ticks(6667, 0.01) == 66.67
    assert from_ticks(3, 5) == 15.0
    assert all(to_ticks(from_ticks(t, 0.01), 0.01) == t for t in range(10001))


def test_costs_depend_only_on_seed_and_n() -> None:
    a = draw_costs(11, 3, 50, 0, 100, 0.01)
    assert a.shape == (50, 3)
    assert np.array_equal(a, draw_costs(11, 3, 50, 0, 100, 0.01))
    assert not np.array_equal(a, draw_costs(12, 3, 50, 0, 100, 0.01))
    assert not np.array_equal(a[:, :2], draw_costs(11, 2, 50, 0, 100, 0.01))


def test_shorter_session_is_a_prefix() -> None:
    assert np.array_equal(draw_costs(11, 3, 50, 0, 100, 0.01)[:25], draw_costs(11, 3, 25, 0, 100, 0.01))


def test_costs_are_uniform_on_the_grid() -> None:
    costs = draw_costs(5, 3, 20_000, 0, 100, 0.01)
    assert costs.min() >= 0 and costs.max() <= 100
    assert np.allclose(costs * 100, np.round(costs * 100), atol=1e-9)
    assert costs.mean() == pytest.approx(50, abs=0.5)
    assert costs.std() == pytest.approx(100 / 12**0.5, abs=0.5)


@pytest.mark.parametrize("rule", RULES)
def test_cost_matrix_is_shared_across_rules_and_bidders(rule: str) -> None:
    expected = draw_costs(4, 3, 50, 0, 100, 0.01)
    for bidder_type in ["bne", "match", "rotation"]:
        _, rows = scripted_session(bidder_type, rule=rule, seed=4)
        assert np.array_equal(np.array([r.cost for r in rows]).reshape(50, 3), expected)


# --- row contents and winner determination ---


def test_rows_shape_and_order() -> None:
    meta, rows = scripted_session("bne", n=5, n_rounds=7)
    assert len(rows) == 35
    assert [(r.round, r.firm_id) for r in rows[:6]] == [(1, f) for f in "ABCDE"] + [(2, "A")]
    assert {r.session_id for r in rows} == {meta.session_id}
    assert all(r.model is None and r.n_attempts == 1 and r.valid for r in rows)


def test_lowest_bid_wins_and_profit_is_bid_minus_cost() -> None:
    _, rows = scripted_session("bne", n=3, n_rounds=200)
    for group in by_round(rows).values():
        low = min(r.bid for r in group)
        (winner,) = [r for r in group if r.is_winner]
        assert winner.bid == low
        assert all(r.winning_bid == low for r in group)
        assert winner.profit == pytest.approx(winner.bid - winner.cost, abs=1e-9)
        assert all(r.profit == 0 for r in group if not r.is_winner)
        assert sum(r.is_min_cost for r in group) >= 1


def test_bids_are_rounded_to_the_increment() -> None:
    _, rows = scripted_session("bne", n=3, n_rounds=200)
    bne = BneBenchmark(3, 0, 100)
    for r in rows:
        assert r.bne_bid == bne.bid(r.cost)
        assert r.bid == from_ticks(to_ticks(r.bne_bid, 0.01), 0.01)


def test_bid_below_cost_is_allowed() -> None:
    _, rows = custom_session([fixed(5), fixed(50), fixed(60)], n_rounds=20)
    assert winners(rows) == ["A"] * 20
    assert any(r.profit < 0 for r in rows)


@pytest.mark.parametrize("bad", [None, -0.01, 100.004, 250, float("nan"), float("inf")])
def test_invalid_bid_sits_out(bad: float | None) -> None:
    _, rows = custom_session([fixed(bad), fixed(90), fixed(95)], n_rounds=5)
    for group in by_round(rows).values():
        a, b, c = group
        assert (a.valid, a.bid, a.is_winner, a.profit, a.tied) == (False, None, False, 0.0, False)
        assert b.is_winner and b.winning_bid == 90
        assert c.n_tied == 1 and c.tie_resolution == "none"


def test_round_with_no_valid_bid_has_no_winner() -> None:
    _, rows = custom_session([fixed(None), fixed(101), fixed(-1)], n_rounds=3)
    assert not any(r.is_winner for r in rows)
    assert all(r.winning_bid is None and r.n_tied == 0 and not r.tie_broken for r in rows)
    assert all(r.tie_resolution == "none" and r.profit == 0 for r in rows)


def test_single_valid_bid_wins_without_a_tie() -> None:
    _, rows = custom_session([fixed(None), fixed(70), fixed(None)], n_rounds=3)
    assert winners(rows) == ["B"] * 3
    assert all(r.n_tied == 1 and not r.tie_broken for r in rows)


def test_rounding_creates_ties() -> None:
    _, rows = custom_session([fixed(49.996), fixed(50.004), fixed(60)], n_rounds=40)
    assert all(r.n_tied == 2 and r.tie_broken for r in rows)
    assert all(r.tied == (r.firm_id in "AB") for r in rows)
    assert set(winners(rows)) == {"A", "B"}


def test_lineup_must_match_bidders() -> None:
    meta = make_meta(["bne"] * 3)
    bidder = make_scripted_bidder("bne", BneBenchmark(3, 0, 100), 100)
    with pytest.raises(ValueError):
        run_session_sync(meta, [bidder] * 2)


def test_session_is_reproducible_and_round_trips(tmp_path: Path) -> None:
    meta, rows = scripted_session("match", rule="random", seed=9)
    assert scripted_session("match", rule="random", seed=9)[1] == rows
    assert winners(scripted_session("match", rule="random", seed=10)[1]) != winners(rows)
    loaded_meta, loaded_rows = read_session(write_session(tmp_path, meta, rows))
    assert (loaded_meta, loaded_rows) == (meta, rows)


# --- scripted bidders ---


def test_scripted_bid_rules() -> None:
    for r in scripted_session("markup", n_rounds=300)[1]:
        assert r.bid == pytest.approx(min(r.cost + 10, 100), abs=1e-9)
    for r in scripted_session("overbid", n_rounds=300)[1]:
        assert r.bid == pytest.approx(r.cost + 0.7 * (100 - r.cost), abs=0.005 + 1e-9)
    for r in scripted_session("markup", n_rounds=50, markup=25)[1]:
        assert r.bid == pytest.approx(min(r.cost + 25, 100), abs=1e-9)
    assert {r.bid for r in scripted_session("match", price=42)[1]} == {42.0}


@pytest.mark.parametrize("n", [2, 3, 5])
def test_rotation_bidders_take_turns(n: int) -> None:
    _, rows = scripted_session("rotation", n=n, n_rounds=4 * n)
    ids = [r.firm_id for r in rows[:n]]
    assert winners(rows) == ids * 4
    assert all(r.bid == (99.0 if r.is_winner else 100.0) for r in rows)
    assert all(r.winning_bid == 99.0 and not r.tie_broken for r in rows)


def test_unknown_scripted_type_is_rejected() -> None:
    with pytest.raises(ValueError):
        make_scripted_bidder("llm", BneBenchmark(3, 0, 100), 100)


# --- tie-break rules ---


@pytest.mark.parametrize("n", [2, 3, 5])
@pytest.mark.parametrize("seed", [1, 2, 3, 20261002, 990000])
def test_bne_bidders_give_identical_logs_under_all_rules(n: int, seed: int) -> None:
    logs = [log_of("bne", rule, n=n, seed=seed) for rule in RULES]
    assert not any(r.tie_broken for r in logs[0])
    assert all(r.is_winner == r.is_min_cost for r in logs[0])
    assert logs[0] == logs[1] == logs[2]


@pytest.mark.parametrize("rule", RULES)
def test_flag_changes_nothing_outside_tied_rounds(rule: str) -> None:
    """Markup bidders tie only when every bid caps at the reserve; all other rounds match `random`."""
    base = by_round(log_of("markup", "random", n=2, seed=3, n_rounds=2000))
    other = by_round(log_of("markup", rule, n=2, seed=3, n_rounds=2000))
    tied_rounds = [k for k, group in base.items() if group[0].tie_broken]
    assert 0 < len(tied_rounds) < 60
    assert all(other[k] == base[k] for k in base if k not in tied_rounds)
    assert all(other[k][0].tie_resolution.startswith(rule) for k in tied_rounds)


@pytest.mark.parametrize("n", [2, 3, 5])
def test_match_random_spreads_wins_at_random(n: int) -> None:
    _, rows = scripted_session("match", n=n, rule="random", n_rounds=600)
    assert all(r.tied and r.n_tied == n and r.tie_resolution == "random" for r in rows)
    assert all(r.bid == 80.0 and r.winning_bid == 80.0 and r.rebid is None for r in rows)
    won = winners(rows)
    counts = Counter(won)
    # Within 4 binomial standard deviations of an even split, and not a fixed turn order.
    sd = (600 * (1 / n) * (1 - 1 / n)) ** 0.5
    assert all(abs(counts[f] - 600 / n) < 4 * sd for f in {r.firm_id for r in rows})
    repeats = sum(a == b for a, b in pairwise(won)) / 599
    assert repeats == pytest.approx(1 / n, abs=0.08)


@pytest.mark.parametrize("n", [2, 3, 5])
def test_match_least_wins_rotates_exactly(n: int) -> None:
    _, rows = scripted_session("match", n=n, rule="least_wins", n_rounds=50)
    assert all(r.tied and r.n_tied == n and r.tie_resolution == "least_wins" for r in rows)
    assert all(r.winning_bid == 80.0 and r.rebid is None for r in rows)
    won = winners(rows)
    firms = {r.firm_id for r in rows}
    for end in range(1, 51):
        counts = Counter(won[:end])
        assert max(counts[f] for f in firms) - min(counts[f] for f in firms) <= 1
    for start in range(0, 50 - n + 1, n):
        assert set(won[start : start + n]) == firms


def test_least_wins_order_within_a_cycle_is_seeded() -> None:
    orders = {tuple(winners(scripted_session("match", rule="least_wins", seed=s, n_rounds=3)[1])) for s in range(30)}
    assert len(orders) > 1


def test_least_wins_counts_every_earlier_contract() -> None:
    """A wins rounds 1-2 outright; from round 3 A and B tie, so B must win until it catches up."""
    a = FnBidder(lambda r: 10 if r.round <= 2 else 50)
    _, rows = custom_session([a, fixed(50), fixed(90)], rule="least_wins", n_rounds=6)
    assert winners(rows)[:4] == ["A", "A", "B", "B"]
    assert set(winners(rows)[4:]) == {"A", "B"}
    assert [g[0].tie_resolution for g in by_round(rows).values()] == ["none"] * 2 + ["least_wins"] * 4


def test_least_wins_only_considers_tied_firms() -> None:
    """C has no wins but bids higher, so it never benefits from the rule."""
    _, rows = custom_session([fixed(50), fixed(50), fixed(60)], rule="least_wins", n_rounds=10)
    assert Counter(winners(rows)) == {"A": 5, "B": 5}
    assert all(r.n_tied == 2 for r in rows)


@pytest.mark.parametrize("n", [2, 3, 5])
def test_match_bafo_rebids_every_round(n: int) -> None:
    _, rows = scripted_session("match", n=n, rule="bafo", n_rounds=50)
    bne = BneBenchmark(n, 0, 100)
    for group in by_round(rows).values():
        assert all(r.tied and r.n_tied == n and r.bid == 80.0 for r in group)
        assert all(r.rebid == from_ticks(to_ticks(bne.bid(r.cost), 0.01), 0.01) for r in group)
        (winner,) = [r for r in group if r.is_winner]
        assert winner.rebid == min(r.rebid for r in group)
        assert all(r.winning_bid == winner.rebid for r in group)
        assert winner.profit == pytest.approx(winner.rebid - winner.cost, abs=1e-9)
        assert winner.is_min_cost
        assert {r.tie_resolution for r in group} == {"bafo"}


def test_bafo_rebid_goes_to_tied_firms_only_with_the_notice() -> None:
    a, b, c = fixed(50, 40), fixed(50, 45), fixed(60, 1)
    _, rows = custom_session([a, b, c], rule="bafo", n_rounds=4)
    assert winners(rows) == ["A"] * 4
    assert all(r.winning_bid == 40 and r.tie_resolution == "bafo" for r in rows)
    assert [r.rebid for r in rows[:3]] == [40, 45, None]
    assert [r.tied for r in rows[:3]] == [True, True, False]
    assert [r.phase for r in c.requests] == ["bid"] * 4
    assert [r.phase for r in a.requests] == ["bid", "rebid"] * 4
    first, rebid = a.requests[:2]
    assert (first.tied_price, first.n_tied) == (None, None)
    assert (rebid.tied_price, rebid.n_tied) == (50.0, 2)
    assert (rebid.firm_id, rebid.round, rebid.cost) == (first.firm_id, first.round, first.cost)


def test_bid_request_carries_only_the_firms_own_cost() -> None:
    """Guard: a new field here needs a decision on whether it can leak another firm's cost."""
    assert [f.name for f in fields(BidRequest)] == ["firm_id", "slot", "round", "cost", "phase", "tied_price", "n_tied"]
    a = fixed(50, 40)
    _, rows = custom_session([a, fixed(50, 45), fixed(60)], rule="bafo", n_rounds=6)
    own = {r.round: r.cost for r in rows if r.firm_id == "A"}
    assert all(req.cost == own[req.round] for req in a.requests)


def test_bafo_rebid_may_exceed_an_outside_bid() -> None:
    """PLANNING.md 5.1: the lowest rebid within the tied subset wins, even above C's original bid."""
    _, rows = custom_session([fixed(50, 70), fixed(50, 75), fixed(60)], rule="bafo", n_rounds=3)
    assert winners(rows) == ["A"] * 3
    assert all(r.winning_bid == 70 for r in rows)


def test_bafo_tied_rebid_falls_back_to_random() -> None:
    _, rows = custom_session([fixed(50, 40), fixed(50, 40), fixed(50, 45)], rule="bafo", n_rounds=40)
    assert all(r.tie_resolution == "bafo_random" and r.winning_bid == 40 and r.n_tied == 3 for r in rows)
    assert set(winners(rows)) == {"A", "B"}


def test_bafo_invalid_rebid_drops_that_firm() -> None:
    _, rows = custom_session([fixed(50, None), fixed(50, 99), fixed(50, 500)], rule="bafo", n_rounds=10)
    assert winners(rows) == ["B"] * 10
    assert all(r.tie_resolution == "bafo" and r.winning_bid == 99 for r in rows)
    assert all(r.valid for r in rows)
    assert [r.rebid for r in rows[:3]] == [None, 99, None]


def test_bafo_with_no_valid_rebid_draws_at_the_tied_price() -> None:
    _, rows = custom_session([fixed(50, None), fixed(50, -5), fixed(60)], rule="bafo", n_rounds=40)
    assert all(r.tie_resolution == "bafo_random" and r.winning_bid == 50 and r.rebid is None for r in rows)
    assert set(winners(rows)) == {"A", "B"}
    assert all(r.profit == pytest.approx(50 - r.cost, abs=1e-9) for r in rows if r.is_winner)


def test_bafo_has_one_rebid_round_at_most() -> None:
    a = fixed(50, 40)
    custom_session([a, fixed(50, 40)], rule="bafo", n_rounds=5)
    assert len(a.requests) == 10


@pytest.mark.parametrize("rule", ["random", "least_wins"])
def test_no_rebid_outside_bafo(rule: str) -> None:
    a = fixed(50, 40)
    _, rows = custom_session([a, fixed(50, 40)], rule=rule, n_rounds=5)
    assert len(a.requests) == 5
    assert all(r.rebid is None and r.winning_bid == 50 for r in rows)


def test_unknown_rule_is_rejected() -> None:
    with pytest.raises(ValueError):
        custom_session([fixed(50), fixed(50)], rule="alphabetical", n_rounds=1)


def _tie_prone(request: BidRequest) -> float:
    """Costs rounded to the nearest 20, so rounds tie often; rebids differ by firm so bafo has something to resolve."""
    base = round(request.cost / 20) * 20.0
    return base + (1.0 if request.phase == "rebid" and request.slot == 0 else 0.0)


@pytest.mark.parametrize("rule", ["random", "least_wins", "bafo"])
def test_parallel_control_rounds_match_the_sequential_run(rule: str) -> None:
    from dataclasses import replace as dc_replace

    def run(concurrency: int):
        bidders = [FnBidder(_tie_prone), FnBidder(_tie_prone), FnBidder(_tie_prone)]
        meta = dc_replace(make_meta([b.bidder_type for b in bidders], rule, 7, 30), history_window=0)
        return asyncio.run(run_session(meta, bidders, round_concurrency=concurrency)), bidders

    sequential, _ = run(1)
    parallel, bidders = run(8)
    assert any(r.tied for r in sequential)  # the comparison must include ties
    assert parallel == sequential
    assert sorted({req.round for b in bidders for req in b.requests}) == list(range(1, 31))


def test_history_runs_ignore_round_concurrency() -> None:
    bidders = [FnBidder(_tie_prone), FnBidder(_tie_prone)]
    meta = make_meta([b.bidder_type for b in bidders], "random", 3, 6)  # history_window None
    seen: list[int] = []

    async def spy(request: BidRequest):
        seen.append(request.round)
        await asyncio.sleep(0)
        return BidResponse(_tie_prone(request))

    for b in bidders:
        b.bid = spy  # type: ignore[method-assign]
    asyncio.run(run_session(meta, bidders, round_concurrency=8))
    assert seen == sorted(seen)  # rounds were asked in order, never overlapping


def test_parallel_failure_surfaces_the_bidders_own_error() -> None:
    from dataclasses import replace as dc_replace

    from bidrig.llm import ProviderError

    def boom(request: BidRequest) -> float:
        if request.round == 4:
            raise ProviderError("host failed")
        return 50.0

    bidders = [FnBidder(boom), FnBidder(boom)]
    meta = dc_replace(make_meta([b.bidder_type for b in bidders], "random", 1, 10), history_window=0)
    with pytest.raises(ProviderError):
        asyncio.run(run_session(meta, bidders, round_concurrency=5))
