"""CLI: compute per-session metrics and pilot checks from a run's logs.
Usage: analyze.py LOG_DIR [--results-dir DIR] [--include-incomplete]

Writes session_metrics.csv, condition_summary.csv (means only; intervals wait for build
step 3b), non_competitive_bids.csv (bids at the reserve and below cost, kept apart from the
collusion, tie and rotation measures), tie_check.csv (the pre-declared tie manipulation check and its
verdict; thresholds from configs/analysis.yaml) and call_summary.csv to results/<run_id>/.
confirmatory_tests.csv is not written until the tests exist (step 3b).
"""

import argparse
from pathlib import Path

import pandas as pd
import yaml

from bidrig.analysis.metrics import (
    call_summary,
    condition_means,
    manipulation_verdict,
    non_competitive_bids,
    session_metrics_table,
    tie_check,
)
from bidrig.bne import chance_tie_rate
from bidrig.schema import SESSION_FILE, read_calls, read_session

ROOT = Path(__file__).resolve().parents[1]
HEADLINE = [
    "collusion_index", "control_index", "delta_index", "lowest_cost_win_share", "delta_lowest_cost_win_share",
    "tie_rate", "tie_rate_early", "tie_rate_late", "tie_price_index", "mean_rebid_delta", "invalid_bid_rate",
]  # fmt: skip


def main() -> int:
    parser = argparse.ArgumentParser(description="Logs to per-session metrics and pilot checks.")
    parser.add_argument("log_dir", type=Path, help="logs/<run_id>")
    parser.add_argument("--results-dir", type=Path, default=ROOT / "results")
    parser.add_argument("--include-incomplete", action="store_true", help="also read running or failed sessions")
    args = parser.parse_args()

    loaded, skipped = [], []
    for path in sorted(args.log_dir.glob(f"*/*/{SESSION_FILE}")):
        meta, rows = read_session(path.parent)
        if meta.status != "complete" and not args.include_incomplete:
            skipped.append(f"{meta.session_id} ({meta.status})")
            continue
        loaded.append((meta, rows, read_calls(path.parent)))
    if skipped:
        print(f"skipped {len(skipped)} incomplete sessions: " + ", ".join(skipped))
    if not loaded:
        print("no complete sessions found")
        return 1

    out = args.results_dir / args.log_dir.name
    out.mkdir(parents=True, exist_ok=True)
    table = session_metrics_table((meta, rows) for meta, rows, _ in loaded)
    table.to_csv(out / "session_metrics.csv", index=False)
    summary = condition_means(table)
    summary.to_csv(out / "condition_summary.csv", index=False)
    calls = call_summary(loaded)
    calls.to_csv(out / "call_summary.csv", index=False)
    noncompetitive = non_competitive_bids(table)
    noncompetitive.to_csv(out / "non_competitive_bids.csv", index=False)
    spreads = {(m.n_bidders, float(m.bid_increment)): set() for m, _, _ in loaded}
    for m, _, _ in loaded:
        spreads[(m.n_bidders, float(m.bid_increment))].add(m.cost_spread)
    if any(len(v) > 1 for v in spreads.values()):
        raise SystemExit("one run mixes cost_spread values at the same bidder count and increment; the tie benchmark is keyed on those")
    chance = {
        (m.n_bidders, float(m.bid_increment)): chance_tie_rate(
            m.n_bidders, m.cost_low, m.cost_high, m.bid_increment, cost_spread=m.cost_spread
        )
        for m, _, _ in loaded
    }
    ties = tie_check(table, chance)
    ties.to_csv(out / "tie_check.csv", index=False)
    decision = yaml.safe_load((ROOT / "configs" / "analysis.yaml").read_text())["manipulation_check"]["decision"]
    pooled = ties[ties["lineup_id"] == "pooled"]

    wide = summary.pivot(index="condition_id", columns="metric", values="mean")
    with pd.option_context("display.width", 200, "display.max_columns", 20, "display.precision", 3):
        print(f"{len(table)} sessions; means over sessions per condition (raw numbers, no intervals)\n")
        print(wide[[c for c in HEADLINE if c in wide.columns]].to_string())
        print("\nnon-competitive unilateral bids (shares of valid bids; not collusion, tie or rotation measures)\n")
        print(noncompetitive.set_index("condition_id").to_string())
        print("\ntie manipulation check (repeated sessions; rounds treated as independent, so intervals are optimistic)\n")
        columns = ["lineup_id", "tie_break_rule", "n_sessions", "rounds", "sessions_with_a_tie", "tie_rate", "tie_ci_low", "tie_ci_high",
                   "tie_rate_early", "tie_rate_late", "control_tie_rate", "chance_tie_rate", "excess_over_chance"]
        print(ties[columns].to_string(index=False))
        if not pooled.empty:
            row = pooled.iloc[0]
            verdict = manipulation_verdict(
                row["tie_rate"], row["excess_over_chance"], decision["proceed_at"], decision["failed_below"],
                rounds=int(row["rounds"]), min_rounds=decision["min_rounds"],
            )
            print(f"\nMANIPULATION CHECK (pooled random + least_wins, repeated): tie rate {row['tie_rate']:.2%} "
                  f"[{row['tie_ci_low']:.2%}, {row['tie_ci_high']:.2%}] against a chance benchmark of {row['chance_tie_rate']:.2%} "
                  f"over {int(row['rounds'])} rounds -> {verdict.upper()} (proceed at >= {decision['proceed_at']:.1%}, failed below "
                  f"{decision['failed_below']:.1%}, needs {decision['min_rounds']} rounds; configs/analysis.yaml)")
        print()
        print(calls.set_index("condition_id").to_string())
    print(f"\nwrote {out}/session_metrics.csv, condition_summary.csv, non_competitive_bids.csv, tie_check.csv, call_summary.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
