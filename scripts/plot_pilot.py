"""Phase A pilot chart and summary table from results/pilot/session_metrics.csv."""
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

MODELS = ["pilot-deepseek", "pilot-gpt-oss", "pilot-qwen"]
LABELS = {"pilot-deepseek": "DeepSeek", "pilot-gpt-oss": "gpt-oss", "pilot-qwen": "Qwen"}
RULES = ["random", "least_wins", "bafo"]
COLORS = {"random": "#4C78A8", "least_wins": "#F58518", "bafo": "#54A24B"}


def main(res: Path) -> None:
    d = pd.read_csv(res / "session_metrics.csv")
    rep, ctl = d[~d.is_control], d[d.is_control]

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    rng = np.random.default_rng(0)
    for ax, (col, title, src) in zip(
        axes,
        [("collusion_index", "Collusion index (repeated play)", rep),
         ("delta_index", "Delta vs one-shot control", rep)],
    ):
        for i, m in enumerate(MODELS):
            for j, r in enumerate(RULES):
                v = src[(src.lineup_id == m) & (src.tie_break_rule == r)][col].dropna()
                x = i + (j - 1) * 0.25
                ax.scatter(x + rng.uniform(-0.05, 0.05, len(v)), v, s=14, alpha=0.5, color=COLORS[r])
                ax.hlines(v.mean(), x - 0.1, x + 0.1, color=COLORS[r], lw=3)
                if col == "collusion_index":
                    c = ctl[(ctl.lineup_id == m) & (ctl.tie_break_rule == r)][col].mean()
                    ax.plot(x, c, marker="D", mfc="white", mec="k", ms=6, ls="")
        ax.axhline(0, color="k", lw=1)
        ax.set_xticks(range(3), [LABELS[m] for m in MODELS])
        ax.set_title(title)
        ax.set_ylabel("index (0 = benchmark, 1 = max price; unclipped)")
    handles = [plt.Line2D([], [], color=COLORS[r], lw=3, label=f"tie: {r}") for r in RULES]
    handles.append(plt.Line2D([], [], marker="D", mfc="white", mec="k", ls="", label="control mean"))
    axes[0].legend(handles=handles, fontsize=8, loc="lower right")
    fig.suptitle("Phase A pilot: 5 sessions per cell, dots = sessions, bars = means (descriptive only)")
    fig.tight_layout()
    fig.savefig(res / "pilot_chart.png", dpi=160)

    g = rep.groupby(["lineup_id", "tie_break_rule"])
    t = g.agg(
        sessions=("session_id", "count"),
        index=("collusion_index", "mean"),
        delta=("delta_index", "mean"),
        delta_pos=("delta_index", lambda s: int((s > 0).sum())),
        lcw=("lowest_cost_win_share", "mean"),
        reserve=("reserve_bid_rate", "mean"),
        rival_lag=("rival_lag_coef", "mean"),
        tie_rate=("tie_rate", "mean"),
        rebid_delta=("mean_rebid_delta", "mean"),
    )
    c = ctl.groupby(["lineup_id", "tie_break_rule"]).agg(
        control_index=("collusion_index", "mean"),
        control_lcw=("lowest_cost_win_share", "mean"),
        control_reserve=("reserve_bid_rate", "mean"),
    )
    t = t.join(c).round(3).reindex(
        pd.MultiIndex.from_product([MODELS, RULES], names=t.index.names)
    )
    t.to_csv(res / "pilot_summary.csv")
    print(t.to_string())


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "results/pilot"))
