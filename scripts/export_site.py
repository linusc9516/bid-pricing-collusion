"""Export every run under logs/ to site/data/ for the static viewer: a run index plus one file per session."""

import argparse
import json
import shutil
from pathlib import Path

from bidrig.analysis.metrics import session_metrics_table
from bidrig.schema import SESSION_FILE, read_calls, read_meta, read_session
from bidrig.viewer import (
    DIFF_BINS,
    DIFF_LOW,
    DIFF_STEP,
    MAX_THINKING_CHARS,
    index_entry,
    session_bundle,
)

ROOT = Path(__file__).resolve().parents[1]


def dump(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="*", help="run ids under --logs-root (default: every run)")
    parser.add_argument("--logs-root", type=Path, default=ROOT / "logs")
    parser.add_argument("--out", type=Path, default=ROOT / "site" / "data")
    parser.add_argument("--max-thinking", type=int, default=MAX_THINKING_CHARS, help="characters of hidden thinking kept per call")
    parser.add_argument("--no-thinking", action="store_true", help="drop hidden thinking text (about a third smaller)")
    parser.add_argument("--no-prompts", action="store_true", help="drop the per-call user prompts and system prompts")
    args = parser.parse_args()

    run_ids = args.runs or sorted(p.name for p in args.logs_root.iterdir() if p.is_dir())
    runs = []
    for run_id in run_ids:
        paths = sorted((args.logs_root / run_id).glob(f"*/*/{SESSION_FILE}"))
        complete = [p.parent for p in paths if read_meta(p.parent).status == "complete"]
        loaded = [(read_session(path), path) for path in complete]
        if not loaded:
            print(f"{run_id}: no complete sessions, skipped")
            continue
        table = session_metrics_table(ms for ms, _ in loaded).set_index("session_id")
        sessions_dir = args.out / "sessions" / run_id
        if sessions_dir.exists():
            shutil.rmtree(sessions_dir)
        sessions_dir.mkdir(parents=True)
        entries = []
        for (meta, rows), path in loaded:
            metrics = table.loc[meta.session_id].to_dict()
            entries.append(index_entry(meta, rows, metrics))
            bundle = session_bundle(meta, rows, read_calls(path), metrics, 0 if args.no_thinking else args.max_thinking)
            if args.no_prompts:
                bundle["system"] = {}
                for r in bundle["rounds"]:
                    for f in r["firms"]:
                        for c in f["calls"]:
                            c["user"] = ""
            (sessions_dir / f"{meta.session_id}.js").write_text(
                f"(window.SESSIONS=window.SESSIONS||{{}})[{dump(meta.session_id)}]={dump(bundle)};\n"
            )
        runs.append({"id": run_id, "diff_bins": {"low": DIFF_LOW, "step": DIFF_STEP, "n": DIFF_BINS}, "sessions": entries})
        size = sum(f.stat().st_size for f in sessions_dir.iterdir()) / 1e6
        print(f"{run_id}: {len(entries)} sessions, {size:.1f} MB")

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "runs.js").write_text(f"window.RUNS = {dump(runs)};\n")
    print(f"wrote {args.out / 'runs.js'} ({len(runs)} runs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
