"""BNE benchmark against the closed form, a Monte Carlo check and a best-response check."""

import math

import numpy as np
import pytest

from bidrig.bne import BneBenchmark, chance_tie_rate, collusion_index

EXPECTED_WINNING_BID = {2: 200 / 3, 3: 50.0, 5: 100 / 3}


@pytest.mark.parametrize("n", [2, 3, 5])
def test_expected_winning_bid_closed_form(n: int) -> None:
    bne = BneBenchmark(n, 0, 100)
    assert bne.expected_winning_bid == pytest.approx(EXPECTED_WINNING_BID[n])
    assert round(bne.expected_winning_bid, 1) == {2: 66.7, 3: 50.0, 5: 33.3}[n]


@pytest.mark.parametrize("n", [2, 3, 5])
def test_bid_function(n: int) -> None:
    bne = BneBenchmark(n, 0, 100)
    assert bne.bid(100) == 100
    assert bne.bid(0) == pytest.approx(100 / n)
    assert bne.bid(40) == pytest.approx(40 + 60 / n)


def test_shifted_support() -> None:
    bne = BneBenchmark(3, 20, 60)
    assert bne.bid(20) == pytest.approx(20 + 40 / 3)
    assert bne.expected_winning_bid == pytest.approx(40.0)


@pytest.mark.parametrize("n", [2, 3, 5])
def test_monte_carlo_expected_winning_bid(n: int) -> None:
    bne = BneBenchmark(n, 0, 100)
    costs = np.random.default_rng(n).uniform(0, 100, size=(200_000, n))
    winning = np.array([bne.bid(c) for c in costs.min(axis=1)])
    second_lowest = np.sort(costs, axis=1)[:, 1]
    # Standard error is under 0.06 at this sample size for every n.
    assert winning.mean() == pytest.approx(bne.expected_winning_bid, abs=0.25)
    assert second_lowest.mean() == pytest.approx(bne.expected_winning_bid, abs=0.25)


@pytest.mark.parametrize("n", [2, 3, 5])
@pytest.mark.parametrize("cost", [0.0, 25.0, 60.0, 95.0])
def test_bid_is_best_response(n: int, cost: float) -> None:
    """Against n - 1 rivals bidding the BNE, no bid on a fine grid beats the BNE bid."""
    bne = BneBenchmark(n, 0, 100)

    def expected_profit(bid: float) -> float:
        # A rival with cost c bids above `bid` iff c > the cost that maps to `bid`.
        rival_cost_at_bid = (bid * n - 100) / (n - 1)
        p_rival_higher = float(np.clip((100 - rival_cost_at_bid) / 100, 0, 1))
        return (bid - cost) * p_rival_higher ** (n - 1)

    grid = np.linspace(0, 100, 10_001)
    best = max(expected_profit(b) for b in grid)
    assert expected_profit(bne.bid(cost)) == pytest.approx(best, abs=1e-4)


def test_rejects_degenerate_inputs() -> None:
    with pytest.raises(ValueError):
        BneBenchmark(1, 0, 100)
    with pytest.raises(ValueError):
        BneBenchmark(3, 100, 100)


def test_collusion_index_is_unclipped() -> None:
    assert collusion_index(50, 50, 100) == 0
    assert collusion_index(100, 50, 100) == 1
    assert collusion_index(35, 50, 100) == pytest.approx(-0.3)
    assert collusion_index(0, 200 / 3, 100) == pytest.approx(-2.0)
    assert math.isnan(collusion_index(100, 100, 100))


@pytest.mark.parametrize(
    ("increment", "expected", "tolerance"),
    [(0.01, 0.0003, 0.0002), (0.5, 0.0123, 0.002), (1.0, 0.024, 0.003), (5.0, 0.117, 0.006)],
)
def test_chance_tie_rate_for_competitive_bidders(increment: float, expected: float, tolerance: float) -> None:
    assert chance_tie_rate(3, 0, 100, increment) == pytest.approx(expected, abs=tolerance)


def test_chance_tie_rate_is_reproducible_and_grows_with_the_grid_and_a_narrow_range() -> None:
    assert chance_tie_rate(3, 0, 100, 1.0) == chance_tie_rate(3, 0, 100, 1.0)
    assert chance_tie_rate(3, 0, 100, 0.01) < chance_tie_rate(3, 0, 100, 1.0) < chance_tie_rate(3, 0, 100, 5.0)
    assert chance_tie_rate(3, 25, 75, 1.0) > chance_tie_rate(3, 0, 100, 1.0)  # same grid, narrower costs: more ties
