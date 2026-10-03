"""Pre-pilot smoke test (PLANNING.md 5.5): one forced tool call per pinned host.

Usage: smoke_test.py [--yes] [--models deepseek gpt-oss] [--roles primary fallback]
Without --yes it prints the planned calls and spends nothing. Costs a few cents in total.
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from bidrig.llm import (
    BudgetExceeded,
    LLMSettings,
    OpenRouterClient,
    ProviderError,
    SpendTracker,
    load_models,
    make_openai_client,
)
from bidrig.prompts import build_messages
from bidrig.runner import load_config
from bidrig.schema import BidRequest, LineupEntry, SessionMeta

ROOT = Path(__file__).resolve().parents[1]
CAP_USD = 0.10


def round_one_meta() -> SessionMeta:
    """A pilot-shaped session (N = 3, random tie-break, full history) for one round-1 prompt."""
    return SessionMeta(
        run_id="smoke", condition_id="smoke", session_id="smoke", seed=1, n_bidders=3, info_condition="full",
        tie_break_rule="random", lineup_id="smoke", lineup=[LineupEntry(f, "llm") for f in "ABC"],
        cost_low=0, cost_high=100, reserve_price=100, bid_increment=0.01, n_rounds=1,
    )  # fmt: skip


def base_settings() -> LLMSettings:
    """Call settings from configs/base.yaml, so the smoke test sends what the pilot will send."""
    return LLMSettings.from_config(load_config(ROOT / "configs" / "base.yaml")["llm"])


async def check_host(client: OpenRouterClient, spec, host) -> dict:
    meta = round_one_meta()
    messages = build_messages(meta, [], BidRequest("A", 0, 1, 37.42), "short", client.settings.max_output_tokens)
    result = {"model": spec.alias, "slug": spec.slug, "host": host.name if host else "(unpinned)", "role": host.role if host else "-"}
    try:
        bid, rows = await client.request_bid(
            spec, host, messages, 100, session_id="smoke", session_seed=1, round_number=1, firm_id="A", slot=0, phase="bid"
        )
    except (ProviderError, BudgetExceeded) as exc:
        return {**result, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
    last = rows[-1]
    raw = json.loads(last.raw_response) if last.raw_response.startswith("{") else {}
    usage = raw.get("usage") or {}
    price_in, price_out = (host.price_in, host.price_out) if host else (spec.price_in, spec.price_out)
    listed = (last.prompt_tokens * price_in + last.completion_tokens * price_out) / 1e6
    return {
        **result,
        "ok": bid is not None,
        "1_tool_call_parsed": bid is not None,
        "bid": bid,
        "attempts": len(rows),
        "2_seed_accepted": True,  # require_parameters rejects the request if the host ignores `seed`
        "3_completion_tokens": last.completion_tokens,
        "3_reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
        "4_provider": last.provider,
        "5_charged_usd": usage.get("cost"),
        "5_listed_usd": round(listed, 8),
        "reasoning": last.reasoning,
        "errors": [r.error for r in rows if r.error],
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--yes", action="store_true", help="actually call the API")
    parser.add_argument("--models", nargs="+", default=["deepseek", "gpt-oss"])
    parser.add_argument("--roles", nargs="+", default=["primary", "fallback", "backup"])
    args = parser.parse_args()

    specs = load_models(ROOT / "configs" / "models.yaml")
    # A model with fewer tiers (or none, like qwen) is called once per distinct host, whatever the roles asked for.
    plan = []
    for m in args.models:
        for r in args.roles:
            host = specs[m].host(r)
            if (m, host.name if host else None) not in [(s.alias, h.name if h else None) for s, h in plan]:
                plan.append((specs[m], host))
    settings = base_settings()
    print(f"settings from configs/base.yaml: {settings}")
    for spec, host in plan:
        where = f"{host.role:8s} {host.name} ({host.quantization})" if host else "unpinned"
        print(f"{spec.alias:9s} {spec.slug:32s} {where}")
    if not args.yes:
        print(f"\n{len(plan)} calls planned, cap ${CAP_USD:.2f}. Nothing sent; rerun with --yes to call the API.")
        return 0

    load_dotenv(ROOT / ".env")
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        print("OPENROUTER_API_KEY is not set (see .env.example)", file=sys.stderr)
        return 1
    base_url = os.environ.get("OPENROUTER_BASE_URL") or None
    client = OpenRouterClient(make_openai_client(key, base_url), base_settings(), SpendTracker(CAP_USD))
    results = [await check_host(client, spec, host) for spec, host in plan]

    out = ROOT / "logs" / "smoke" / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2) + "\n")
    for r in results:
        print(json.dumps(r))
    print(f"\nspent about ${client.spend.spent_usd:.4f} at listed prices; results in {out}")
    return 0 if all(r["ok"] for r in results) else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
