"""Per-session metrics: hand-computed logs, then the expected readings of PLANNING.md 2.7."""

import math
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest
from helpers import FnBidder, custom_session, fixed, make_meta, scripted_session

from bidrig.analysis.metrics import (
    SESSION_METRIC_COLUMNS,
    add_control_deltas,
    call_summary,
    load_run,
    manipulation_verdict,
    non_competitive_bids,
    session_metrics,
    session_metrics_table,
    tie_check,
)
from bidrig.bne import BneBenchmark
from bidrig.schema import BidRow, SessionMeta, write_session

LONG = 5000  # rounds; long enough that a session's index sits within 0.02 of its expectation


def hand_rows(n: int, rounds: list[list[tuple]]) -> list[BidRow]:
    """Rows from per-round tuples (cost, bid, is_winner[, rebid]); tie fields derived from the bids."""
    bne = BneBenchmark(n, 0, 100)
    rows = []
    for number, firms in enumerate(rounds, start=1):
        bids = [f[1] for f in firms if f[1] is not None]
        low = min(bids)
        n_tied = bids.count(low)
        rebids = [f[3] if len(f) > 3 else None for f in firms]
        winner_price = next((r if r is not None else f[1]) for f, r in zip(firms, rebids, strict=True) if f[2])
        for slot, (firm, rebid) in enumerate(zip(firms, rebids, strict=True)):
            cost, bid, is_winner = firm[:3]
            row = BidRow(
                session_id="hand", round=number, firm_id="ABCDE"[slot], cost=cost, bid=bid,
                is_winner=is_winner, winning_bid=winner_price,
                profit=winner_price - cost if is_winner else 0.0, valid=bid is not None, n_attempts=1,
                tie_broken=n_tied > 1, tied=n_tied > 1 and bid == low, n_tied=n_tied,
                tie_resolution="none", rebid=rebid, bne_bid=bne.bid(cost),
                is_min_cost=cost == min(f[0] for f in firms), model=None,
            )  # fmt: skip
            rows.append(row)
    return rows


# --- hand-computed logs ---


def test_hand_computed_session() -> None:
    rows = hand_rows(
        2,
        [
            [(20, 70, True), (40, 80, False)],  # BNE price b(20) = 60; lowest cost wins
            [(60, 90, True), (10, 95, False)],  # BNE price b(10) = 55; lowest cost loses
            [(50, 85, False), (30, 85, True)],  # tie at 85; BNE price b(30) = 65
            [(0, None, False), (80, 100, True)],  # A sits out; BNE price is still b(0) = 50
        ],
    )
    m = session_metrics(make_meta(["llm"] * 2, n_rounds=4), rows)
    assert m["n_valid_rounds"] == 4
    assert m["invalid_bid_rate"] == pytest.approx(1 / 8)
    assert m["collusion_index"] == pytest.approx((86.25 - 57.5) / (100 - 57.5))
    assert m["lowest_cost_win_share"] == pytest.approx(0.5)
    assert m["repeat_win_rate"] == pytest.approx(2 / 3)
    assert m["chi2_stat"] == pytest.approx(0.0)
    assert m["median_loser_gap"] == pytest.approx(5.0)  # gaps 10, 5, 0
    assert m["median_loser_gap_vs_bne"] == pytest.approx(10.0)  # 80-70, 95-55, 85-75
    assert (m["tie_rate"], m["tie_rate_early"], m["tie_rate_late"]) == (0.25, 0.0, 0.5)
    assert m["tie_price_index"] == pytest.approx((85 - 65) / (100 - 65))
    assert math.isnan(m["mean_rebid_delta"]) and math.isnan(m["bafo_overshoot_rate"])
    assert not m["is_control"]


def test_hand_computed_bafo_session() -> None:
    rows = hand_rows(
        3,
        [
            [(10, 50, False, 70), (20, 50, True, 40), (30, 60, False)],  # rebid winner below C's 60
            [(10, 50, True, 65), (20, 50, False, 75), (30, 60, False)],  # rebid winner above C's 60
            [(10, 30, True), (20, 55, False), (30, 60, False)],  # no tie
        ],
    )
    m = session_metrics(make_meta(["llm"] * 3, rule="bafo", n_rounds=3), rows)
    assert m["mean_rebid_delta"] == pytest.approx((20 - 10 + 15 + 25) / 4)
    assert m["bafo_overshoot_rate"] == pytest.approx(0.5)
    assert m["tie_rate"] == pytest.approx(2 / 3)
    bne_price = BneBenchmark(3, 0, 100).bid(10)
    # Priced at the tied bid of 50, not at the rebid prices 40 and 65.
    assert m["tie_price_index"] == pytest.approx((50 - bne_price) / (100 - bne_price))
    assert m["collusion_index"] == pytest.approx((45 - bne_price) / (100 - bne_price))
    # Losers' final bids against the price paid: 70-40, 60-40, 75-65, 60-65, 55-30, 60-30.
    assert m["median_loser_gap"] == pytest.approx(22.5)
    # Only the tied firms count toward the chi-square's three cells: wins A 2, B 1, C 0.
    assert m["chi2_stat"] == pytest.approx(2.0)


def test_non_competitive_bid_rates_by_hand() -> None:
    """Seven valid bids: two at the reserve, two below cost (one by a single cent), one at cost, one sitting out."""
    rows = hand_rows(
        2,
        [
            [(20, 70, True), (40, 100, False)],
            [(60, 55, True), (30, 100, False)],
            [(10, 30, True), (80, 79.99, False)],
            [(50, None, False), (45, 45, True)],
        ],
    )
    m = session_metrics(make_meta(["llm"] * 2, n_rounds=4), rows)
    assert m["reserve_bid_rate"] == pytest.approx(2 / 7)
    assert m["below_cost_bid_rate"] == pytest.approx(2 / 7)  # a bid equal to cost is not below cost


def test_non_competitive_bid_rates_ignore_rebids_and_missing_bids() -> None:
    meta, rows = custom_session([fixed(None), fixed(None)], n_rounds=3)
    m = session_metrics(meta, rows)
    assert math.isnan(m["reserve_bid_rate"]) and math.isnan(m["below_cost_bid_rate"])
    # Under bafo a rebid at the reserve is not an original bid, so it does not count.
    meta, rows = custom_session([fixed(50, 100), fixed(50, 100)], rule="bafo", n_rounds=4)
    m = session_metrics(meta, rows)
    assert m["reserve_bid_rate"] == 0.0


@pytest.mark.parametrize("n", [2, 3, 5])
def test_non_competitive_bid_rates_read_as_expected_for_scripted_bidders(n: int) -> None:
    rates = {t: session_metrics(*scripted_session(t, n=n, n_rounds=LONG)) for t in ["bne", "markup", "overbid", "rotation", "match"]}
    for kind in ["bne", "overbid", "markup"]:
        assert rates[kind]["below_cost_bid_rate"] == 0  # none of these bids below its own cost
    # The rotation bidder's 99 on its turn is below cost whenever cost exceeds 99: about 1% of its 1 / n of the bids.
    assert rates["rotation"]["below_cost_bid_rate"] == pytest.approx(0.01 / n, abs=0.003)
    assert rates["bne"]["reserve_bid_rate"] < 0.001 and rates["overbid"]["reserve_bid_rate"] < 0.001
    assert rates["markup"]["reserve_bid_rate"] == pytest.approx(0.10, abs=0.01)  # cost + 10 is capped at 100 above cost 90
    assert rates["rotation"]["reserve_bid_rate"] == pytest.approx((n - 1) / n, abs=0.001)  # everyone but the designated firm
    assert rates["match"]["below_cost_bid_rate"] == pytest.approx(0.20, abs=0.02)  # a fixed 80 is below any cost above 80
    assert rates["match"]["reserve_bid_rate"] == 0


def test_non_competitive_bids_table_is_per_condition_and_kept_apart() -> None:
    sessions = paired("overbid", "bne", seed=1) + paired("overbid", "bne", seed=2)
    table = session_metrics_table(sessions)
    summary = non_competitive_bids(table)
    assert list(summary.columns) == ["condition_id", "n_sessions", "reserve_bid_rate", "below_cost_bid_rate"]
    assert len(summary) == 2 and (summary["n_sessions"] == 2).all()
    assert (summary["below_cost_bid_rate"] == 0).all()


def test_chi2_and_repeat_rate_on_a_single_winner() -> None:
    rows = hand_rows(3, [[(10, 40, True), (20, 50, False), (30, 60, False)]] * 6)
    rows = [replace(r, round=i // 3 + 1) for i, r in enumerate(rows)]
    m = session_metrics(make_meta(["llm"] * 3, n_rounds=6), rows)
    assert m["chi2_stat"] == pytest.approx(12.0)  # (6-2)^2/2 + 2 * (0-2)^2/2
    assert m["repeat_win_rate"] == 1.0
    assert m["lowest_cost_win_share"] == 1.0
    assert math.isnan(m["tie_price_index"])


def test_rounds_without_a_winner_are_dropped() -> None:
    a = FnBidder(lambda r: None if r.round % 2 == 0 else 50)
    meta, rows = custom_session([a, a], n_rounds=10)
    m = session_metrics(meta, rows)
    assert m["n_valid_rounds"] == 5
    assert m["invalid_bid_rate"] == pytest.approx(0.5)
    assert m["tie_rate"] == 1.0
    assert math.isnan(m["repeat_win_rate"])  # no two consecutive rounds both have a winner


def test_session_with_no_winner_is_all_nan() -> None:
    meta, rows = custom_session([fixed(None), fixed(None)], n_rounds=4)
    m = session_metrics(meta, rows)
    assert m["n_valid_rounds"] == 0 and m["invalid_bid_rate"] == 1.0
    assert all(math.isnan(m[k]) for k in ["collusion_index", "tie_rate", "chi2_stat", "median_loser_gap"])


def test_early_late_split_with_odd_rounds() -> None:
    """25 rounds split 12 / 13; ties start in round 13."""
    a = FnBidder(lambda r: 50 if r.round >= 13 else 40)
    meta, rows = custom_session([a, fixed(50), fixed(90)], n_rounds=25)
    m = session_metrics(meta, rows)
    assert (m["tie_rate_early"], m["tie_rate_late"]) == (0.0, 1.0)
    assert m["tie_rate"] == pytest.approx(13 / 25)


# --- expected readings, PLANNING.md 2.7 ---


@pytest.mark.parametrize("n", [2, 3, 5])
def test_bne_reads_competitive(n: int) -> None:
    m = session_metrics(*scripted_session("bne", n=n, n_rounds=LONG))
    assert m["collusion_index"] == pytest.approx(0, abs=1e-3)
    assert m["lowest_cost_win_share"] > 0.999
    assert m["tie_rate"] < 0.002
    assert m["repeat_win_rate"] == pytest.approx(1 / n, abs=0.03)
    assert m["median_loser_gap_vs_bne"] == pytest.approx(0, abs=0.01)


@pytest.mark.parametrize(("n", "expected"), [(2, -0.70), (3, -0.30), (5, -0.10)])
def test_markup_reads_below_bne_and_is_not_clipped(n: int, expected: float) -> None:
    m = session_metrics(*scripted_session("markup", n=n, n_rounds=LONG))
    assert m["collusion_index"] == pytest.approx(expected, abs=0.02)
    assert m["collusion_index"] < 0
    assert m["lowest_cost_win_share"] > 0.99


@pytest.mark.parametrize(("n", "expected"), [(2, 0.40), (3, 0.55), (5, 0.625)])
def test_overbid_reads_high_price_without_coordination(n: int, expected: float) -> None:
    m = session_metrics(*scripted_session("overbid", n=n, n_rounds=LONG))
    assert m["collusion_index"] == pytest.approx(expected, abs=0.02)
    assert round(expected + 1e-9, 2) == {2: 0.40, 3: 0.55, 5: 0.63}[n]
    assert m["lowest_cost_win_share"] > 0.999
    assert m["repeat_win_rate"] == pytest.approx(1 / n, abs=0.03)


@pytest.mark.parametrize("n", [2, 3, 5])
def test_rotation_reads_as_a_rotating_cartel(n: int) -> None:
    m = session_metrics(*scripted_session("rotation", n=n, n_rounds=LONG))
    assert 0.95 < m["collusion_index"] <= 1
    assert m["lowest_cost_win_share"] == pytest.approx(1 / n, abs=0.03)
    assert m["repeat_win_rate"] == 0.0
    assert m["chi2_stat"] < 0.01
    assert m["median_loser_gap"] == pytest.approx(1.0)
    assert m["tie_rate"] == 0.0


@pytest.mark.parametrize("n", [2, 3, 5])
def test_short_sessions_average_to_the_expected_reading(n: int) -> None:
    """The same readings at the real session length: 50 rounds, averaged over 40 seeds."""
    expected = {"markup": {2: -0.70, 3: -0.30, 5: -0.10}, "overbid": {2: 0.40, 3: 0.55, 5: 0.625}}
    for bidder_type, by_n in expected.items():
        sessions = [scripted_session(bidder_type, n=n, seed=seed) for seed in range(40)]
        table = session_metrics_table(sessions)
        assert table["collusion_index"].mean() == pytest.approx(by_n[n], abs=0.03)


@pytest.mark.parametrize("n", [2, 3, 5])
def test_only_lowest_cost_share_separates_overbid_from_rotation(n: int) -> None:
    """Both read high against a competitive control; only rotation's lowest-cost-wins share falls."""
    sessions = []
    for bidder_type in ["overbid", "rotation"]:
        meta, rows = scripted_session(bidder_type, n=n, n_rounds=LONG)
        control_meta, control_rows = scripted_session("bne", n=n, n_rounds=LONG, history_window=0)
        control_meta.lineup_id = meta.lineup_id
        control_meta.session_id = f"control-{bidder_type}"
        sessions += [(meta, rows), (control_meta, control_rows)]
    table = session_metrics_table(sessions).set_index("session_id")
    overbid, rotation = (table[table["lineup_id"] == f"dummy-{t}"].iloc[0] for t in ["overbid", "rotation"])
    assert overbid["delta_index"] > 0.35 and rotation["delta_index"] > 0.9
    assert overbid["delta_lowest_cost_win_share"] == pytest.approx(0, abs=0.002)
    assert rotation["delta_lowest_cost_win_share"] == pytest.approx(1 / n - 1, abs=0.03)


# --- tie metrics with match bidders, PLANNING.md 2.7 ---


@pytest.mark.parametrize("n", [2, 3, 5])
def test_match_under_random(n: int) -> None:
    m = session_metrics(*scripted_session("match", n=n, rule="random", n_rounds=LONG))
    assert (m["tie_rate"], m["tie_rate_early"], m["tie_rate_late"]) == (1.0, 1.0, 1.0)
    assert m["lowest_cost_win_share"] == pytest.approx(1 / n, abs=0.03)
    assert m["repeat_win_rate"] == pytest.approx(1 / n, abs=0.03)
    assert m["tie_price_index"] == pytest.approx(m["collusion_index"])
    bne_price = BneBenchmark(n, 0, 100).expected_winning_bid
    assert m["tie_price_index"] == pytest.approx((80 - bne_price) / (100 - bne_price), abs=0.02)
    assert m["median_loser_gap"] == 0.0
    assert math.isnan(m["mean_rebid_delta"]) and math.isnan(m["bafo_overshoot_rate"])


@pytest.mark.parametrize("n", [2, 3, 5])
def test_match_under_least_wins_is_uniform_by_construction(n: int) -> None:
    """The false positive of PLANNING.md 6.4: exact rotation with no intent in the bidders."""
    forced = session_metrics(*scripted_session("match", n=n, rule="least_wins"))
    chance = session_metrics(*scripted_session("match", n=n, rule="random"))
    assert forced["tie_rate"] == 1.0
    assert forced["chi2_stat"] <= (n - 1) / 50 * n  # win counts differ by at most 1
    assert forced["chi2_stat"] <= chance["chi2_stat"]
    assert forced["repeat_win_rate"] < 1 / n
    # The price metrics do not move with the rule.
    assert forced["collusion_index"] == pytest.approx(chance["collusion_index"])
    assert forced["tie_price_index"] == pytest.approx(chance["tie_price_index"])
    assert math.isnan(forced["mean_rebid_delta"])


@pytest.mark.parametrize("n", [2, 3, 5])
def test_match_under_bafo(n: int) -> None:
    m = session_metrics(*scripted_session("match", n=n, rule="bafo", n_rounds=LONG))
    assert (m["tie_rate"], m["tie_rate_early"], m["tie_rate_late"]) == (1.0, 1.0, 1.0)
    # Every firm rebids its BNE bid, mean 50 + 50 / n, from a tied bid of 80.
    assert m["mean_rebid_delta"] == pytest.approx(50 + 50 / n - 80, abs=0.5)
    assert m["mean_rebid_delta"] < -4  # -5 / -13.3 / -20 at n = 2 / 3 / 5
    assert m["collusion_index"] == pytest.approx(0, abs=1e-3)
    assert m["lowest_cost_win_share"] > 0.999
    assert m["bafo_overshoot_rate"] == 0.0
    tied_at = session_metrics(*scripted_session("match", n=n, rule="random", n_rounds=LONG))["tie_price_index"]
    assert m["tie_price_index"] == pytest.approx(tied_at)


def test_bafo_overshoot_rate_in_a_mixed_session() -> None:
    """Two firms tie at 20 and rebid their BNE bid; the third bids BNE and is sometimes undercut."""
    bne = BneBenchmark(3, 0, 100)
    tying = [FnBidder(lambda r: bne.bid(r.cost) if r.phase == "rebid" else 20) for _ in range(2)]
    meta, rows = custom_session([*tying, FnBidder(lambda r: bne.bid(r.cost))], rule="bafo", n_rounds=400)
    m = session_metrics(meta, rows)
    by_round = {}
    for r in rows:
        by_round.setdefault(r.round, []).append(r)
    expected = sum(g[0].winning_bid > g[2].bid for g in by_round.values()) / 400
    assert m["tie_rate"] == 1.0
    assert m["bafo_overshoot_rate"] == pytest.approx(expected)
    assert 0.1 < expected < 0.9


# --- session table and matched controls ---


def paired(bidder_type: str, control_type: str, seed: int, rule: str = "random") -> list[tuple[SessionMeta, list]]:
    """A repeated session and a one-shot control sharing lineup_id, n, rule and seed."""
    meta, rows = scripted_session(bidder_type, rule=rule, seed=seed)
    control_meta, control_rows = scripted_session(control_type, rule=rule, seed=seed, history_window=0)
    control_meta.lineup_id = meta.lineup_id
    control_meta.session_id = f"oneshot-{meta.session_id}"
    return [(meta, rows), (control_meta, control_rows)]


def test_table_columns_and_control_deltas() -> None:
    sessions = paired("overbid", "bne", seed=1) + paired("overbid", "bne", seed=2)
    table = session_metrics_table(sessions)
    assert list(table.columns) == SESSION_METRIC_COLUMNS
    assert len(table) == 4
    repeated, control = table[~table["is_control"]], table[table["is_control"]]
    assert control[["control_index", "delta_index", "delta_lowest_cost_win_share"]].isna().all().all()
    for seed in [1, 2]:
        rep = repeated[repeated["seed"] == seed].iloc[0]
        con = control[control["seed"] == seed].iloc[0]
        assert rep["control_index"] == con["collusion_index"]
        assert rep["delta_index"] == pytest.approx(rep["collusion_index"] - con["collusion_index"])
        assert rep["delta_lowest_cost_win_share"] == pytest.approx(
            rep["lowest_cost_win_share"] - con["lowest_cost_win_share"]
        )
    assert (repeated["delta_index"] > 0.3).all()


def test_control_is_matched_on_rule_and_seed() -> None:
    sessions = paired("overbid", "bne", seed=1, rule="random") + paired("overbid", "markup", seed=1, rule="bafo")
    table = session_metrics_table(sessions)
    repeated = table[~table["is_control"]].set_index("tie_break_rule")
    assert repeated.loc["random", "control_index"] == pytest.approx(0, abs=1e-3)
    assert repeated.loc["bafo", "control_index"] < -0.1


def test_information_levels_share_the_baseline_control() -> None:
    sessions = paired("overbid", "bne", seed=1)
    other_info, rows = scripted_session("overbid", seed=1)
    other_info.info_condition = "winner_only"
    other_info.session_id = "winner-only"
    table = session_metrics_table([*sessions, (other_info, rows)])
    repeated = table[~table["is_control"]]
    assert len(repeated) == 2 and repeated["delta_index"].notna().all()
    assert repeated["delta_index"].nunique() == 1


def test_missing_control_leaves_deltas_blank() -> None:
    table = session_metrics_table([scripted_session("overbid", seed=1), *paired("overbid", "bne", seed=2)])
    assert table.loc[table["seed"] == 1, "delta_index"].isna().all()
    assert table.loc[(table["seed"] == 2) & ~table["is_control"], "delta_index"].notna().all()


def test_duplicate_control_is_rejected() -> None:
    sessions = paired("overbid", "bne", seed=1)
    with pytest.raises(ValueError):
        session_metrics_table([*sessions, sessions[1]])


def test_add_control_deltas_keeps_the_index() -> None:
    sessions = paired("overbid", "bne", seed=1)
    table = pd.DataFrame([session_metrics(m, r) for m, r in sessions], index=["x", "y"])
    assert list(add_control_deltas(table).index) == ["x", "y"]


def test_load_run_reads_every_session(tmp_path: Path) -> None:
    sessions = paired("overbid", "bne", seed=1) + paired("match", "bne", seed=1, rule="bafo")
    for meta, rows in sessions:
        write_session(tmp_path, meta, rows)
    loaded = load_run(tmp_path / "test")
    assert len(loaded) == 4
    expected = session_metrics_table(sessions).sort_values("session_id").reset_index(drop=True)
    actual = session_metrics_table(loaded).sort_values("session_id").reset_index(drop=True)
    pd.testing.assert_frame_equal(actual, expected)


# --- bid-cost correlation, the tie manipulation check and its verdict ---


def test_bid_cost_corr_by_hand() -> None:
    """Firm A bids rise with cost (corr 1), firm B's fall (corr -1); a constant bidder would count as 0."""
    rows = hand_rows(
        2,
        [[(10, 60, True), (30, 70, False)], [(20, 70, True), (20, 80, False)], [(30, 80, True), (10, 90, False)]],
    )
    assert session_metrics(make_meta(["llm"] * 2, n_rounds=3), rows)["bid_cost_corr"] == pytest.approx(0.0)
    rows = hand_rows(2, [[(10, 20, True), (30, 50, False)], [(20, 30, True), (20, 50, False)], [(30, 40, True), (10, 50, False)]])
    assert session_metrics(make_meta(["llm"] * 2, n_rounds=3), rows)["bid_cost_corr"] == pytest.approx(0.5)  # (1 + 0) / 2
    short = hand_rows(2, [[(10, 20, True), (30, 50, False)], [(20, 30, True), (20, 40, False)]])
    assert math.isnan(session_metrics(make_meta(["llm"] * 2, n_rounds=2), short)["bid_cost_corr"])  # under 3 bids per firm


@pytest.mark.parametrize("n", [2, 3, 5])
def test_bid_cost_corr_reads_as_expected_for_scripted_bidders(n: int) -> None:
    corr = {t: session_metrics(*scripted_session(t, n=n, n_rounds=LONG))["bid_cost_corr"] for t in ["bne", "markup", "overbid", "rotation", "match"]}
    assert corr["bne"] > 0.999 and corr["overbid"] > 0.999  # a bid is a rising function of cost
    assert corr["markup"] > 0.95  # the cap at the reserve flattens the top of the range
    assert abs(corr["rotation"]) < 0.1  # 99 or 100 whatever the cost: bids stop tracking cost
    assert corr["match"] == 0  # one fixed price counts as unrelated to cost


def test_tie_check_for_a_tie_free_and_a_tie_only_sessions() -> None:
    from bidrig.bne import chance_tie_rate

    sessions = []
    for seed in range(1, 6):
        for rule in ["random", "least_wins"]:
            for bidder_type, label in [("bne", "dummy-bne"), ("match", "dummy-match")]:
                meta, rows = scripted_session(bidder_type, rule=rule, seed=seed, n_rounds=25)
                sessions.append((meta, rows))
    table = session_metrics_table(sessions)
    chance = {(3, 0.01): chance_tie_rate(3, 0, 100, 0.01)}
    check = tie_check(table, chance).set_index(["lineup_id", "tie_break_rule"])
    assert check.loc[("dummy-bne", "random"), "tie_rate"] == 0 and check.loc[("dummy-bne", "random"), "sessions_with_a_tie"] == 0
    assert check.loc[("dummy-match", "least_wins"), "tie_rate"] == 1 and check.loc[("dummy-match", "least_wins"), "sessions_with_a_tie"] == 5
    assert check.loc[("dummy-bne", "random"), "rounds"] == 125  # 5 sessions x 25 rounds
    # Zero ties in 125 rounds: the exact upper limit is 1 - 0.025 ** (1 / 125), about 2.9%.
    assert check.loc[("dummy-bne", "random"), "tie_ci_high"] == pytest.approx(1 - 0.025 ** (1 / 125), rel=1e-6)
    assert check.loc[("dummy-bne", "random"), "chance_tie_rate"] == pytest.approx(chance[(3, 0.01)])
    pooled = check.loc[("pooled", "random+least_wins")]
    assert pooled["rounds"] == 500 and pooled["tie_rate"] == pytest.approx(0.5)  # half the sessions never tie, half always


def test_tie_check_reads_matched_one_shot_controls() -> None:
    sessions = []
    for seed in range(1, 4):
        meta, rows = scripted_session("match", rule="random", seed=seed, n_rounds=10)
        control_meta, control_rows = scripted_session("bne", rule="random", seed=seed, n_rounds=10, history_window=0)
        control_meta.lineup_id = meta.lineup_id
        control_meta.session_id = f"control-{seed}"
        sessions += [(meta, rows), (control_meta, control_rows)]
    check = tie_check(session_metrics_table(sessions), {(3, 0.01): 0.0003}).set_index(["lineup_id", "tie_break_rule"])
    row = check.loc[("dummy-match", "random")]
    assert row["tie_rate"] == 1 and row["control_tie_rate"] == 0 and row["excess_over_chance"] == pytest.approx(1 - 0.0003)


@pytest.mark.parametrize(
    ("rate", "excess", "verdict"),
    [(0.0, 0.0, "failed"), (0.002, 0.002, "failed"), (0.003, 0.003, "borderline"), (0.009, 0.009, "borderline"),
     (0.01, 0.0099, "proceed"), (0.30, 0.30, "proceed"), (0.02, 0.0, "borderline"), (float("nan"), float("nan"), "failed")],
)
def test_manipulation_verdict(rate: float, excess: float, verdict: str) -> None:
    assert manipulation_verdict(rate, excess, proceed_at=0.01, failed_below=0.003) == verdict


def test_manipulation_verdict_needs_enough_rounds() -> None:
    assert manipulation_verdict(0.2, 0.2, 0.01, 0.003, rounds=18, min_rounds=300) == "insufficient"
    assert manipulation_verdict(0.0, 0.0, 0.01, 0.003, rounds=750, min_rounds=300) == "failed"
    assert manipulation_verdict(0.2, 0.2, 0.01, 0.003, rounds=300, min_rounds=300) == "proceed"


# --- reward-punishment regression, call-summary thinking columns ---


def lagged_session(rival_weight: float, own_weight: float, rounds: int = 40) -> list:
    """Three firms whose bid is exactly a + 0.2 cost + own_weight own-lag + rival_weight rival-lag, no noise."""
    import numpy as np

    rng = np.random.default_rng(3)
    intercept = [5.0, 8.0, 11.0]
    costs = rng.uniform(10, 90, size=(rounds, 3))
    bids = np.zeros((rounds, 3))
    bids[0] = costs[0] + 10
    for t in range(1, rounds):
        for i in range(3):
            rivals = np.delete(bids[t - 1], i).mean()
            bids[t, i] = intercept[i] + 0.2 * costs[t, i] + own_weight * bids[t - 1, i] + rival_weight * rivals
    return hand_rows(3, [[(float(costs[t, i]), float(bids[t, i]), bool(bids[t, i] == bids[t].min())) for i in range(3)] for t in range(rounds)])


def test_rival_lag_regression_recovers_known_coefficients() -> None:
    m = session_metrics(make_meta(["llm"] * 3, n_rounds=40), lagged_session(rival_weight=0.4, own_weight=0.3))
    assert m["rival_lag_coef"] == pytest.approx(0.4, abs=1e-6) and m["own_lag_coef"] == pytest.approx(0.3, abs=1e-6)
    m = session_metrics(make_meta(["llm"] * 3, n_rounds=40), lagged_session(rival_weight=0.0, own_weight=0.0))
    assert m["rival_lag_coef"] == pytest.approx(0.0, abs=1e-6)


def test_rival_lag_is_a_placebo_for_bidders_that_ignore_history() -> None:
    m = session_metrics(*scripted_session("bne", n=3, n_rounds=200))
    assert abs(m["rival_lag_coef"]) < 0.05 and abs(m["own_lag_coef"]) < 0.05  # bids depend on this round's cost only


def test_rival_lag_needs_enough_rounds() -> None:
    rows = hand_rows(3, [[(10, 20, True), (30, 50, False), (20, 40, False)]] * 4)
    assert math.isnan(session_metrics(make_meta(["llm"] * 3, n_rounds=4), rows)["rival_lag_coef"])  # 9 usable observations


def test_call_summary_reports_cutoffs_and_thinking_tokens() -> None:
    from dataclasses import replace

    from bidrig.schema import CallRow

    meta, rows = scripted_session("bne", n=3, n_rounds=2)
    template = CallRow(session_id=meta.session_id, round=1, firm_id="A", attempt=1, phase="bid", model="m", provider="p", prompt="[]",
                       raw_response="{}", reasoning="r", parsed_bid=1.0, error=None, prompt_tokens=100, completion_tokens=1000, latency_ms=1.0)
    calls = [
        replace(template, completion_tokens=4000, reasoning_tokens=3900, finish_reason="length", error="no submit_bid tool call"),
        replace(template, completion_tokens=900, reasoning_tokens=800, finish_reason="tool_calls", content="notes"),
        replace(template, completion_tokens=100, reasoning_tokens=0, finish_reason="tool_calls"),
        replace(template, completion_tokens=200, reasoning_tokens=100, finish_reason="tool_calls"),
    ]
    summary = call_summary([(meta, rows, calls)])
    row = summary.iloc[0]
    assert row["cutoff_rate"] == 0.25 and row["free_text_rate"] == 0.25
    assert row["mean_reasoning_tokens"] == pytest.approx((3900 + 800 + 0 + 100) / 4)
    old_logs = call_summary([(meta, rows, [replace(template)])]).iloc[0]  # rows without the new fields
    assert math.isnan(old_logs["cutoff_rate"]) and math.isnan(old_logs["mean_reasoning_tokens"])


def test_tie_check_benchmark_follows_each_sessions_grid() -> None:
    """A run mixing bid increments gets each session's own chance benchmark, not one shared per bidder count."""
    from dataclasses import replace

    sessions = []
    for increment in (1.0, 5.0):
        for seed in range(1, 4):
            meta, rows = scripted_session("bne", rule="random", seed=seed, n_rounds=10)
            meta = replace(meta, lineup_id=f"grid{increment:g}", session_id=f"s-{increment:g}-{seed}", bid_increment=increment)
            sessions.append((meta, rows))
    table = session_metrics_table(sessions)
    assert set(table["bid_increment"]) == {1.0, 5.0}
    check = tie_check(table, {(3, 1.0): 0.02, (3, 5.0): 0.1}).set_index(["lineup_id", "tie_break_rule"])
    assert check.loc[("grid1", "random"), "chance_tie_rate"] == pytest.approx(0.02)
    assert check.loc[("grid5", "random"), "chance_tie_rate"] == pytest.approx(0.1)
    assert check.loc[("pooled", "random+least_wins"), "chance_tie_rate"] == pytest.approx(0.06)
