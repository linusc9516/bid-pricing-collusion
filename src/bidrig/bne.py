"""Closed-form Bayes-Nash equilibrium benchmark for uniform-cost first-price procurement auctions.

Derivation and the collusion index built on it are in PLANNING.md section 2.4.
"""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class BneBenchmark:
    """Symmetric BNE for n >= 2 bidders with i.i.d. costs ~ U[cost_low, cost_high]; built once per bidder count."""

    n_bidders: int
    cost_low: float
    cost_high: float

    def __post_init__(self) -> None:
        if self.n_bidders < 2:
            raise ValueError(f"BNE needs at least 2 bidders, got {self.n_bidders}")
        if not self.cost_low < self.cost_high:
            raise ValueError(f"need cost_low < cost_high, got [{self.cost_low}, {self.cost_high}]")

    def bid(self, cost: float) -> float:
        """Equilibrium bid at `cost` in [cost_low, cost_high], unrounded; lies in [cost, cost_high]."""
        return cost + (self.cost_high - cost) / self.n_bidders

    @property
    def expected_winning_bid(self) -> float:
        """Mean winning bid over cost draws, in cost units."""
        # Equals the expected second-lowest cost, by revenue equivalence.
        return self.cost_low + 2 * (self.cost_high - self.cost_low) / (self.n_bidders + 1)


def collusion_index(mean_winning_bid: float, mean_bne_winning_bid: float, reserve_price: float) -> float:
    """Unclipped index in (-inf, 1]: 0 = winning bids at BNE, 1 = all at the reserve; NaN if BNE is at the reserve."""
    headroom = reserve_price - mean_bne_winning_bid
    if headroom == 0:
        return float("nan")
    return (mean_winning_bid - mean_bne_winning_bid) / headroom


def chance_tie_rate(
    n_bidders: int,
    cost_low: float,
    cost_high: float,
    bid_increment: float,
    n_draws: int = 400_000,
    seed: int = 0,
) -> float:
    """Share of rounds in [0, 1] with an exact tie at the lowest bid if every firm bids its BNE bid on the bid grid.

    The tie rate that fully competitive bidders produce by chance: costs are drawn and rounded to
    `bid_increment` as the auctioneer does, each bid is the closed-form BNE bid rounded half-up to the
    increment, and a tie is two or more firms sharing the lowest rounded bid. Monte Carlo with a fixed seed,
    so it is reproducible; the standard error is under 0.001 at the rates that matter here.
    """
    bne = BneBenchmark(n_bidders, cost_low, cost_high)
    rng = np.random.default_rng(seed)
    costs = np.floor(rng.uniform(cost_low, cost_high, size=(n_draws, n_bidders)) / bid_increment + 0.5) * bid_increment
    bids = costs + (bne.cost_high - costs) / n_bidders
    ticks = np.floor(bids / bid_increment + 0.5)
    return float(((ticks == ticks.min(axis=1, keepdims=True)).sum(axis=1) > 1).mean())
