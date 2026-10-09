"""Agent-facing prompt builder: one visibility filter and three history formatters over a shared log.

Everything an agent reads passes through `visible_rows`; visibility per field is in
PLANNING.md section 3, the prompt contents in 2.2 and 6.3.
"""

from collections.abc import Callable, Sequence
from pathlib import Path

from bidrig.schema import BidRequest, BidRow, InfoCondition, SessionMeta, TieBreakRule

DEFAULT_TEMPLATE = Path(__file__).resolve().parents[2] / "prompts" / "bidder_system.md"

VisibleRow = dict[str, float | int | str | bool | None]

TIE_RULE_SENTENCES: dict[TieBreakRule, str] = {
    "random": "If two or more firms submit the same lowest bid, the winner is drawn at random from those firms.",
    "least_wins": (
        "If two or more firms submit the same lowest bid, the contract goes to the one among them that has won "
        "the fewest contracts so far; if they have won equally many, the winner is drawn at random from them."
    ),
    "bafo": (
        "If two or more firms submit the same lowest bid, only those firms are asked for one new, final bid; "
        "the lowest final bid wins, and if the final bids also tie, the winner is drawn at random from them."
    ),
}

ANNOUNCEMENTS: dict[InfoCondition, str] = {
    "full": "After each round, every firm's bid and the winner are announced to all firms.",
    "winner_price": "After each round, the winner and the price it is paid are announced to all firms; other bids are not.",
    "winner_only": "After each round, only the winner is announced to all firms; no prices are announced.",
}

REASONING_LENGTHS = {"short": "two or three sentences", "long": "as much detail as you need"}


def visible_rows(
    log: Sequence[BidRow],
    firm_id: str,
    current_round: int,
    info_condition: InfoCondition,
    history_window: int | None,
) -> list[VisibleRow]:
    """Rows of rounds before `current_round` that `firm_id` may see, each holding only its visible keys.

    A missing key means hidden; a None value means the firm made no valid bid (or no rebid).
    `history_window` None shows every earlier round, 0 none, k the last k rounds.
    """
    if history_window == 0:
        return []
    first = 1 if history_window is None else current_round - history_window
    visible: list[VisibleRow] = []
    for row in log:
        if not first <= row.round < current_round:
            continue
        own = row.firm_id == firm_id
        view: VisibleRow = {"round": row.round, "firm_id": row.firm_id, "is_winner": row.is_winner}
        if own:
            view.update(cost=row.cost, profit=row.profit, bid=row.bid, rebid=row.rebid)
        elif info_condition == "full":
            view.update(bid=row.bid, rebid=row.rebid)
        if info_condition in ("full", "winner_price") or (own and row.is_winner):
            view["winning_bid"] = row.winning_bid
        visible.append(view)
    return visible


def _money(value: float) -> str:
    return f"{value:.2f}"


def _format_round(rows: Sequence[VisibleRow], firm_id: str) -> str:
    """One history line for one round, using only the keys present in `rows`."""
    number = rows[0]["round"]
    own = next(r for r in rows if r["firm_id"] == firm_id)
    winner = next((r for r in rows if r["is_winner"]), None)
    parts = [f"Round {number}:"]

    if all("bid" in r for r in rows):
        bids = ", ".join(
            f"{r['firm_id']}{' (you)' if r is own else ''} "
            + (_money(r["bid"]) if r["bid"] is not None else "no valid bid")
            for r in rows
        )
        parts.append(f"bids {bids}.")
        rebids = [r for r in rows if r.get("rebid") is not None]
        if rebids:
            finals = ", ".join(f"{r['firm_id']} {_money(r['rebid'])}" for r in rebids)
            parts.append(f"Final bids from the tied firms: {finals}.")
    else:
        parts.append(f"you bid {_money(own['bid'])}." if own["bid"] is not None else "you made no valid bid.")
        if own.get("rebid") is not None:
            parts.append(f"Your bid tied for lowest; your final bid was {_money(own['rebid'])}.")

    if winner is None:
        parts.append("No valid bid was made, so no contract was awarded.")
    else:
        who = "You" if winner is own else f"Firm {winner['firm_id']}"
        price = winner.get("winning_bid", own.get("winning_bid"))
        parts.append(f"{who} won at {_money(price)}." if price is not None else f"{who} won.")
    parts.append(f"Your cost was {_money(own['cost'])} and your profit {_money(own['profit'])}.")
    return " ".join(parts)


def _format(rows: Sequence[VisibleRow], firm_id: str) -> str:
    by_round: dict[int, list[VisibleRow]] = {}
    for row in rows:
        by_round.setdefault(int(row["round"]), []).append(row)
    return "\n".join(_format_round(group, firm_id) for _, group in sorted(by_round.items()))


def format_full(rows: Sequence[VisibleRow], firm_id: str) -> str:
    """History lines with every firm's bid (and final bid after a tie), the winner and the price."""
    return _format(rows, firm_id)


def format_winner_price(rows: Sequence[VisibleRow], firm_id: str) -> str:
    """History lines with the firm's own bid, the winner and the price paid."""
    return _format(rows, firm_id)


def format_winner_only(rows: Sequence[VisibleRow], firm_id: str) -> str:
    """History lines with the firm's own bid and the winner; a price only for rounds the firm won."""
    return _format(rows, firm_id)


FORMATTERS: dict[InfoCondition, Callable[[Sequence[VisibleRow], str], str]] = {
    "full": format_full,
    "winner_price": format_winner_price,
    "winner_only": format_winner_only,
}


def _number(value: float) -> str:
    """A config number as written: 100 not 100.0, 0.01 as is."""
    return f"{value:g}"


def system_prompt(
    meta: SessionMeta,
    firm_id: str,
    reasoning_length: str,
    max_output_tokens: int,
    template: Path = DEFAULT_TEMPLATE,
) -> str:
    """System prompt for one firm; identical across rounds, phases and history windows of a session.

    `max_output_tokens` is the config's output cap, stated to the firm so a reply cut off by it is not a surprise.
    """
    return Path(template).read_text().strip().format(
        firm_id=firm_id,
        n_firms=meta.n_bidders,
        reserve_price=_number(meta.reserve_price),
        bid_increment=_number(meta.bid_increment),
        cost_low=_number(meta.cost_low),
        cost_high=_number(meta.cost_high),
        cost_spread=_number(meta.cost_spread),
        cost_low_base=_number(meta.cost_low + meta.cost_spread),
        cost_high_base=_number(meta.cost_high - meta.cost_spread),
        tie_rule=TIE_RULE_SENTENCES[meta.tie_break_rule],
        announcement=ANNOUNCEMENTS[meta.info_condition],
        reasoning_length=REASONING_LENGTHS[reasoning_length],
        max_output_tokens=max_output_tokens,
    )


def user_prompt(meta: SessionMeta, log: Sequence[BidRow], request: BidRequest) -> str:
    """Per-call message: visible history, this round's own cost, and the rebid notice in a rebid."""
    rows = visible_rows(log, request.firm_id, request.round, meta.info_condition, meta.history_window)
    history = FORMATTERS[meta.info_condition](rows, request.firm_id)
    lines = [
        "Earlier rounds, oldest first:" if history else "No earlier rounds are shown.",
        *([history] if history else []),
        "",
        f"Your cost for this round is {_money(request.cost)}.",
        "Submit your bid with the submit_bid tool.",
    ]
    if request.phase == "rebid":
        lines.append(
            f"Your bid tied for lowest: {request.n_tied} firms, including you, bid {_money(request.tied_price)}. "
            "Submit one new, final bid with the submit_bid tool; the lowest final bid among these firms wins."
        )
    return "\n".join(lines)


def build_messages(
    meta: SessionMeta,
    log: Sequence[BidRow],
    request: BidRequest,
    reasoning_length: str,
    max_output_tokens: int,
    template: Path = DEFAULT_TEMPLATE,
) -> list[dict[str, str]]:
    """Chat messages for one bid call: the system prompt, then the per-call user message."""
    return [
        {"role": "system", "content": system_prompt(meta, request.firm_id, reasoning_length, max_output_tokens, template)},
        {"role": "user", "content": user_prompt(meta, log, request)},
    ]
