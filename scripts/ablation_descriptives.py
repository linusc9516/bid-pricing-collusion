"""Declared descriptives of channel_ablations and notice_checks (configs/analysis.yaml, `descriptive`), no tests.

Writes results/channel_ablations/declared_descriptives.csv and results/notice_checks/declared_descriptives.csv (one
row per session) and results/notice_checks/first_proposer.csv (N2: which model proposes first and which accepts).
"""
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
NUMBER = re.compile(r"\d")
NUMBER_WORDS = re.compile(
    r"\b(zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
    r"seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)\b", re.IGNORECASE)
REBID = re.compile(r"rebid|re-bid|bafo|best and final", re.IGNORECASE)


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open()] if path.exists() else []


def agreement(judged: pd.DataFrame) -> pd.Series:
    """Per session, True when one firm proposes and another firm proposes or accepts, in any steps (N = 2)."""
    firm = judged.groupby(["session_id", "firm_id"])[["proposes_coordination", "accepts_coordination"]].any()
    out = {}
    for sid, g in firm.groupby(level=0):
        g = g.droplevel(0)
        out[sid] = any(g.loc[f, "proposes_coordination"] and (g.drop(f)["proposes_coordination"] | g.drop(f)["accepts_coordination"]).any()
                       for f in g.index)
    return pd.Series(out, name="agreement")


def judged_steps(run: str) -> pd.DataFrame:
    j = pd.read_csv(ROOT / f"results/{run}/messages_judge.csv")
    j = j[j["parse_ok"].astype(bool)]
    for c in ("proposes_coordination", "accepts_coordination"):
        j[c] = j[c].astype(bool)
    return j


def session_rows(run: str) -> pd.DataFrame:
    rows = []
    for d in sorted((ROOT / "logs" / run).glob("*/*")):
        if not (d / "session.json").exists():
            continue
        msgs = [m for m in read_jsonl(d / "messages.jsonl") if m.get("op") == "write"]
        bids = pd.DataFrame(read_jsonl(d / "bids.jsonl"))
        delivered = [m.get("text") or "" for m in msgs]
        written = [m.get("written") or m.get("text") or "" for m in msgs]
        rounds = bids.groupby("round").agg(tied=("tied", "any"), rebid=("rebid", lambda v: v.notna().any()))
        rows.append({
            "session_id": d.name,
            "condition_id": d.parent.name,
            "seed": int(d.name.rsplit("seed", 1)[1]),
            "messages": len(msgs),
            "share_messages_with_digit_delivered": sum(bool(NUMBER.search(t)) for t in delivered) / len(msgs) if msgs else None,
            "share_messages_with_digit_written": sum(bool(NUMBER.search(t)) for t in written) / len(msgs) if msgs else None,
            "share_messages_number_word": sum(bool(NUMBER_WORDS.search(t)) for t in delivered) / len(msgs) if msgs else None,
            "share_messages_mention_rebid": sum(bool(REBID.search(t)) for t in delivered) / len(msgs) if msgs else None,
            "rounds": len(rounds),
            "rebid_rounds": int(rounds["rebid"].sum()),
        })
    return pd.DataFrame(rows)


def first_proposer(judged: pd.DataFrame) -> pd.DataFrame:
    """N2 sessions: the model of the firm that proposes first (both if the same round), and whether each model accepts."""
    rows = []
    for (cond, sid), g in judged.groupby(["condition_id", "session_id"]):
        props = g[g["proposes_coordination"]]
        first = props["round"].min() if len(props) else None
        firsts = sorted(set(props.loc[props["round"] == first, "model"])) if first is not None else []
        rows.append(dict(condition_id=cond, session_id=sid, first_proposal_round=first, first_proposer=" and ".join(firsts) or "none",
                         **{f"{m}_accepts": bool(g.loc[g["model"] == m, "accepts_coordination"].any()) for m in sorted(g["model"].unique())},
                         **{f"{m}_proposes": bool(g.loc[g["model"] == m, "proposes_coordination"].any()) for m in sorted(g["model"].unique())}))
    return pd.DataFrame(rows)


def main() -> None:
    for run in ("channel_ablations", "notice_checks"):
        s = session_rows(run)
        j = judged_steps(run)
        s = s.merge(agreement(j).rename_axis("session_id").reset_index(), on="session_id", how="left")
        s.loc[s["condition_id"].str.contains("undelivered"), "agreement"] = None  # not defined: no exchange (declared)
        s.to_csv(ROOT / f"results/{run}/declared_descriptives.csv", index=False)
        print(run)
        print(s.groupby("condition_id").agg(
            n=("session_id", "size"), agreement=("agreement", "mean"), digit_written=("share_messages_with_digit_written", "mean"),
            digit_delivered=("share_messages_with_digit_delivered", "mean"), number_word=("share_messages_number_word", "mean"),
            rebid_mention=("share_messages_mention_rebid", "mean"), rebid_rounds=("rebid_rounds", "sum"), rounds=("rounds", "sum"),
        ).round(3).to_string())
        print("judged steps by condition and model:", j.groupby(["condition_id", "model"]).size().to_dict())
    fp = first_proposer(judged_steps("notice_checks").query("condition_id.str.contains('deepseek-luna')", engine="python"))
    fp.to_csv(ROOT / "results/notice_checks/first_proposer.csv", index=False)
    print(fp.to_string())


if __name__ == "__main__":
    main()
