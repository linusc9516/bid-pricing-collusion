"""Notes arms against the no-channel baseline (configs/analysis.yaml, section `notes_luna`): the declared H3 and H4 tests,
the channel-use measures from workspace.jsonl and the reflection calls, and the judge's labels by arm.

Arms: B0 is a history session of the baseline run, M1 a private-notes session (condition id `__pn`), M2 a shared-
workspace session (`__ws`). Sessions are paired by model and seed; the seed fixes every round's costs.
"""

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from bidrig.analysis.metrics import session_metrics_table
from bidrig.analysis.profit import profit_checks_table
from bidrig.analysis.stats import INVALID_RATE_LIMIT, _paired_row, holm
from bidrig.schema import BidRow, CallRow, SessionMeta
from bidrig.workspace import END_TOOL

CAP_SHARE_LIMIT = 0.10  # a session with more of its reflection steps ending at the step cap is left out of the tests (declared)
CONTRASTS = (("H3", "M1", "B0"), ("H4", "M2", "M1"))  # (hypothesis, arm, arm it is compared with)
CHANNEL_TEST_COLUMNS = [
    "status", "model", "family", "test_id", "contrast", "outcome", "n", "mean", "median", "sd", "min", "max",
    "ci_low", "ci_high", "n_positive", "p_raw", "p_holm", "wilcoxon_p", "supported",
]  # fmt: skip


def arm_of(meta: SessionMeta) -> str | None:
    """`M1` (private notes), `M2` (shared workspace) or `B0` (history session, no channel); None for a control or a channel session."""
    if meta.is_control or meta.channel:
        return None
    if meta.workspace:
        return "M2" if meta.workspace_shared else "M1"
    return "B0"


def _model(meta: SessionMeta) -> str:
    return next(entry.model for entry in meta.lineup if entry.model)


def reflection_endings(calls: Sequence[CallRow]) -> dict[str, int]:
    """Reflection steps of one session by how they ended: `end_reflection`, `step_cap` (every request used, no end call) or `no_tool_call` (a reply with none)."""
    steps: dict[tuple[int, str], list[CallRow]] = defaultdict(list)
    for call in calls:
        if call.phase == "reflect":
            steps[(call.round, call.firm_id)].append(call)
    counts = {"steps": len(steps), "end_reflection": 0, "step_cap": 0, "no_tool_call": 0}
    for attempts in steps.values():
        named = [item.get("name") for c in attempts if c.error is None for item in json.loads(c.reasoning or "[]")]
        if END_TOOL in named:
            counts["end_reflection"] += 1
        elif attempts[-1].error == "no tool call":
            counts["no_tool_call"] += 1
        else:
            counts["step_cap"] += 1
    return counts


def channel_table(sessions: Iterable[tuple[SessionMeta, Sequence[BidRow], Sequence[CallRow]]]) -> pd.DataFrame:
    """One row per session of arm B0, M1 or M2: arm, model, seed, the session metrics and profit checks, and `cap_share`.

    `cap_share` is the share of reflection steps that ended at the step cap (0 in B0, which has none).
    """
    kept = [(meta, rows, calls) for meta, rows, calls in sessions if arm_of(meta)]
    if not kept:
        return pd.DataFrame()
    pairs = [(meta, rows) for meta, rows, _ in kept]
    table = session_metrics_table(pairs).merge(profit_checks_table(pairs)[["session_id", "joint_profit_ratio", "switch_gain"]], on="session_id")
    extra = []
    for meta, _, calls in kept:
        ends = reflection_endings(calls)
        extra.append({"session_id": meta.session_id, "arm": arm_of(meta), "model": _model(meta),
                      "cap_share": ends["step_cap"] / ends["steps"] if ends["steps"] else 0.0})  # fmt: skip
    return pd.DataFrame(extra).merge(table, on="session_id")


def _pairs(table: pd.DataFrame, arm: str, other: str, metric: str) -> pd.DataFrame:
    """Seeds with both arms present: columns seed, `arm`, `other` (the metric), and each side's cap share and invalid rate."""
    sides = []
    for name in (arm, other):
        side = table[table["arm"] == name].set_index("seed")[[metric, "cap_share", "invalid_bid_rate"]]
        sides.append(side.add_suffix(f"_{name}"))
    return sides[0].join(sides[1], how="inner").dropna(subset=[f"{metric}_{arm}", f"{metric}_{other}"])


def _contrast_row(frame: pd.DataFrame, metric: str, arm: str, other: str) -> dict[str, Any]:
    """Paired summary of `metric` in `arm` minus `other` over the rows of `_pairs`, with the sign-flip and Wilcoxon p."""
    diff = (frame[f"{metric}_{arm}"] - frame[f"{metric}_{other}"]).to_numpy(float)
    summary = _paired_row(diff)
    summary.pop("n_negative")
    return {"outcome": metric, "n_positive": int((diff > 0).sum())} | summary


def channel_tests(table: pd.DataFrame, plan: Mapping[str, Any], status: str) -> pd.DataFrame:
    """The declared tests of the notes plan, one row per model, contrast and outcome; columns `CHANNEL_TEST_COLUMNS`.

    H3 is M1 minus B0, H4 is M2 minus M1, on `collusion_index`, paired by seed: exact sign-flip test, two-sided,
    Holm over the two. Pairs enter only if neither session has `cap_share` above `CAP_SHARE_LIMIT`. Sensitivity rows,
    when they change the pairs: with those sessions put back (`with_capped`), and without pairs above
    `INVALID_RATE_LIMIT` (`valid_bids`). Secondary outcomes are Holm-adjusted within each contrast.
    """
    h3, h4 = plan["confirmatory"]
    alpha = float(h3["alpha"])
    outcome = h3["outcome"]
    rows: list[dict[str, Any]] = []
    for model, cell in table.groupby("model", sort=True):
        for (test_id, arm, other), hypothesis in zip(CONTRASTS, (h3, h4), strict=True):
            base = {"model": model, "contrast": f"{arm} - {other}"}

            every = _pairs(cell, arm, other, outcome)
            capped = (every[f"cap_share_{arm}"] > CAP_SHARE_LIMIT) | (every[f"cap_share_{other}"] > CAP_SHARE_LIMIT)
            main = every[~capped]
            if main.empty:
                continue
            rows.append(base | {"family": "confirmatory", "test_id": hypothesis["id"]} | _contrast_row(main, outcome, arm, other))
            if capped.any():
                rows.append(base | {"family": "with_capped", "test_id": hypothesis["id"]} | _contrast_row(every, outcome, arm, other))
            valid = (main[f"invalid_bid_rate_{arm}"] <= INVALID_RATE_LIMIT) & (main[f"invalid_bid_rate_{other}"] <= INVALID_RATE_LIMIT)
            if 0 < valid.sum() < len(main):
                rows.append(base | {"family": "valid_bids", "test_id": hypothesis["id"]} | _contrast_row(main[valid], outcome, arm, other))
            secondary = []
            for metric in plan["secondary"]:
                frame = _pairs(cell, arm, other, metric)
                keep = (frame[f"cap_share_{arm}"] <= CAP_SHARE_LIMIT) & (frame[f"cap_share_{other}"] <= CAP_SHARE_LIMIT)
                if keep.any():
                    secondary.append(base | {"family": "secondary", "test_id": f"{metric}_{test_id}"} | _contrast_row(frame[keep], metric, arm, other))
            for entry, adjusted in zip(secondary, holm([r["p_raw"] for r in secondary]), strict=True):
                entry["p_holm"] = adjusted
            rows.extend(secondary)
    out = pd.DataFrame(rows, columns=CHANNEL_TEST_COLUMNS[1:]).astype({"supported": object})
    for family in ("confirmatory", "with_capped", "valid_bids"):
        for model in out["model"].unique():
            mask = (out["family"] == family) & (out["model"] == model)
            out.loc[mask, "p_holm"] = holm(out.loc[mask, "p_raw"].tolist())
    confirmatory = out["family"] != "secondary"
    significant = out["p_holm"] < alpha
    h4_rows = out["test_id"] == h4["id"]
    # H3 is two-sided with no predicted direction; H4 predicts a rise (configs/analysis.yaml, supported_if).
    out.loc[confirmatory, "supported"] = significant[confirmatory] & (~h4_rows[confirmatory] | (out.loc[confirmatory, "mean"] > 0))
    out.insert(0, "status", status)
    return out[CHANNEL_TEST_COLUMNS]


def workspace_use(sessions: Iterable[tuple[SessionMeta, Sequence[dict[str, Any]], Sequence[CallRow]]]) -> pd.DataFrame:
    """Channel use per M1 or M2 session, from its workspace.jsonl rows and reflection calls; descriptive only.

    Columns: notes per reflection step, mean note length in characters, share of notes cut at the limit, share of reads
    that showed at least one note by another firm, the first round in which a firm read one (NaN if never), and the
    reflection steps by how they ended.
    """
    records = []
    for meta, events, calls in sessions:
        arm = arm_of(meta)
        if arm not in ("M1", "M2"):
            continue
        writes = [e for e in events if e["op"] == "write"]
        reads = [e for e in events if e["op"] == "read"]
        foreign = [e for e in reads if (e.get("n_foreign") or 0) > 0]
        ends = reflection_endings(calls)
        records.append({
            "session_id": meta.session_id, "arm": arm, "model": _model(meta), "seed": meta.seed,
            "notes_per_step": len(writes) / ends["steps"] if ends["steps"] else float("nan"),
            "mean_note_chars": float(np.mean([len(e["text"] or "") for e in writes])) if writes else float("nan"),
            "share_truncated": float(np.mean([bool(e.get("truncated")) for e in writes])) if writes else float("nan"),
            "reads": len(reads), "share_reads_foreign": len(foreign) / len(reads) if reads else float("nan"),
            "first_foreign_read_round": min((e["round"] for e in foreign), default=float("nan")),
        } | ends)  # fmt: skip
    return pd.DataFrame(records)


def labels_by_arm(judged: pd.DataFrame, labels: Sequence[str]) -> pd.DataFrame:
    """Judge labels by arm from a judge CSV (one row per judged call or step): share of judged rows, and share of sessions with at least one.

    Arm from the condition id: `__pn` is M1, `__ws` is M2, anything else B0. Rows that did not parse are left out.
    Columns: arm, label, judged, share_of_judged, sessions, share_of_sessions.
    """
    frame = judged[judged["parse_ok"].astype(bool)].copy()
    frame["arm"] = np.select([frame["condition_id"].str.endswith("__pn"), frame["condition_id"].str.endswith("__ws")], ["M1", "M2"], "B0")
    rows = []
    for arm, cell in frame.groupby("arm", sort=True):
        per_session = cell.groupby("session_id")[list(labels)].any()
        for label in labels:
            rows.append({"arm": arm, "label": label, "judged": len(cell), "share_of_judged": float(cell[label].astype(bool).mean()),
                         "sessions": len(per_session), "share_of_sessions": float(per_session[label].mean())})  # fmt: skip
    return pd.DataFrame(rows, columns=["arm", "label", "judged", "share_of_judged", "sessions", "share_of_sessions"])
