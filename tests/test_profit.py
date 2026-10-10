"""analysis/profit.py: joint profit, switching alone, best reply and round blocks, on hand-computed sessions."""

import math

import pytest
from helpers import make_meta, scripted_session
from test_metrics import hand_rows

from bidrig.analysis.profit import (
    PROFIT_CHECK_COLUMNS,
    best_reply,
    joint_profit_ratio,
    profit_checks_table,
    round_block_gaps,
    switch_gain,
    switch_profits,
)


def test_joint_profit_ratio_by_hand() -> None:
    """Benchmark play: the lower-cost firm wins at (100 + cost) / 2. Costs 10 and 30, then 40 and 20: profits 45 + 40 = 85."""
    at_benchmark = hand_rows(2, [[(10, 55, True), (30, 65, False)], [(40, 70, False), (20, 60, True)]])
    assert joint_profit_ratio(at_benchmark) == pytest.approx(1.0)
    # The cost-30 firm wins round 1 at 80 (profit 50); round 2 as before (40): 90 against 85.
    wrong_winner = hand_rows(2, [[(10, 90, False), (30, 80, True)], [(40, 70, False), (20, 60, True)]])
    assert joint_profit_ratio(wrong_winner) == pytest.approx(90 / 85)
    below_cost = hand_rows(2, [[(10, 5, True), (30, 65, False)]])  # the winner loses 5; benchmark profit is 45
    assert joint_profit_ratio(below_cost) == pytest.approx(-5 / 45)


def test_switching_alone_by_hand() -> None:
    """Round 1: A (cost 10) bids 90 and loses to B's 80. Round 2: A (cost 40) wins at 60 against B's 61 (cost 20)."""
    rows = hand_rows(2, [[(10, 90, False), (30, 80, True)], [(40, 60, True), (20, 61, False)]])
    (a_actual, a_alone), (b_actual, b_alone) = switch_profits(rows)
    assert (a_actual, b_actual) == pytest.approx((20.0, 50.0))
    assert a_alone == pytest.approx(45.0)  # benchmark bid 55 beats 80 (+45); benchmark bid 70 loses to 61 (0)
    assert b_alone == pytest.approx(35.0 + 0.5 * 40.0)  # benchmark bid 65 beats 90 (+35); benchmark bid 60 ties A's 60 (half of 40)
    assert switch_gain(rows) == pytest.approx((45.0 + 55.0) / 70.0 - 1)


def test_best_reply_by_hand() -> None:
    """Firm B bids 80 in every round. Firm A (cost 20) bids 79.99, the best reply, for five rounds and then 60 in round 7."""
    rounds = [[(20, 79.99, True), (90, 80, False)] for _ in range(6)] + [[(20, 60, True), (90, 80, False)]]
    meta = make_meta(["llm"] * 2, n_rounds=7)
    out = best_reply(meta, hand_rows(2, rounds))
    # Only rounds 6 and 7 have five earlier rounds. Firm A: round 6 is the best reply (59.99), round 7 earns 40 of 59.99.
    # Firm B (cost 90) cannot beat 79.99 or 60 without bidding under its cost: no attainable profit, so its forgone
    # share is NaN and left out of the mean, and its bids of 80 are not near its best reply (its cost, 90).
    assert out["forgone_vs_earlier"] == pytest.approx(1 - (59.99 + 40.0) / (2 * 59.99), abs=1e-6)
    assert out["best_reply_share"] == pytest.approx((0.5 + 0.0) / 2)
    assert 0 <= out["forgone_vs_session"] < 1
    short = best_reply(make_meta(["llm"] * 2, n_rounds=3), hand_rows(2, rounds[:3]))
    assert all(math.isnan(v) for v in short.values())  # no round has five earlier rounds


def test_benchmark_bidders_gain_nothing_by_switching_and_table_columns() -> None:
    meta, rows = scripted_session("bne", n=2, n_rounds=60)
    # Bids are rounded to the 0.01 grid and the benchmark bid is not, so the two differ by under half a cent a round.
    assert switch_gain(rows) == pytest.approx(0.0, abs=1e-3) and joint_profit_ratio(rows) == pytest.approx(1.0, abs=1e-3)
    table = profit_checks_table([(meta, rows)])
    assert list(table.columns) == PROFIT_CHECK_COLUMNS
    assert 0 <= table.loc[0, "best_reply_share"] <= 1


def test_round_blocks_cover_every_valid_bid_once() -> None:
    meta, rows = scripted_session("markup", n=2, n_rounds=12)
    blocks = round_block_gaps([(meta, rows)], edges=(1, 5, 10, 50))
    assert list(blocks["block"]) == ["1", "2-5", "6-10", "11-12"]
    assert blocks["n_bids"].sum() == sum(r.valid for r in rows) and list(blocks["n_bids"]) == [2, 8, 10, 4]
    overall = sum(r.bid - r.bne_bid for r in rows) / len(rows)
    assert (blocks["mean_bid_minus_benchmark"] * blocks["n_bids"]).sum() / blocks["n_bids"].sum() == pytest.approx(overall)
