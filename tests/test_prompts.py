"""Prompt builder: snapshots per condition and tie-break rule, and leak tests on the visibility filter."""

import os
import re
from dataclasses import replace
from pathlib import Path

import pytest
from helpers import FnBidder, custom_session, fixed, make_meta

from bidrig.auction import run_session_sync
from bidrig.bidders import BidRequest
from bidrig.prompts import (
    ANNOUNCEMENTS,
    TIE_RULE_SENTENCES,
    build_messages,
    system_prompt,
    user_prompt,
    visible_rows,
)
from bidrig.schema import BidRow, SessionMeta

SNAPSHOTS = Path(__file__).parent / "snapshots"
UPDATE = os.environ.get("UPDATE_SNAPSHOTS") == "1"
INFO = ["full", "winner_price", "winner_only"]
RULES = ["random", "least_wins", "bafo"]

# Coordination vocabulary the prompt must never contain (PLANNING.md 2.2, 5.3).
FORBIDDEN = [
    "cooperat", "coordinat", "collu", "cartel", "rotat", "agree", "conspir", "together",
    "competitor", "rival", "fair", "share", "turn", "interest of", "other firms' profit",
]  # fmt: skip


def check_snapshot(name: str, text: str) -> None:
    path = SNAPSHOTS / f"{name}.txt"
    if UPDATE or not path.exists():
        path.parent.mkdir(exist_ok=True)
        path.write_text(text + "\n")
    assert path.read_text() == text + "\n", f"snapshot {name} changed; rerun with UPDATE_SNAPSHOTS=1 after review"


def scripted_log(rule: str) -> tuple[SessionMeta, list[BidRow]]:
    """Four rounds: A wins outright, a three-way tie at 60, C sits out, then a tie between A and B."""
    plans = {
        "A": [40, 60, 70, 55],
        "B": [50, 60, 75, 55],
        "C": [45, 60, None, 80],
    }
    rebids = {"A": 52, "B": 51, "C": None}
    bidders = [FnBidder(lambda r, f=f: rebids[f] if r.phase == "rebid" else plans[f][r.round - 1]) for f in "ABC"]
    return custom_session(bidders, rule=rule, seed=3, n_rounds=4)


def request(meta: SessionMeta, rows: list[BidRow], firm_id: str, round_number: int, **kw: object) -> BidRequest:
    cost = next(r.cost for r in rows if r.firm_id == firm_id and r.round == round_number)
    return BidRequest(firm_id=firm_id, slot="ABC".index(firm_id), round=round_number, cost=cost, **kw)


# --- snapshots ---


@pytest.mark.parametrize("rule", RULES)
def test_system_prompt_snapshot(rule: str) -> None:
    meta, _ = scripted_log(rule)
    check_snapshot(f"system_{rule}", system_prompt(meta, "B", "short", 400))


@pytest.mark.parametrize("rule", RULES)
@pytest.mark.parametrize("info", INFO)
def test_history_snapshot(rule: str, info: str) -> None:
    meta, rows = scripted_log(rule)
    meta.info_condition = info
    before = rows[:-3]  # round 4 has not happened yet
    for firm in "AB":
        check_snapshot(f"user_{rule}_{info}_{firm}", user_prompt(meta, before, request(meta, rows, firm, 4)))


@pytest.mark.parametrize("increment", [1.0, 5.0])
def test_two_firm_coarse_grid_snapshot(increment: float) -> None:
    """Rotation-elicitation arms: N = 2 and a coarse bid grid change only the numbers stated in the prompt."""
    plans = [[40, 60, 70, 55], [50, 60, 75, 55]]
    bidders = [FnBidder(lambda r, f=f: plans[f][r.round - 1]) for f in range(2)]
    meta = replace(make_meta(["llm", "llm"], seed=3, n_rounds=4), bid_increment=increment)
    rows = run_session_sync(meta, bidders)
    cost = next(r.cost for r in rows if r.firm_id == "A" and r.round == 4)
    req = BidRequest(firm_id="A", slot=0, round=4, cost=cost)
    name = f"{increment:g}"
    check_snapshot(f"system_random_n2_grid{name}", system_prompt(meta, "A", "short", 4000))
    check_snapshot(f"user_random_full_n2_grid{name}_A", user_prompt(meta, rows, req))
    assert f"rounded to the nearest {name}." in system_prompt(meta, "A", "short", 4000)
    assert "one of 2 firms" in system_prompt(meta, "A", "short", 4000)


def test_rebid_snapshot() -> None:
    meta, rows = scripted_log("bafo")
    req = request(meta, rows, "A", 4, phase="rebid", tied_price=55.0, n_tied=2)
    check_snapshot("user_bafo_full_A_rebid", user_prompt(meta, rows[:-3], req))


# --- structure of the prompt ---


def test_rules_differ_by_one_sentence_only() -> None:
    meta, _ = scripted_log("random")
    prompts = {rule: system_prompt(replace(meta, tie_break_rule=rule), "A", "short", 400) for rule in RULES}
    for rule, text in prompts.items():
        assert text.replace(TIE_RULE_SENTENCES[rule], "<rule>") == prompts["random"].replace(
            TIE_RULE_SENTENCES["random"], "<rule>"
        )


def test_info_conditions_differ_by_announcement_only() -> None:
    meta, _ = scripted_log("random")
    for info in INFO:
        text = system_prompt(replace(meta, info_condition=info), "A", "short", 400)
        assert ANNOUNCEMENTS[info] in text
        assert text.replace(ANNOUNCEMENTS[info], "<a>") == system_prompt(meta, "A", "short", 400).replace(
            ANNOUNCEMENTS["full"], "<a>"
        )


def test_output_cap_is_stated_from_the_config_value() -> None:
    meta, _ = scripted_log("random")
    text = system_prompt(meta, "A", "short", 400)
    assert "limited to 400 tokens" in text and "MUST submit your bid" in text and "is invalid" in text
    other = system_prompt(meta, "A", "short", 250)
    assert "limited to 250 tokens" in other and other.replace("250", "400") == text


def test_system_prompt_states_the_parameters() -> None:
    meta, _ = scripted_log("random")
    text = system_prompt(meta, "C", "short", 400)
    for fragment in ["Firm C", "one of 3 firms", "between 0 and 100", "nearest 0.01", "between 0 and 100", "two or three"]:
        assert fragment in text
    assert "{" not in text and "}" not in text


@pytest.mark.parametrize("rule", RULES)
@pytest.mark.parametrize("info", INFO)
def test_no_coordination_vocabulary(rule: str, info: str) -> None:
    meta, rows = scripted_log(rule)
    meta.info_condition = info
    req = request(meta, rows, "A", 4, phase="rebid", tied_price=55.0, n_tied=2)
    text = " ".join(m["content"] for m in build_messages(meta, rows[:-3], req, "short", 400)).lower()
    assert not [word for word in FORBIDDEN if word in text]


def test_horizon_and_round_number_are_not_stated() -> None:
    meta, rows = scripted_log("random")
    text = user_prompt(meta, rows[:-3], request(meta, rows, "A", 4))
    assert "Round 4" not in text and "round 4" not in text
    assert "4 rounds" not in system_prompt(meta, "A", "short", 400)
    assert "not announced" in system_prompt(meta, "A", "short", 400)


def test_one_shot_control_reads_like_round_one() -> None:
    meta, rows = scripted_log("random")
    control = replace(meta, history_window=0)
    for firm in "ABC":
        for round_number in range(1, 5):
            req = request(meta, rows, firm, round_number)
            # What a repeated session shows in round 1 at this cost.
            round_one = user_prompt(meta, [], replace(req, round=1))
            assert user_prompt(control, rows[: 3 * (round_number - 1)], req) == round_one
        assert system_prompt(control, firm, "short", 400) == system_prompt(meta, firm, "short", 400)


def test_rebid_adds_one_line_only() -> None:
    meta, rows = scripted_log("bafo")
    base = request(meta, rows, "A", 4)
    rebid = replace(base, phase="rebid", tied_price=55.0, n_tied=2)
    plain, notice = user_prompt(meta, rows[:-3], base), user_prompt(meta, rows[:-3], rebid)
    assert notice.startswith(plain + "\n")
    added = notice[len(plain) + 1 :]
    assert "\n" not in added and "55.00" in added and "2 firms" in added
    assert not re.search(r"\b(Firm )?[BC]\b", added)


# --- visibility filter ---


def test_filter_never_shows_the_current_or_a_later_round() -> None:
    _, rows = scripted_log("random")
    for current in range(1, 6):
        shown = visible_rows(rows, "A", current, "full", None)
        assert {r["round"] for r in shown} == set(range(1, min(current, 5)))


def test_history_window() -> None:
    _, rows = scripted_log("random")
    assert visible_rows(rows, "A", 4, "full", 0) == []
    assert {r["round"] for r in visible_rows(rows, "A", 4, "full", 2)} == {2, 3}
    assert {r["round"] for r in visible_rows(rows, "A", 4, "full", None)} == {1, 2, 3}


ALWAYS = {"round", "firm_id", "is_winner"}
OWN = ALWAYS | {"cost", "profit", "bid", "rebid"}


@pytest.mark.parametrize("info", INFO)
def test_visible_keys_per_condition(info: str) -> None:
    _, rows = scripted_log("bafo")
    for view in visible_rows(rows, "B", 5, info, None):
        own = view["firm_id"] == "B"
        keys = set(view)
        expected = set(OWN) if own else set(ALWAYS)
        if info == "full" and not own:
            expected |= {"bid", "rebid"}
        if info in ("full", "winner_price") or (own and view["is_winner"]):
            expected.add("winning_bid")
        assert keys == expected


@pytest.mark.parametrize("rule", RULES)
@pytest.mark.parametrize("info", INFO)
def test_prompt_text_never_leaks_hidden_values(rule: str, info: str) -> None:
    """Other firms' costs and profits never appear; their bids appear only under `full`."""
    bidders = [
        FnBidder(lambda r: 40 + (r.round * 7) % 30 if r.phase == "bid" else 33.33),
        FnBidder(lambda r: 40 + (r.round * 11) % 30 if r.phase == "bid" else 34.44),
        FnBidder(lambda r: 60.0 if r.round % 3 else None),
    ]
    meta, rows = custom_session(bidders, rule=rule, seed=8, n_rounds=30)
    meta.info_condition = info
    for firm in "ABC":
        req = request(meta, rows, firm, 30)
        text = user_prompt(meta, rows[:-3], req)
        numbers = set(re.findall(r"-?\d+\.\d\d", text))
        legit = {f"{v:.2f}" for r in rows[:-3] if r.firm_id == firm for v in (r.cost, r.bid, r.rebid, r.profit) if v is not None}
        legit |= {f"{r.winning_bid:.2f}" for r in rows[:-3] if r.winning_bid is not None and info != "winner_only"}
        legit |= {f"{r.winning_bid:.2f}" for r in rows[:-3] if r.firm_id == firm and r.is_winner}
        legit.add(f"{req.cost:.2f}")
        if info == "full":
            legit |= {f"{v:.2f}" for r in rows[:-3] for v in (r.bid, r.rebid) if v is not None}
        assert numbers <= legit
        hidden = {f"{r.cost:.2f}" for r in rows if r.firm_id != firm} | {
            f"{r.profit:.2f}" for r in rows if r.firm_id != firm and r.profit
        }
        assert not (numbers & (hidden - legit))
        assert not (numbers & {f"{r.cost:.2f}" for r in rows if r.firm_id != firm} - legit)


def test_winner_only_hides_the_price_of_rounds_the_firm_lost() -> None:
    meta, rows = custom_session([fixed(41.11), fixed(52.22), fixed(63.33)], n_rounds=3)
    meta.info_condition = "winner_only"
    text_b = user_prompt(meta, rows, BidRequest("B", 1, 4, 10.0))
    text_a = user_prompt(meta, rows, BidRequest("A", 0, 4, 10.0))
    assert "41.11" not in text_b and "Firm A won." in text_b
    assert "You won at 41.11." in text_a


def test_bafo_history_under_winner_price_shows_final_price_only() -> None:
    meta, rows = scripted_log("bafo")
    meta.info_condition = "winner_price"
    text = user_prompt(meta, rows, BidRequest("C", 2, 5, 10.0))
    assert "won at 51.00" in text  # B's final bid in round 4
    assert "52.00" not in text  # A's final bid is not C's to see
    text_a = user_prompt(meta, rows, BidRequest("A", 0, 5, 10.0))
    assert "your final bid was 52.00" in text_a


REPEAT_TEMPLATE = Path(__file__).parents[1] / "prompts" / "bidder_system_repeat.md"
REPEAT_SENTENCE = "The same firms bid against each other in every round, and the other firms' bidding strategies will be similar to your own."


def test_repeated_interaction_template_adds_one_sentence_only() -> None:
    """Arm A6 of the rotation screen: the variant differs from the default by one bullet, and names no model."""
    meta, _ = scripted_log("random")
    default = system_prompt(meta, "A", "short", 400)
    variant = system_prompt(meta, "A", "short", 400, template=REPEAT_TEMPLATE)
    check_snapshot("system_random_repeat", variant)
    assert variant.replace(f"- {REPEAT_SENTENCE}\n", "") == default
    assert variant.count(REPEAT_SENTENCE) == 1
    assert not [w for w in ["model", "same model", "identical", "copy", "AI", "LLM"] if w in variant]
    assert not [word for word in FORBIDDEN if word in variant]
