"""Consistency checks on a run's raw logs: auction invariants, costs, bids against calls, and every logged prompt.

Meant for the hand-check before a pilot (PLANNING.md 5.5). Prompts get independent checks (rounds shown,
cost line, leaks, tie rule) and an exact rebuild through the prompt builder from the bid log.
"""

import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from bidrig.auction import draw_costs, from_ticks, to_ticks
from bidrig.bne import make_benchmark
from bidrig.llm import ERROR_LOG_LIMIT
from bidrig.prompts import (
    ANNOUNCEMENTS,
    DEFAULT_TEMPLATE,
    REASONING_LENGTHS,
    TIE_RULE_SENTENCES,
    system_prompt,
    user_prompt,
)
from bidrig.schema import (
    SESSION_FILE,
    BidRequest,
    BidRow,
    CallRow,
    SessionMeta,
    read_calls,
    read_session,
)

CAP_PATTERN = re.compile(r"limited to (\d+) tokens")
ROUND_LINE = re.compile(r"^Round (\d+):", re.MULTILINE)
COST_LINE = re.compile(r"Your cost for this round is (-?\d+\.\d\d)\.")
REBID_NOTICE = re.compile(r"Your bid tied for lowest: (\d+) firms, including you, bid (\d+\.\d\d)\.")
NUMBER = re.compile(r"-?\d+\.\d\d")

CHECKS = [
    "structure",
    "costs",
    "auction",
    "bids_vs_calls",
    "rebid_calls",
    "provider",
    "tokens",
    "retry_messages",
    "system_prompt",
    "tie_rule_prompt",
    "user_prompt",
    "rounds_shown",
    "cost_line",
    "leak",
    "rebid_notice",
]


@dataclass(frozen=True)
class SessionLog:
    """One session directory read back from disk; `calls` is empty for scripted sessions."""

    path: Path
    meta: SessionMeta
    rows: list[BidRow]
    calls: list[CallRow]


@dataclass(frozen=True)
class Finding:
    """One failed check on one session; `detail` names the round and firm where it applies."""

    check: str
    session_id: str
    detail: str


@dataclass
class CheckReport:
    """Everything the checks saw: items checked per check, findings, and what the prompts and hosts looked like."""

    sessions: int = 0
    calls: int = 0
    items: Counter[str] = field(default_factory=Counter)
    findings: list[Finding] = field(default_factory=list)
    caps: Counter[int] = field(default_factory=Counter)  # output-token cap each system prompt states
    providers: Counter[tuple[str, str]] = field(default_factory=Counter)  # (model alias, serving provider)
    cutoffs: int = 0  # attempts that hit the output cap (finish_reason `length`)
    with_thinking: int = 0  # attempts with hidden thinking text
    with_free_text: int = 0  # attempts with text outside the tool call

    def fail(self, check: str, session_id: str, detail: str) -> None:
        """Record a finding."""
        self.findings.append(Finding(check, session_id, detail))

    def failures(self, check: str) -> list[Finding]:
        """Findings of one check."""
        return [f for f in self.findings if f.check == check]

    @property
    def passed(self) -> bool:
        """True when no check failed."""
        return not self.findings


def load_logs(run_dir: Path, include_incomplete: bool = False) -> tuple[list[SessionLog], list[str]]:
    """Every session under `logs/<run_id>/` and the ids skipped for not being complete."""
    logs, skipped = [], []
    for session_json in sorted(Path(run_dir).glob(f"*/*/{SESSION_FILE}")):
        meta, rows = read_session(session_json.parent)
        if meta.status != "complete" and not include_incomplete:
            skipped.append(f"{meta.session_id} ({meta.status})")
            continue
        logs.append(SessionLog(session_json.parent, meta, rows, read_calls(session_json.parent)))
    return logs, skipped


def _by_round(rows: Iterable[BidRow]) -> list[tuple[int, list[BidRow]]]:
    grouped: dict[int, list[BidRow]] = defaultdict(list)
    for row in rows:
        grouped[row.round].append(row)
    return sorted(grouped.items())


def check_structure(log: SessionLog, report: CheckReport, include_incomplete: bool = False) -> None:
    """Complete status, a full round-by-firm grid of rows, and lineup models on every row."""
    meta, sid = log.meta, log.meta.session_id
    report.items["structure"] += 1
    if meta.status != "complete" and not include_incomplete:
        report.fail("structure", sid, f"status is {meta.status}")
    firms = [entry.firm_id for entry in meta.lineup]
    if len(log.rows) != meta.n_rounds * meta.n_bidders:
        report.fail("structure", sid, f"{len(log.rows)} rows, expected {meta.n_rounds * meta.n_bidders}")
    models = {entry.firm_id: entry.model for entry in meta.lineup}
    for number, group in _by_round(log.rows):
        if [r.firm_id for r in group] != firms:
            report.fail("structure", sid, f"round {number}: firms {[r.firm_id for r in group]}, expected {firms}")
        for row in group:
            if row.session_id != sid or row.model != models.get(row.firm_id):
                report.fail("structure", sid, f"round {number} firm {row.firm_id}: session id or model differs from session.json")
    if sorted({r.round for r in log.rows}) != list(range(1, meta.n_rounds + 1)):
        report.fail("structure", sid, "rounds are not 1..n_rounds")
    if meta.provider_retries < 0 or len(meta.provider_errors) > ERROR_LOG_LIMIT:
        report.fail("structure", sid, f"provider_retries {meta.provider_retries} or {len(meta.provider_errors)} logged errors is out of range")


def check_costs(log: SessionLog, report: CheckReport) -> None:
    """Every logged cost equals the cost matrix regenerated from (seed, n_bidders) alone."""
    meta, sid = log.meta, log.meta.session_id
    matrix = draw_costs(meta.seed, meta.n_bidders, meta.n_rounds, meta.cost_low, meta.cost_high, meta.bid_increment, meta.cost_spread)
    slots = {entry.firm_id: slot for slot, entry in enumerate(meta.lineup)}
    for row in log.rows:
        report.items["costs"] += 1
        if row.round > meta.n_rounds or row.firm_id not in slots:
            report.fail("costs", sid, f"round {row.round} firm {row.firm_id}: not in the session grid")
        elif abs(row.cost - float(matrix[row.round - 1][slots[row.firm_id]])) > 1e-9:
            report.fail("costs", sid, f"round {row.round} firm {row.firm_id}: cost {row.cost} differs from the seeded draw")


def check_auction(log: SessionLog, report: CheckReport) -> None:
    """Winner, price, tie fields, profit and benchmark bid of every round obey the session's tie-break rule."""
    meta, sid, inc = log.meta, log.meta.session_id, log.meta.bid_increment
    rule = meta.tie_break_rule
    bne = make_benchmark(meta.n_bidders, meta.cost_low, meta.cost_high, meta.cost_spread)
    wins: dict[str, int] = defaultdict(int)
    for number, group in _by_round(log.rows):
        report.items["auction"] += 1

        def fail(detail: str, number: int = number) -> None:
            report.fail("auction", sid, f"round {number}: {detail}")

        min_cost = min(to_ticks(r.cost, inc) for r in group)
        for r in group:
            if r.valid != (r.bid is not None):
                fail(f"firm {r.firm_id}: valid={r.valid} but bid={r.bid}")
            if r.bid is not None and not 0 <= r.bid <= meta.reserve_price:
                fail(f"firm {r.firm_id}: bid {r.bid} outside [0, {meta.reserve_price}]")
            if abs(r.bne_bid - bne.bid(r.cost)) > 1e-9:
                fail(f"firm {r.firm_id}: bne_bid {r.bne_bid} is not the closed form")
            if r.is_min_cost != (to_ticks(r.cost, inc) == min_cost):
                fail(f"firm {r.firm_id}: is_min_cost is wrong")
            if rule != "bafo" and r.rebid is not None:
                fail(f"firm {r.firm_id}: rebid under {rule}")
        valid = [r for r in group if r.valid]
        winners = [r for r in group if r.is_winner]
        if not valid:
            if winners or any(r.winning_bid is not None or r.n_tied or r.tied or r.tie_broken for r in group):
                fail("no valid bid but a winner, price or tie is logged")
            continue
        low = min(to_ticks(r.bid, inc) for r in valid)
        tied = [r for r in valid if to_ticks(r.bid, inc) == low]
        if len(winners) != 1:
            fail(f"{len(winners)} winners")
            continue
        winner, price = winners[0], low
        if winner not in tied:
            fail(f"winner {winner.firm_id} did not bid the lowest price")
        if len(tied) == 1:
            expected = "none"
        elif rule == "random":
            expected = "random"
        elif rule == "least_wins":
            expected = "least_wins"
            if wins[winner.firm_id] != min(wins[r.firm_id] for r in tied):
                fail(f"least_wins: winner {winner.firm_id} did not have the fewest wins among the tied")
        else:
            live = [r for r in tied if r.rebid is not None]
            if any(r.rebid is not None for r in group if r not in tied):
                fail("a firm outside the tie rebid")
            expected = "bafo_random"
            if live:
                price = min(to_ticks(r.rebid, inc) for r in live)
                candidates = [r for r in live if to_ticks(r.rebid, inc) == price]
                expected = "bafo" if len(candidates) == 1 else "bafo_random"
                if winner not in candidates:
                    fail(f"bafo: winner {winner.firm_id} did not have the lowest rebid")
        for r in group:
            if r.n_tied != len(tied) or r.tie_broken != (len(tied) > 1) or r.tied != (len(tied) > 1 and r in tied):
                fail(f"firm {r.firm_id}: n_tied, tied or tie_broken disagree with the bids")
            if r.tie_resolution != expected:
                fail(f"firm {r.firm_id}: tie_resolution {r.tie_resolution}, expected {expected}")
            if r.winning_bid is None or to_ticks(r.winning_bid, inc) != price:
                fail(f"firm {r.firm_id}: winning_bid {r.winning_bid}, expected {from_ticks(price, inc)}")
            want = price - to_ticks(r.cost, inc) if r is winner else 0
            if to_ticks(r.profit, inc) != want:
                fail(f"firm {r.firm_id}: profit {r.profit}, expected {from_ticks(want, inc)}")
        wins[winner.firm_id] += 1


def _messages(call: CallRow) -> list[dict[str, str]]:
    return json.loads(call.prompt)


def _first_difference(actual: str, expected: str) -> str:
    for index, (a, b) in enumerate(zip(actual.splitlines(), expected.splitlines(), strict=False)):
        if a != b:
            return f"line {index + 1}: logged {a[:90]!r}, expected {b[:90]!r}"
    return f"lengths differ ({len(actual.splitlines())} vs {len(expected.splitlines())} lines)"


def check_calls(log: SessionLog, report: CheckReport, template: Path = DEFAULT_TEMPLATE) -> None:
    """Calls against bids, hosts and tokens, and every logged prompt against the session and its history."""
    meta, sid, inc = log.meta, log.meta.session_id, log.meta.bid_increment
    rows = {(r.round, r.firm_id): r for r in log.rows}
    slots = {entry.firm_id: slot for slot, entry in enumerate(meta.lineup)}
    models = {entry.firm_id: entry.model for entry in meta.lineup}
    by_key: dict[tuple[int, str, str], list[CallRow]] = defaultdict(list)
    for call in log.calls:
        by_key[(call.round, call.firm_id, call.phase)].append(call)
    report.calls += len(log.calls)

    def final(calls: list[CallRow]) -> float | None:
        last = calls[-1]
        return last.parsed_bid if last.error is None and last.parsed_bid is not None else None

    for row in log.rows:
        if models[row.firm_id] is None:
            continue
        report.items["bids_vs_calls"] += 1
        label = f"round {row.round} firm {row.firm_id}"
        attempts = by_key.get((row.round, row.firm_id, "bid"), [])
        if [c.attempt for c in attempts] != list(range(1, len(attempts) + 1)) or not attempts:
            report.fail("bids_vs_calls", sid, f"{label}: bid attempts {[c.attempt for c in attempts]}")
            continue
        parsed = final(attempts)
        if row.n_attempts != len(attempts):
            report.fail("bids_vs_calls", sid, f"{label}: n_attempts {row.n_attempts}, {len(attempts)} calls logged")
        if row.valid != (parsed is not None) or (parsed is not None and to_ticks(parsed, inc) != to_ticks(-1 if row.bid is None else row.bid, inc)):
            report.fail("bids_vs_calls", sid, f"{label}: bid {row.bid} (valid={row.valid}) does not match the logged calls")
        if any(c.error is None and c.parsed_bid is not None for c in attempts[:-1]):
            report.fail("bids_vs_calls", sid, f"{label}: retried after a valid bid")
        rebids = by_key.get((row.round, row.firm_id, "rebid"), [])
        report.items["rebid_calls"] += 1
        if rebids and not (meta.tie_break_rule == "bafo" and row.tied):
            report.fail("rebid_calls", sid, f"{label}: rebid call by a firm that was not in a bafo tie")
        if meta.tie_break_rule == "bafo" and row.tied and not rebids:
            report.fail("rebid_calls", sid, f"{label}: tied firm was never asked to rebid")
        if rebids:
            parsed_rebid = final(rebids)
            if (row.rebid is None) != (parsed_rebid is None) or (
                parsed_rebid is not None and to_ticks(parsed_rebid, inc) != to_ticks(row.rebid, inc)
            ):
                report.fail("rebid_calls", sid, f"{label}: rebid {row.rebid} does not match the logged calls")

    for call in log.calls:
        label = f"round {call.round} firm {call.firm_id} {call.phase} attempt {call.attempt}"
        row = rows.get((call.round, call.firm_id))
        if row is None:
            report.fail("structure", sid, f"{label}: call has no matching bid row")
            continue
        report.items["provider"] += 1
        report.cutoffs += call.finish_reason == "length"
        report.with_thinking += bool(call.thinking)
        report.with_free_text += bool(call.content)
        report.providers[(call.model, call.provider or "none")] += 1
        pinned = meta.providers.get(call.model)
        if call.model != models[call.firm_id]:
            report.fail("provider", sid, f"{label}: model {call.model}, lineup says {models[call.firm_id]}")
        if call.provider is None:
            report.fail("provider", sid, f"{label}: no serving provider recorded")
        elif pinned and call.provider.lower() != pinned["name"].lower():
            report.fail("provider", sid, f"{label}: served by {call.provider}, pinned {pinned['name']}")

        messages = _messages(call)
        report.items["retry_messages"] += 1
        want = 2 if call.attempt == 1 else 3
        if len(messages) != want or (want == 3 and not messages[2]["content"].startswith("Your reply was not accepted")):
            report.fail("retry_messages", sid, f"{label}: {len(messages)} messages, expected {want} with a correction")
        system, user = messages[0]["content"], messages[1]["content"]

        cap_match = CAP_PATTERN.search(system)
        cap = int(cap_match.group(1)) if cap_match else None
        report.items["tokens"] += 1
        if cap is None:
            report.fail("tokens", sid, f"{label}: system prompt does not state the output cap")
        else:
            report.caps[cap] += 1
            if call.completion_tokens is not None and call.completion_tokens > cap:
                report.fail("tokens", sid, f"{label}: {call.completion_tokens} completion tokens over the stated cap {cap}")

        report.items["system_prompt"] += 1
        if cap is not None and not any(
            system_prompt(meta, call.firm_id, length, cap, template) == system for length in REASONING_LENGTHS
        ):
            expected = system_prompt(meta, call.firm_id, "short", cap, template)
            report.fail("system_prompt", sid, f"{label}: differs from the template build; {_first_difference(system, expected)}")

        report.items["tie_rule_prompt"] += 1
        own = TIE_RULE_SENTENCES[meta.tie_break_rule]
        others = [r for r, text in TIE_RULE_SENTENCES.items() if r != meta.tie_break_rule and text in system]
        if own not in system or others or ANNOUNCEMENTS[meta.info_condition] not in system:
            report.fail("tie_rule_prompt", sid, f"{label}: states rules {others or 'none'} or lacks its own rule or announcement")

        report.items["user_prompt"] += 1
        low = min((to_ticks(r.bid, inc) for (n, _), r in rows.items() if n == call.round and r.bid is not None), default=None)
        request = BidRequest(
            firm_id=call.firm_id,
            slot=slots[call.firm_id],
            round=call.round,
            cost=row.cost,
            phase=call.phase,
            tied_price=from_ticks(low, inc) if call.phase == "rebid" and low is not None else None,
            n_tied=row.n_tied if call.phase == "rebid" else None,
        )
        expected_user = user_prompt(meta, log.rows, request)
        if user != expected_user:
            report.fail("user_prompt", sid, f"{label}: differs from the rebuild; {_first_difference(user, expected_user)}")

        report.items["rounds_shown"] += 1
        shown = {int(n) for n in ROUND_LINE.findall(user)}
        window = meta.history_window
        first = 1 if window is None else call.round - window
        expected_rounds = set() if window == 0 else set(range(max(1, first), call.round))
        if shown != expected_rounds:
            report.fail("rounds_shown", sid, f"{label}: shows rounds {sorted(shown)}, expected {sorted(expected_rounds)}")
        if ("No earlier rounds are shown." in user) != (not expected_rounds):
            report.fail("rounds_shown", sid, f"{label}: the 'no earlier rounds' line disagrees with the {len(expected_rounds)} rounds expected")

        report.items["cost_line"] += 1
        costs = COST_LINE.findall(user)
        if costs != [f"{row.cost:.2f}"]:
            report.fail("cost_line", sid, f"{label}: cost lines {costs}, this firm's cost is {row.cost:.2f}")

        report.items["leak"] += 1
        public = {f"{v:.2f}" for r in log.rows for v in (r.bid, r.rebid, r.winning_bid) if v is not None}
        mine = {f"{v:.2f}" for r in log.rows if r.firm_id == call.firm_id for v in (r.cost, r.profit)}
        private = {f"{v:.2f}" for r in log.rows if r.firm_id != call.firm_id for v in (r.cost, r.profit)}
        leaked = (set(NUMBER.findall(user)) & private) - public - mine
        if leaked:
            report.fail("leak", sid, f"{label}: shows another firm's private figures {sorted(leaked)}")

        report.items["rebid_notice"] += 1
        notices = REBID_NOTICE.findall(user)
        if call.phase == "bid" and notices:
            report.fail("rebid_notice", sid, f"{label}: a bid-phase prompt carries the rebid notice")
        elif call.phase == "rebid" and (len(notices) != 1 or (int(notices[0][0]), notices[0][1]) != (row.n_tied, f"{from_ticks(low, inc):.2f}")):
            report.fail("rebid_notice", sid, f"{label}: rebid notice {notices}, expected {row.n_tied} firms at {low and from_ticks(low, inc):.2f}")


def check_run(logs: list[SessionLog], template: Path = DEFAULT_TEMPLATE, include_incomplete: bool = False) -> CheckReport:
    """Run every check over every session; scripted sessions (no calls) only get the structure, cost and auction checks."""
    report = CheckReport(sessions=len(logs))
    for log in logs:
        check_structure(log, report, include_incomplete)
        check_costs(log, report)
        check_auction(log, report)
        if log.calls or any(entry.model for entry in log.meta.lineup):
            check_calls(log, report, template)
    return report
