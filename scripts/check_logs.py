"""CLI: check a run's raw logs against the auction rules and the prompt design (PLANNING.md 5.5).
Usage: check_logs.py RUN_DIR [--expect-cap N] [--max-failures N] [--include-incomplete]
       check_logs.py RUN_DIR --pick
       check_logs.py RUN_DIR --show SESSION_ID ROUND FIRM [--phase bid|rebid]

Exits 1 if any check fails. --pick lists representative prompts to read by hand; --show prints one.
"""

import argparse
import json
import sys
from pathlib import Path

from bidrig.checks import CHECKS, SessionLog, check_run, load_logs

RULES = ["random", "least_wins", "bafo"]


def pick(logs: list[SessionLog], run_dir: Path) -> list[str]:
    """Commands that print one repeated and one control prompt per tie rule, plus a rebid prompt if any exists."""
    lines = []
    for rule in RULES:
        for window, round_number, kind in [(None, None, "repeated, last round"), (0, 2, "one-shot control, round 2")]:
            sessions = sorted(
                (log for log in logs if log.meta.tie_break_rule == rule and log.meta.history_window == window and log.calls),
                key=lambda log: (log.meta.lineup[0].model or "", log.meta.session_id),
            )
            if sessions:
                meta = sessions[0].meta
                lines.append(
                    f"{rule:10s} {kind:26s} {meta.lineup[0].model}: "
                    f"check_logs.py {run_dir} --show {meta.session_id} {round_number or meta.n_rounds} A"
                )
    for log in logs:
        rebid = next((c for c in log.calls if c.phase == "rebid"), None)
        if rebid:
            lines.append(f"{'bafo':10s} {'rebid call':26s} {rebid.model}: check_logs.py {run_dir} --show {log.meta.session_id} {rebid.round} {rebid.firm_id} --phase rebid")
            break
    return lines


def show(logs: list[SessionLog], session_id: str, round_number: int, firm_id: str, phase: str) -> int:
    """Print the first attempt of one call: the conversation sent and what the model answered."""
    matches = [log for log in logs if session_id in log.meta.session_id]
    if len(matches) != 1:
        print(f"{len(matches)} sessions match {session_id!r}", file=sys.stderr)
        return 2
    log = matches[0]
    calls = [c for c in log.calls if (c.round, c.firm_id, c.phase) == (round_number, firm_id, phase)]
    if not calls:
        print(f"no {phase} call by firm {firm_id} in round {round_number}", file=sys.stderr)
        return 2
    meta = log.meta
    print(f"session {meta.session_id}\nrule {meta.tie_break_rule}  info {meta.info_condition}  history_window {meta.history_window}  seed {meta.seed}")
    for message in json.loads(calls[0].prompt):
        print(f"\n--- {message['role']} ---\n{message['content']}")
    for call in calls:
        print(f"\n--- answer, attempt {call.attempt} (provider {call.provider}, {call.completion_tokens} completion tokens) ---")
        print(f"bid {call.parsed_bid}  error {call.error}\nreasoning: {call.reasoning}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check a run's logs against the auction rules and the prompt design.")
    parser.add_argument("run_dir", type=Path, help="logs/<run_id>")
    parser.add_argument("--expect-cap", type=int, help="fail unless every system prompt states this output-token cap")
    parser.add_argument("--max-failures", type=int, default=3, help="examples printed per failing check")
    parser.add_argument("--include-incomplete", action="store_true", help="also check running or failed sessions")
    parser.add_argument("--pick", action="store_true", help="list representative prompts to read by hand")
    parser.add_argument("--show", nargs=3, metavar=("SESSION_ID", "ROUND", "FIRM"), help="print one call")
    parser.add_argument("--phase", choices=["bid", "rebid"], default="bid")
    args = parser.parse_args(argv)

    logs, skipped = load_logs(args.run_dir, args.include_incomplete)
    if args.show:
        return show(logs, args.show[0], int(args.show[1]), args.show[2], args.phase)
    if args.pick:
        print("\n".join(pick(logs, args.run_dir)) or "no model calls in this run")
        return 0
    if not logs:
        print(f"no complete sessions under {args.run_dir}", file=sys.stderr)
        return 2

    report = check_run(logs, include_incomplete=args.include_incomplete)
    if args.expect_cap is not None and set(report.caps) - {args.expect_cap}:
        report.fail("tokens", "-", f"system prompts state caps {dict(report.caps)}, expected {args.expect_cap}")

    print(f"checked {report.sessions} sessions ({report.calls} call rows) in {args.run_dir}")
    if skipped:
        print(f"skipped {len(skipped)} incomplete: {', '.join(skipped[:5])}")
    print(f"  {'check':16s} {'items':>6s} {'failures':>9s}")
    for name in CHECKS:
        if report.items[name]:
            print(f"  {name:16s} {report.items[name]:6d} {len(report.failures(name)):9d}")
    if report.caps:
        print(f"output caps stated in the prompts: {dict(report.caps)}")
    if report.providers:
        print("serving hosts: " + ", ".join(f"{model}/{host} {n}" for (model, host), n in sorted(report.providers.items())))
    for name in CHECKS:
        failures = report.failures(name)
        for finding in failures[: args.max_failures]:
            print(f"FAIL {name} {finding.session_id}: {finding.detail}")
        if len(failures) > args.max_failures:
            print(f"     ... and {len(failures) - args.max_failures} more {name} failures")
    print("RESULT: PASS" if report.passed else f"RESULT: FAIL ({len(report.findings)} findings)")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
