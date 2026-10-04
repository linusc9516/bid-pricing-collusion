"""Viewer export: session bundles, JSON safety, and the example export script."""

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from helpers import custom_session, fixed

from bidrig.schema import CallRow, write_session
from bidrig.viewer import METRIC_KEYS, session_bundle

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def call(session_id: str, rnd: int, firm: str, bid: float | None, thinking: str | None = None, phase: str = "bid") -> CallRow:
    messages = [{"role": "system", "content": f"system for {firm}"}, {"role": "user", "content": f"user r{rnd} {firm} {phase}"}]
    return CallRow(
        session_id=session_id, round=rnd, firm_id=firm, attempt=1, phase=phase, model="fake-model", provider="Host",
        prompt=json.dumps(messages), raw_response=None, reasoning="because", parsed_bid=bid, error=None,
        prompt_tokens=10, completion_tokens=20, latency_ms=5.0, reasoning_tokens=7, finish_reason="tool_calls",
        thinking=thinking, content=None,
    )  # fmt: skip


def two_round_session():
    meta, rows = custom_session([fixed(50.0), fixed(None), fixed(60.0)], n_rounds=2)
    calls = [call(meta.session_id, r, f, 50.0, thinking="t" * 40) for r in (1, 2) for f in "ABC"]
    return meta, rows, calls


def test_bundle_has_rounds_firms_calls_and_prompts() -> None:
    meta, rows, calls = two_round_session()
    bundle = session_bundle(meta, rows, calls, {"collusion_index": float("nan"), "tie_rate": 0.0}, max_thinking=10)
    assert bundle["id"] == meta.session_id and bundle["control"] is False and len(bundle["rounds"]) == 2
    first = bundle["rounds"][0]
    assert first["winner"] == "A" and [f["id"] for f in first["firms"]] == ["A", "B", "C"]
    assert first["firms"][1]["bid"] is None and first["firms"][1]["valid"] is False  # firm B sat out
    assert bundle["system"]["A"] == "system for A" and bundle["system"]["C"] == "system for C"
    shown = first["firms"][0]["calls"][0]
    assert shown["user"] == "user r1 A bid" and shown["thinking"] == "t" * 10 and shown["thinking_chars"] == 40
    assert shown["tokens"] == [10, 20, 7] and shown["finish"] == "tool_calls"
    assert set(bundle["metrics"]) == set(METRIC_KEYS)
    assert bundle["metrics"]["collusion_index"] is None and bundle["metrics"]["tie_rate"] == 0.0


def test_bundle_without_calls_is_json_safe() -> None:
    meta, rows = custom_session([fixed(50.0), fixed(60.0)], n_rounds=3)
    bundle = session_bundle(meta, rows, [], {k: float("nan") for k in METRIC_KEYS})
    assert bundle["system"] == {} and all(f["calls"] == [] for r in bundle["rounds"] for f in r["firms"])
    json.dumps(bundle, allow_nan=False)  # raises on NaN or infinity


def test_rebid_is_kept_next_to_the_original_bid() -> None:
    meta, rows = custom_session([fixed(50.0, rebid=48.0), fixed(50.0, rebid=51.0)], rule="bafo", n_rounds=1)
    calls = [call(meta.session_id, 1, "A", 50.0), call(meta.session_id, 1, "A", 48.0, phase="rebid")]
    bundle = session_bundle(meta, rows, calls)
    row = bundle["rounds"][0]["firms"][0]
    assert bundle["rounds"][0]["tie"] == "bafo" and row["bid"] == 50.0 and row["rebid"] == 48.0
    assert [c["phase"] for c in row["calls"]] == ["bid", "rebid"]


def test_export_script_reads_logs_and_writes_a_loadable_js_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import export_examples

    meta, rows, calls = two_round_session()
    control_meta = replace(meta, history_window=0, condition_id="oneshot__" + meta.condition_id, session_id="oneshot__" + meta.session_id)
    control_rows = [replace(r, session_id=control_meta.session_id) for r in rows]
    control_calls = [call(control_meta.session_id, r, f, 50.0) for r in (1, 2) for f in "ABC"]
    logs = tmp_path / "logs"
    write_session(logs, meta, rows, calls)
    write_session(logs, control_meta, control_rows, control_calls)
    spec = tmp_path / "spec.yaml"
    spec.write_text(yaml.safe_dump({"examples": [{
        "id": "x", "title": "T", "blurb": "B", "look_for": "L", "run": meta.run_id,
        "session": meta.session_id, "control": control_meta.session_id,
    }]}))  # fmt: skip
    out = tmp_path / "data" / "examples.js"
    monkeypatch.setattr(sys, "argv", ["export_examples", "--spec", str(spec), "--logs-root", str(logs), "--out", str(out)])
    assert export_examples.main() == 0
    text = out.read_text()
    assert text.startswith("window.EXAMPLES = ") and text.rstrip().endswith(";")
    payload = json.loads(text[len("window.EXAMPLES = "):].rstrip().rstrip(";"))
    example = payload["examples"][0]
    assert example["title"] == "T" and [s["control"] for s in example["sessions"]] == [False, True]
    assert example["sessions"][0]["metrics"]["delta_index"] is not None  # paired with its control
    first_run = text
    monkeypatch.setattr(sys, "argv", ["export_examples", "--spec", str(spec), "--logs-root", str(logs), "--out", str(out)])
    export_examples.main()
    assert out.read_text() == first_run  # deterministic
