"""CLI: compute per-session metrics and pilot checks from a run's logs.
Usage: analyze.py LOG_DIR [--results-dir DIR] [--include-incomplete]

Writes session_metrics.csv, condition_summary.csv (means only; intervals wait for build
step 3b) and call_summary.csv to results/<run_id>/. confirmatory_tests.csv is not written
until the tests exist (step 3b).
"""

import argparse
from pathlib import Path

import pandas as pd

from bidrig.analysis.metrics import call_summary, condition_means, session_metrics_table
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

    wide = summary.pivot(index="condition_id", columns="metric", values="mean")
    with pd.option_context("display.width", 200, "display.max_columns", 20, "display.precision", 3):
        print(f"{len(table)} sessions; means over sessions per condition (raw numbers, no intervals)\n")
        print(wide[[c for c in HEADLINE if c in wide.columns]].to_string())
        print()
        print(calls.set_index("condition_id").to_string())
    print(f"\nwrote {out}/session_metrics.csv, condition_summary.csv, call_summary.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
