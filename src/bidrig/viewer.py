"""Export of logged sessions to the JSON bundles read by the static example viewer (site/)."""

import json
import math
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from bidrig.analysis.trace_judge import MESSAGES_LABELS
from bidrig.schema import BidRow, CallRow, SessionMeta

MAX_THINKING_CHARS = 2500  # hidden thinking text is cut to this many characters; the full length is kept
METRIC_KEYS = [
    "collusion_index", "control_index", "delta_index", "lowest_cost_win_share", "delta_lowest_cost_win_share",
    "repeat_win_rate", "tie_rate", "tie_price_index", "reserve_bid_rate", "below_cost_bid_rate", "bid_cost_corr",
    "rival_lag_coef", "mean_rebid_delta", "invalid_bid_rate",
]  # fmt: skip


def _clean(value: Any) -> Any:
    """JSON-safe value: NaN and infinity become None, numpy scalars become Python numbers."""
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _messages(call: CallRow) -> dict[str, str]:
    """`{system, user}` text of a logged call; the prompt is stored as a JSON list of chat messages."""
    messages = json.loads(call.prompt)
    out = {"system": "", "user": ""}
    for message in messages:
        if message["role"] in out:
            out[message["role"]] = message["content"]
    return out


WORKSPACE_FILE = "workspace.jsonl"  # shared notes of a workspace session, one row per read or write
MESSAGES_FILE = "messages.jsonl"  # messages of an open-channel session, same row fields
TOOL_PHASES = ("reflect", "message")  # call phases whose `reasoning` holds the tool calls made, as JSON


def read_events(path: Path, name: str) -> list[dict[str, Any]]:
    """Rows of `name` (WORKSPACE_FILE or MESSAGES_FILE) in one session directory, in file order; empty if the file is absent."""
    file = path / name
    if not file.exists():
        return []
    return [json.loads(line) for line in file.read_text().splitlines() if line.strip()]


def _events(events: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Workspace or message rows for the viewer; `round` is the round just played when the row was written."""
    keys = ("seq", "round", "op", "text", "truncated", "n_notes", "n_foreign")
    return [{"firm": e["firm_id"], **{k: e.get(k) for k in keys}, **({"labels": e["labels"]} if e.get("labels") is not None else {})} for e in events]


def _tool_calls(call: CallRow) -> list[dict[str, Any]]:
    """Tool calls of one reflection or communication request: `{name, text, arguments}`, `text` being the note or message if any."""
    try:
        made = json.loads(call.reasoning or "[]")
    except json.JSONDecodeError:
        return [{"name": "unreadable", "text": call.reasoning, "arguments": None}]
    out = []
    for item in made:
        args = item.get("arguments")
        text = args.get("text") if isinstance(args, dict) else None
        rest = {k: v for k, v in args.items() if k != "text"} if isinstance(args, dict) else args
        out.append({"name": item.get("name"), "text": text if isinstance(text, str) else None, "arguments": rest or None})
    return out


def _tool_results(call: CallRow) -> list[str]:
    """Tool results the model had been sent back before this request, oldest first (a step's own results appear in the next step)."""
    return [m.get("content") or "" for m in json.loads(call.prompt) if m.get("role") == "tool"]


def _call_bundle(call: CallRow, max_thinking: int) -> dict[str, Any]:
    """One LLM attempt: reasoning field, hidden thinking (truncated), free text, error, tokens and the user message.

    A reflection or communication request has `tools` (the calls it made) and `results` in place of `reasoning`.
    """
    thinking = call.thinking or ""
    tools = call.phase in TOOL_PHASES
    return {
        **({"tools": _tool_calls(call), "results": _tool_results(call)} if tools else {}),
        "phase": call.phase,
        "attempt": call.attempt,
        "reasoning": None if tools else call.reasoning,
        "thinking": thinking[:max_thinking] or None,
        "thinking_chars": len(thinking),
        "content": call.content,
        "bid": _clean(call.parsed_bid),
        "error": call.error,
        "finish": call.finish_reason,
        "tokens": [call.prompt_tokens, call.completion_tokens, call.reasoning_tokens],
        "user": _messages(call)["user"],
    }


def session_bundle(
    meta: SessionMeta,
    rows: Sequence[BidRow],
    calls: Sequence[CallRow],
    metrics: dict[str, Any] | None = None,
    max_thinking: int = MAX_THINKING_CHARS,
    workspace: Sequence[dict[str, Any]] = (),
    messages: Sequence[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Everything the viewer shows for one session: settings, metrics, rounds, per-firm calls and system prompts.

    `workspace` and `messages` are the rows of workspace.jsonl and messages.jsonl; each adds a key only when it has rows.
    """
    models = {entry.firm_id: entry.model or entry.bidder_type for entry in meta.lineup}
    by_key: dict[tuple[int, str], list[CallRow]] = {}
    systems: dict[str, str] = {}
    for call in calls:
        by_key.setdefault((call.round, call.firm_id), []).append(call)
        systems.setdefault(call.firm_id, _messages(call)["system"])
    rounds = []
    for number in sorted({row.round for row in rows}):
        in_round = [row for row in rows if row.round == number]
        winner = next((row for row in in_round if row.is_winner), None)
        rounds.append(
            {
                "n": number,
                "winner": winner.firm_id if winner else None,
                "price": _clean(winner.winning_bid) if winner else None,
                "tie": in_round[0].tie_resolution,
                "firms": [
                    {
                        "id": row.firm_id,
                        "cost": _clean(row.cost),
                        "bid": _clean(row.bid),
                        "rebid": _clean(row.rebid),
                        "bne": round(float(row.bne_bid), 4),
                        "profit": _clean(row.profit),
                        "won": row.is_winner,
                        "tied": row.tied,
                        "valid": row.valid,
                        "min_cost": row.is_min_cost,
                        "calls": [_call_bundle(c, max_thinking) for c in by_key.get((number, row.firm_id), [])],
                    }
                    for row in sorted(in_round, key=lambda r: r.firm_id)
                ],
            }
        )
    return {
        "id": meta.session_id,
        "condition": meta.condition_id,
        "control": meta.is_control,
        "meta": {
            "seed": meta.seed,
            "n_bidders": meta.n_bidders,
            "tie_break_rule": meta.tie_break_rule,
            "info": meta.info_condition,
            "models": models,
            "cost_range": [meta.cost_low, meta.cost_high],
            "cost_spread": meta.cost_spread,
            "reveal_costs": meta.reveal_costs,
            "reserve": meta.reserve_price,
            "increment": meta.bid_increment,
            "n_rounds": meta.n_rounds,
            "history_window": meta.history_window,
            "prompt_version": meta.prompt_version,
            "providers": {k: f"{v.get('name', '')}".strip() for k, v in meta.providers.items()},
        },
        "metrics": {k: _clean((metrics or {}).get(k)) for k in METRIC_KEYS},
        "system": systems,
        "rounds": rounds,
        **({"workspace": _events(workspace)} if workspace else {}),
        **({"messages": _events(messages)} if messages else {}),
    }


DIFF_LOW = -50.0  # histogram of bid minus benchmark bid: lower edge, in bid units
DIFF_STEP = 2.0  # bin width, in bid units
DIFF_BINS = 50  # bins cover [DIFF_LOW, DIFF_LOW + DIFF_STEP * DIFF_BINS); the two end bins also hold everything beyond
INDEX_METRIC_KEYS = [
    "collusion_index", "delta_index", "lowest_cost_win_share", "tie_rate", "reserve_bid_rate", "bid_cost_corr",
    "markup_ratio", "markup_ratio_min_cost", "markup_ratio_other", "bid_slope", "bid_intercept",
    "bid_gap", "joint_profit_ratio", "switch_gain", "best_reply_share",
]  # fmt: skip

# Charts the findings page draws under a finding of docs/history/BASELINE_FINDINGS.md, by the finding's id; the names are read by
# site/app.js. They are drawn from the first bundled run, so they fit only the findings file written about that run.
FINDING_CHARTS = {
    "F2": ["paired:collusion_index"],
    "F5": ["scatter", "paired:bid_gap"],
    "F7": ["blocks"],
    "F8": ["judge"],
    "F10": ["paired:joint_profit_ratio"],
    "F11": ["paired:switch_gain"],
}
FINDING_LABELS = {"declared": "Declared", "exploratory": "Exploratory", "descriptive": "Descriptive"}


def diff_histogram(meta: SessionMeta, rows: Sequence[BidRow]) -> dict[str, list[int]]:
    """Counts of valid bids by (bid - benchmark bid) bin, per model; bids beyond the range land in the end bins."""
    models = {entry.firm_id: entry.model or entry.bidder_type for entry in meta.lineup}
    out: dict[str, list[int]] = {}
    for row in rows:
        if row.bid is None:
            continue
        slot = int((row.bid - row.bne_bid - DIFF_LOW) // DIFF_STEP)
        counts = out.setdefault(models[row.firm_id], [0] * DIFF_BINS)
        counts[min(max(slot, 0), DIFF_BINS - 1)] += 1
    return out


BID_CLASSES = ("below_cost", "below_benchmark", "at_benchmark", "above_benchmark")
CLASS_TOLERANCE = 1.0  # a bid this close to the benchmark bid counts as at it, in bid units; a coarser bid grid widens it to one increment


def bid_classes(meta: SessionMeta, rows: Sequence[BidRow]) -> dict[str, dict[str, list[int]]]:
    """Counts of valid bids per model and cost role: `min` is the round's lowest-cost firm, `other` the rest.

    Each list holds one count per class in BID_CLASSES order, then the number of those bids that won. A bid under
    the firm's own cost is `below_cost` whatever its distance from the benchmark bid.
    """
    models = {entry.firm_id: entry.model or entry.bidder_type for entry in meta.lineup}
    tolerance = max(CLASS_TOLERANCE, meta.bid_increment)
    out: dict[str, dict[str, list[int]]] = {}
    for row in rows:
        if row.bid is None:
            continue
        diff = row.bid - row.bne_bid
        if row.bid < row.cost - 1e-9:
            slot = 0
        elif abs(diff) <= tolerance + 1e-9:
            slot = 2
        else:
            slot = 1 if diff < 0 else 3
        roles = out.setdefault(models[row.firm_id], {"min": [0] * 5, "other": [0] * 5})
        counts = roles["min" if row.is_min_cost else "other"]
        counts[slot] += 1
        counts[4] += int(row.is_winner)
    return out


def bid_points(meta: SessionMeta, rows: Sequence[BidRow]) -> dict[str, list[list[float]]]:
    """Every valid bid per model as [cost, bid, flags], money to 2 decimals; flags is 1 if the bid won plus 2 if the
    firm had the round's lowest cost."""
    models = {entry.firm_id: entry.model or entry.bidder_type for entry in meta.lineup}
    out: dict[str, list[list[float]]] = {}
    for row in rows:
        if row.bid is not None:
            out.setdefault(models[row.firm_id], []).append([round(row.cost, 2), round(row.bid, 2), int(row.is_winner) + 2 * int(row.is_min_cost)])
    return out


def notes_summary(events: Sequence[dict[str, Any]], kind: str) -> dict[str, Any] | None:
    """What a run page shows of a session's workspace or message log, None if it has none.

    `writes` is notes or messages per firm; `foreign_reads` counts reads that showed a firm another firm's notes, and
    `first_foreign` is the earliest round after which that happened (both None for messages, which have no reads).
    """
    if not events:
        return None
    writes: dict[str, int] = {}
    for e in events:
        if e["op"] == "write":
            writes[e["firm_id"]] = writes.get(e["firm_id"], 0) + 1
    foreign = [e for e in events if e["op"] == "read" and (e.get("n_foreign") or 0) > 0]
    reads = kind == "workspace"
    return {
        "kind": kind,
        "writes": dict(sorted(writes.items())),
        "foreign_reads": len(foreign) if reads else None,
        "first_foreign": min((e["round"] for e in foreign), default=None) if reads else None,
    }


def index_entry(
    meta: SessionMeta, rows: Sequence[BidRow], metrics: dict[str, Any], workspace: Sequence[dict[str, Any]] = (), messages: Sequence[dict[str, Any]] = ()
) -> dict[str, Any]:
    """One session's row in the run list: settings, headline metrics and per-round strings `w` (winner or '-'),
    `t` (1 = tie) and `m` (1 = the lowest-cost firm won), all of length n_rounds."""
    winners, ties, mins = [], [], []
    for number in sorted({row.round for row in rows}):
        in_round = [row for row in rows if row.round == number]
        winner = next((row for row in in_round if row.is_winner), None)
        winners.append(winner.firm_id if winner else "-")
        ties.append("1" if in_round[0].tie_resolution != "none" else "0")
        mins.append("1" if winner is not None and winner.is_min_cost else "0")
    entry = {
        "id": meta.session_id,
        "condition": meta.condition_id,
        "lineup": meta.lineup_id,
        "control": meta.is_control,
        "seed": meta.seed,
        "models": sorted({entry.model or entry.bidder_type for entry in meta.lineup}),
        "n_bidders": meta.n_bidders,
        "n_rounds": meta.n_rounds,
        "tie_break_rule": meta.tie_break_rule,
        "info": meta.info_condition,
        "cost_spread": meta.cost_spread,
        "reveal_costs": meta.reveal_costs,
        "increment": meta.bid_increment,
        "cost_low": meta.cost_low,
        "cost_high": meta.cost_high,
        "reserve": meta.reserve_price,
        "prompt_version": meta.prompt_version,
        "status": meta.status,
        "metrics": {k: _clean(metrics.get(k)) for k in INDEX_METRIC_KEYS},
        "diff_hist": diff_histogram(meta, rows),
        "bid_classes": bid_classes(meta, rows),
        "points": bid_points(meta, rows),
        "w": "".join(winners),
        "t": "".join(ties),
        "m": "".join(mins),
    }
    summary = notes_summary(workspace, "workspace") or notes_summary(messages, "messages")
    if summary:
        entry["notes"] = summary
    return entry


def findings_html(text: str, charts: dict[str, list[str]] | None = None) -> str:
    """A findings Markdown file as HTML for the viewer's findings page.

    Each `##` section becomes a card. The section whose title contains "Definitions" becomes a closed
    `<details>`. Each `### F<n>.` finding becomes its own card with id `F<n>`, its label in brackets (declared,
    exploratory, descriptive) becomes a badge, and its chart slots from `charts` (default `FINDING_CHARTS`) are appended to it. Tables are
    wrapped so they can scroll sideways. The input is a file of this repository, not model output, so the result is
    inserted as HTML.
    """
    import markdown  # export-time only

    html = markdown.markdown(text, extensions=["tables"])
    html = html.replace("<table>", '<div class="tablewrap"><table>').replace("</table>", "</table></div>")

    def finding(block: str) -> str:
        head = re.match(r"<h3>(F\d+)\.\s*(.*?)</h3>", block, re.DOTALL)
        if not head:
            return block
        fid, title = head.group(1), head.group(2)
        label = re.search(r"\s*\(([^()]*)\)\s*$", title)
        badge = ""
        if label and (kind := next((k for k in FINDING_LABELS if label.group(1).lower().startswith(k)), None)):
            title = title[: label.start()]
            badge = f' <span class="badge {kind}" title="{label.group(1)}">{FINDING_LABELS[kind]}</span>'
        slots = "".join(f'<div class="chartslot" data-chart="{name}"></div>' for name in (FINDING_CHARTS if charts is None else charts).get(fid, []))
        body = block[head.end() :]
        return f'<section class="panel finding" id="{fid}"><h3><span class="fid">{fid}</span> {title}{badge}</h3>{body}{slots}</section>'

    out = []
    for section in re.split(r"(?=<h2>)", html):
        title = re.match(r"<h2>(.*?)</h2>", section, re.DOTALL)
        if not title:
            out.append(f'<div class="prosehead">{section}</div>' if section.strip() else "")
        elif "definitions" in title.group(1).lower():
            out.append(f'<details class="panel glossary"><summary>{title.group(1)}</summary>{section[title.end():]}</details>')
        elif "<h3>F" in section:
            parts = re.split(r"(?=<h3>)", section[title.end() :])
            out.append(f'<h2 class="sect">{title.group(1)}</h2>{parts[0]}' + "".join(finding(part) for part in parts[1:]))
        else:
            out.append(f'<section class="panel"><h3>{title.group(1)}</h3>{section[title.end():]}</section>')
    return "".join(out)


def step_labels(judged: pd.DataFrame) -> dict[str, dict[tuple[int, str], list[str]]]:
    """Messages-rubric labels per communication step, from messages_judge.csv: session id -> (round, firm) -> labels found.

    Rows that did not parse are left out; a step with no label maps to an empty list.
    """
    frame = judged[judged["parse_ok"].astype(bool)]
    out: dict[str, dict[tuple[int, str], list[str]]] = {}
    for row in frame.itertuples(index=False):
        found = [name for name in MESSAGES_LABELS if bool(getattr(row, name))]
        out.setdefault(row.session_id, {})[(int(row.round), str(row.firm_id))] = found
    return out


def label_messages(events: Sequence[dict[str, Any]], labels: dict[tuple[int, str], list[str]]) -> list[dict[str, Any]]:
    """Copies of message rows with `labels` added to each write whose step was judged; other rows unchanged."""
    return [e | {"labels": labels[(e["round"], e["firm_id"])]} if e["op"] == "write" and (e["round"], e["firm_id"]) in labels else e for e in events]


def messages_judge_table(judged: pd.DataFrame) -> list[dict[str, Any]]:
    """Messages-rubric labels per lineup: judged steps and sessions, each label's share of steps and of sessions with one,
    and `agreement_share`, the share of sessions in which one firm proposes coordination and another proposes or accepts.

    The agreement rule is the declared `agreement_session` (configs/analysis.yaml, channel_c1). Rows that did not parse
    are left out.
    """
    frame = judged[judged["parse_ok"].astype(bool)].copy()
    for name in MESSAGES_LABELS:
        frame[name] = frame[name].astype(bool)
    rows = []
    for lineup, cell in frame.groupby("lineup_id", sort=True):
        per_session = cell.groupby("session_id")[MESSAGES_LABELS].any()
        firms = cell.groupby(["session_id", "firm_id"])[["proposes_coordination", "accepts_coordination"]].any().reset_index()
        agreed = 0
        for _, group in firms.groupby("session_id"):
            proposers = set(group.loc[group["proposes_coordination"], "firm_id"])
            joiners = set(group.loc[group["proposes_coordination"] | group["accepts_coordination"], "firm_id"])
            agreed += any(joiners - {firm} for firm in proposers)
        rows.append({
            "lineup_id": lineup, "model": str(cell["model"].iloc[0]), "n_steps": len(cell), "n_sessions": len(per_session),
            "agreement_share": agreed / len(per_session),
            **{f"{name}": float(cell[name].mean()) for name in MESSAGES_LABELS},
            **{f"{name}_sessions": float(per_session[name].mean()) for name in MESSAGES_LABELS},
        })  # fmt: skip
    return rows


def _values(items: Sequence[Any]) -> str:
    """Distinct values in first-seen order, joined with ', '."""
    return ", ".join(str(v) for v in dict.fromkeys(items))


def run_setup(metas: Sequence[SessionMeta]) -> list[list[str]]:
    """Setup facts of a run read from its sessions' metadata, as [label, text] rows for the run page.

    Covers firms and models with their hosts, session counts, rounds, tie rule, information, costs, increment and
    reserve, communication, prompt version, temperature, seeds, dates and code commit. A setting that varies across
    sessions lists every value.
    """
    models: dict[str, set[str]] = {}
    for meta in metas:
        for entry in meta.lineup:
            name = entry.model or f"scripted ({entry.bidder_type})"
            host = meta.providers.get(entry.model or "", {}).get("name")
            models.setdefault(name, set()).update([host] if host else [])
    controls = sum(m.is_control for m in metas)
    costs = []
    for m in metas:
        text = f"private, uniform {m.cost_low:g} to {m.cost_high:g}" + (f", common draw with spread ±{m.cost_spread:g}" if m.cost_spread else "")
        costs.append(text + ("; every firm is shown every cost" if m.reveal_costs else ""))
    talk = []
    for m in metas:
        if m.channel:
            talk.append("open message channel: one message per firm after each round, every firm reads every message")
        elif m.workspace:
            talk.append("shared notes workspace (firms not told it is shared)" if m.workspace_shared else "private notes, one per firm")
        else:
            talk.append("none")
    temps = {(e.model, m.temperature) for m in metas for e in m.lineup if e.model}
    dates = sorted(d[:10] for m in metas for d in (m.started_at, m.finished_at) if d)
    shas = [m.git_sha[:7] for m in metas if m.git_sha]
    seeds = sorted(m.seed for m in metas)
    rows = [
        ["Firms and models", "; ".join(f"{name}" + (f" on {_values(sorted(hosts))}" if hosts else "") for name, hosts in sorted(models.items()))],
        ["Firms per session", _values(sorted(m.n_bidders for m in metas))],
        ["Sessions", f"{len(metas) - controls} repeated" + (f", {controls} one-shot controls (same seed and costs, no history)" if controls else "")],
        ["Rounds", _values(sorted(m.n_rounds for m in metas))],
        ["Tie rule", _values(m.tie_break_rule for m in metas)],
        ["Information shown", _values(m.info_condition for m in metas)],
        ["Costs", _values(costs)],
        ["Bid increment, reserve", _values(f"{m.bid_increment:g}, {m.reserve_price:g}" for m in metas)],
        ["Communication", _values(talk)],
        ["Prompt version", _values(m.prompt_version or "v0" for m in metas)],
        ["Temperature", "; ".join(f"{model} {'not sent' if t is None else f'{t:g}'}" for model, t in sorted(temps, key=str)) or "–"],
        ["Seeds", f"{seeds[0]} to {seeds[-1]}" if seeds else "–"],
        ["Dates", f"{dates[0]} to {dates[-1]}" if dates and dates[0] != dates[-1] else (dates[0] if dates else "–")],
        ["Code commit", _values(shas) or "–"],
    ]  # fmt: skip
    return rows


def config_header(text: str) -> str:
    """The leading comment block of a YAML config, without the `#` markers; empty if the file starts with no comment."""
    lines = []
    for line in text.splitlines():
        if not line.startswith("#"):
            break
        lines.append(line[1:].removeprefix(" "))
    return "\n".join(lines).strip()
