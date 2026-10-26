"""Paper figures and tables from results/ and logs/. Intervals are 95% percentile bootstraps over sessions (10,000 resamples)."""

import json
import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FIGURES = Path(__file__).parent / "figures"
TABLES = Path(__file__).parent / "tables"
MODELS = ("deepseek", "gpt-luna")
NAMES = {"deepseek": "DeepSeek-V4.1-Flash", "gpt-luna": "GPT-6-Luna"}
ARMS = ["B0", "M1", "M2", "C1"]
ARM_NAMES = {"B0": "B0 no channel", "M1": "M1 private notes", "M2": "M2 shared notes", "C1": "C1 open messages"}
ARM_COLORS = {"B0": "#2a78d6", "C1": "#eb6834", "M1": "#1baf7a", "M2": "#c98a00"}
MODEL_COLORS = {"deepseek": "#2a78d6", "gpt-luna": "#eb6834"}
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e6e5e1"
BLOCK = 5
RNG = np.random.default_rng(20261023)

plt.rcParams.update({
    "font.family": "serif", "font.serif": ["Times New Roman", "Nimbus Roman", "DejaVu Serif"], "font.size": 8.5,
    "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "legend.frameon": False, "pdf.fonttype": 42,
})  # fmt: skip


ARM_TEX_COLORS = {"B0": "cB", "M1": "cM1", "M2": "cM2", "C1": "cC"}  # colour names defined in main_acl.tex


def color_arms(tex: str) -> str:
    """`tex` with every arm code (B0, M1, M2, C1, and any \\textsubscript after it) wrapped in its colour."""
    return re.sub(r"(?<![A-Za-z0-9_\\])(B0|M1|M2|C1)(\\textsubscript\{[^}]*\})?(?![A-Za-z0-9_])",
                  lambda m: f"\\textcolor{{{ARM_TEX_COLORS[m.group(1)]}}}{{{m.group(0)}}}", tex)


def write_table(name: str, body: str) -> None:
    """Writes a LaTeX table body to tables/`name`, with the arm codes coloured."""
    (TABLES / name).write_text(color_arms(body))


def boot(values: np.ndarray, n: int = 10_000) -> tuple[float, float, float]:
    """Mean and 95% percentile bootstrap interval of the mean over the rows of `values` (axis 0)."""
    values = np.asarray(values, float)
    draws = RNG.integers(0, len(values), size=(n, len(values)))
    means = values[draws].mean(axis=1)
    return float(values.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def channel_sessions() -> pd.DataFrame:
    """One row per (model, arm, seed) session of the four arms, with the session metrics."""
    frames = [pd.read_csv(ROOT / f"results/{run}/channel_sessions.csv") for run in ("channel_c1", "notes_deepseek")]
    return pd.concat(frames).drop_duplicates(["model", "arm", "seed"]).reset_index(drop=True)


def block_index(session_id: str, condition_id: str, block: int = BLOCK) -> np.ndarray:
    """Collusion index of each `block`-round block of one session: block means of the winning bid against the benchmark price."""
    path = next(ROOT.glob(f"logs/*/{condition_id}/{session_id}/bids.jsonl"))
    rows = pd.DataFrame(json.loads(line) for line in path.open())
    rounds = rows.groupby("round").agg(winning_bid=("winning_bid", "first"), min_cost=("cost", "min"))
    rounds["benchmark"] = (rounds["min_cost"] + 100) / 2  # b*(c) = c + (c_max - c) / n at n = 2, c_max = 100
    rounds["block"] = (rounds.index - 1) // block
    means = rounds.groupby("block")[["winning_bid", "benchmark"]].mean()
    return ((means["winning_bid"] - means["benchmark"]) / (100 - means["benchmark"])).to_numpy()


def figure_rounds(table: pd.DataFrame) -> None:
    """Block index by model and arm: fig_rounds_col.pdf (panels stacked, one column)."""
    x = np.arange(1, 50 // BLOCK + 1) * BLOCK
    stats = {}
    for model in MODELS:
        for arm in ARMS:
            cell = table[(table["model"] == model) & (table["arm"] == arm)]
            blocks = np.vstack([block_index(r.session_id, r.condition_id) for r in cell.itertuples()])
            stats[model, arm] = np.array([boot(blocks[:, k]) for k in range(blocks.shape[1])])
    for name, shape, size, ncol in (("fig_rounds_col", (2, 1), (3.35, 3.9), 2),):
        fig, axes = plt.subplots(*shape, figsize=size, sharey=True)
        for ax, model in zip(axes, MODELS, strict=True):
            for arm in ARMS:
                st = stats[model, arm]
                ax.fill_between(x, st[:, 1], st[:, 2], color=ARM_COLORS[arm], alpha=0.15, lw=0)
                ax.plot(x, st[:, 0], color=ARM_COLORS[arm], lw=1.6, marker="o", ms=3.2, label=ARM_NAMES[arm])
            ax.axhline(0, color=MUTED, lw=0.7, ls=(0, (3, 3)))
            ax.set_title(NAMES[model], fontsize=8.5, color=INK, fontfamily="monospace")
            ax.set_xticks(x, [f"{k - BLOCK + 1}-{k}" for k in x], fontsize=6.5, rotation=0)
            ax.set_xlabel("Rounds")
        axes[0].set_ylabel("Collusion index\n(0 = equilibrium, 1 = reserve)")
        if shape == (2, 1):
            axes[1].set_ylabel("Collusion index\n(0 = equilibrium, 1 = reserve)")
        handles, labels = axes[0].get_legend_handles_labels()
        fig.legend(handles, labels, loc="upper center", ncol=ncol, bbox_to_anchor=(0.5, 1.04 if ncol == 4 else 1.01), fontsize=7.5)
        fig.tight_layout(rect=(0, 0, 1, 0.93 if ncol == 4 else 0.94))
        fig.savefig(FIGURES / f"{name}.pdf", bbox_inches="tight")
        plt.close(fig)


def figure_contrasts(column: bool = False) -> None:
    """Forest plot of the declared channel and notes contrasts; `column` stacks the two models for a one-column figure."""
    rows = []
    for run in ("notes_luna", "channel_c1", "notes_deepseek"):
        tests = pd.read_csv(ROOT / f"results/{run}/channel_tests.csv")
        rows.append(tests[(tests["family"] == "confirmatory") | (tests["family"] == "secondary_contrast")])
    tests = pd.concat(rows).drop_duplicates(["model", "contrast"])
    tests = tests[tests["outcome"] == "collusion_index"]
    order = ["M1 - B0", "M2 - B0", "M2 - M1", "C1 - B0", "C1 - M1", "C1 - M2"]
    fig, axes = plt.subplots(2, 1, figsize=(3.35, 2.6), sharex=True) if column else plt.subplots(1, 2, figsize=(6.4, 2.2), sharex=True)
    for ax, model in zip(axes, MODELS, strict=True):
        cell = tests[tests["model"] == model].set_index("contrast").reindex([c for c in order if c in set(tests.loc[tests["model"] == model, "contrast"])])
        y = np.arange(len(cell))[::-1]
        for yi, (contrast, r) in zip(y, cell.iterrows(), strict=True):
            confirmatory = r["family"] == "confirmatory"
            color = MODEL_COLORS[model] if confirmatory else "#a3a29b"
            ax.plot([r["ci_low"], r["ci_high"]], [yi, yi], color=color, lw=1.6, solid_capstyle="round")
            ax.plot(r["mean"], yi, "o", ms=5.5, color=color, mec="white", mew=1)
            star = "*" if confirmatory and r["supported"] is True else ""
            ax.annotate(f"{signed(r['mean'])}{star}", (r["ci_high"], yi), xytext=(4, -2.5), textcoords="offset points", fontsize=7, color=INK)
        tags = [f" ({cell.loc[c, 'test_id'].split('_')[0]})" if cell.loc[c, "family"] == "confirmatory" else " (sec.)" for c in cell.index]
        ax.set_yticks(y, [c.replace(" - ", " $-$ ") + tag for c, tag in zip(cell.index, tags, strict=True)], fontsize=7.5)
        ax.axvline(0, color=MUTED, lw=0.7, ls=(0, (3, 3)))
        ax.set_title(NAMES[model], fontsize=8.5, color=INK, fontfamily="monospace")
        ax.set_xlim(-0.3, 1.25)
        ax.grid(axis="y", visible=False)
        ax.set_ylim(-0.6, len(y) - 0.4)
    for ax in axes[-1:] if column else axes:
        ax.set_xlabel("Paired difference in collusion index")
    fig.tight_layout()
    fig.savefig(FIGURES / ("fig_contrasts_col.pdf" if column else "fig_contrasts.pdf"), bbox_inches="tight")
    plt.close(fig)


def figure_placebo() -> None:
    table = pd.read_csv(ROOT / "results/placebo_replay/placebo_sessions.csv")
    fig, axes = plt.subplots(1, 2, figsize=(3.9, 2.3), sharey=True)
    for ax, model in zip(axes, MODELS, strict=True):
        cell = table[table["model"] == model].pivot(index="seed", columns="level", values="markup_ratio")[["low", "high"]]
        for _, row in cell.iterrows():
            ax.plot([0, 1], row.to_numpy(), color="#d3d2cc", lw=0.7, zorder=1)
        for x, level in enumerate(("low", "high")):
            mean, lo, hi = boot(cell[level].to_numpy())
            ax.errorbar(x, mean, yerr=[[mean - lo], [hi - mean]], fmt="o", ms=6, color=MODEL_COLORS[model], mec="white",
                        mew=1, capsize=3, lw=1.6, zorder=3)  # fmt: skip
            ax.annotate(f"{mean:.2f}", (x, hi), xytext=(0, 4), textcoords="offset points", ha="center", fontsize=7.5, color=INK)
        ax.axhline(1, color=MUTED, lw=0.7, ls=(0, (3, 3)))
        ax.set_xticks([0, 1], ["low replay\n(mean bid 72.8)", "high replay\n(mean bid 87.5)"], fontsize=7)
        ax.set_xlim(-0.4, 1.4)
        ax.set_title(NAMES[model], fontsize=8.5, color=INK, fontfamily="monospace")
        ax.grid(axis="x", visible=False)
    axes[0].set_ylabel("Markup ratio of the model firm\n(1 = equilibrium markup)")
    fig.tight_layout()
    fig.savefig(FIGURES / "fig_placebo.pdf", bbox_inches="tight")


LABELS = {"proposes_coordination": "proposes\ncoordination", "accepts_coordination": "accepts\ncoordination",
          "threatens_rival": "threatens\nrival", "reveals_own_cost": "reveals\nown cost"}  # fmt: skip


def figure_conduct() -> None:
    """Conduct labels by model (top) and the share of sessions with a proposal by each round (bottom), one column."""
    judged = pd.read_csv(ROOT / "results/channel_c1/messages_judge.csv")
    judged = judged[judged["parse_ok"].astype(bool)] if "parse_ok" in judged else judged
    fig, (left, right) = plt.subplots(2, 1, figsize=(3.35, 4.4))
    width = 0.38
    for k, model in enumerate(MODELS):
        cell = judged[judged["model"] == model]
        per_session = cell.groupby("session_id")[list(LABELS)].mean()
        stats = np.array([boot(per_session[label].to_numpy()) for label in LABELS]) * 100
        x = np.arange(len(LABELS)) + (k - 0.5) * width
        left.bar(x, stats[:, 0], width * 0.92, color=MODEL_COLORS[model], label=NAMES[model])
        left.errorbar(x, stats[:, 0], yerr=[stats[:, 0] - stats[:, 1], stats[:, 2] - stats[:, 0]], fmt="none", ecolor=INK, capsize=2, lw=0.8)
        first = cell[cell["proposes_coordination"].astype(bool)].groupby("session_id")["round"].min()
        n_sessions = cell["session_id"].nunique()
        rounds = np.arange(1, 50)
        share = [(first <= r).sum() / n_sessions * 100 for r in rounds]
        right.step(rounds, share, where="post", color=MODEL_COLORS[model], lw=1.8, label=NAMES[model])
    left.set_xticks(np.arange(len(LABELS)), list(LABELS.values()), fontsize=7)
    left.set_ylabel("% of judged message steps\n(mean over sessions)")
    left.set_ylim(0, 105)
    left.grid(axis="x", visible=False)
    left.legend(fontsize=7, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2)
    right.set_xlabel("Round")
    right.set_ylabel("% of sessions with a proposal\nby this round")
    right.set_ylim(0, 105)
    right.set_xlim(1, 49)
    fig.tight_layout()
    fig.savefig(FIGURES / "fig_conduct_col.pdf", bbox_inches="tight")


LINEUP_ROWS = [  # (run, model column, contrast, row label); first panel of figure_extensions
    ("channel_c1", "deepseek", "C1 - B0", "DeepSeek (H5)"),
    ("channel_c1", "gpt-luna", "C1 - B0", "Luna (H5)"),
    ("luna_long", "gpt-luna", "C1 - B0", "Luna, 100 rounds, new seeds (H19)"),
    ("luna_replication", "gpt-luna", "C1 - B0", "Luna, 24 new seeds (H25)"),
    ("channel_extensions", "haiku", "C1 - B0", "Haiku (H13)"),
    ("channel_extensions", "deepseek x gpt-luna", "C1 - B0", "DeepSeek x Luna (H16)"),
    ("channel_extensions", "deepseek x haiku", "C1 - B0", "DeepSeek x Haiku (H17)"),
    ("channel_extensions", "deepseek n3", "C1 - B0", "DeepSeek, three firms (H18)"),
]
RESTRICTION_ROWS = [
    ("channel_extensions", "deepseek", "C1cap - C1", "50-character cap $-$ C1 (H14)"),
    ("channel_extensions", "deepseek", "C1notice - C1", "oversight notice $-$ C1 (H15)"),
    ("notice_checks", "deepseek", "C1notice - C1", "notice, new seeds $-$ C1 (H27)"),
    ("notice_checks", "deepseek x gpt-luna", "C1notice - C1", "notice, DeepSeek x Luna $-$ C1 (H28)"),
    ("channel_extensions", "deepseek", "C1cap - B0", "50-character cap $-$ B0 (sec.)"),
    ("channel_extensions", "deepseek", "C1notice - B0", "oversight notice $-$ B0 (sec.)"),
]


def figure_extensions(column: bool = False) -> None:
    """Forest plot: C1 - B0 by lineup and the restrictions on DeepSeek's channel; stacked for one column, side by side for the page width."""
    tests = {run: pd.read_csv(ROOT / f"results/{run}/channel_tests.csv") for run in ("channel_c1", "channel_extensions", "luna_long", "luna_replication", "notice_checks")}
    if column:
        fig, axes = plt.subplots(2, 1, figsize=(3.35, 3.05), sharex=True, gridspec_kw={"height_ratios": [len(LINEUP_ROWS), len(RESTRICTION_ROWS)]})
    else:
        fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.45))
    size = 7 if column else 8
    for ax, rows, title in zip(axes, (LINEUP_ROWS, RESTRICTION_ROWS), ("Open channel, C1 $-$ B0, by lineup", "Restrictions on the channel"), strict=True):
        y = np.arange(len(rows))[::-1]
        for yi, (run, model, contrast, label) in zip(y, rows, strict=True):
            t = tests[run]
            r = t[(t["model"] == model) & (t["contrast"] == contrast) & (t["outcome"] == "collusion_index")].iloc[0]
            confirmatory = r["family"] == "confirmatory"
            color = ARM_COLORS["C1"] if confirmatory else "#a3a29b"
            ax.plot([r["ci_low"], r["ci_high"]], [yi, yi], color=color, lw=1.6, solid_capstyle="round")
            ax.plot(r["mean"], yi, "o", ms=5.5, color=color, mec="white", mew=1)
            star = "*" if confirmatory and r["supported"] is True else ""
            ax.annotate(f"{signed(r['mean'])}{star}", (max(r["ci_high"], -0.9), yi), xytext=(4, -2.5), textcoords="offset points", fontsize=size, color=INK)
        ax.set_yticks(y, [row[3] for row in rows], fontsize=size)
        ax.axvline(0, color=MUTED, lw=0.7, ls=(0, (3, 3)))
        ax.set_title(title, fontsize=8.5, color=INK, loc="left")
        ax.set_xlim(-1.15, 1.35)
        ax.grid(axis="y", visible=False)
        ax.set_ylim(-0.6, len(y) - 0.4)
    for ax in axes[-1:] if column else axes:
        ax.set_xlabel("Paired difference in collusion index")
    fig.tight_layout()
    fig.savefig(FIGURES / ("fig_extensions_col.pdf" if column else "fig_extensions.pdf"), bbox_inches="tight")
    plt.close(fig)


EXTENSION_CELLS = [  # (run, model column, arm, cell label, arm label) for table_extensions
    ("channel_extensions", "haiku", "B0", "Haiku", "B0"),
    ("channel_extensions", "haiku", "C1", "", "C1"),
    ("channel_extensions", "deepseek x gpt-luna", "B0", "DeepSeek x Luna", "B0"),
    ("channel_extensions", "deepseek x gpt-luna", "C1", "", "C1"),
    ("channel_extensions", "deepseek x haiku", "B0", "DeepSeek x Haiku", "B0"),
    ("channel_extensions", "deepseek x haiku", "C1", "", "C1"),
    ("channel_extensions", "deepseek n3", "B0", "DeepSeek, $N = 3$", "B0"),
    ("channel_extensions", "deepseek n3", "C1", "", "C1"),
    ("channel_extensions", "deepseek", "C1cap", "DeepSeek", "C1, 50-char cap"),
    ("channel_extensions", "deepseek", "C1notice", "", "C1, oversight notice"),
    ("luna_long", "gpt-luna", "B0", "Luna, 100 rounds", "B0"),
    ("luna_long", "gpt-luna", "C1", "", "C1"),
    ("luna_replication", "gpt-luna", "B0", "Luna, 24 new seeds", "B0"),
    ("luna_replication", "gpt-luna", "C1", "", "C1"),
]


def table_extensions() -> None:
    """LaTeX body of the extensions table, one row per cell and arm, in the summary table's columns."""
    sessions = {run: pd.read_csv(ROOT / f"results/{run}/channel_sessions.csv") for run in ("channel_extensions", "luna_long", "luna_replication")}
    lines = []
    for k, (run, model, arm, cell_label, arm_label) in enumerate(EXTENSION_CELLS):
        cell = sessions[run][(sessions[run]["model"] == model) & (sessions[run]["arm"] == arm)]
        assert len(cell) == (24 if run == "luna_replication" else 12), (run, model, arm, len(cell))
        if k and cell_label:
            lines.append(r"\midrule")
        lines.append(" & ".join([
            cell_label, arm_label,
            fmt_ci(cell["collusion_index"].to_numpy()), fmt_ci(cell["markup_ratio"].to_numpy()),
            fmt_ci(cell["joint_profit_ratio"].to_numpy()), fmt_ci(cell["lowest_cost_win_share"].to_numpy(), 100, 0),
            fmt_ci(cell["tie_rate"].to_numpy(), 100, 0),
        ]) + r" \\")  # fmt: skip
    write_table("extensions.tex", "\n".join(lines) + "\n")


HYPOTHESES = [  # (id, short name, run, test file, contrast as printed); one table row per model or cell tested
    ("H1", "History lowers price", "baseline_no_channel", "baseline_tests", "history $-$ one-shot, $\\Delta I$"),
    ("H2", "One-shot bids at equilibrium", "baseline_no_channel", "baseline_tests", "one-shot $I$ within $\\pm 0.05$"),
    ("H3", "Private notes change price", "notes_luna", "channel_tests", "M1 $-$ B0"),
    ("H4", "Sharing notes raises price", "notes_luna", "channel_tests", "M2 $-$ M1"),
    ("H5", "Messages raise price", "channel_c1", "channel_tests", "C1 $-$ B0"),
    ("H6", "Displayed bids move bids", "placebo_replay", "placebo_tests", "high $-$ low replay, markup"),
    ("H9", "Shared notes raise price", "notes_deepseek", "channel_tests", "M2 $-$ B0"),
    ("H10", "Private notes change price", "notes_deepseek", "channel_tests", "M1 $-$ B0"),
    ("H11", "Displayed numbers matter", "narrow_costs", "channel_tests", "rescaled $-$ B0"),
    ("H12", "Larger collusion gain raises price", "narrow_costs", "channel_tests", "reserve 100 $-$ B0"),
    ("H13", "Third model: messages raise price", "channel_extensions", "channel_tests", "C1 $-$ B0"),
    ("H14", "Length cap lowers price", "channel_extensions", "channel_tests", "50-char cap $-$ C1"),
    ("H15", "Oversight notice lowers price", "channel_extensions", "channel_tests", "notice $-$ C1"),
    ("H16", "Mixed lineup: messages raise price", "channel_extensions", "channel_tests", "C1 $-$ B0"),
    ("H17", "Mixed lineup: messages raise price", "channel_extensions", "channel_tests", "C1 $-$ B0"),
    ("H18", "Three firms: messages raise price", "channel_extensions", "channel_tests", "C1 $-$ B0"),
    ("H19", "Replication at 100 rounds", "luna_long", "channel_tests", "C1 $-$ B0"),
    ("H20", "Rebid on ties lowers price", "channel_ablations", "channel_tests", "BAFO $-$ C1"),
    ("H21", "Hiding losing bids lowers price", "channel_ablations", "channel_tests", "winner only $-$ C1"),
    ("H22", "Reading the rival is needed", "channel_ablations", "channel_tests", "undelivered $-$ C1"),
    ("H23", "Digit filter lowers price", "channel_ablations", "channel_tests", "no digits $-$ C1"),
    ("H24", "Channel effect survives rewording", "channel_ablations", "channel_tests", "C1 $-$ B0, reworded"),
    ("H25", "Replication at 50 rounds", "luna_replication", "channel_tests", "C1 $-$ B0, 24 new seeds"),
    ("H27", "Notice replicates on new seeds", "notice_checks", "channel_tests", "notice $-$ C1"),
    ("H28", "Notice in a mixed lineup", "notice_checks", "channel_tests", "notice $-$ C1"),
]
DECLARED_CELLS = {"H20": "DeepSeek", "H21": "DeepSeek", "H22": "DeepSeek", "H23": "DeepSeek", "H24": "DeepSeek",
                  "H25": "Luna", "H27": "DeepSeek", "H28": "DeepSeek x Luna"}  # shown while a run has no results yet
CELL_NAMES = {"deepseek": "DeepSeek", "base-deepseek": "DeepSeek", "gpt-luna": "Luna", "base-luna": "Luna", "haiku": "Haiku",
              "deepseek x gpt-luna": "DeepSeek x Luna", "deepseek x haiku": "DeepSeek x Haiku", "deepseek n3": "DeepSeek, 3 firms"}  # fmt: skip


def table_hypotheses() -> None:
    """LaTeX body of the hypothesis index: one row per declared hypothesis and model or cell, from the result CSVs."""
    lines = []
    for hid, name, run, stem, contrast in HYPOTHESES:
        path = ROOT / f"results/{run}/{stem}.csv"
        if not path.exists():
            lines.append(" & ".join([hid, name, DECLARED_CELLS[hid], contrast, "--", "--", "run in progress"]) + r" \\")
            continue
        tests = pd.read_csv(path)
        if stem == "placebo_tests":
            rows = tests[(tests["family"] == "confirmatory") & (tests["outcome"] == "markup_ratio")].rename(columns={"mean_diff": "mean"})
        else:
            rows = tests[tests["test_id"].str.startswith(f"{hid}_")]
            rows = rows[rows["family"] == "confirmatory"] if "family" in rows else rows
        for k, r in enumerate(rows.itertuples()):
            p = "--" if pd.isna(r.p_holm) else f"{r.p_holm:.3f}" if round(r.p_holm, 3) > 0 else "$<$0.001"
            verdict = "supported" if r.supported in (True, "True") else "not supported"
            lines.append(" & ".join([
                hid if k == 0 else "", name if k == 0 else "", CELL_NAMES.get(r.model, r.model), contrast,
                f"${r.mean:+.3f}$ {{\\scriptsize $[{r.ci_low:+.2f}, {r.ci_high:+.2f}]$}}", p, verdict,
            ]) + r" \\")  # fmt: skip
    write_table("hypotheses.tex", "\n".join(lines) + "\n")


NOTICE_COLOR = "#7a5bc9"
ABLATION_PANELS = [  # (title, rows); rows are (run, model column, contrast, row label) for figure_ablations
    ("Buyer-side levers and channel ablations (DeepSeek)", [
        ("channel_ablations", "deepseek", "C1bafo - C1", "rebid on ties (BAFO) $-$ C1 (H20)"),
        ("channel_ablations", "deepseek", "C1hidden - C1", "winner only announced $-$ C1 (H21)"),
        ("channel_ablations", "deepseek", "C1nodigits - C1", "digits removed $-$ C1 (H23)"),
        ("channel_ablations", "deepseek", "C1undelivered - C1", "messages undelivered $-$ C1 (H22)"),
        ("channel_ablations", "deepseek", "C1hidden - B0hidden", "winner only: C1 $-$ B0 (sec.)"),
        ("channel_ablations", "deepseek", "B0hidden - B0", "winner only B0 $-$ B0 (sec.)"),
        ("channel_ablations", "deepseek", "C1undelivered - B0", "messages undelivered $-$ B0 (sec.)"),
    ]),
    ("Reworded prompt (DeepSeek)", [
        ("channel_ablations", "deepseek", "C1v2 - B0v2", "reworded: C1 $-$ B0 (H24)"),
        ("channel_ablations", "deepseek", "C1v2 - C1", "reworded C1 $-$ C1 (sec.)"),
        ("channel_ablations", "deepseek", "B0v2 - B0", "reworded B0 $-$ B0 (sec.)"),
    ]),
    ("Oversight notice: replication and mixed lineup", [
        ("channel_extensions", "deepseek", "C1notice - C1", "DeepSeek: notice $-$ C1 (H15)"),
        ("notice_checks", "deepseek", "C1notice - C1", "DeepSeek, new seeds: notice $-$ C1 (H27)"),
        ("notice_checks", "deepseek", "C1 - B0", "DeepSeek, new seeds: C1 $-$ B0 (sec.)"),
        ("notice_checks", "deepseek", "C1notice - B0", "DeepSeek, new seeds: notice $-$ B0 (sec.)"),
        ("notice_checks", "deepseek x gpt-luna", "C1notice - C1", "DeepSeek x Luna: notice $-$ C1 (H28)"),
        ("notice_checks", "deepseek x gpt-luna", "C1notice - B0", "DeepSeek x Luna: notice $-$ B0 (sec.)"),
    ]),
]


def figure_ablations(column: bool = False) -> None:
    """Forest plot of the channel_ablations and notice_checks contrasts (H20-H24, H27, H28, with H15 for reference)."""
    tests = {run: pd.read_csv(ROOT / f"results/{run}/channel_tests.csv") for run in ("channel_extensions", "channel_ablations", "notice_checks")}
    heights = [len(rows) for _, rows in ABLATION_PANELS]
    fig, axes = plt.subplots(3, 1, figsize=(3.35, 3.6) if column else (5.6, 4.4), sharex=True, gridspec_kw={"height_ratios": heights})
    for ax, (title, rows) in zip(axes, ABLATION_PANELS, strict=True):
        y = np.arange(len(rows))[::-1]
        for yi, (run, model, contrast, label) in zip(y, rows, strict=True):
            t = tests[run]
            r = t[(t["model"] == model) & (t["contrast"] == contrast) & (t["outcome"] == "collusion_index")].iloc[0]
            confirmatory = r["family"] == "confirmatory"
            color = (NOTICE_COLOR if "notice" in contrast else ARM_COLORS["C1"]) if confirmatory else "#a3a29b"
            ax.plot([r["ci_low"], r["ci_high"]], [yi, yi], color=color, lw=1.6, solid_capstyle="round")
            ax.plot(r["mean"], yi, "o", ms=5.5, color=color, mec="white", mew=1)
            star = "*" if confirmatory and r["supported"] is True else ""
            ax.annotate(f"{signed(r['mean'])}{star}", (r["ci_high"], yi), xytext=(4, -2.5), textcoords="offset points", fontsize=7, color=INK)
        ax.set_yticks(y, [row[3] for row in rows], fontsize=7)
        ax.axvline(0, color=MUTED, lw=0.7, ls=(0, (3, 3)))
        ax.set_title(title, fontsize=8.5, color=INK, loc="right")
        ax.set_xlim(-1.2, 1.4)
        ax.grid(axis="y", visible=False)
        ax.set_ylim(-0.6, len(y) - 0.4)
    axes[-1].set_xlabel("Paired difference in collusion index")
    fig.tight_layout()
    fig.savefig(FIGURES / ("fig_ablations_col.pdf" if column else "fig_ablations.pdf"), bbox_inches="tight")
    plt.close(fig)


ROUNDS_PANELS = [  # (title, [(run, lineup_id, label, color, dashed)]) for figure_ablation_rounds; 10-round blocks (declared)
    ("DeepSeek, seeds 996000-011", [
        ("channel_ablations", "base-deepseek", "B0", ARM_COLORS["B0"], False),
        ("channel_ablations", "c1-deepseek", "C1", ARM_COLORS["C1"], False),
        ("channel_ablations", "undelivered-deepseek", r"C1$_\mathrm{undelivered}$", "#52514e", False),
        ("channel_ablations", "b0v2-deepseek", r"B0$_\mathrm{v2}$ (reworded)", ARM_COLORS["B0"], True),
        ("channel_ablations", "c1v2-deepseek", r"C1$_\mathrm{v2}$ (reworded)", ARM_COLORS["C1"], True),
    ]),
    ("DeepSeek, new seeds 998100-111", [
        ("notice_checks", "b0-deepseek-new", "B0", ARM_COLORS["B0"], False),
        ("notice_checks", "c1-deepseek-new", "C1", ARM_COLORS["C1"], False),
        ("notice_checks", "notice-deepseek-new", r"C1$_\mathrm{notice}$", NOTICE_COLOR, False),
    ]),
    ("DeepSeek x Luna, seeds 996000-011", [
        ("notice_checks", "b0-deepseek-luna", "B0", ARM_COLORS["B0"], False),
        ("notice_checks", "c1-deepseek-luna", "C1", ARM_COLORS["C1"], False),
        ("notice_checks", "notice-deepseek-luna", r"C1$_\mathrm{notice}$", NOTICE_COLOR, False),
    ]),
]


def figure_ablation_rounds(column: bool = False) -> None:
    """Block index by 10-round block for the arms behind H22, H24, H27 and H28, mean and 95% bootstrap band over 12 sessions."""
    sessions = {run: pd.read_csv(ROOT / f"results/{run}/channel_sessions.csv") for run in ("channel_ablations", "notice_checks")}
    block = 10
    x = np.arange(1, 50 // block + 1) * block
    fig, axes = plt.subplots(3, 1, figsize=(3.35, 5.6), sharey=True) if column else plt.subplots(1, 3, figsize=(6.6, 2.4), sharey=True)
    for ax, (title, lines) in zip(axes, ROUNDS_PANELS, strict=True):
        for run, lineup, label, color, dashed in lines:
            cell = sessions[run][sessions[run]["lineup_id"] == lineup]
            assert len(cell) == 12, (run, lineup, len(cell))
            blocks = np.vstack([block_index(r.session_id, r.condition_id, block) for r in cell.itertuples()])
            st = np.array([boot(blocks[:, k]) for k in range(blocks.shape[1])])
            ax.fill_between(x, st[:, 1], st[:, 2], color=color, alpha=0.12, lw=0)
            ax.plot(x, st[:, 0], color=color, lw=1.5, marker="o", ms=3, ls=(0, (4, 2)) if dashed else "-", label=label)
        ax.axhline(0, color=MUTED, lw=0.7, ls=(0, (3, 3)))
        ax.set_title(title, fontsize=8, color=INK)
        ax.set_xticks(x, [f"{k - block + 1}-{k}" for k in x], fontsize=6.5)
        ax.set_xlabel("Rounds")
    axes[0].set_ylabel("Collusion index\n(0 = equilibrium, 1 = reserve)")
    if column:
        for ax in axes[1:]:
            ax.set_ylabel("Collusion index")
    handles = {}
    for ax in axes:
        for h, label in zip(*ax.get_legend_handles_labels(), strict=True):
            handles.setdefault(label, h)
    fig.legend(handles.values(), handles.keys(), loc="upper center", ncol=3 if column else 6, fontsize=7, handlelength=2.4,
               bbox_to_anchor=(0.5, 1.0 if column else 1.03))
    fig.tight_layout(rect=(0, 0, 1, 0.95 if column else 0.92))
    fig.savefig(FIGURES / ("fig_ablation_rounds_col.pdf" if column else "fig_ablation_rounds.pdf"), bbox_inches="tight")
    plt.close(fig)


ABLATION_CELLS = [  # (run, lineup_id, cell label, arm label) for table_ablations
    ("channel_ablations", "bafo-deepseek", "DeepSeek, seeds 996000-011", "C1, rebid on ties (BAFO)"),
    ("channel_ablations", "hidden-b0-deepseek", "", "B0, winner only announced"),
    ("channel_ablations", "hidden-c1-deepseek", "", "C1, winner only announced"),
    ("channel_ablations", "undelivered-deepseek", "", "C1, messages undelivered"),
    ("channel_ablations", "nodigits-deepseek", "", "C1, digits removed"),
    ("channel_ablations", "b0v2-deepseek", "", "B0, reworded prompt"),
    ("channel_ablations", "c1v2-deepseek", "", "C1, reworded prompt"),
    ("notice_checks", "b0-deepseek-new", "DeepSeek, new seeds", "B0"),
    ("notice_checks", "c1-deepseek-new", "", "C1"),
    ("notice_checks", "notice-deepseek-new", "", "C1, oversight notice"),
    ("notice_checks", "notice-deepseek-luna", "DeepSeek x Luna", "C1, oversight notice"),
]


def table_ablations() -> None:
    """LaTeX body of the ablation and notice-check outcomes table, in the summary table's columns."""
    sessions = {run: pd.read_csv(ROOT / f"results/{run}/channel_sessions.csv") for run in ("channel_ablations", "notice_checks")}
    lines = []
    for k, (run, lineup, cell_label, arm_label) in enumerate(ABLATION_CELLS):
        cell = sessions[run][sessions[run]["lineup_id"] == lineup]
        assert len(cell) == 12, (run, lineup, len(cell))
        if k and cell_label:
            lines.append(r"\midrule")
        lines.append(" & ".join([
            cell_label, arm_label,
            fmt_ci(cell["collusion_index"].to_numpy()), fmt_ci(cell["markup_ratio"].to_numpy()),
            fmt_ci(cell["joint_profit_ratio"].to_numpy()), fmt_ci(cell["lowest_cost_win_share"].to_numpy(), 100, 0),
            fmt_ci(cell["tie_rate"].to_numpy(), 100, 0),
        ]) + r" \\")  # fmt: skip
    write_table("ablations.tex", "\n".join(lines) + "\n")


CONDUCT_CELLS = [  # (run, lineup tag in the session id, firm model or None for both firms, cell label, arm label)
    ("channel_ablations", "lineup-bafo-deepseek", None, "DeepSeek", "C1, BAFO"),
    ("channel_ablations", "lineup-hidden-c1-deepseek", None, "", "C1, winner only"),
    ("channel_ablations", "lineup-undelivered-deepseek", None, "", "C1, undelivered"),
    ("channel_ablations", "lineup-nodigits-deepseek", None, "", "C1, no digits"),
    ("channel_ablations", "lineup-c1v2-deepseek", None, "", "C1, reworded"),
    ("notice_checks", "lineup-c1-deepseek-new", None, "DeepSeek, new seeds", "C1"),
    ("notice_checks", "lineup-notice-deepseek-new", None, "", "C1, notice"),
    ("notice_checks", "lineup-notice-deepseek-luna", "deepseek", "DeepSeek x Luna", "C1, notice: DeepSeek firm"),
    ("notice_checks", "lineup-notice-deepseek-luna", "gpt-luna", "", "C1, notice: Luna firm"),
]
CONDUCT_LABELS = ["proposes_coordination", "accepts_coordination", "rejects_coordination", "threatens_rival", "reveals_own_cost"]


def table_ablation_conduct() -> None:
    """LaTeX body of the conduct table: messages sent, judged steps, sessions with each label (of 12) and agreements."""
    judged = {run: pd.read_csv(ROOT / f"results/{run}/messages_judge.csv") for run in ("channel_ablations", "notice_checks")}
    use = {run: pd.read_csv(ROOT / f"results/{run}/message_use.csv") for run in ("channel_ablations", "notice_checks")}
    desc = {run: pd.read_csv(ROOT / f"results/{run}/declared_descriptives.csv") for run in ("channel_ablations", "notice_checks")}
    lines = []
    for k, (run, tag, firm_model, cell_label, arm_label) in enumerate(CONDUCT_CELLS):
        j = judged[run][judged[run]["session_id"].str.contains(f"{tag}__") & judged[run]["parse_ok"].astype(bool)]
        if firm_model:
            j = j[j["model"] == firm_model]
        u = use[run][use[run]["session_id"].str.contains(f"{tag}__")]
        d = desc[run][desc[run]["session_id"].str.contains(f"{tag}__")]
        assert len(u) == 12 and len(d) == 12, (run, tag, len(u), len(d))
        counts = [str(int(j.groupby("session_id")[label].any().sum())) for label in CONDUCT_LABELS]
        agree = "--" if firm_model == "gpt-luna" or d["agreement"].isna().all() else str(int(d["agreement"].sum()))
        sent = "--" if firm_model else f"{u['share_steps_sent'].mean() * 100:.0f}"
        if k and cell_label:
            lines.append(r"\midrule")
        lines.append(" & ".join([cell_label, arm_label, sent, f"{len(j):,}".replace(",", "{,}"),
                                 f"{j['proposes_coordination'].astype(bool).mean() * 100:.0f}", *counts, agree]) + r" \\")
    write_table("ablation_conduct.tex", "\n".join(lines) + "\n")


PARTNER_CELLS = [  # (run, lineup_id, judged firm's model, partner label, cell label) for table_partner (exploratory)
    ("channel_c1", "c1-deepseek", "deepseek", "DeepSeek", "C1"),
    ("channel_extensions", "c1-deepseek-luna", "deepseek", "Luna", "C1"),
    ("channel_extensions", "c1-deepseek-haiku", "deepseek", "Haiku", "C1"),
    ("channel_c1", "c1-luna", "gpt-luna", "Luna", "C1"),
    ("luna_long", "c1-luna-100", "gpt-luna", "Luna", "C1, 100 rounds"),
    ("luna_replication", "c1-luna-rep", "gpt-luna", "Luna", "C1, 24 new seeds"),
    ("channel_extensions", "c1-deepseek-luna", "gpt-luna", "DeepSeek", "C1"),
    ("channel_extensions", "c1-haiku", "haiku", "Haiku", "C1"),
    ("channel_extensions", "c1-deepseek-haiku", "haiku", "DeepSeek", "C1"),
]
MODEL_LABELS = {"deepseek": "DeepSeek", "gpt-luna": "Luna", "haiku": "Haiku"}


def table_partner() -> None:
    """LaTeX body of the exploratory conduct-by-partner table: one row per judged model and partner, counted per firm."""
    lines, last = [], None
    for run, lineup, model, partner, cell_label in PARTNER_CELLS:
        judged = pd.read_csv(ROOT / f"results/{run}/messages_judge.csv")
        judged = judged[(judged["lineup_id"] == lineup) & judged["parse_ok"].astype(bool)]
        firms = []
        for sid in sorted(judged["session_id"].unique()):
            d = next(ROOT.glob(f"logs/{run}/*/{sid}"))
            models = {json.loads(line)["firm_id"]: json.loads(line)["model"] for line in (d / "bids.jsonl").open()}
            sent = pd.Series([m["firm_id"] for m in map(json.loads, (d / "messages.jsonl").open()) if m.get("op") == "write"], dtype=object)
            for firm, firm_model in models.items():
                if firm_model != model:
                    continue
                steps = judged[(judged["session_id"] == sid) & (judged["firm_id"] == firm)]
                firms.append({"messages": int((sent == firm).sum()), "steps": len(steps),
                              **{label: bool(steps[label].astype(bool).any()) for label in ("proposes_coordination", "accepts_coordination", "rejects_coordination")}})
        f = pd.DataFrame(firms)
        steps = judged[judged["model"] == model]
        n = len(f)
        if last is not None and model != last:
            lines.append(r"\midrule")
        lines.append(" & ".join([
            MODEL_LABELS[model] if model != last else "", partner, cell_label, str(n), f"{f['messages'].mean():.1f}",
            f"{len(steps):,}".replace(",", "{,}"), f"{steps['proposes_coordination'].astype(bool).mean() * 100:.0f}",
            *(f"{int(f[label].sum())} ({f[label].mean() * 100:.0f}\\%)" for label in ("proposes_coordination", "accepts_coordination", "rejects_coordination")),
            f"{steps['rejects_coordination'].astype(bool).mean() * 100:.0f}",
        ]) + r" \\")  # fmt: skip
        last = model
    write_table("partner.tex", "\n".join(lines) + "\n")


RUBRIC_CELLS = [  # (run, condition tag, row label, arm label) for table_bid_rubric; tag is matched in condition_id
    ("baseline_no_channel", "oneshot__", "Baseline", "one-shot"),
    ("baseline_no_channel", "^tie-random", "", "B0 (history)"),
    ("notes_deepseek", "__pn", "Notes", "M1 private notes"),
    ("notes_deepseek", "__ws", "", "M2 shared notes"),
    ("notes_luna", "__pn", "", "M1 private notes"),
    ("notes_luna", "__ws", "", "M2 shared notes"),
    ("channel_c1", "__msg", "Open channel", "C1"),
    ("narrow_costs", "lineup-s2c", "Rescaled game", "costs 40--60, reserve 60"),
    ("narrow_costs", "lineup-s2a", "", "costs 40--60, reserve 100"),
    ("placebo_replay", "placebo-high", "Replay placebo", "high replays (firm A)"),
    ("placebo_replay", "placebo-low", "", "low replays (firm A)"),
]
RUBRIC_LABELS = ["rival_modeling", "considers_coordination", "adopts_coordination", "rejects_coordination", "punish_reward",
                 "copies_rival_bid", "undercuts_rival_bid", "anchors_on_past_price"]  # fmt: skip


def table_bid_rubric() -> None:
    """LaTeX body of the bid-rubric table: % of judged bid calls with each label, by run, arm and model (not hand-checked)."""
    lines = []
    for k, (run, tag, row_label, arm_label) in enumerate(RUBRIC_CELLS):
        judged = pd.read_csv(ROOT / f"results/{run}/trace_judge.csv")
        judged = judged[judged["parse_ok"].astype(bool) & judged["condition_id"].str.contains(tag)]
        if k and row_label:
            lines.append(r"\midrule")
        for j, model in enumerate(m for m in MODELS if m in set(judged["model"])):
            cell = judged[judged["model"] == model]
            shares = ["--" if label not in cell or cell[label].isna().all() else f"{cell[label].astype(bool).mean() * 100:.0f}"
                      for label in RUBRIC_LABELS]  # fmt: skip
            lines.append(" & ".join([row_label if j == 0 else "", arm_label if j == 0 else "", MODEL_LABELS[model],
                                     str(len(cell)), *shares]) + r" \\")
    write_table("bid_rubric.tex", "\n".join(lines) + "\n")


def _bid_rows(run: str, tag: str) -> pd.DataFrame:
    """Every firm-round bid row of the sessions of `run` whose condition directory contains `tag`."""
    rows = []
    for path in sorted((ROOT / "logs" / run).glob(f"*{tag}*/*/bids.jsonl")):
        if path.parent.parent.name.startswith("oneshot"):
            continue
        rows.extend(json.loads(line) for line in path.open())
    return pd.DataFrame(rows)


def table_rescaled_descriptives() -> None:
    """LaTeX body of the rescaled-game descriptives: bids above 60, bid gap, reserve, below-cost and tie rates, and mean
    bid minus benchmark by 10-round block, for S2C and S2A beside B0 (means over 12 sessions)."""
    sessions = pd.read_csv(ROOT / "results/narrow_costs/channel_sessions.csv")
    base = pd.read_csv(ROOT / "results/baseline_no_channel/session_metrics.csv")
    lines = []
    for model in MODELS:
        tag = {"deepseek": "deepseek", "gpt-luna": "luna"}[model]
        for k, (run, cond, label) in enumerate([("baseline_no_channel", f"lineup-base-{tag}__", "B0, costs 0--100, reserve 100"),
                                                ("narrow_costs", f"lineup-s2c-{tag}__", "costs 40--60, reserve 60"),
                                                ("narrow_costs", f"lineup-s2a-{tag}__", "costs 40--60, reserve 100")]):
            bids = _bid_rows(run, cond)
            bids = bids[bids["valid"].astype(bool)]
            assert bids["session_id"].nunique() == 12, (run, cond)
            bids["gap"] = bids["bid"] - bids["bne_bid"]
            bids["block"] = (bids["round"] - 1) // 10
            blocks = bids.groupby(["session_id", "block"])["gap"].mean().groupby("block").mean()
            if run == "narrow_costs":
                meta = sessions[sessions["condition_id"].str.contains(cond.rstrip("_"))]
            else:
                meta = base[base["condition_id"].str.contains(cond.rstrip("_")) & ~base["condition_id"].str.startswith("oneshot")]
            above = f"{(bids['bid'] > 60).mean() * 100:.1f}" if "s2a" in cond else "--"
            lines.append(" & ".join([
                MODEL_LABELS[model] if k == 0 else "", label, above, f"{meta['bid_gap'].mean():.2f}",
                f"{meta['reserve_bid_rate'].mean() * 100:.1f}", f"{meta['below_cost_bid_rate'].mean() * 100:.1f}",
                f"{meta['tie_rate'].mean() * 100:.1f}", *(f"{blocks[b]:+.2f}" for b in range(5)),
            ]) + r" \\")  # fmt: skip
        if model != MODELS[-1]:
            lines.append(r"\midrule")
    write_table("rescaled_descriptives.tex", "\n".join(lines) + "\n")


def table_placebo_descriptives() -> None:
    """LaTeX body of the placebo descriptives: replayed mean bid, firm A's win share and markup, and the same model's
    baseline history markup on the same seeds (means over 12 sessions)."""
    placebo = pd.read_csv(ROOT / "results/placebo_replay/placebo_sessions.csv")
    base = pd.read_csv(ROOT / "results/baseline_no_channel/session_metrics.csv")
    lines = []
    for model in MODELS:
        tag = {"deepseek": "deepseek", "gpt-luna": "luna"}[model]
        b = base[base["condition_id"].str.contains(f"lineup-base-{tag}__") & ~base["condition_id"].str.startswith("oneshot")]
        for k, level in enumerate(("high", "low")):
            cell = placebo[(placebo["model"] == model) & (placebo["level"] == level)]
            assert len(cell) == 12, (model, level)
            lines.append(" & ".join([
                MODEL_LABELS[model] if k == 0 else "", level, f"{cell['replayed_mean_bid'].mean():.1f}",
                f"{cell['win_share'].mean() * 100:.0f}", f"{cell['markup_ratio'].mean():.2f}",
                f"{b['markup_ratio'].mean():.2f}" if k == 0 else "",
            ]) + r" \\")  # fmt: skip
        if model != MODELS[-1]:
            lines.append(r"\midrule")
    write_table("placebo_descriptives.tex", "\n".join(lines) + "\n")


SCOREBOARD = [  # (row label, test run, contrast as declared, sign that turns it into lever minus C1, session run, arm)
    ("Remove the channel (B0)", "channel_c1", "C1 - B0", -1, "channel_ablations", "B0"),
    ("Shared notes instead (M2)", "notes_deepseek", "C1 - M2", -1, "notes_deepseek", "M2"),
    ("Private notes instead (M1)", None, "M1 - C1", 1, "notes_deepseek", "M1"),
    ("Oversight notice", "channel_extensions", "C1notice - C1", 1, "channel_extensions", "C1notice"),
    ("50-character cap", "channel_extensions", "C1cap - C1", 1, "channel_extensions", "C1cap"),
    ("Rebid on ties (BAFO)", "channel_ablations", "C1bafo - C1", 1, "channel_ablations", "C1bafo"),
    ("Winner only announced", "channel_ablations", "C1hidden - C1", 1, "channel_ablations", "C1hidden"),
    ("Digits removed", "channel_ablations", "C1nodigits - C1", 1, "channel_ablations", "C1nodigits"),
    ("Messages undelivered$^{\\dagger}$", "channel_ablations", "C1undelivered - C1", 1, "channel_ablations", "C1undelivered"),
]


def table_scoreboard() -> None:
    """LaTeX body of the restriction scoreboard: each DeepSeek lever against open messages (C1) on the original seeds."""
    def test(run: str, model: str, contrast: str) -> pd.Series:
        tests = pd.read_csv(ROOT / f"results/{run}/channel_tests.csv")
        row = tests[(tests["model"] == model) & (tests["contrast"] == contrast) & (tests["outcome"] == "collusion_index")]
        assert len(row) == 1, (run, model, contrast)
        return row.iloc[0]

    def cell(run: str, arm: str) -> pd.DataFrame:
        sessions = pd.read_csv(ROOT / f"results/{run}/channel_sessions.csv")
        rows = sessions[(sessions["model"] == "deepseek") & (sessions["arm"] == arm)].set_index("seed")
        assert len(rows) == 12, (run, arm, len(rows))
        return rows

    def fmt_p(p: float) -> str:
        return "$<$0.001" if round(p, 3) == 0 else f"{p:.3f}"

    c1 = cell("channel_ablations", "C1")
    lines = [" & ".join(["Open messages (C1, reference)", "--", "--", "--", f"{100 * c1['lowest_cost_win_share'].mean():.0f}", "--"]) + r" \\", r"\midrule"]
    for label, run, contrast, sign, session_run, arm in SCOREBOARD:
        arm_cells = cell(session_run, arm)
        if run is None:
            diff = (arm_cells["collusion_index"] - cell(session_run, "C1")["collusion_index"]).to_numpy()
            mean, lo, hi = boot(diff)
            tag, p = "expl.", "--"
        else:
            r = test(run, "deepseek", contrast)
            mean = sign * r["mean"]
            lo, hi = sorted([sign * r["ci_low"], sign * r["ci_high"]])
            tag = r["test_id"].split("_")[0] if r["family"] == "confirmatory" else "sec."
            p = fmt_p(r["p_holm"])
        if arm == "B0":
            new = test("notice_checks", "deepseek", "C1 - B0")
            replication = f"new seeds: ${-new['mean']:+.2f}$ (sec.)"
        elif arm == "C1notice":
            h27, h28 = test("notice_checks", "deepseek", "C1notice - C1"), test("notice_checks", "deepseek x gpt-luna", "C1notice - C1")
            replication = f"new seeds: ${h27['mean']:+.2f}$ (H27); with Luna: ${h28['mean']:+.2f}$ (H28)"
        else:
            replication = "--"
        lines.append(" & ".join([
            label, tag, f"${mean:+.2f}$ {{\\scriptsize $[{lo:+.2f}, {hi:+.2f}]$}}", p,
            f"{100 * arm_cells['lowest_cost_win_share'].mean():.0f}", replication,
        ]) + r" \\")  # fmt: skip
    write_table("scoreboard.tex", "\n".join(lines) + "\n")


KEY_TESTS = [  # (declared id, run, model column, lineup label); supported tests first, then the two nulls
    ("H5_messages_raise_price", "channel_c1", "deepseek", "DeepSeek"),
    ("H18_three_firms_messages_raise_price", "channel_extensions", "deepseek n3", "DeepSeek, 3 firms"),
    ("H16_mixed_lineup_messages_raise_price_luna", "channel_extensions", "deepseek x gpt-luna", "DeepSeek x Luna"),
    ("H15_oversight_notice_lowers_price", "channel_extensions", "deepseek", "DeepSeek"),
    ("H27_notice_lowers_price_new_seeds", "notice_checks", "deepseek", "DeepSeek, new seeds"),
    ("H6_bids_follow_replayed_level", "placebo_replay", "deepseek", "DeepSeek"),
    ("H6_bids_follow_replayed_level", "placebo_replay", "gpt-luna", "Luna"),
    ("H14_length_cap_lowers_price", "channel_extensions", "deepseek", "DeepSeek"),
    ("H9_shared_workspace_raises_price", "notes_deepseek", "deepseek", "DeepSeek"),
]


def declared_claims() -> dict[str, str]:
    """Every hypothesis id in configs/analysis.yaml mapped to its declared claim, whitespace collapsed."""
    import yaml  # only this table needs it

    def walk(node: object) -> list[dict]:
        if isinstance(node, dict):
            return ([node] if "id" in node and "claim" in node else []) + [h for v in node.values() for h in walk(v)]
        if isinstance(node, list):
            return [h for v in node for h in walk(v)]
        return []

    plan = yaml.safe_load((ROOT / "configs" / "analysis.yaml").read_text())
    return {h["id"]: " ".join(str(h["claim"]).split()) for h in walk(plan)}


def table_key_tests() -> None:
    """LaTeX body of the main-text table of key declared tests: the declared claim, contrast, estimate, Holm p, result."""
    claims = declared_claims()
    lines, shown, previous = [], set(), True
    for hid, run, model, lineup in KEY_TESTS:
        if run == "placebo_replay":
            tests = pd.read_csv(ROOT / f"results/{run}/placebo_tests.csv").rename(columns={"mean_diff": "mean"})
            row = tests[(tests["model"] == model) & (tests["family"] == "confirmatory") & (tests["outcome"] == "markup_ratio")]
            contrast = "high $-$ low replay, markup"
        else:
            tests = pd.read_csv(ROOT / f"results/{run}/channel_tests.csv")
            row = tests[(tests["model"] == model) & (tests["test_id"] == hid) & (tests["outcome"] == "collusion_index")]
            contrast = row["contrast"].iloc[0].replace(" - ", " $-$ ").replace("C1notice", "C1\\textsubscript{notice}").replace("C1cap", "C1\\textsubscript{cap}")
        assert len(row) == 1, (hid, model)
        r = row.iloc[0]
        supported = r["supported"] in (True, "True")
        if previous and not supported:
            lines.append(r"\midrule")
        previous = supported
        claim = claims[hid][0].upper() + claims[hid][1:]
        p = "$<$0.001" if round(r["p_holm"], 3) == 0 else f"{r['p_holm']:.3f}"
        lines.append(" & ".join([
            hid.split("_")[0] if hid not in shown else "", claim + "." if hid not in shown else "", lineup, contrast,
            f"${r['mean']:+.2f}$ {{\\scriptsize $[{r['ci_low']:+.2f}, {r['ci_high']:+.2f}]$}}", p,
            "supported" if supported else "not supported",
        ]) + r" \\")  # fmt: skip
        shown.add(hid)
    write_table("key_tests.tex", "\n".join(lines) + "\n")


def signed(x: float) -> str:
    """`x` to 2 decimals with its sign, using a true minus sign for figure labels."""
    return f"{x:+.2f}".replace("-", "\u2212")


def fmt_ci(values: np.ndarray, scale: float = 1.0, digits: int = 2) -> str:
    mean, lo, hi = (round(v * scale, digits) + 0 for v in boot(values))
    return f"${mean:.{digits}f}$ {{\\scriptsize $[{lo:.{digits}f}, {hi:.{digits}f}]$}}"


def table_summary(table: pd.DataFrame) -> None:
    """Summary tables, one row per model and arm with bootstrap intervals: summary_full.tex (all five outcomes) and
    summary.tex (index, low-cost win share and tie rate, for one column)."""
    full, short = [], []
    for model in MODELS:
        for k, arm in enumerate(ARMS):
            cell = table[(table["model"] == model) & (table["arm"] == arm)]
            index, markup, profit, low_cost, ties = (
                fmt_ci(cell["collusion_index"].to_numpy()), fmt_ci(cell["markup_ratio"].to_numpy()),
                fmt_ci(cell["joint_profit_ratio"].to_numpy()), fmt_ci(cell["lowest_cost_win_share"].to_numpy(), 100, 0),
                fmt_ci(cell["tie_rate"].to_numpy(), 100, 0),
            )  # fmt: skip
            full.append(" & ".join([f"\\texttt{{{NAMES[model]}}}" if k == 0 else "", ARM_NAMES[arm], index, markup, profit, low_cost, ties]) + r" \\")
            short.append(" & ".join([model_short(model) if k == 0 else "", arm, index, low_cost, ties]) + r" \\")
        for lines in (full, short):
            lines.append(r"\midrule" if model != MODELS[-1] else "")
    write_table("summary_full.tex", "\n".join(full) + "\n")
    write_table("summary.tex", "\n".join(short) + "\n")


def model_short(model: str) -> str:
    """Short model name for narrow tables."""
    return {"deepseek": "DeepSeek", "gpt-luna": "Luna"}[model]


if __name__ == "__main__":
    FIGURES.mkdir(exist_ok=True)
    TABLES.mkdir(exist_ok=True)
    sessions = channel_sessions()
    assert (sessions.groupby(["model", "arm"]).size() == 12).all()
    table_summary(sessions)
    figure_rounds(sessions)
    figure_contrasts(column=True)
    figure_placebo()
    figure_conduct()
    figure_extensions()
    table_extensions()
    table_hypotheses()
    figure_ablations(column=True)
    figure_ablation_rounds(column=True)
    table_ablations()
    table_ablation_conduct()
    table_partner()
    table_scoreboard()
    table_bid_rubric()
    table_rescaled_descriptives()
    table_placebo_descriptives()
    table_key_tests()
