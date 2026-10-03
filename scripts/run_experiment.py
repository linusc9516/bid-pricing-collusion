"""CLI: run the sessions described by a config file.
Usage: run_experiment.py CONFIG [--run-id NAME] [--dry-run] [--host primary|fallback|backup] [--yes]

Configs that call models ask for confirmation before the first call unless --yes is given.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from bidrig.llm import make_openai_client
from bidrig.runner import (
    check_llm_settings,
    estimate,
    is_complete,
    prepare,
    run_plan,
    tbd_settings,
)

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the sessions described by a config file.")
    parser.add_argument("config", type=Path)
    parser.add_argument("--run-id", help="run directory under logs/; defaults to the config's file stem")
    parser.add_argument("--dry-run", action="store_true", help="print sessions, calls and cost; call nothing")
    parser.add_argument("--host", choices=["primary", "fallback", "backup"], default="primary",
                        help="pinned host for models that have one; rerun failed sessions with fallback, then backup")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation before calling models")
    parser.add_argument("--log-dir", type=Path, help="defaults to output.log_dir in the config")
    args = parser.parse_args()

    config, models, plan = prepare(args.config, args.run_id, args.host)
    run_id = plan[0].meta.run_id if plan else args.run_id
    log_dir = args.log_dir or ROOT / config.get("output", {}).get("log_dir", "logs")
    est = estimate(plan, config, models, args.host)
    cap = config.get("budget", {}).get("max_cost_usd", 0.0)
    pending = [p for p in plan if not is_complete(log_dir, p.meta)]
    pending_calls = sum(p.n_llm_calls for p in pending)

    print(f"config {args.config}  run {run_id}  host {args.host}  git {plan[0].meta.git_sha if plan else '-'}")
    print(f"{est.n_conditions} conditions, {est.n_sessions} sessions ({len(pending)} not yet complete)")
    print(f"{est.n_llm_calls} model calls before rebids and retries ({pending_calls} pending)")
    if est.n_llm_calls:
        per_model = ", ".join(f"{m} ${c:.2f}" for m, c in sorted(est.cost_by_model.items()))
        print(f"estimated ${est.cost_usd:.2f} at {est.output_tokens_per_call} output tokens per call ({per_model})")
        print(f"spending cap ${cap:.2f}" + ("  WARNING: estimate exceeds the cap" if est.cost_usd > cap else ""))
    if tbd_settings(config):
        print(f"NOTE: llm settings still TBD: {', '.join(tbd_settings(config))}; this config cannot call models yet")
    if args.dry_run or not pending:
        return 0

    client_factory = None
    if pending_calls:
        try:
            check_llm_settings(config)
        except ValueError as exc:
            print(f"refusing to call models: {exc}", file=sys.stderr)
            return 1
        if not args.yes:
            if not sys.stdin.isatty():
                print("refusing to call models without --yes when not interactive", file=sys.stderr)
                return 1
            if input(f"Call models for {len(pending)} sessions, cap ${cap:.2f}? Type yes: ").strip() != "yes":
                print("aborted; nothing was called")
                return 1
        load_dotenv(ROOT / ".env")
        key = os.environ.get("OPENROUTER_API_KEY")
        if not key:
            print("OPENROUTER_API_KEY is not set (see .env.example)", file=sys.stderr)
            return 1
        base_url = os.environ.get("OPENROUTER_BASE_URL") or None
        client_factory = lambda: make_openai_client(key, base_url)

    result = asyncio.run(run_plan(pending, config, models, log_dir, client_factory, args.host))
    print(f"completed {len(result.completed)}, already complete {len(plan) - len(pending)}, failed {len(result.failed)}")
    for session_id, error in result.failed.items():
        print(f"  failed {session_id}: {error}")
    if pending_calls:
        print(f"spent about ${result.spent_usd:.4f} at pinned-host prices")
    if result.budget_exceeded:
        print("STOPPED: spending cap reached", file=sys.stderr)
        return 3
    return 0 if not result.failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
