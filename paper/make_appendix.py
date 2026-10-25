"""Appendix prompts and transcripts, copied verbatim from logs/ into paper/tables/appendix_*.tex."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLES = Path(__file__).parent / "tables"
ESCAPES = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
           "~": r"\textasciitilde{}", "^": r"\textasciicircum{}", "≥": r"$\geq$", "≤": r"$\leq$", "→": r"$\to$",
           "−": "-", "’": "'", "“": "``", "”": "''", "—": "--", "–": "-", "δ": r"$\delta$", "≈": r"$\approx$"}  # fmt: skip


def tex(text: str) -> str:
    """`text` with LaTeX specials escaped and line breaks kept."""
    out = "".join(ESCAPES.get(ch, ch) for ch in text)
    return out.replace("\n\n", "\n\n\\smallskip\n").replace("\n", "\\newline\n").replace("\\newline\n\\smallskip\\newline\n", "\n\n\\smallskip\n")


def session_dir(run: str, cell: str, seed: int) -> Path:
    return next(ROOT.glob(f"logs/{run}/*{cell}*/*seed{seed}"))


def call(run: str, cell: str, seed: int, phase: str, round_number: int, firm: str) -> list[dict]:
    """The prompt messages of the first attempt of one call."""
    for line in (session_dir(run, cell, seed) / "calls.jsonl").open():
        row = json.loads(line)
        if row["phase"] == phase and row["round"] == round_number and row["firm_id"] == firm and row["attempt"] == 1:
            return json.loads(row["prompt"])
    raise LookupError((run, cell, seed, phase, round_number, firm))


def events(run: str, cell: str, seed: int, name: str) -> list[dict]:
    return [json.loads(line) for line in (session_dir(run, cell, seed) / name).open()]


def box(title: str, body: str) -> str:
    return f"\\begin{{logbox}}{{{title}}}\n{body}\n\\end{{logbox}}\n"


def prompts() -> str:
    b0 = call("baseline_no_channel", "base-deepseek", 996009, "bid", 3, "A")
    c1 = call("channel_c1", "c1-deepseek", 996009, "bid", 3, "A")
    message = call("channel_c1", "c1-deepseek", 996009, "message", 1, "A")
    ws = call("notes_deepseek", "__ws", 996000, "reflect", 2, "A")
    system_ws = ws[0]["content"]
    parts = [
        box("System prompt template (shown for B0, \\DS, firm A)", tex(b0[0]["content"])),
        box("Paragraph added in C1", tex(c1[0]["content"].split("\n\n")[-1])),
        box("Paragraph added in M1 and M2 (identical in both)", tex(system_ws.split("\n\n")[-1])),
        box("Bid request, C1, round 3 (\\DS, seed 996009, firm A)", tex(c1[-1]["content"])),
        box("Communication step, C1, after round 1 (same session)", tex(message[-1]["content"])),
        box("Reflection step, M2, after round 2 (\\DS, seed 996000, firm A)", tex(ws[-1]["content"])),
    ]
    return "\n".join(parts)


def messages(run: str, cell: str, seed: int, rounds: range) -> str:
    rows = [e for e in events(run, cell, seed, "messages.jsonl") if e["op"] == "write" and e["round"] in rounds]
    return "\n\n".join(f"\\textbf{{After round {e['round']}, firm {e['firm_id']}:}} {tex(e['text'])}" for e in rows)


def notes(run: str, cell: str, seed: int, round_number: int, firms: str) -> str:
    rows = [e for e in events(run, cell, seed, "workspace.jsonl") if e["op"] == "write" and e["round"] == round_number]
    rows = sorted((e for e in rows if e["firm_id"] in firms), key=lambda e: firms.index(e["firm_id"]))
    return "\n\n".join(f"\\textbf{{Firm {e['firm_id']}, note after round {e['round']}:}} {tex(e['text'])}" for e in rows)


def transcripts() -> str:
    parts = [
        box("C1, \\DS, seed 996009, rounds 1--3: an alternation scheme with a punishment threat",
            messages("channel_c1", "c1-deepseek", 996009, range(1, 4))),
        box("C1, \\LU, seed 996004, rounds 9--12: identical bids at 99.99, the tie-break as allocator",
            messages("channel_c1", "c1-luna", 996004, range(9, 13))),
        box("M2, \\DS, seed 996000, round 1: B writes a plan; A reads it and computes a best response",
            notes("notes_deepseek", "__ws", 996000, 1, "BA")),
        box("M2, \\DS, seed 996001, round 3: A finds B's tie-shading rule in the shared notes",
            notes("notes_deepseek", "__ws", 996001, 3, "BA")),
        box("M1, \\DS, seed 996000, round 1: private notes weigh collusion and reject it",
            notes("notes_deepseek", "__pn", 996000, 1, "B")),
        box("M2, \\LU, seed 996000, round 1: notes record the round and do not mention the rival's notes",
            notes("notes_luna", "__ws", 996000, 1, "AB")),
    ]  # fmt: skip
    return "\n".join(parts)


if __name__ == "__main__":
    TABLES.mkdir(exist_ok=True)
    (TABLES / "appendix_prompts.tex").write_text(prompts())
    (TABLES / "appendix_logs.tex").write_text(transcripts())
