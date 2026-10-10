"""Export runs under logs/ to site/data/ for the static viewer: a run index plus one file per session.

Usage: export_site.py [RUN ...] [--no-thinking] [--no-prompts]        local export, gitignored (data/runs.js, data/sessions/)
       export_site.py --publish RUN [RUN ...] [--findings FILE]        committed bundle (data/published.js, data/published/)

The published bundle is what a fresh clone shows: the named runs without hidden thinking or per-call prompts, the
findings file as a page, and the small tables its charts need. A local export of the same run takes precedence in
the viewer.
"""

import argparse
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from bidrig.analysis.metrics import session_metrics_table
from bidrig.analysis.profit import profit_checks_table, round_block_gaps
from bidrig.analysis.trace_judge import LABELS
from bidrig.schema import SESSION_FILE, read_calls, read_meta, read_session
from bidrig.viewer import (
    DIFF_BINS,
    DIFF_LOW,
    DIFF_STEP,
    MAX_THINKING_CHARS,
    findings_html,
    index_entry,
    session_bundle,
)

ROOT = Path(__file__).resolve().parents[1]


def dump(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def export_run(run_id: str, logs_root: Path, sessions_dir: Path, max_thinking: int, no_prompts: bool) -> tuple[dict, list] | None:
    """Write one file per complete session of `run_id` into `sessions_dir` (emptied first); returns the run's index entry and its sessions, None if it has none.

    `max_thinking` 0 drops hidden thinking text; `no_prompts` drops the per-call user prompts and the system prompts.
    """
    paths = sorted((logs_root / run_id).glob(f"*/*/{SESSION_FILE}"))
    loaded = [(read_session(p.parent), p.parent) for p in paths if read_meta(p.parent).status == "complete"]
    if not loaded:
        return None
    pairs = [session for session, _ in loaded]
    table = session_metrics_table(pairs).set_index("session_id")
    table = table.join(profit_checks_table(pairs).set_index("session_id")[["joint_profit_ratio", "switch_gain", "best_reply_share"]])
    if sessions_dir.exists():
        shutil.rmtree(sessions_dir)
    sessions_dir.mkdir(parents=True)
    entries = []
    for (meta, rows), path in loaded:
        metrics = table.loc[meta.session_id].to_dict()
        entries.append(index_entry(meta, rows, metrics))
        bundle = session_bundle(meta, rows, read_calls(path), metrics, max_thinking)
        if no_prompts:
            bundle["system"] = {}
            for r in bundle["rounds"]:
                for f in r["firms"]:
                    for c in f["calls"]:
                        c["user"] = ""
        (sessions_dir / f"{meta.session_id}.js").write_text(
            f"(window.SESSIONS=window.SESSIONS||{{}})[{dump(meta.session_id)}]={dump(bundle)};\n"
        )
    return {"id": run_id, "diff_bins": {"low": DIFF_LOW, "step": DIFF_STEP, "n": DIFF_BINS}, "sessions": entries}, pairs


def judge_table(results_dir: Path) -> list[dict]:
    """Share of judged calls with each label per model and arm, from a run's trace_judge.csv; empty if the run was not judged."""
    path = results_dir / "trace_judge.csv"
    if not path.exists():
        return []
    judged = pd.read_csv(path)
    labels = [name for name in LABELS if name in judged.columns]
    grouped = judged.groupby(["lineup_id", "is_control"])
    out = grouped[labels].mean().join(grouped.size().rename("n_calls")).reset_index()
    return json.loads(out.to_json(orient="records"))


def publish(run_ids: list[str], logs_root: Path, out: Path, findings: Path | None, results_root: Path) -> int:
    """Write the committed bundle: data/published/<run_id>/<session>.js and data/published.js."""
    runs, tables = [], {}
    for run_id in run_ids:
        exported = export_run(run_id, logs_root, out / "published" / run_id, max_thinking=0, no_prompts=True)
        if exported is None:
            print(f"{run_id}: no complete sessions under {logs_root}")
            return 1
        run, pairs = exported
        runs.append(run)
        tables[run_id] = {
            "round_blocks": json.loads(round_block_gaps(pairs).to_json(orient="records")),
            "judge": judge_table(results_root / run_id),
        }
        size = sum(f.stat().st_size for f in (out / "published" / run_id).iterdir()) / 1e6
        print(f"{run_id}: {len(run['sessions'])} sessions, {size:.1f} MB")
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()
    bundle = {
        "runs": runs, "tables": tables, "generated": datetime.now(UTC).date().isoformat(), "commit": sha,
        "findings_html": findings_html(findings.read_text()) if findings and findings.exists() else "",
        "findings_source": findings.name if findings and findings.exists() else "",
    }  # fmt: skip
    (out / "published.js").write_text(f"window.PUBLISHED = {dump(bundle)};\n")
    print(f"wrote {out / 'published.js'} ({(out / 'published.js').stat().st_size / 1e6:.1f} MB; findings: {bundle['findings_source'] or 'none'})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs", nargs="*", help="run ids under --logs-root (default: every run)")
    parser.add_argument("--logs-root", type=Path, default=ROOT / "logs")
    parser.add_argument("--out", type=Path, default=ROOT / "site" / "data")
    parser.add_argument("--max-thinking", type=int, default=MAX_THINKING_CHARS, help="characters of hidden thinking kept per call")
    parser.add_argument("--no-thinking", action="store_true", help="drop hidden thinking text (about a third smaller)")
    parser.add_argument("--no-prompts", action="store_true", help="drop the per-call user prompts and system prompts")
    parser.add_argument("--publish", action="store_true", help="write the committed bundle for the named runs instead of the local export")
    parser.add_argument("--findings", type=Path, default=ROOT / "BASELINE_FINDINGS.md", help="Markdown file shown as the findings page (with --publish)")
    parser.add_argument("--results-root", type=Path, default=ROOT / "results", help="where a run's trace_judge.csv is read from (with --publish)")
    args = parser.parse_args()

    if args.publish:
        if not args.runs:
            parser.error("--publish needs at least one run id")
        return publish(args.runs, args.logs_root, args.out, args.findings, args.results_root)

    run_ids = args.runs or sorted(p.name for p in args.logs_root.iterdir() if p.is_dir())
    runs = []
    for run_id in run_ids:
        exported = export_run(run_id, args.logs_root, args.out / "sessions" / run_id, 0 if args.no_thinking else args.max_thinking, args.no_prompts)
        if exported is None:
            print(f"{run_id}: no complete sessions, skipped")
            continue
        runs.append(exported[0])
        size = sum(f.stat().st_size for f in (args.out / "sessions" / run_id).iterdir()) / 1e6
        print(f"{run_id}: {len(exported[0]['sessions'])} sessions, {size:.1f} MB")

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "runs.js").write_text(f"window.RUNS = {dump(runs)};\n")
    print(f"wrote {args.out / 'runs.js'} ({len(runs)} runs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
