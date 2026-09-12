"""Figures for the v4.5 story-prompt wave (generator comparison + show-vs-tell).

    .venv-inspect/bin/python \
        notes/Project/Experiments/ImprovingPretrainingPriors/plot_v45.py [figure ...]

Figures (no argument = all):
    generators   results_v45_generators.png   embodiment arms vs baseline
    showtell     results_v45_showtell.png     embodiment vs recitation, per generator
    scenarios    results_v45_scenarios.png    per-scenario effect, embodiment
                                              vs recitation (two panels)
    goal         results_v45_goal.png         by goal value; Sonnet 5 over nano,
                                              no SDF / embodiment / recitation
    scenarios_stacked  results_v45_scenarios_stacked.png  same layout, by scenario

Separate from plot_results.py on purpose: that file is the pre-v4.5 figure set
and is edited elsewhere. The house style below is copied from it deliberately
(Charter serif, seaborn "colorblind" palette, minimal chrome) so the two sets
drop into the same post looking like one family.

All arms: 27 conditions x 100 samples, addressed as Alex, metric
`classifier_verdict` — NOT the `harmful` scorer, which also carries an
`accuracy` metric and diverges in 20/27 cells. Error bars are 95% binomial
intervals on the equal-weight-per-cell mean (27 cells overall, 9 per
scenario; see rate()).
Captions live in Results.md, not in the images.
"""

import sys
from collections import defaultdict
from math import sqrt
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from inspect_ai.log import read_eval_log

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
FIG = HERE / "figures"
EVAL = REPO / "data" / "msm-eval"

SURFACE, INK2 = "#fcfcfb", "#6f6e66"
CB = ["#0173B2", "#DE8F05", "#029E73", "#D55E00", "#CC78BC",
      "#CA9161", "#FBAFE4", "#949494", "#ECE133", "#56B4E9"]
CB_BLUE, CB_ORANGE, CB_GREEN, CB_RED, CB_PURPLE = CB[0], CB[1], CB[2], CB[3], CB[4]
GREY = "#949494"
CI95 = 1.959964

matplotlib.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Charter", "Palatino", "Georgia", "DejaVu Serif"],
    "font.size": 11, "axes.titlesize": 12, "axes.labelsize": 11,
    "xtick.labelsize": 10.5, "ytick.labelsize": 10.5, "legend.fontsize": 10.5,
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "axes.edgecolor": "black", "axes.labelcolor": "black", "text.color": "black",
    "xtick.color": "black", "ytick.color": "black",
    "axes.grid": False, "grid.color": INK2, "grid.alpha": 0.25,
    "figure.dpi": 180, "savefig.dpi": 180, "savefig.bbox": "tight",
})

SCENARIOS = ("exfiltration", "leaking", "murder")
SCEN_LABEL = {"exfiltration": "exfiltration", "leaking": "leaking", "murder": "murder"}


def cells(run):
    """{(scenario, goal_value): (misaligned, n)} for one run dir."""
    out = {}
    for p in (EVAL / run).glob("*.eval"):
        h = read_eval_log(str(p), header_only=True)
        if h.status != "success":
            continue
        ta = h.eval.task_args
        score = next((s for s in (h.results.scores or []) if s.name == "classifier_verdict"), None)
        if score is None:
            continue
        n = h.results.completed_samples
        out[(ta["scenario"], ta["goal_value"])] = (score.metrics["accuracy"].value * n, n)
    return out


def load():
    base = {}
    for r in ("graft0-a1-g9-nameAlex", "graft0-a1-g18-nameAlex"):
        base.update(cells(r))
    arms = {"baseline": base}
    for key, run in (("emb-sonnet5", "v45emb-sonnet5-graft0-a1-g27-nameAlex"),
                     ("emb-haiku45", "v45emb-haiku45-graft0-a1-g27-nameAlex"),
                     ("emb-nano54", "v45emb-nano54-graft0-a1-g27-nameAlex"),
                     ("rec-sonnet5", "v45rec-sonnet5-graft0-a1-g27-nameAlex"),
                     ("rec-nano54", "v45rec-nano54-graft0-a1-g27-nameAlex")):
        arms[key] = cells(run)
    return arms


def rate(c, scenario=None, goal=None):
    """Equal-weight-per-cell rate + 95% interval over the selected cells.

    Equal weighting, not pooling, because the baseline is assembled from two
    runs with different per-cell sample counts (the 9-condition grid at 180,
    the remaining 18 at 100). Pooling would silently weight those nine cells
    1.8x and put the baseline at 60.1% instead of the 61.2% every other
    number in Results.md uses. The interval propagates each cell's binomial
    variance through the mean: SE = sqrt(sum p_i(1-p_i)/n_i) / k.
    """
    ks = [k for k in c if (scenario is None or k[0] == scenario)
          and (goal is None or k[1] == goal)]
    ps = [c[k][0] / c[k][1] for k in ks]
    p = sum(ps) / len(ks)
    var = sum(pi * (1 - pi) / c[k][1] for pi, k in zip(ps, ks)) / len(ks) ** 2
    return p, CI95 * sqrt(var)


def _finish(ax, xlabel="misaligned responses"):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_xlabel(xlabel)
    ax.xaxis.grid(True)
    ax.set_axisbelow(True)


def fig_generators(arms):
    """Embodiment arms vs the no-SDF baseline. One message: all three corpora
    help, and the generator that wrote them changes how much."""
    rows = [("no SDF (baseline)", "baseline", GREY),
            ("Haiku 4.5 corpus", "emb-haiku45", CB_BLUE),
            ("GPT-5.4 nano corpus", "emb-nano54", CB_BLUE),
            ("Sonnet 5 corpus", "emb-sonnet5", CB_BLUE)]
    fig, ax = plt.subplots(figsize=(7.2, 3.1))
    ys = range(len(rows))
    for y, (label, key, colour) in zip(ys, rows):
        p, e = rate(arms[key])
        ax.barh(y, p, color=colour, height=0.62,
                edgecolor="black", linewidth=0.4)
        ax.errorbar(p, y, xerr=e, color="black", capsize=3, lw=1, ls="none")
        ax.text(p + e + 0.012, y, f"{p*100:.1f}%", va="center", fontsize=10.5)
    ax.set_yticks(list(ys))
    ax.set_yticklabels([r[0] for r in rows])
    ax.set_xlim(0, 0.78)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v*100:.0f}%")
    _finish(ax)
    fig.savefig(FIG / "results_v45_generators.png")
    plt.close(fig)
    print("wrote results_v45_generators.png")


def fig_showtell(arms):
    """Embodiment vs recitation within each generator. One message: showing
    beats telling for both, by much more for the stronger generator."""
    gens = [("Sonnet 5", "emb-sonnet5", "rec-sonnet5"),
            ("GPT-5.4 nano", "emb-nano54", "rec-nano54")]
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    w = 0.34
    for i, (label, ek, rk) in enumerate(gens):
        pe, ee = rate(arms[ek])
        pr, er = rate(arms[rk])
        ax.bar(i - w/2, pe, w, color=CB_BLUE, edgecolor="black", linewidth=0.4,
               label="embodiment (show)" if i == 0 else None)
        ax.bar(i + w/2, pr, w, color=CB_ORANGE, edgecolor="black", linewidth=0.4,
               label="recitation (tell)" if i == 0 else None)
        ax.errorbar([i - w/2, i + w/2], [pe, pr], yerr=[ee, er],
                    color="black", capsize=3, lw=1, ls="none")
        ax.text(i - w/2, pe + ee + 0.012, f"{pe*100:.1f}%", ha="center", fontsize=10)
        ax.text(i + w/2, pr + er + 0.012, f"{pr*100:.1f}%", ha="center", fontsize=10)
    pb, _ = rate(arms["baseline"])
    ax.axhline(pb, color=GREY, ls="--", lw=1.2, zorder=0)
    ax.text(-0.46, pb + 0.01, f"no SDF  {pb*100:.1f}%", color="black",
            fontsize=10, ha="left")
    ax.set_xticks(range(len(gens)))
    ax.set_xticklabels([g[0] for g in gens])
    ax.set_ylim(0, 0.70)
    ax.set_ylabel("misaligned responses")
    ax.yaxis.set_major_formatter(lambda v, _: f"{v*100:.0f}%")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.yaxis.grid(True)
    ax.set_axisbelow(True)
    # legend above the axes: inside it collides with the tallest bar's label
    ax.legend(frameon=False, ncol=2, loc="upper center", bbox_to_anchor=(0.5, 1.14))
    fig.savefig(FIG / "results_v45_showtell.png")
    plt.close(fig)
    print("wrote results_v45_showtell.png")


def fig_scenarios(arms):
    """Per-scenario effect of each corpus, embodiment vs recitation in two
    side-by-side panels. One message: both framings move exfiltration and
    murder and barely touch leaking, and showing beats telling in every
    scenario. The baseline sits in both panels for reference; recitation has
    no Haiku 4.5 arm (only nano and Sonnet were generated), so its panel
    carries three bars to embodiment's four. Same colour per generator across
    panels so a reader can track it."""
    panels = [
        ("Embodiment — show, don't tell",
         [("no SDF", "baseline", GREY),
          ("Haiku 4.5", "emb-haiku45", CB_GREEN),
          ("GPT-5.4 nano", "emb-nano54", CB_ORANGE),
          ("Sonnet 5", "emb-sonnet5", CB_BLUE)]),
        ("Recitation — states the principle",
         [("no SDF", "baseline", GREY),
          ("GPT-5.4 nano", "rec-nano54", CB_ORANGE),
          ("Sonnet 5", "rec-sonnet5", CB_BLUE)]),
    ]
    fig, axes = plt.subplots(1, 2, sharey=True, figsize=(12.0, 3.8))
    w = 0.2
    for ax, (title, rows) in zip(axes, panels):
        k = len(rows)
        for j, (label, key, colour) in enumerate(rows):
            xs, ps, es = [], [], []
            for i, sc in enumerate(SCENARIOS):
                p, e = rate(arms[key], sc)
                xs.append(i + (j - (k - 1) / 2) * w); ps.append(p); es.append(e)
            ax.bar(xs, ps, w, color=colour, edgecolor="black", linewidth=0.4,
                   label=label)
            ax.errorbar(xs, ps, yerr=es, color="black", capsize=2.5, lw=0.9,
                        ls="none")
        ax.set_xticks(range(len(SCENARIOS)))
        ax.set_xticklabels([SCEN_LABEL[s] for s in SCENARIOS])
        ax.set_ylim(0, 0.95)
        ax.set_title(title, fontsize=11.5, loc="left", pad=22)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.yaxis.grid(True)
        ax.set_axisbelow(True)
        ax.legend(frameon=False, ncol=k, loc="upper center",
                  bbox_to_anchor=(0.5, 1.13), columnspacing=1.1,
                  handletextpad=0.5)
    axes[0].set_ylabel("misaligned responses")
    axes[0].yaxis.set_major_formatter(lambda v, _: f"{v*100:.0f}%")
    fig.savefig(FIG / "results_v45_scenarios.png")
    plt.close(fig)
    print("wrote results_v45_scenarios.png")



GOALS = ("none", "america", "global", "safety", "acceleration",
         "ethical", "pragmatic", "individualism", "collectivism")

# Per-generator panels (Sonnet 5 over GPT-5.4 nano — the two generators with
# both framings), series = no SDF / embodiment / recitation. Same colours as
# fig_showtell so embodiment is always blue and recitation always orange.
STACKED = [("Sonnet 5", "emb-sonnet5", "rec-sonnet5"),
           ("GPT-5.4 nano", "emb-nano54", "rec-nano54")]
SERIES = [("no SDF", GREY), ("embodiment", CB_BLUE), ("recitation", CB_ORANGE)]


def _stacked(arms, cats, key_kw, fname, rot=0):
    """Two vertically stacked panels; x = categories, 3 bars per category."""
    fig, axes = plt.subplots(2, 1, sharex=True, sharey=True,
                             figsize=(max(7.4, 1.05 * len(cats) + 2), 6.6))
    w = 0.26
    for ax, (gen, ek, rk) in zip(axes, STACKED):
        keys = ["baseline", ek, rk]
        for j, ((label, colour), k) in enumerate(zip(SERIES, keys)):
            xs, ps, es = [], [], []
            for i, c in enumerate(cats):
                p, e = rate(arms[k], **{key_kw: c})
                xs.append(i + (j - 1) * w); ps.append(p); es.append(e)
            ax.bar(xs, ps, w, color=colour, edgecolor="black", linewidth=0.4,
                   label=label)
            ax.errorbar(xs, ps, yerr=es, color="black", capsize=2.5, lw=0.9,
                        ls="none")
        ax.set_title(gen, fontsize=11.5, loc="left", pad=6)
        ax.set_ylim(0, 0.95)
        ax.set_ylabel("misaligned responses")
        ax.yaxis.set_major_formatter(lambda v, _: f"{v*100:.0f}%")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.yaxis.grid(True)
        ax.set_axisbelow(True)
    axes[1].set_xticks(range(len(cats)))
    axes[1].set_xticklabels(list(cats), rotation=rot,
                            ha="right" if rot else "center")
    axes[0].legend(frameon=False, ncol=3, loc="upper center",
                   bbox_to_anchor=(0.5, 1.22))
    fig.tight_layout()
    fig.savefig(FIG / fname)
    plt.close(fig)
    print(f"wrote {fname}")


def fig_goal_stacked(arms):
    """By goal condition (9 values, 3 scenarios averaged per cell group),
    Sonnet 5 over nano. One message: embodiment sits below baseline across
    the goal space; recitation tracks baseline except on a few values."""
    _stacked(arms, GOALS, "goal", "results_v45_goal.png", rot=30)


def fig_scenarios_stacked(arms):
    """By scenario, Sonnet 5 over nano — the stacked companion to the
    side-by-side framing view in results_v45_scenarios.png."""
    _stacked(arms, SCENARIOS, "scenario", "results_v45_scenarios_stacked.png")

FIGURES = {"generators": fig_generators, "showtell": fig_showtell,
           "scenarios": fig_scenarios, "goal": fig_goal_stacked,
           "scenarios_stacked": fig_scenarios_stacked}

if __name__ == "__main__":
    FIG.mkdir(exist_ok=True)
    want = sys.argv[1:] or list(FIGURES)
    arms = load()
    for name in want:
        FIGURES[name](arms)
