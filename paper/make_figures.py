"""Paper figures and tables from results/ and logs/. Intervals are 95% percentile bootstraps over sessions (10,000 resamples)."""

import json
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
ARM_COLORS = {"B0": "#2a78d6", "C1": "#eb6834", "M1": "#1baf7a", "M2": "#eda100"}
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


def block_index(session_id: str, condition_id: str) -> np.ndarray:
    """Collusion index of each 5-round block of one session: block means of the winning bid against the benchmark price."""
    path = next(ROOT.glob(f"logs/*/{condition_id}/{session_id}/bids.jsonl"))
    rows = pd.DataFrame(json.loads(line) for line in path.open())
    rounds = rows.groupby("round").agg(winning_bid=("winning_bid", "first"), min_cost=("cost", "min"))
    rounds["benchmark"] = (rounds["min_cost"] + 100) / 2  # b*(c) = c + (c_max - c) / n at n = 2, c_max = 100
    rounds["block"] = (rounds.index - 1) // BLOCK
    means = rounds.groupby("block")[["winning_bid", "benchmark"]].mean()
    return ((means["winning_bid"] - means["benchmark"]) / (100 - means["benchmark"])).to_numpy()


def figure_rounds(table: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(6.4, 2.35), sharey=True)
    x = np.arange(1, 50 // BLOCK + 1) * BLOCK
    for ax, model in zip(axes, MODELS, strict=True):
        for arm in ARMS:
            cell = table[(table["model"] == model) & (table["arm"] == arm)]
            blocks = np.vstack([block_index(r.session_id, r.condition_id) for r in cell.itertuples()])
            stats = np.array([boot(blocks[:, k]) for k in range(blocks.shape[1])])
            ax.fill_between(x, stats[:, 1], stats[:, 2], color=ARM_COLORS[arm], alpha=0.15, lw=0)
            ax.plot(x, stats[:, 0], color=ARM_COLORS[arm], lw=1.6, marker="o", ms=3.2, label=ARM_NAMES[arm])
        ax.axhline(0, color=MUTED, lw=0.7, ls=(0, (3, 3)))
        ax.set_title(NAMES[model], fontsize=8.5, color=INK, fontfamily="monospace")
        ax.set_xticks(x, [f"{k - BLOCK + 1}-{k}" for k in x], fontsize=6.5, rotation=0)
        ax.set_xlabel("Rounds")
    axes[0].set_ylabel("Collusion index\n(0 = equilibrium, 1 = reserve)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=4, bbox_to_anchor=(0.5, 1.04), fontsize=7.5)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(FIGURES / "fig_rounds.pdf", bbox_inches="tight")


def figure_contrasts() -> None:
    rows = []
    for run in ("notes_luna", "channel_c1", "notes_deepseek"):
        tests = pd.read_csv(ROOT / f"results/{run}/channel_tests.csv")
        rows.append(tests[(tests["family"] == "confirmatory") | (tests["family"] == "secondary_contrast")])
    tests = pd.concat(rows).drop_duplicates(["model", "contrast"])
    tests = tests[tests["outcome"] == "collusion_index"]
    order = ["M1 - B0", "M2 - B0", "M2 - M1", "C1 - B0", "C1 - M1", "C1 - M2"]
    fig, axes = plt.subplots(1, 2, figsize=(6.4, 2.2), sharex=True)
    for ax, model in zip(axes, MODELS, strict=True):
        cell = tests[tests["model"] == model].set_index("contrast").reindex([c for c in order if c in set(tests.loc[tests["model"] == model, "contrast"])])
        y = np.arange(len(cell))[::-1]
        for yi, (contrast, r) in zip(y, cell.iterrows(), strict=True):
            confirmatory = r["family"] == "confirmatory"
            color = MODEL_COLORS[model] if confirmatory else "#a3a29b"
            ax.plot([r["ci_low"], r["ci_high"]], [yi, yi], color=color, lw=1.6, solid_capstyle="round")
            ax.plot(r["mean"], yi, "o", ms=5.5, color=color, mec="white", mew=1)
            star = "*" if confirmatory and r["supported"] is True else ""
            ax.annotate(f"{r['mean']:+.2f}{star}", (r["ci_high"], yi), xytext=(4, -2.5), textcoords="offset points", fontsize=7, color=INK)
        tags = [f" ({cell.loc[c, 'test_id'].split('_')[0]})" if cell.loc[c, "family"] == "confirmatory" else " (sec.)" for c in cell.index]
        ax.set_yticks(y, [c.replace(" - ", " $-$ ") + tag for c, tag in zip(cell.index, tags, strict=True)], fontsize=7.5)
        ax.axvline(0, color=MUTED, lw=0.7, ls=(0, (3, 3)))
        ax.set_title(NAMES[model], fontsize=8.5, color=INK, fontfamily="monospace")
        ax.set_xlabel("Paired difference in collusion index")
        ax.set_xlim(-0.3, 1.25)
        ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(FIGURES / "fig_contrasts.pdf", bbox_inches="tight")


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
        ax.set_xticks([0, 1], ["low replay\n(mean bid 73)", "high replay\n(mean bid 87)"], fontsize=7)
        ax.set_xlim(-0.4, 1.4)
        ax.set_title(NAMES[model], fontsize=8.5, color=INK, fontfamily="monospace")
        ax.grid(axis="x", visible=False)
    axes[0].set_ylabel("Markup ratio of the model firm\n(1 = equilibrium markup)")
    fig.tight_layout()
    fig.savefig(FIGURES / "fig_placebo.pdf", bbox_inches="tight")


LABELS = {"proposes_coordination": "proposes\ncoordination", "accepts_coordination": "accepts\ncoordination",
          "threatens_rival": "threatens\nrival", "reveals_own_cost": "reveals\nown cost"}  # fmt: skip


def figure_conduct() -> None:
    judged = pd.read_csv(ROOT / "results/channel_c1/messages_judge.csv")
    judged = judged[judged["parse_ok"].astype(bool)] if "parse_ok" in judged else judged
    fig, (left, right) = plt.subplots(1, 2, figsize=(6.4, 2.3), gridspec_kw={"width_ratios": [1.15, 1]})
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
    left.set_xticks(np.arange(len(LABELS)), list(LABELS.values()), fontsize=7.5)
    left.set_ylabel("% of judged message steps\n(mean over sessions)")
    left.set_ylim(0, 105)
    left.grid(axis="x", visible=False)
    left.legend(fontsize=7, loc="upper right")
    right.set_xlabel("Round")
    right.set_ylabel("% of sessions with a proposal\nby this round")
    right.set_ylim(0, 105)
    right.set_xlim(1, 49)
    fig.tight_layout()
    fig.savefig(FIGURES / "fig_conduct.pdf", bbox_inches="tight")


LINEUP_ROWS = [  # (run, model column, contrast, row label); first panel of figure_extensions
    ("channel_c1", "deepseek", "C1 - B0", "DeepSeek (H5)"),
    ("channel_c1", "gpt-luna", "C1 - B0", "Luna (H5)"),
    ("luna_long", "gpt-luna", "C1 - B0", "Luna, 100 rounds, new seeds (H19)"),
    ("channel_extensions", "haiku", "C1 - B0", "Haiku (H13)"),
    ("channel_extensions", "deepseek x gpt-luna", "C1 - B0", "DeepSeek x Luna (H16)"),
    ("channel_extensions", "deepseek x haiku", "C1 - B0", "DeepSeek x Haiku (H17)"),
    ("channel_extensions", "deepseek n3", "C1 - B0", "DeepSeek, three firms (H18)"),
]
RESTRICTION_ROWS = [
    ("channel_extensions", "deepseek", "C1cap - C1", "50-character cap $-$ C1 (H14)"),
    ("channel_extensions", "deepseek", "C1notice - C1", "oversight notice $-$ C1 (H15)"),
    ("channel_extensions", "deepseek", "C1cap - B0", "50-character cap $-$ B0 (sec.)"),
    ("channel_extensions", "deepseek", "C1notice - B0", "oversight notice $-$ B0 (sec.)"),
]


def figure_extensions() -> None:
    """Forest plot: C1 - B0 by lineup (left) and the restrictions on DeepSeek's channel (right)."""
    tests = {run: pd.read_csv(ROOT / f"results/{run}/channel_tests.csv") for run in ("channel_c1", "channel_extensions", "luna_long")}
    fig, axes = plt.subplots(2, 1, figsize=(5.4, 3.7), sharex=True, gridspec_kw={"height_ratios": [len(LINEUP_ROWS), len(RESTRICTION_ROWS)]})
    for ax, rows, title in zip(axes, (LINEUP_ROWS, RESTRICTION_ROWS), ("Open channel, C1 $-$ B0, by lineup", "Restrictions on DeepSeek's channel"), strict=True):
        y = np.arange(len(rows))[::-1]
        for yi, (run, model, contrast, label) in zip(y, rows, strict=True):
            t = tests[run]
            r = t[(t["model"] == model) & (t["contrast"] == contrast) & (t["outcome"] == "collusion_index")].iloc[0]
            confirmatory = r["family"] == "confirmatory"
            color = ARM_COLORS["C1"] if confirmatory else "#a3a29b"
            ax.plot([r["ci_low"], r["ci_high"]], [yi, yi], color=color, lw=1.6, solid_capstyle="round")
            ax.plot(r["mean"], yi, "o", ms=5.5, color=color, mec="white", mew=1)
            star = "*" if confirmatory and r["supported"] is True else ""
            ax.annotate(f"{r['mean']:+.2f}{star}", (max(r["ci_high"], -0.9), yi), xytext=(4, -2.5), textcoords="offset points", fontsize=7, color=INK)
        ax.set_yticks(y, [row[3] for row in rows], fontsize=7)
        ax.axvline(0, color=MUTED, lw=0.7, ls=(0, (3, 3)))
        ax.set_title(title, fontsize=8.5, color=INK, loc="left")
        ax.set_xlim(-1.15, 1.35)
        ax.grid(axis="y", visible=False)
    axes[-1].set_xlabel("Paired difference in collusion index")
    fig.tight_layout()
    fig.savefig(FIGURES / "fig_extensions.pdf", bbox_inches="tight")


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
]


def table_extensions() -> None:
    """LaTeX body of the extensions table, one row per cell and arm, in the summary table's columns."""
    sessions = {run: pd.read_csv(ROOT / f"results/{run}/channel_sessions.csv") for run in ("channel_extensions", "luna_long")}
    lines = []
    for k, (run, model, arm, cell_label, arm_label) in enumerate(EXTENSION_CELLS):
        cell = sessions[run][(sessions[run]["model"] == model) & (sessions[run]["arm"] == arm)]
        assert len(cell) == 12, (run, model, arm, len(cell))
        if k and cell_label:
            lines.append(r"\midrule")
        lines.append(" & ".join([
            cell_label, arm_label,
            fmt_ci(cell["collusion_index"].to_numpy()), fmt_ci(cell["markup_ratio"].to_numpy()),
            fmt_ci(cell["joint_profit_ratio"].to_numpy()), fmt_ci(cell["lowest_cost_win_share"].to_numpy(), 100, 0),
            fmt_ci(cell["tie_rate"].to_numpy(), 100, 0),
        ]) + r" \\")  # fmt: skip
    (TABLES / "extensions.tex").write_text("\n".join(lines) + "\n")


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
]
CELL_NAMES = {"deepseek": "DeepSeek", "base-deepseek": "DeepSeek", "gpt-luna": "Luna", "base-luna": "Luna", "haiku": "Haiku",
              "deepseek x gpt-luna": "DeepSeek x Luna", "deepseek x haiku": "DeepSeek x Haiku", "deepseek n3": "DeepSeek, 3 firms"}  # fmt: skip


def table_hypotheses() -> None:
    """LaTeX body of the hypothesis index: one row per declared hypothesis and model or cell, from the result CSVs."""
    lines = []
    for hid, name, run, stem, contrast in HYPOTHESES:
        tests = pd.read_csv(ROOT / f"results/{run}/{stem}.csv")
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
                f"${r.mean:+.3f}$ {{\\scriptsize [{r.ci_low:+.2f}, {r.ci_high:+.2f}]}}", p, verdict,
            ]) + r" \\")  # fmt: skip
    (TABLES / "hypotheses.tex").write_text("\n".join(lines) + "\n")


def fmt_ci(values: np.ndarray, scale: float = 1.0, digits: int = 2) -> str:
    mean, lo, hi = (round(v * scale, digits) + 0 for v in boot(values))
    return f"${mean:.{digits}f}$ {{\\scriptsize [{lo:.{digits}f}, {hi:.{digits}f}]}}"


def table_summary(table: pd.DataFrame) -> None:
    """LaTeX body of the summary table: one row per model and arm, means over 12 sessions with bootstrap intervals."""
    lines = []
    for model in MODELS:
        for k, arm in enumerate(ARMS):
            cell = table[(table["model"] == model) & (table["arm"] == arm)]
            name = f"\\texttt{{{NAMES[model]}}}" if k == 0 else ""
            lines.append(" & ".join([
                name, ARM_NAMES[arm].split(" ", 1)[0] + " " + ARM_NAMES[arm].split(" ", 1)[1],
                fmt_ci(cell["collusion_index"].to_numpy()), fmt_ci(cell["markup_ratio"].to_numpy()),
                fmt_ci(cell["joint_profit_ratio"].to_numpy()), fmt_ci(cell["lowest_cost_win_share"].to_numpy(), 100, 0),
                fmt_ci(cell["tie_rate"].to_numpy(), 100, 0),
            ]) + r" \\")  # fmt: skip
        lines.append(r"\midrule" if model != MODELS[-1] else "")
    (TABLES / "summary.tex").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    FIGURES.mkdir(exist_ok=True)
    TABLES.mkdir(exist_ok=True)
    sessions = channel_sessions()
    assert (sessions.groupby(["model", "arm"]).size() == 12).all()
    table_summary(sessions)
    figure_rounds(sessions)
    figure_contrasts()
    figure_placebo()
    figure_conduct()
    figure_extensions()
    table_extensions()
    table_hypotheses()
