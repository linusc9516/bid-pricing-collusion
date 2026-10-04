"""Export the curated example sessions in site/examples.yaml to site/data/examples.js for the static viewer."""

import argparse
import json
from pathlib import Path

import yaml

from bidrig.analysis.metrics import session_metrics_table
from bidrig.schema import read_calls, read_session
from bidrig.viewer import MAX_THINKING_CHARS, session_bundle

ROOT = Path(__file__).resolve().parents[1]


def find_session(logs_root: Path, run: str, session_id: str) -> Path:
    """Directory of one session under logs/<run>/; raises if it is missing or ambiguous."""
    found = sorted((logs_root / run).glob(f"*/{session_id}"))
    if len(found) != 1:
        raise SystemExit(f"{run}/{session_id}: expected one session directory, found {len(found)}")
    return found[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=ROOT / "site" / "examples.yaml")
    parser.add_argument("--logs-root", type=Path, default=ROOT / "logs")
    parser.add_argument("--out", type=Path, default=ROOT / "site" / "data" / "examples.js")
    parser.add_argument("--max-thinking", type=int, default=MAX_THINKING_CHARS, help="characters of hidden thinking kept per call")
    args = parser.parse_args()

    spec = yaml.safe_load(args.spec.read_text())
    loaded = {}
    for example in spec["examples"]:
        for key in ("session", "control"):
            if example.get(key):
                path = find_session(args.logs_root, example["run"], example[key])
                loaded[example[key]] = (*read_session(path), read_calls(path))
    table = session_metrics_table((meta, rows) for meta, rows, _ in loaded.values()).set_index("session_id")

    examples = []
    for example in spec["examples"]:
        sessions = []
        for key in ("session", "control"):
            sid = example.get(key)
            if sid:
                meta, rows, calls = loaded[sid]
                sessions.append(session_bundle(meta, rows, calls, table.loc[sid].to_dict(), args.max_thinking))
        examples.append({**{k: example[k] for k in ("id", "title", "blurb", "look_for", "run")}, "sessions": sessions})

    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"examples": examples}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    args.out.write_text(f"window.EXAMPLES = {payload};\n")
    print(f"wrote {args.out} ({args.out.stat().st_size / 1e6:.2f} MB, {sum(len(e['sessions']) for e in examples)} sessions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
