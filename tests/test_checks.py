"""Log checker: clean runs pass, and each kind of corruption is caught by the check that should catch it."""

import asyncio
import importlib.util
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from test_llm import FakeOpenAI, completion

from bidrig.checks import (
    CHECKS,
    COST_LINE,
    REBID_NOTICE,
    SessionLog,
    check_run,
    load_logs,
)
from bidrig.prompts import TIE_RULE_SENTENCES
from bidrig.runner import prepare, run_plan

CONFIGS = Path(__file__).parents[1] / "configs"
HOSTS = {"inference-net": "InferenceNet", "crusoe": "Crusoe", None: "Alibaba"}


def responder(bid_for: Callable[[str, float], float]) -> Callable[[dict[str, Any]], Any]:
    """A fake model: reads its cost and prompt, answers with `bid_for(user_text, cost)` from the host it was routed to."""

    def respond(kwargs: dict[str, Any]) -> Any:
        only = kwargs["extra_body"].get("provider", {"only": [None]})["only"][0]
        user = kwargs["messages"][1]["content"]
        cost = float(COST_LINE.search(user).group(1))
        return completion({"reasoning": "Because.", "bid": bid_for(user, cost)}, provider=HOSTS[only])

    return respond


def play(log_dir: Path, bid_for: Callable[[str, float], float], config_name: str = "pilot_tiny.yaml") -> Path:
    """Run a config through the real runner against a fake client; returns the run directory."""
    config, models, plan = prepare(CONFIGS / config_name)
    fake = FakeOpenAI(fn=responder(bid_for))
    result = asyncio.run(run_plan(plan, config, models, log_dir, lambda: fake))
    assert not result.failed
    return log_dir / plan[0].meta.run_id


@pytest.fixture(scope="module")
def normal_run(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return play(tmp_path_factory.mktemp("normal"), lambda user, cost: min(cost + 25, 100))


@pytest.fixture(scope="module")
def tie_run(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Everyone bids 50, so every round ties; a rebid is cost plus 10."""
    return play(tmp_path_factory.mktemp("ties"), lambda user, cost: cost + 10 if REBID_NOTICE.search(user) else 50.0)


def fresh(run: Path, tmp_path: Path) -> Path:
    return Path(shutil.copytree(run, tmp_path / run.name))


def report_for(run: Path, **kwargs: Any) -> Any:
    logs, _ = load_logs(run, include_incomplete=kwargs.pop("include_incomplete", False))
    return check_run(logs, **kwargs)


def rewrite(path: Path, change: Callable[[dict[str, Any]], None]) -> None:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    for row in rows:
        change(row)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def edit_messages(call: dict[str, Any], change: Callable[[list[dict[str, str]]], None]) -> None:
    messages = json.loads(call["prompt"])
    change(messages)
    call["prompt"] = json.dumps(messages)


def pick(run: Path, rule: str | None = None, window: int | None = None, model: str | None = None, tie: bool = False) -> SessionLog:
    logs, _ = load_logs(run, include_incomplete=True)
    for log in logs:
        meta = log.meta
        if (rule is None or meta.tie_break_rule == rule) and meta.history_window == window and (model is None or meta.lineup[0].model == model):
            return log
    raise LookupError((rule, window, model))


# --- clean runs ---


def test_clean_run_passes_every_check(normal_run: Path) -> None:
    report = report_for(normal_run)
    assert report.passed, report.findings[:3]
    assert report.sessions == 18 and report.calls == 162
    assert all(report.items[name] for name in CHECKS if name != "rebid_notice") and report.items["rebid_notice"] == 162
    assert dict(report.caps) == {500: 162}
    assert {k: v for k, v in report.providers.items()} == {("deepseek", "InferenceNet"): 54, ("gpt-oss", "Crusoe"): 54, ("qwen", "Alibaba"): 54}


def test_tie_run_passes_with_rebids_and_rotation(tie_run: Path) -> None:
    report = report_for(tie_run)
    assert report.passed, report.findings[:3]
    logs, _ = load_logs(tie_run)
    rebid_calls = [(log.meta.tie_break_rule, c) for log in logs for c in log.calls if c.phase == "rebid"]
    assert rebid_calls and {rule for rule, _ in rebid_calls} == {"bafo"}
    assert all(r.tied for log in logs for r in log.rows)
    least_wins = [log for log in logs if log.meta.tie_break_rule == "least_wins" and log.meta.history_window is None]
    assert least_wins and all(len({r.firm_id for r in log.rows if r.is_winner}) == 3 for log in least_wins)


def test_zero_bids_and_losses_are_not_mistaken_for_missing(tmp_path: Path) -> None:
    run = play(tmp_path, lambda user, cost: cost + 10 if REBID_NOTICE.search(user) else 0.0)
    report = report_for(run)
    assert report.passed, report.findings[:3]
    logs, _ = load_logs(run)
    assert any(r.bid == 0.0 and r.is_winner and r.profit < 0 for log in logs for r in log.rows)


def test_scripted_sessions_pass_without_calls(tmp_path: Path) -> None:
    config, models, plan = prepare(CONFIGS / "sanity_tiebreak.yaml", "scripted")
    asyncio.run(run_plan(plan, config, models, tmp_path))
    report = report_for(tmp_path / "scripted")
    assert report.passed, report.findings[:3]
    assert report.sessions == 108 and report.calls == 0 and not report.items["user_prompt"]


# --- corruption is caught ---


def tamper_off_by_one(run: Path) -> None:
    log = pick(run, window=None, model="deepseek")
    extra = "\nRound 2: bids A (you) 1.00, B 2.00, C 3.00. You won at 1.00. Your cost was 5.00 and your profit 1.00."
    rewrite(log.path / "calls.jsonl", lambda c: edit_messages(c, lambda m: m.__setitem__(1, {**m[1], "content": m[1]["content"] + extra}))
            if (c["round"], c["firm_id"], c["phase"]) == (2, "A", "bid") else None)


def tamper_leak(run: Path) -> None:
    log = pick(run, window=None, model="deepseek")
    other = next(r.cost for r in log.rows if r.round == 3 and r.firm_id == "B")
    rewrite(log.path / "calls.jsonl", lambda c: edit_messages(c, lambda m: m.__setitem__(1, {**m[1], "content": m[1]["content"] + f"\nFirm B's cost was {other:.2f}."}))
            if (c["round"], c["firm_id"]) == (3, "A") else None)


def tamper_wrong_rule(run: Path) -> None:
    log = pick(run, rule="random", window=None, model="gpt-oss")
    swap = lambda m: m.__setitem__(0, {**m[0], "content": m[0]["content"].replace(TIE_RULE_SENTENCES["random"], TIE_RULE_SENTENCES["least_wins"])})
    rewrite(log.path / "calls.jsonl", lambda c: edit_messages(c, swap))


def tamper_control_history(run: Path) -> None:
    log = pick(run, window=0, model="qwen")
    extra = "\nRound 1: bids A (you) 40.00, B 50.00, C 60.00. You won at 40.00. Your cost was 10.00 and your profit 30.00."
    rewrite(log.path / "calls.jsonl", lambda c: edit_messages(c, lambda m: m.__setitem__(1, {**m[1], "content": m[1]["content"] + extra}))
            if c["round"] == 2 else None)


def tamper_cost_line(run: Path) -> None:
    log = pick(run, window=None, model="qwen")
    cost = next(r.cost for r in log.rows if r.round == 2 and r.firm_id == "A")
    rewrite(log.path / "calls.jsonl", lambda c: edit_messages(c, lambda m: m.__setitem__(1, {**m[1], "content": m[1]["content"].replace(f"is {cost:.2f}.", f"is {cost + 1:.2f}.")}))
            if (c["round"], c["firm_id"]) == (2, "A") else None)


def tamper_system_prompt(run: Path) -> None:
    log = pick(run, window=None, model="gpt-oss")
    rewrite(log.path / "calls.jsonl", lambda c: edit_messages(c, lambda m: m.__setitem__(0, {**m[0], "content": m[0]["content"].replace("maximise your firm's", "maximise your own")})))


def tamper_bid(run: Path) -> None:
    log = pick(run, window=None, model="deepseek")
    rewrite(log.path / "bids.jsonl", lambda r: r.update(bid=r["bid"] + 0.5) if (r["round"], r["firm_id"]) == (2, "C") and not r["is_winner"] else None)


def tamper_provider(run: Path) -> None:
    log = pick(run, window=None, model="deepseek")
    rewrite(log.path / "calls.jsonl", lambda c: c.update(provider="Morph") if c["round"] == 1 else None)


def tamper_cost(run: Path) -> None:
    log = pick(run, window=None, model="qwen")
    rewrite(log.path / "bids.jsonl", lambda r: r.update(cost=r["cost"] + 0.01) if (r["round"], r["firm_id"]) == (1, "B") else None)


def tamper_tokens(run: Path) -> None:
    log = pick(run, window=None, model="qwen")
    rewrite(log.path / "calls.jsonl", lambda c: c.update(completion_tokens=9999) if c["round"] == 1 else None)


def tamper_status(run: Path) -> None:
    log = pick(run, window=None, model="qwen")
    meta = json.loads((log.path / "session.json").read_text())
    (log.path / "session.json").write_text(json.dumps({**meta, "status": "running"}))


def tamper_error_log(run: Path) -> None:
    log = pick(run, window=None, model="qwen")
    meta = json.loads((log.path / "session.json").read_text())
    (log.path / "session.json").write_text(json.dumps({**meta, "provider_errors": ["x"] * 25}))


def tamper_retry(run: Path) -> None:
    log = pick(run, window=None, model="qwen")
    rewrite(log.path / "calls.jsonl", lambda c: c.update(attempt=2) if (c["round"], c["firm_id"]) == (1, "A") else None)


def tamper_winner(run: Path) -> None:
    log = pick(run, window=None, model="deepseek")
    def flip(row: dict[str, Any]) -> None:
        if row["round"] == 2:
            row["is_winner"] = row["firm_id"] == "C"
            row["profit"] = round(row["winning_bid"] - row["cost"], 2) if row["firm_id"] == "C" else 0.0
    rewrite(log.path / "bids.jsonl", flip)


@pytest.mark.parametrize(
    ("tamper", "expected"),
    [
        (tamper_off_by_one, {"rounds_shown", "user_prompt"}),
        (tamper_leak, {"leak", "user_prompt"}),
        (tamper_wrong_rule, {"tie_rule_prompt", "system_prompt"}),
        (tamper_control_history, {"rounds_shown", "user_prompt"}),
        (tamper_cost_line, {"cost_line", "user_prompt"}),
        (tamper_system_prompt, {"system_prompt"}),
        (tamper_bid, {"bids_vs_calls"}),
        (tamper_provider, {"provider"}),
        (tamper_cost, {"costs"}),
        (tamper_tokens, {"tokens"}),
        (tamper_retry, {"retry_messages", "bids_vs_calls"}),
        (tamper_error_log, {"structure"}),
        (tamper_winner, {"auction"}),
    ],
)
def test_corruption_is_caught(normal_run: Path, tmp_path: Path, tamper: Callable[[Path], None], expected: set[str]) -> None:
    run = fresh(normal_run, tmp_path)
    tamper(run)
    caught = {f.check for f in report_for(run).findings}
    assert expected <= caught, (tamper.__name__, caught)
    # Editing the bids or costs also makes later history prompts disagree with the log; nothing else should fire.
    knock_on = {"auction", "user_prompt", "bids_vs_calls", "costs", "cost_line", "leak"}
    assert caught <= expected | knock_on, (tamper.__name__, caught)


def test_incomplete_session_is_flagged(normal_run: Path, tmp_path: Path) -> None:
    run = fresh(normal_run, tmp_path)
    tamper_status(run)
    logs, skipped = load_logs(run)
    assert len(logs) == 17 and len(skipped) == 1
    assert {f.check for f in report_for(run, include_incomplete=True).findings} == {"structure"}


def test_missing_rebid_notice_is_caught(tie_run: Path, tmp_path: Path) -> None:
    run = fresh(tie_run, tmp_path)
    log = pick(run, rule="bafo", window=None, model="deepseek")
    strip = lambda m: m.__setitem__(1, {**m[1], "content": REBID_NOTICE.sub("", m[1]["content"])})
    rewrite(log.path / "calls.jsonl", lambda c: edit_messages(c, strip) if c["phase"] == "rebid" else None)
    assert {"rebid_notice", "user_prompt"} <= {f.check for f in report_for(run).findings}


def test_bafo_rebid_that_disagrees_with_its_call_is_caught(tie_run: Path, tmp_path: Path) -> None:
    run = fresh(tie_run, tmp_path)
    log = pick(run, rule="bafo", window=None, model="deepseek")
    rewrite(log.path / "bids.jsonl", lambda r: r.update(rebid=r["rebid"] + 0.5) if r["round"] == 1 and r["rebid"] is not None else None)
    assert "rebid_calls" in {f.check for f in report_for(run).findings}


def test_least_wins_violation_is_caught(tie_run: Path, tmp_path: Path) -> None:
    run = fresh(tie_run, tmp_path)
    log = pick(run, rule="least_wins", window=None, model="deepseek")
    wins = {}
    for r in log.rows:
        if r.round < 3 and r.is_winner:
            wins[r.firm_id] = wins.get(r.firm_id, 0) + 1
    most = max(wins, key=wins.get)
    def flip(row: dict[str, Any]) -> None:
        if row["round"] == 3:
            row["is_winner"] = row["firm_id"] == most
            row["profit"] = round(row["winning_bid"] - row["cost"], 2) if row["firm_id"] == most else 0.0
    rewrite(log.path / "bids.jsonl", flip)
    assert any("fewest wins" in f.detail for f in report_for(run).failures("auction"))


# --- the CLI ---


@pytest.fixture(scope="module")
def cli() -> Any:
    spec = importlib.util.spec_from_file_location("check_logs", Path(__file__).parents[1] / "scripts" / "check_logs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_passes_and_fails_with_exit_codes(cli: Any, normal_run: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([str(normal_run), "--expect-cap", "500"]) == 0
    out = capsys.readouterr().out
    assert "RESULT: PASS" in out and "checked 18 sessions (162 call rows)" in out and "qwen/Alibaba 54" in out
    assert cli.main([str(normal_run), "--expect-cap", "400"]) == 1
    assert "expected 400" in capsys.readouterr().out
    run = fresh(normal_run, tmp_path)
    tamper_leak(run)
    assert cli.main([str(run), "--max-failures", "1"]) == 1
    out = capsys.readouterr().out
    assert "FAIL leak" in out and "RESULT: FAIL" in out


def test_cli_pick_and_show(cli: Any, tie_run: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([str(tie_run), "--pick"]) == 0
    picked = capsys.readouterr().out.splitlines()
    assert {line.split()[0] for line in picked} == {"random", "least_wins", "bafo"} and any("rebid call" in line for line in picked)
    command = next(line for line in picked if "one-shot control" in line and line.startswith("bafo"))
    session_id, round_number, firm = command.split("--show ")[1].split()
    assert cli.main([str(tie_run), "--show", session_id, round_number, firm]) == 0
    out = capsys.readouterr().out
    assert "--- system ---" in out and "No earlier rounds are shown." in out and "--- answer, attempt 1" in out
    assert cli.main([str(tie_run), "--show", "no-such-session", "1", "A"]) == 2
    # An exact id wins even when it is also a substring of its one-shot control's id.
    repeated = next(line for line in picked if line.startswith("bafo") and "repeated" in line).split("--show ")[1].split()[0]
    assert cli.main([str(tie_run), "--show", repeated, "2", "A"]) == 0
    assert f"session {repeated}\n" in capsys.readouterr().out


def test_cli_reports_cutoffs_and_free_text(normal_run: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_logs", Path(__file__).parents[1] / "scripts" / "check_logs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main([str(normal_run)]) == 0
    assert "attempts cut off at the cap: 0 of 162; with hidden thinking text: 162; with free text outside the tool call: 0" in capsys.readouterr().out
