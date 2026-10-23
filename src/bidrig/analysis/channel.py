"""Channel arms against the no-channel baseline (configs/analysis.yaml, sections `notes_luna` and `channel_c1`): the
declared H3, H4 and H5 tests, the channel-use measures from workspace.jsonl or messages.jsonl and the calls, and the
judge's labels by arm.

Arms: B0 is a history session of the baseline run, M1 a private-notes session (condition id `__pn`), M2 a shared-
workspace session (`__ws`), C1 an open-channel session (`__msg`). Sessions are paired by model and seed; the seed fixes
every round's costs.
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
# Keyed by the hypothesis id's prefix: (arm, arm it is compared with, whether support needs a rise). H3 and H10 are
# two-sided with no predicted direction; H4, H5 and H9 predict a rise (configs/analysis.yaml, supported_if).
CONTRASTS = {
    "H3": ("M1", "B0", False), "H4": ("M2", "M1", True), "H5": ("C1", "B0", True),
    "H9": ("M2", "B0", True), "H10": ("M1", "B0", False), "H11": ("S2C", "B0", False), "H12": ("S2A", "B0", True),
}  # fmt: skip
NARROW_COSTS = {(40.0, 60.0, 60.0): "S2C", (40.0, 60.0, 100.0): "S2A"}  # (cost_low, cost_high, reserve_price) of the narrow-cost arms
# Declared secondary contrasts on the confirmatory outcome, Holm-adjusted over the pair: for H5, C1 against M2 and M1 of
# notes_luna; for H9 (notes_deepseek), M2 against M1 and C1 of channel_c1 against M2.
SECONDARY_CONTRASTS = {"H5": (("C1", "M2"), ("C1", "M1")), "H9": (("M2", "M1"), ("C1", "M2"))}
CHANNEL_TEST_COLUMNS = [
    "status", "model", "family", "test_id", "contrast", "outcome", "n", "mean", "median", "sd", "min", "max",
    "ci_low", "ci_high", "n_positive", "p_raw", "p_holm", "wilcoxon_p", "supported",
]  # fmt: skip


def arm_of(meta: SessionMeta) -> str | None:
    """`M1` (private notes), `M2` (shared workspace), `C1` (open channel), `S2C` (rescaled game), `S2A` (narrow costs, reserve 100) or `B0` (history session, no channel, costs 0 to 100); None for a control or an undeclared cost range."""
    if meta.is_control:
        return None
    if meta.workspace or meta.channel:
        if (meta.cost_low, meta.cost_high, meta.reserve_price) != (0, 100, 100):
            return None
    elif (meta.cost_low, meta.cost_high, meta.reserve_price) != (0, 100, 100):
        return NARROW_COSTS.get((float(meta.cost_low), float(meta.cost_high), float(meta.reserve_price)))
    if meta.channel:
        return "C1"
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
    """One row per session of arm B0, M1, M2 or C1: arm, model, seed, the session metrics and profit checks, and `cap_share`.

    `cap_share` is the share of reflection steps that ended at the step cap (0 in B0 and C1, which have none).
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
    """The declared tests of a channel plan, one row per model, contrast and outcome; columns `CHANNEL_TEST_COLUMNS`.

    Each confirmatory hypothesis is the contrast `CONTRASTS` gives for its id's prefix (H3 M1 minus B0, H4 M2 minus M1,
    H5 C1 minus B0), on `collusion_index`, paired by seed: exact sign-flip test, two-sided. Holm runs over the plan's
    hypotheses within a model when it has several (H3 and H4), else over the models (H5). Pairs enter only if neither
    session has `cap_share` above `CAP_SHARE_LIMIT`. Sensitivity rows, when they change the pairs: with those sessions
    put back (`with_capped`), and without pairs above `INVALID_RATE_LIMIT` (`valid_bids`). Secondary outcomes are
    Holm-adjusted within each model and contrast; `SECONDARY_CONTRASTS` (family `secondary_contrast`) within each model.
    """
    hypotheses = plan["confirmatory"]
    alpha = float(hypotheses[0]["alpha"])
    outcome = hypotheses[0]["outcome"]
    rows: list[dict[str, Any]] = []
    for model, cell in table.groupby("model", sort=True):
        for hypothesis in hypotheses:
            test_id = hypothesis["id"].split("_")[0]
            arm, other, _ = CONTRASTS[test_id]
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
            extra = []
            for first, second in SECONDARY_CONTRASTS.get(test_id, ()):
                frame = _pairs(cell, first, second, outcome)
                keep = (frame[f"cap_share_{first}"] <= CAP_SHARE_LIMIT) & (frame[f"cap_share_{second}"] <= CAP_SHARE_LIMIT)
                if keep.any():
                    extra.append({"model": model, "contrast": f"{first} - {second}", "family": "secondary_contrast",
                                  "test_id": f"{first}_{second}_{test_id}"} | _contrast_row(frame[keep], outcome, first, second))  # fmt: skip
            for group in (secondary, extra):
                for entry, adjusted in zip(group, holm([r["p_raw"] for r in group]), strict=True):
                    entry["p_holm"] = adjusted
                rows.extend(group)
    out = pd.DataFrame(rows, columns=CHANNEL_TEST_COLUMNS[1:]).astype({"supported": object})
    per_model = len(hypotheses) > 1
    for family in ("confirmatory", "with_capped", "valid_bids"):
        for model in out["model"].unique() if per_model else [None]:
            mask = (out["family"] == family) & ((out["model"] == model) if per_model else True)
            out.loc[mask, "p_holm"] = holm(out.loc[mask, "p_raw"].tolist())
    confirmatory = out["family"].isin(["confirmatory", "with_capped", "valid_bids"])
    needs_rise = out["test_id"].map(lambda t: CONTRASTS.get(str(t).split("_")[0], (None, None, False))[2]).astype(bool)
    rise_ok = ~needs_rise | (out["mean"] > 0)
    out.loc[confirmatory, "supported"] = (out["p_holm"] < alpha)[confirmatory] & rise_ok[confirmatory]
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


def message_use(sessions: Iterable[tuple[SessionMeta, Sequence[dict[str, Any]], Sequence[CallRow]]]) -> pd.DataFrame:
    """Channel use per C1 session, from its messages.jsonl rows and communication calls; descriptive only.

    Columns: communication steps, share of steps in which a message was sent, the first round with one (NaN if never),
    mean message length in characters, share of messages cut at `max_chars`, and share of communication requests that
    ended without a tool call or with an error.
    """
    records = []
    for meta, events, calls in sessions:
        if arm_of(meta) != "C1":
            continue
        sent = [e for e in events if e["op"] == "write"]
        requests = [c for c in calls if c.phase == "message"]
        steps = {(c.round, c.firm_id) for c in requests}
        records.append({
            "session_id": meta.session_id, "arm": "C1", "model": _model(meta), "seed": meta.seed, "steps": len(steps),
            "share_steps_sent": len({(e["round"], e["firm_id"]) for e in sent}) / len(steps) if steps else float("nan"),
            "first_message_round": min((e["round"] for e in sent), default=float("nan")),
            "mean_message_chars": float(np.mean([len(e["text"] or "") for e in sent])) if sent else float("nan"),
            "share_truncated": float(np.mean([bool(e.get("truncated")) for e in sent])) if sent else float("nan"),
            "share_requests_failed": sum(c.error is not None for c in requests) / len(requests) if requests else float("nan"),
        })  # fmt: skip
    return pd.DataFrame(records)


def labels_by_arm(judged: pd.DataFrame, labels: Sequence[str]) -> pd.DataFrame:
    """Judge labels by arm from a judge CSV (one row per judged call or step): share of judged rows, and share of sessions with at least one.

    Arm from the condition id: `__pn` is M1, `__ws` is M2, `__msg` is C1, a cell `s2c-` or `s2a-` is S2C or S2A, anything else B0. Rows that did not parse are
    left out. Columns: arm, label, judged, share_of_judged, sessions, share_of_sessions.
    """
    frame = judged[judged["parse_ok"].astype(bool)].copy()
    suffix = frame["condition_id"].str
    frame["arm"] = np.select(
        [suffix.endswith("__pn"), suffix.endswith("__ws"), suffix.endswith("__msg"), suffix.contains("lineup-s2c-"), suffix.contains("lineup-s2a-")],
        ["M1", "M2", "C1", "S2C", "S2A"], "B0",
    )
    rows = []
    for arm, cell in frame.groupby("arm", sort=True):
        per_session = cell.groupby("session_id")[list(labels)].any()
        for label in labels:
            rows.append({"arm": arm, "label": label, "judged": len(cell), "share_of_judged": float(cell[label].astype(bool).mean()),
                         "sessions": len(per_session), "share_of_sessions": float(per_session[label].mean())})  # fmt: skip
    return pd.DataFrame(rows, columns=["arm", "label", "judged", "share_of_judged", "sessions", "share_of_sessions"])
