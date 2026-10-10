"""Bayes-Nash equilibrium benchmarks for first-price procurement auctions.

`BneBenchmark` is the closed form for i.i.d. uniform costs; `CommonCostBenchmark` is the numeric
equilibrium for the common-cost draw (`cost_spread` > 0). Derivation and the collusion index built on
them are in PLANNING.md section 2.4.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache

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

    def round_bids(self, costs: Sequence[float]) -> list[float]:
        """Equilibrium bid of every firm in one round, in slot order."""
        return [self.bid(c) for c in costs]

    @property
    def expected_winning_bid(self) -> float:
        """Mean winning bid over cost draws, in cost units."""
        # Equals the expected second-lowest cost, by revenue equivalence.
        return self.cost_low + 2 * (self.cost_high - self.cost_low) / (self.n_bidders + 1)


def _clip_pow(t: np.ndarray, m: int) -> np.ndarray:
    return np.clip(t, 0.0, 1.0) ** m


def _clip_pow_integral(t: np.ndarray, m: int) -> np.ndarray:
    """Antiderivative of clip(t, 0, 1)**m, zero for t <= 0."""
    inside = np.clip(t, 0.0, 1.0) ** (m + 1) / (m + 1)
    return inside + np.maximum(t - 1.0, 0.0)


def _hazard(cost: np.ndarray, n: int, low: float, high: float, spread: float) -> np.ndarray:
    """Rate at which the chance that all n - 1 rivals' costs exceed x falls as x rises, evaluated at x = cost.

    Given own cost c the base is uniform on [max(c - s, low + s), min(c + s, high - s)], and a rival's cost
    exceeds x with probability clip((base + s - x) / 2s, 0, 1); the hazard is -d log Q / dx at x = c.
    """
    m = n - 1
    lo = np.maximum(cost - spread, low + spread)
    hi = np.minimum(cost + spread, high - spread)
    t_lo, t_hi = (lo + spread - cost) / (2 * spread), (hi + spread - cost) / (2 * spread)
    width = hi - lo
    q = 2 * spread * (_clip_pow_integral(t_hi, m) - _clip_pow_integral(t_lo, m)) / width
    return (_clip_pow(t_hi, m) - _clip_pow(t_lo, m)) / (width * q)


@cache
def _solve_common_cost(n: int, low: float, high: float, spread: float, points: int) -> tuple[np.ndarray, np.ndarray]:
    """Equilibrium markup u(c) = b(c) - c on a cost grid; returns (grid, u).

    The first-order condition b' = (b - c) * hazard(c) gives u' = hazard * u - 1. It is integrated down
    from the top of the cost range, where the rivals' costs almost surely lie below (b(high) = high),
    starting on the local solution u = (high - c) / (k + 1) with k = hazard * (high - c). Integrating
    downwards is stable: the homogeneous solution decays as c falls.
    """
    eps = 1e-4 * (high - low)
    grid = np.linspace(low + eps, high - eps, points)[::-1]
    h = _hazard(grid, n, low, high, spread)
    k = h[0] * (high - grid[0])
    u = np.empty(points)
    u[0] = (high - grid[0]) / (k + 1)
    step = grid[1] - grid[0]  # negative
    for i in range(points - 1):
        mid = _hazard(np.array([(grid[i] + grid[i + 1]) / 2]), n, low, high, spread)[0]
        k1 = h[i] * u[i] - 1
        k2 = mid * (u[i] + step * k1 / 2) - 1
        k3 = mid * (u[i] + step * k2 / 2) - 1
        k4 = h[i + 1] * (u[i] + step * k3) - 1
        u[i + 1] = u[i] + step * (k1 + 2 * k2 + 2 * k3 + k4) / 6
    return grid[::-1].copy(), u[::-1].copy()


@dataclass(frozen=True)
class CommonCostBenchmark:
    """Symmetric equilibrium for n >= 2 bidders with common-cost draws: cost = base + U[-s, s], base ~ U[low + s, high - s].

    Each firm sees only its own cost. No closed form: the bid function is solved numerically once per
    (n, range, spread) and interpolated. Same interface as `BneBenchmark` (`bid`, `expected_winning_bid`).
    """

    n_bidders: int
    cost_low: float
    cost_high: float
    cost_spread: float
    grid_points: int = 4001

    def __post_init__(self) -> None:
        if self.n_bidders < 2:
            raise ValueError(f"benchmark needs at least 2 bidders, got {self.n_bidders}")
        if not 0 < 2 * self.cost_spread < self.cost_high - self.cost_low:
            raise ValueError(f"need 0 < cost_spread < (cost_high - cost_low) / 2, got {self.cost_spread}")

    def bid(self, cost: float) -> float:
        """Equilibrium bid at `cost` in [cost_low, cost_high], unrounded; lies in [cost, cost_high]."""
        return float(self.bids(np.asarray(cost)))

    def round_bids(self, costs: Sequence[float]) -> list[float]:
        """Equilibrium bid of every firm in one round, in slot order."""
        return [self.bid(c) for c in costs]

    def bids(self, costs: np.ndarray) -> np.ndarray:
        """Vectorised `bid`."""
        grid, markup = _solve_common_cost(self.n_bidders, self.cost_low, self.cost_high, self.cost_spread, self.grid_points)
        return np.minimum(costs + np.interp(costs, grid, markup), self.cost_high)

    @property
    def expected_winning_bid(self) -> float:
        """Mean equilibrium bid of the lowest-cost firm, in cost units (Monte Carlo, fixed seed, standard error under 0.05)."""
        rng = np.random.default_rng(0)
        base = rng.uniform(self.cost_low + self.cost_spread, self.cost_high - self.cost_spread, size=(200_000, 1))
        costs = base + rng.uniform(-self.cost_spread, self.cost_spread, size=(200_000, self.n_bidders))
        return float(self.bids(costs.min(axis=1)).mean())


@dataclass(frozen=True)
class CompleteInfoBenchmark:
    """Bertrand outcome when every firm sees every firm's cost: no bidder gains by bidding below the rivals' lowest cost.

    Firm i bids max(its cost, the lowest rival cost), so the lowest-cost firm bids the second-lowest cost
    and wins there, and every other firm bids its own cost. The benchmark price is the second-lowest cost,
    an upper edge: the winner would in practice undercut it by one bid increment. It does not depend on
    the cost distribution, so the same function serves i.i.d. and common-cost draws.
    """

    n_bidders: int
    cost_low: float
    cost_high: float

    def __post_init__(self) -> None:
        if self.n_bidders < 2:
            raise ValueError(f"benchmark needs at least 2 bidders, got {self.n_bidders}")

    def bid(self, cost: float) -> float:
        raise NotImplementedError("the complete-information benchmark needs every firm's cost; use `round_bids`")

    def round_bids(self, costs: Sequence[float]) -> list[float]:
        """Equilibrium bid of every firm in one round, in slot order."""
        others = list(costs)
        return [max(c, min(others[:i] + others[i + 1 :])) for i, c in enumerate(others)]


Benchmark = BneBenchmark | CommonCostBenchmark | CompleteInfoBenchmark


def make_benchmark(
    n_bidders: int, cost_low: float, cost_high: float, cost_spread: float = 0.0, reveal_costs: bool = False
) -> Benchmark:
    """Complete-information Bertrand if costs are revealed; else the closed form for `cost_spread` 0, the numeric common-cost equilibrium otherwise."""
    if reveal_costs:
        return CompleteInfoBenchmark(n_bidders, cost_low, cost_high)
    if cost_spread == 0:
        return BneBenchmark(n_bidders, cost_low, cost_high)
    return CommonCostBenchmark(n_bidders, cost_low, cost_high, cost_spread)


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
    cost_spread: float = 0.0,
) -> float:
    """Share of rounds in [0, 1] with an exact tie at the lowest bid if every firm bids its BNE bid on the bid grid.

    The tie rate that fully competitive bidders produce by chance: costs are drawn and rounded to
    `bid_increment` as the auctioneer does, each bid is the closed-form BNE bid rounded half-up to the
    increment, and a tie is two or more firms sharing the lowest rounded bid. Monte Carlo with a fixed seed,
    so it is reproducible; the standard error is under 0.001 at the rates that matter here.
    """
    bne = make_benchmark(n_bidders, cost_low, cost_high, cost_spread)
    rng = np.random.default_rng(seed)
    if cost_spread == 0:
        raw = rng.uniform(cost_low, cost_high, size=(n_draws, n_bidders))
    else:
        base = rng.uniform(cost_low + cost_spread, cost_high - cost_spread, size=(n_draws, 1))
        raw = base + rng.uniform(-cost_spread, cost_spread, size=(n_draws, n_bidders))
    costs = np.floor(raw / bid_increment + 0.5) * bid_increment
    bids = bne.bids(costs) if isinstance(bne, CommonCostBenchmark) else costs + (bne.cost_high - costs) / n_bidders
    ticks = np.floor(bids / bid_increment + 0.5)
    return float(((ticks == ticks.min(axis=1, keepdims=True)).sum(axis=1) > 1).mean())
