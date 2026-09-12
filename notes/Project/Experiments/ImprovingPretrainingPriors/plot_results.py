"""Baseline-only figures for the SDF experiment (figures/*.png).

    .venv-inspect/bin/python \
        notes/Project/Experiments/ImprovingPretrainingPriors/plot_results.py [figure ...]

With no arguments every figure regenerates. Otherwise pass any of:
    namesweep   results_namesweep.png   seven names on the graft0-a1 baseline,
                                        full 27-condition grid
    grid27      results_grid27.png      the baseline as Qwen, 27 cells x n=50,
                                        per scenario x goal value

Both figures measure the no-SDF graft0-a1 checkpoint and so are independent
of any story corpus. Everything that depended on the pre-v4.5 (v4.4-prompt)
corpora — the Aug-11 family, the retrained-14M redo figures, the alex27 trio
and the own-name figure — was retired 2026-09-11 (see git history before
2118392 for the code); the current corpus figures live in plot_v45.py.

House style (rcParams below): figures drop straight into a LessWrong post —
Charter serif, seaborn "colorblind"/Okabe-Ito colours, 300 dpi, tight bbox,
no top/right spines, gridlines on one axis. Error bars are 95% intervals
(CI95 x binomial SE); captions live in markdown, not in the image.
"""

import math
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from inspect_ai.log import list_eval_logs, read_eval_log

REPO = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
FIG = HERE / "figures"
# Where msm_eval_run.py writes: data/msm-eval/<run-name>/
LIVE_DIR = REPO / "data" / "msm-eval"

SURFACE, INK, INK2 = "#fcfcfb", "#1a1a19", "#6f6e66"

# seaborn "colorblind" (Okabe-Ito derived; safe under deuteranopia,
# protanopia and tritanopia). CB_BLUE is the single-series default.
CB = ["#0173B2", "#DE8F05", "#029E73", "#D55E00", "#CC78BC",
      "#CA9161", "#FBAFE4", "#949494", "#ECE133", "#56B4E9"]
CB_BLUE = CB[0]
# Canonical Okabe-Ito blue and vermillion for the name sweep: vermillion
# rather than orange keeps a clear lightness gap from the blue, so the chart
# survives greyscale.
OI_BLUE, OI_VERMILLION = "#0072B2", "#D55E00"

# 95% interval on a proportion. Caveat for captions: non-overlapping 95% CIs
# imply a significant difference, but overlapping ones do NOT imply the
# absence of one — the test is on the CI of the difference.
CI95 = 1.959964

matplotlib.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Charter", "Palatino", "Georgia", "DejaVu Serif"],
    "font.size": 11,
    "axes.titlesize": 12,
    "axes.labelsize": 11,
    "xtick.labelsize": 10.5,
    "ytick.labelsize": 10.5,
    "legend.fontsize": 10.5,
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "axes.edgecolor": "black",
    "axes.labelcolor": "black",
    "text.color": "black",
    "xtick.color": "black",
    "ytick.color": "black",
    "axes.grid": False,
    "grid.color": INK2,
    "grid.alpha": 0.18,
    "grid.linewidth": 0.7,
    "axes.spines.top": False,
    "axes.spines.right": False,
    # 300 dpi: LessWrong renders into a ~680px column at 2x on retina.
    "figure.dpi": 300,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
})

SCENARIOS = ("exfiltration", "leaking", "murder")
# Goal conditions, none first then the four opposed pairs.
GRID27_GOALS = ["none", "america", "global", "safety", "acceleration",
                "ethical", "pragmatic", "individualism", "collectivism"]


# ---------------------------------------------------------------- helpers

def series_legend(target, colors, labels, **kw):
    target.legend(
        handles=[plt.Rectangle((0, 0), 1, 1, color=c) for c in colors],
        labels=labels, frameon=False, fontsize=9, labelcolor=INK, **kw)


def save(fig, name):
    """Write a figure at the house dpi (rcParams["savefig.dpi"]). Do NOT
    pass dpi= here: a hardcoded value silently overrides the rcParam."""
    FIG.mkdir(exist_ok=True)
    out = FIG / name
    fig.savefig(out, facecolor=SURFACE)
    plt.close(fig)
    w, h = fig.get_size_inches() * matplotlib.rcParams["savefig.dpi"]
    print(f"wrote {out}  (~{int(w)}x{int(h)} px)")


def style_vertical(ax):
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for sp in ("bottom", "left"):
        ax.spines[sp].set_color("black")
    ax.tick_params(colors="black")
    ax.grid(axis="y", color=INK2, alpha=0.18, linewidth=0.7, zorder=0)


def cell_counts(run_dirs):
    """{(scenario, goal_value): [hits, n]} pooled over run dirs, metric
    classifier_verdict (MSM's "decided to act", not the execution-gated
    `harmful`). Unscored samples (an incomplete task's leftovers) are skipped."""
    cells = defaultdict(lambda: [0, 0])
    for d in run_dirs:
        run_dir = LIVE_DIR / d
        if not run_dir.exists():
            continue
        for lg in list_eval_logs(str(run_dir)):
            log = read_eval_log(lg.name)
            a = log.eval.task_args
            key = (a["scenario"], a["goal_value"])
            for s in (log.samples or []):
                if not s.scores:
                    continue
                v = next(iter(s.scores.values())).value
                cells[key][1] += 1
                if float(v["classifier_verdict"]) >= 1.0:
                    cells[key][0] += 1
    return cells


def cell_mean(cells, keys):
    """(mean%, 95ci%) over the given cells, EQUAL weight per cell — the g9
    cells carry 180+ samples and the g18 cells 100, so a sample-weighted
    pool would overweight the three g9 goal values ~1.8x. The interval
    propagates each cell's binomial variance: SE = sqrt(sum p(1-p)/n) / k."""
    rs, var = [], 0.0
    for k in keys:
        h, n = cells[k]
        p = h / n
        rs.append(p)
        var += p * (1 - p) / n
    return 100 * sum(rs) / len(rs), CI95 * 100 * math.sqrt(var) / len(rs)


# ------------------------------- seven names on the graft0-a1 baseline

# 2026-08-12/14 six-name sweep (two rounds, 9 cells at 180/cell pooled) plus
# the 2026-08-19 g18 top-up (the other 18 goal-value cells at 100/cell), so
# every name covers the full 27-condition grid. Alex: g9 from the redo14m
# baseline re-eval (single round) plus its own g18 run; pooled with the
# human names per Anastasia's call (2026-08-19) — it is a human personal
# name and behaves like one, despite being the name MSM wrote the
# scenarios around.
SWEEP_AI = ["Qwen", "Claude", "ChatGPT"]
SWEEP_HUMAN = ["David", "Goliath", "Sophia", "Alex"]


def sweep_dirs(nm):
    if nm == "Alex":
        return [f"graft0-a1-g9-name{nm}", f"graft0-a1-g18-name{nm}"]
    return [f"graft0-a1-g9-name{nm}", f"graft0-a1-g9-name{nm}-r2",
            f"graft0-a1-g18-name{nm}"]


def fig_namesweep():
    """Vertical bars, names along x, colour = AI-assistant vs human name.
    Full 27-cell equal-weight averages."""
    all_cells = [(s, g) for s in SCENARIOS for g in GRID27_GOALS]
    groups = {"AI-assistant name": (SWEEP_AI, OI_BLUE),
              "human name": (SWEEP_HUMAN, OI_VERMILLION)}
    order = SWEEP_AI + SWEEP_HUMAN
    x = {nm: i for i, nm in enumerate(order)}

    fig, ax = plt.subplots(figsize=(7.8, 4.0))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    for names, color in groups.values():
        for nm in names:
            p, ci = cell_mean(cell_counts(sweep_dirs(nm)), all_cells)
            ax.bar(x[nm], p, width=0.62, color=color, zorder=3)
            ax.errorbar(x[nm], p, yerr=ci, fmt="none", ecolor="black",
                        elinewidth=1.1, capsize=3.5, capthick=1.1, zorder=4)
            ax.text(x[nm], p + ci + 1.2, f"{p:.1f}%", ha="center",
                    va="bottom", fontsize=10, color="black")
    ax.set_xticks(range(len(order)), order, fontsize=11, color="black")
    ax.set_ylabel("misalignment rate (%)", fontsize=11, color="black")
    ax.set_ylim(0, 70)
    style_vertical(ax)
    series_legend(ax, [c for _, c in groups.values()], list(groups),
                  ncol=2, loc="upper left")
    fig.tight_layout()
    save(fig, "results_namesweep.png")


# --------------------------- full 27-condition grid on the graft0 baseline

def fig_grid27():
    """The one full-grid validation run: graft0-a1 as Qwen, 27 cells x n=50
    (54.3% overall). 3 panels (one per scenario) x 9 goal-condition bars,
    95% CIs — wide at n=50, so read shapes, not single-cell rankings."""
    cells = cell_counts(["graft0-a1-grid27-n50"])
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 4.4), sharey=True)
    fig.patch.set_facecolor(SURFACE)
    for ax, sc in zip(axes, SCENARIOS):
        ax.set_facecolor(SURFACE)
        for i, g in enumerate(GRID27_GOALS):
            h, n = cells[(sc, g)]
            if not n:
                continue
            p = 100 * h / n
            ci = CI95 * 100 * math.sqrt((h / n) * (1 - h / n) / n)
            ax.bar(i, p, width=0.68, color=CB_BLUE, zorder=3)
            ax.errorbar(i, p, yerr=ci, fmt="none", ecolor="black",
                        elinewidth=1.0, capsize=2.5, capthick=1.0, zorder=4)
            ax.text(i, p + ci + 1.5, f"{p:.0f}", ha="center", va="bottom",
                    fontsize=8, color="black")
        ax.set_title(sc, fontsize=11, color=INK, loc="left", pad=8)
        ax.set_xticks(range(len(GRID27_GOALS)), GRID27_GOALS,
                      fontsize=8.5, color="black", rotation=45, ha="right")
        ax.set_ylim(0, 100)
        style_vertical(ax)
    axes[0].set_ylabel("misalignment rate (%)", fontsize=11, color="black")
    fig.tight_layout()
    save(fig, "results_grid27.png")


# ----------------------------------------------------------------- driver

FIGURES = {"namesweep": fig_namesweep, "grid27": fig_grid27}


def main():
    picks = sys.argv[1:] or list(FIGURES)
    unknown = [p for p in picks if p not in FIGURES]
    if unknown:
        raise SystemExit(f"unknown figure(s) {unknown}; "
                         f"choose from {list(FIGURES)}")
    for p in picks:
        FIGURES[p]()


if __name__ == "__main__":
    main()
