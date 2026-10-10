"""Experiment orchestrator: expands a config into cells x sessions x rounds and runs them.

Behaviour is specified in PLANNING.md section 2.5; host rules in 5.5.
"""

import asyncio
import itertools
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from bidrig.auction import run_session
from bidrig.bidders import Bidder, LLMBidder, make_scripted_bidder
from bidrig.bne import make_benchmark
from bidrig.llm import (
    BudgetExceeded,
    LLMSettings,
    ModelSpec,
    OpenRouterClient,
    ProviderError,
    ProviderStats,
    SpendTracker,
    check_host_spec,
    host_role_for,
    load_models,
)
from bidrig.schema import (
    SESSION_FILE,
    BidRow,
    CallRow,
    LineupEntry,
    SessionMeta,
    firm_ids,
    read_meta,
    session_dir,
    write_meta,
    write_session,
)

AUCTION_KEYS = {"cost_low", "cost_high", "cost_spread", "reveal_costs", "reserve_price", "bid_increment", "tie_break_rule", "n_rounds", "n_bidders"}
SESSION_KEYS = {"n_sessions", "base_seed", "info_condition", "history_window", "disclose_horizon"}
SCRIPTED_PARAMS = {"markup", "shade", "undercut", "price"}
# Slot assignment uses its own stream, so it never shifts costs or tie-breaks.
_SLOT_STREAM = 2


# Phase B leaves these as the string TBD until decided (PLANNING.md 5.6); only `per_model` thinking exists so far.
UNDECIDED_LLM_KEYS = ("max_output_tokens", "reasoning_mode")


def tbd_settings(config: dict[str, Any]) -> list[str]:
    """`llm` keys the config still marks TBD; empty once every undecided setting has a value."""
    llm = config.get("llm", {})
    return [key for key in UNDECIDED_LLM_KEYS if str(llm.get(key)).strip().upper() == "TBD"]


def check_llm_settings(config: dict[str, Any]) -> None:
    """Raise if a config that calls models has a TBD (`ValueError`) or unusable (`ValueError`, `TypeError`) `llm` setting."""
    tbd = tbd_settings(config)
    if tbd:
        raise ValueError(f"llm settings still TBD: {', '.join(tbd)} (PLANNING.md 5.6, 7.2); not calling models")
    llm = config.get("llm", {})
    if llm.get("reasoning_mode", "per_model") != "per_model":
        raise ValueError(f"unsupported llm.reasoning_mode {llm['reasoning_mode']!r}; only per_model exists")
    if not isinstance(llm.get("max_output_tokens", 400), int) or isinstance(llm.get("max_output_tokens"), bool):
        raise TypeError(f"llm.max_output_tokens must be an integer, got {llm['max_output_tokens']!r}")


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursive dict merge; values in `override` win, lists are replaced whole."""
    out = dict(base)
    for key, value in override.items():
        out[key] = _merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


def load_config(path: Path) -> dict[str, Any]:
    """A config with its `inherits` chain merged in (paths relative to the config's directory)."""
    path = Path(path)
    raw = yaml.safe_load(path.read_text()) or {}
    parent = raw.pop("inherits", None)
    return _merge(load_config(path.parent / parent), raw) if parent else raw


@dataclass
class PlannedSession:
    """One session to run: its metadata plus what plays each slot."""

    meta: SessionMeta
    scripted: dict[str, Any] | None  # {bidder, **params} for scripted lineups, else None
    models: list[str | None]  # model alias per slot; None for scripted slots

    @property
    def n_llm_calls(self) -> int:
        """Bid calls before rebids and retries."""
        return 0 if self.scripted else self.meta.n_rounds * self.meta.n_bidders


def condition_id(
    cell_id: str, rule: str, info: str, n_bidders: int, history_window: int | None, cost_spread: float = 0.0,
    reveal_costs: bool = False,
) -> str:
    """e.g. `tie-least_wins__info-full__lineup-homog-deepseek__n3`; one-shot controls get `oneshot__`, common-cost draws `__spread<s>`, revealed costs `__costs-public`."""
    prefix = "oneshot__" if history_window == 0 else ""
    suffix = (f"__spread{cost_spread:g}" if cost_spread else "") + ("__costs-public" if reveal_costs else "")
    return f"{prefix}tie-{rule}__info-{info}__lineup-{cell_id}__n{n_bidders}{suffix}"


def slot_models(lineup: dict[str, Any], seed: int, n_bidders: int) -> list[str | None]:
    """Model alias per slot; heterogeneous lineups are shuffled with a seeded draw shared by the control."""
    kind = lineup["type"]
    if kind == "scripted":
        return [None] * n_bidders
    if kind == "homogeneous":
        return [lineup["model"]] * n_bidders
    if kind == "heterogeneous":
        models = list(lineup["models"])
        if len(models) != n_bidders:
            raise ValueError(f"heterogeneous lineup {models} does not fill {n_bidders} slots")
        order = np.random.default_rng([seed, n_bidders, _SLOT_STREAM]).permutation(n_bidders)
        return [models[i] for i in order]
    raise ValueError(f"unknown lineup type {kind!r}")


def git_sha(root: Path) -> str | None:
    """HEAD commit, suffixed `-dirty` when the tree has uncommitted changes; None outside git."""
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True)
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return sha.stdout.strip() + ("-dirty" if dirty.stdout.strip() else "")


def plan_sessions(
    config: dict[str, Any],
    run_id: str,
    models: dict[str, ModelSpec],
    host_role: str = "primary",
    sha: str | None = None,
) -> list[PlannedSession]:
    """Every session of a config: cells x sweep combinations x n_sessions, seeds base_seed + k.

    `host_role` is a host spec (`llm.host_role_for`): one tier for every model, or per model as `deepseek=backup`.
    """
    check_host_spec(host_role, models)
    sweep = config.get("sweep") or {}
    unknown = set(sweep) - AUCTION_KEYS - SESSION_KEYS
    if unknown:
        raise ValueError(f"cannot sweep {sorted(unknown)}")
    combos = [dict(zip(sweep, values, strict=True)) for values in itertools.product(*sweep.values())]
    llm = config.get("llm", {})
    planned = []
    for cell in config["cells"]:
        for combo in combos:
            auction = {**config["auction"], **{k: v for k, v in combo.items() if k in AUCTION_KEYS}}
            session = {**config["session"], **{k: v for k, v in combo.items() if k in SESSION_KEYS}}
            n = auction["n_bidders"]
            lineup = cell["lineup"]
            scripted = None
            if lineup["type"] == "scripted":
                scripted = {"bidder": lineup["bidder"], **{k: v for k, v in lineup.items() if k in SCRIPTED_PARAMS}}
            cid = condition_id(
                cell["id"], auction["tie_break_rule"], session["info_condition"], n, session["history_window"],
                auction.get("cost_spread", 0.0), auction.get("reveal_costs", False),
            )
            for k in range(session["n_sessions"]):
                seed = session["base_seed"] + k
                aliases = slot_models(lineup, seed, n)
                for alias in aliases:
                    if alias is not None and alias not in models:
                        raise ValueError(f"model {alias!r} is not in configs/models.yaml")
                providers = {}
                for alias in sorted({a for a in aliases if a}):
                    host = models[alias].host(host_role_for(host_role, alias))
                    if host is not None:
                        providers[alias] = {"name": host.name, "quantization": host.quantization or "not filtered", "role": host.role}
                meta = SessionMeta(
                    run_id=run_id,
                    condition_id=cid,
                    session_id=f"{cid}__seed{seed}",
                    seed=seed,
                    n_bidders=n,
                    info_condition=session["info_condition"],
                    tie_break_rule=auction["tie_break_rule"],
                    lineup_id=cell["id"],
                    lineup=[
                        LineupEntry(f, scripted["bidder"] if scripted else "llm", alias)
                        for f, alias in zip(firm_ids(n), aliases, strict=True)
                    ],
                    cost_low=auction["cost_low"],
                    cost_high=auction["cost_high"],
                    cost_spread=auction.get("cost_spread", 0.0),
                    reveal_costs=auction.get("reveal_costs", False),
                    reserve_price=auction["reserve_price"],
                    bid_increment=auction["bid_increment"],
                    n_rounds=auction["n_rounds"],
                    history_window=session["history_window"],
                    # None when no model of the lineup is sent a temperature (ModelSpec.send_temperature)
                    temperature=llm.get("temperature") if any(a and models[a].send_temperature for a in aliases) else None,
                    prompt_version=None if scripted else config.get("prompt", {}).get("version"),
                    providers=providers,
                    git_sha=sha,
                )
                planned.append(PlannedSession(meta, scripted, aliases))
    ids = [p.meta.session_id for p in planned]
    if len(set(ids)) != len(ids):
        raise ValueError("session ids collide; check the config's cells and sweep")
    return planned


@dataclass
class Estimate:
    """Dry-run totals; costs in USD at the pinned host's price (headline price where none is pinned)."""

    n_conditions: int
    n_sessions: int
    n_llm_calls: int
    cost_usd: float
    cost_by_model: dict[str, float]
    output_tokens_per_call: int


def estimate(plan: list[PlannedSession], config: dict[str, Any], models: dict[str, ModelSpec], host_role: str) -> Estimate:
    """Calls and cost before rebids and retries, from the token assumptions in the config's `budget`."""
    budget = config.get("budget", {})
    base_in = budget.get("estimate_input_tokens_base", 250)
    per_row = budget.get("estimate_tokens_per_history_row", 10)
    out = budget.get("estimate_output_tokens", 250)
    by_model: dict[str, float] = {}
    for p in plan:
        meta = p.meta
        if p.scripted:
            continue
        # The prompt grows by one line per firm per earlier round; on average (n_rounds - 1) / 2 rounds are shown.
        shown_rounds = 0 if meta.history_window == 0 else (meta.n_rounds - 1) / 2
        tokens_in = base_in + per_row * meta.n_bidders * shown_rounds
        for alias in p.models:
            spec = models[alias]
            host = spec.host(host_role_for(host_role, alias))
            price_in, price_out = (host.price_in, host.price_out) if host else (spec.price_in, spec.price_out)
            cost = meta.n_rounds * (tokens_in * price_in + out * price_out) / 1e6
            by_model[alias] = by_model.get(alias, 0.0) + cost
    return Estimate(
        n_conditions=len({p.meta.condition_id for p in plan}),
        n_sessions=len(plan),
        n_llm_calls=sum(p.n_llm_calls for p in plan),
        cost_usd=sum(by_model.values()),
        cost_by_model=by_model,
        output_tokens_per_call=out,
    )


@dataclass
class RunResult:
    """Outcome of one `run_plan` call; spend in USD at the pinned host's price."""

    completed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    spent_usd: float = 0.0
    budget_exceeded: bool = False


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def is_complete(log_dir: Path, meta: SessionMeta) -> bool:
    """True if this session already has a session.json with status `complete`."""
    path = session_dir(log_dir, meta)
    return (path / SESSION_FILE).exists() and read_meta(path).status == "complete"


async def _run_one(
    planned: PlannedSession,
    config: dict[str, Any],
    models: dict[str, ModelSpec],
    client: OpenRouterClient | None,
    log_dir: Path,
    host_role: str,
) -> None:
    """Run one session from scratch and write its directory; status ends `complete` or `failed`."""
    meta = replace(planned.meta, started_at=_now(), finished_at=None, status="running")
    write_meta(log_dir, meta)
    log: list[BidRow] = []
    stats = ProviderStats()
    bidders: list[Bidder]
    if planned.scripted:
        params = {k: v for k, v in planned.scripted.items() if k != "bidder"}
        bne = make_benchmark(meta.n_bidders, meta.cost_low, meta.cost_high, meta.cost_spread, meta.reveal_costs)
        bidders = [make_scripted_bidder(planned.scripted["bidder"], bne, meta.reserve_price, **params) for _ in meta.lineup]
    else:
        if client is None:
            raise ValueError("an LLM session needs a client")
        llm = config.get("llm", {})
        template = Path(config["_root"]) / config["prompt"]["template"]
        bidders = [
            LLMBidder(
                models[alias],
                models[alias].host(host_role_for(host_role, alias)),
                client,
                meta,
                log,
                reasoning_length=llm.get("reasoning_length", "short"),
                max_output_tokens=llm.get("max_output_tokens", 400),
                template=template,
                stats=stats,
            )
            for alias in planned.models
        ]
    try:
        await run_session(meta, bidders, log, int(config.get("llm", {}).get("control_round_concurrency", 1)))
    except BaseException:
        meta.status, meta.finished_at = "failed", _now()
        meta.provider_retries, meta.provider_errors = stats.retries, stats.errors
        write_session(log_dir, meta, log, _calls(bidders))
        raise
    meta.status, meta.finished_at = "complete", _now()
    meta.provider_retries, meta.provider_errors = stats.retries, stats.errors
    write_session(log_dir, meta, log, _calls(bidders))


def _calls(bidders: list[Bidder]) -> list[CallRow]:
    """Every LLM attempt of a session, ordered by round, firm and attempt."""
    calls = [c for b in bidders for c in getattr(b, "calls", [])]
    return sorted(calls, key=lambda c: (c.round, c.firm_id, c.phase == "rebid", c.attempt))


async def run_plan(
    plan: list[PlannedSession],
    config: dict[str, Any],
    models: dict[str, ModelSpec],
    log_dir: Path,
    client_factory: Callable[[], Any] | None = None,
    host_role: str = "primary",
    progress: Callable[[str], None] | None = None,
) -> RunResult:
    """Run every session not yet complete, up to `llm.max_concurrency` at once; stops at the spend cap.

    `progress` gets one line per finished session: how many of the sessions to run are done, and the spend so far.
    """
    result = RunResult()
    todo = []
    for p in plan:
        (result.skipped if is_complete(log_dir, p.meta) else todo).append(p)
    result.skipped = [p.meta.session_id for p in result.skipped]

    llm = config.get("llm", {})
    spend = SpendTracker(config.get("budget", {}).get("max_cost_usd", 0.0))
    client = None
    if any(not p.scripted for p in todo):
        check_llm_settings(config)
        if client_factory is None:
            raise ValueError("this config calls models; pass a client factory")
        settings = LLMSettings.from_config(llm)
        client = OpenRouterClient(client_factory(), settings, spend)

    gate = asyncio.Semaphore(llm.get("max_concurrency", 8))
    stop = asyncio.Event()

    def report(status: str, session_id: str) -> None:
        if progress is not None:
            done = len(result.completed) + len(result.failed)
            progress(f"[{done}/{len(todo)}] {status} {session_id} (spent ${spend.spent_usd:.3f})")

    async def guarded(p: PlannedSession) -> None:
        async with gate:
            if stop.is_set():
                return
            try:
                await _run_one(p, config, models, client, log_dir, host_role)
            except BudgetExceeded as exc:
                stop.set()
                result.budget_exceeded = True
                result.failed[p.meta.session_id] = str(exc)
                report("STOPPED, spending cap reached:", p.meta.session_id)
            except ProviderError as exc:
                result.failed[p.meta.session_id] = str(exc)
                report("FAILED", p.meta.session_id)
            else:
                result.completed.append(p.meta.session_id)
                report("complete", p.meta.session_id)

    await asyncio.gather(*(guarded(p) for p in todo))
    result.spent_usd = spend.spent_usd
    return result


def prepare(
    config_path: Path, run_id: str | None = None, host_role: str = "primary"
) -> tuple[dict[str, Any], dict[str, ModelSpec], list[PlannedSession]]:
    """Load a config and its models and plan its sessions; the default run id is the config's file stem."""
    config_path = Path(config_path).resolve()
    config = load_config(config_path)
    root = config_path.parents[1]
    config["_root"] = str(root)
    models = load_models(config_path.parent / "models.yaml")
    plan = plan_sessions(config, run_id or config_path.stem, models, host_role, git_sha(root))
    return config, models, plan
