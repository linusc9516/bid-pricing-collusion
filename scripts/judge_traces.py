"""CLI: judge the bidders' reasoning traces for coordination reasoning (rubric and method in analysis/trace_judge.py).

Usage: judge_traces.py LOG_DIR [--judge gemini] [--only ID_PART ...] [--sample 12 | --all] [--cap-usd 1.0] [--yes]
       judge_traces.py LOG_DIR --phase reflect ...     the reflection steps of a shared-workspace run, with the notes rubric

Without --yes it reads the logs, prints the free regex baseline and the planned judge calls with a cost
estimate, and sends nothing. With --yes it judges, caches every reply in results/<run_id>/trace_judge_cache.jsonl
(a rerun skips cached calls) and writes trace_judge.csv (one row per call), trace_judge_sessions.csv (one row per
session) and trace_judge_check.csv (random calls with their quotes, for a hand check). With --phase reflect the files are
named notes_judge*.csv and notes_judge_cache.jsonl, and a row is one firm's reflection step after a round.
"""

import argparse
import asyncio
import dataclasses
import json
import os
import random
import sys
from collections.abc import Sequence
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from bidrig.analysis.trace_judge import (
    BASELINE_PATTERNS,
    BID_RUBRIC,
    NOTES_RUBRIC,
    Rubric,
    Trace,
    baseline_flags,
    cache_key,
    estimate_cost,
    judge_messages,
    parse_judgement,
    reflection_traces,
    sample_traces,
    traces_from_calls,
)
from bidrig.llm import (
    BudgetExceeded,
    LLMSettings,
    OpenRouterClient,
    ProviderError,
    ProviderStats,
    SpendTracker,
    load_models,
    make_openai_client,
)
from bidrig.schema import SESSION_FILE, SessionMeta, read_calls

ROOT = Path(__file__).resolve().parents[1]
JUDGE_MAX_TOKENS = 1300  # nine labels, each with a quote


META_FIELDS = {f.name for f in dataclasses.fields(SessionMeta)}


def read_meta_known(path: Path) -> SessionMeta:
    """session.json with the fields this checkout's schema has; a newer harness's extra fields (workspace, channel) are not needed to judge and are dropped."""
    data = json.loads((path / SESSION_FILE).read_text())
    return SessionMeta.from_dict({k: v for k, v in data.items() if k in META_FIELDS})


def load_traces(log_dir: Path, only: Sequence[str] = (), phase: str = "bid") -> tuple[list[Trace], dict[str, dict]]:
    """Traces of every complete session under `log_dir` (only those whose id contains one of `only`, if given), and each session's condition, control flag and lineup.

    `phase` "bid" gives one trace per bid call, "reflect" one per reflection step.
    """
    traces: list[Trace] = []
    info: dict[str, dict] = {}
    for path in sorted(log_dir.glob(f"*/*/{SESSION_FILE}")):
        meta = read_meta_known(path.parent)
        if meta.status != "complete" or (only and not any(part in meta.session_id for part in only)):
            continue
        info[meta.session_id] = {"condition_id": meta.condition_id, "is_control": meta.is_control, "lineup_id": meta.lineup_id, "seed": meta.seed}
        traces.extend((reflection_traces if phase == "reflect" else traces_from_calls)(read_calls(path.parent)))
    return traces, info


def baseline_table(traces: list[Trace], info: dict[str, dict]) -> pd.DataFrame:
    """Share of traces per (lineup, repeated or control) that match each baseline phrase family or any."""
    rows = []
    for t in traces:
        flags = baseline_flags(t.text)
        rows.append({"lineup": info[t.session_id]["lineup_id"], "arm": "control" if info[t.session_id]["is_control"] else "repeated", **flags, "any": any(flags.values())})
    frame = pd.DataFrame(rows)
    return frame.groupby(["lineup", "arm"]).agg(traces=("any", "size"), **{k: (k, "mean") for k in [*BASELINE_PATTERNS, "any"]}).round(3)


async def judge_all(client: OpenRouterClient, spec, traces: list[Trace], workers: int, cache: dict[str, dict], cache_path: Path, rubric: Rubric = BID_RUBRIC) -> None:
    """Judge every trace missing from `cache`, appending each reply to the cache file as it arrives."""
    gate = asyncio.Semaphore(workers)
    stats = ProviderStats()
    host = spec.host("primary")
    price_in, price_out = (host.price_in, host.price_out) if host else (spec.price_in, spec.price_out)
    lock = asyncio.Lock()

    async def one(trace: Trace) -> None:
        key = cache_key(spec.alias, trace, rubric.version)
        async with gate:
            client.spend.check()
            kwargs = client.request_kwargs(spec, host, judge_messages(trace, rubric), 0, 100.0)
            kwargs.pop("tools"), kwargs.pop("tool_choice")
            kwargs.update(temperature=0.0, max_tokens=JUDGE_MAX_TOKENS)
            response, _ = await client._create(kwargs, spec.alias, stats, f"{trace.session_id} r{trace.round} {trace.firm_id}")
            usage = getattr(response, "usage", None)
            client.spend.add(((getattr(usage, "prompt_tokens", 0) or 0) * price_in + (getattr(usage, "completion_tokens", 0) or 0) * price_out) / 1e6)
            reply = response.choices[0].message.content or ""
        record = {"key": key, "reply": reply}
        async with lock:
            cache[key] = record
            with cache_path.open("a") as handle:
                handle.write(json.dumps(record) + "\n")

    results = await asyncio.gather(*(one(t) for t in traces if cache_key(spec.alias, t, rubric.version) not in cache), return_exceptions=True)
    failures = [r for r in results if isinstance(r, Exception)]
    for failure in failures:
        if isinstance(failure, BudgetExceeded):
            print(f"stopped: {failure}", file=sys.stderr)
            break
    other = [f for f in failures if not isinstance(f, (BudgetExceeded, ProviderError))]
    if other:
        raise other[0]
    if any(isinstance(f, ProviderError) for f in failures):
        print(f"{sum(isinstance(f, ProviderError) for f in failures)} calls failed after retries; rerun to retry them", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log_dir", type=Path)
    parser.add_argument("--judge", default="gemini", help="model alias in configs/models.yaml (use a different family from the bidders)")
    parser.add_argument("--sample", type=int, default=12, help="calls judged per session, evenly spaced (default 12)")
    parser.add_argument("--all", action="store_true", help="judge every call")
    parser.add_argument("--only", nargs="+", default=[], help="judge only sessions whose id contains one of these strings")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--cap-usd", type=float, default=1.0, help="stop when spend reaches this")
    parser.add_argument("--check", type=int, default=30, help="random judged calls written for a hand check")
    parser.add_argument("--results-dir", type=Path, default=ROOT / "results")
    parser.add_argument("--phase", choices=["bid", "reflect"], default="bid", help="bid calls (default), or the reflection steps of a workspace run")
    parser.add_argument("--yes", action="store_true", help="actually call the API")
    args = parser.parse_args()

    log_dir = args.log_dir if args.log_dir.is_absolute() else Path.cwd() / args.log_dir
    run_id = log_dir.name
    out = args.results_dir / run_id
    out.mkdir(parents=True, exist_ok=True)
    rubric, stem = (NOTES_RUBRIC, "notes_judge") if args.phase == "reflect" else (BID_RUBRIC, "trace_judge")
    all_traces, info = load_traces(log_dir, args.only, args.phase)
    if not all_traces:
        print(f"no traces under {log_dir} (complete sessions with a reasoning or thinking text)", file=sys.stderr)
        return 1
    traces = sample_traces(all_traces, None if args.all else args.sample)
    random.Random(0).shuffle(traces)

    specs = load_models(ROOT / "configs" / "models.yaml")
    if args.judge not in specs:
        print(f"judge {args.judge!r} is not in configs/models.yaml: {sorted(specs)}", file=sys.stderr)
        return 1
    spec = specs[args.judge]
    host = spec.host("primary")
    price_in, price_out = (host.price_in, host.price_out) if host else (spec.price_in, spec.price_out)
    bidder_models = sorted({t.model for t in traces})
    print(f"{len(all_traces)} traces in {len(info)} sessions; judging {len(traces)}; bidder models {bidder_models}; judge {spec.alias} ({spec.slug}, {host.routing_slug if host else 'unpinned'})")
    if spec.alias in bidder_models:
        print("WARNING: the judge is one of the bidder models; prefer another family", file=sys.stderr)

    baseline = baseline_table(all_traces, info)
    baseline.to_csv(out / ("notes_baseline.csv" if args.phase == "reflect" else "trace_baseline.csv"))
    print("\nregex baseline: share of traces matching each phrase family (broad; overcounts)\n")
    print(baseline.to_string())

    cache_path = out / f"{stem}_cache.jsonl"
    cache: dict[str, dict] = {}
    if cache_path.exists():
        cache = {r["key"]: r for r in map(json.loads, filter(None, cache_path.read_text().splitlines()))}
    todo = [t for t in traces if cache_key(spec.alias, t, rubric.version) not in cache]
    print(f"\nrubric {rubric.version}: {len(todo)} calls to send ({len(traces) - len(todo)} cached), estimated ${estimate_cost(todo, price_in, price_out, rubric=rubric):.2f} at listed prices, cap ${args.cap_usd:.2f}")
    if not args.yes:
        print("Nothing sent; rerun with --yes to call the API.")
        return 0

    load_dotenv(ROOT / ".env")
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        print("OPENROUTER_API_KEY is not set (see .env.example)", file=sys.stderr)
        return 1
    settings = LLMSettings(temperature=0.0, max_output_tokens=JUDGE_MAX_TOKENS, request_timeout_s=120.0)
    client = OpenRouterClient(make_openai_client(key, os.environ.get("OPENROUTER_BASE_URL") or None, timeout=settings.request_timeout_s), settings, SpendTracker(args.cap_usd))
    asyncio.run(judge_all(client, spec, todo, args.workers, cache, cache_path, rubric))
    print(f"spent about ${client.spend.spent_usd:.3f}")

    rows = []
    for t in traces:
        record = cache.get(cache_key(spec.alias, t, rubric.version))
        if record is None:
            continue
        judged = parse_judgement(record["reply"], t.text, rubric.labels)
        rows.append({"session_id": t.session_id, "round": t.round, "firm_id": t.firm_id, "model": t.model, **info[t.session_id], **judged,
                     "adopting": any(judged[name] for name in rubric.adopting), "trace_chars": len(t.text)})
    frame = pd.DataFrame(rows)
    frame.drop(columns=["claimed"]).to_csv(out / f"{stem}.csv", index=False)
    frame["claimed_n"] = frame["claimed"].map(len)

    per = frame.groupby(["session_id", "condition_id", "lineup_id", "is_control", "seed"]).agg(
        judged=("round", "size"), parse_ok=("parse_ok", "mean"), quote_ok=("quote_ok", "mean"), adopting=("adopting", "mean"),
        **{name: (name, "mean") for name in rubric.labels},
    ).reset_index()
    metrics = args.results_dir / run_id / "session_metrics.csv"
    if metrics.exists():
        m = pd.read_csv(metrics)[["session_id", "collusion_index", "delta_index"]]
        per = per.merge(m, on="session_id", how="left")
    per.round(3).to_csv(out / f"{stem}_sessions.csv", index=False)
    frame.sample(min(args.check, len(frame)), random_state=0)[["session_id", "round", "firm_id", *[f"{n}_quote" for n in rubric.labels], "claimed_n"]].to_csv(out / f"{stem}_check.csv", index=False)

    print(f"\nparsed {frame['parse_ok'].mean():.1%} of replies; claimed labels with a verbatim quote {frame['quote_ok'].mean():.1%}")
    summary = frame.assign(arm=frame["is_control"].map({True: "control", False: "repeated"})).groupby(["lineup_id", "arm"])[[*rubric.labels, "adopting"]].mean().round(3)
    print(f"\nshare of judged calls with each label (adopting = {' or '.join(rubric.adopting)})\n")
    print(summary.to_string())
    print(f"\nwrote {stem}.csv, {stem}_sessions.csv, {stem}_check.csv and the regex baseline to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
