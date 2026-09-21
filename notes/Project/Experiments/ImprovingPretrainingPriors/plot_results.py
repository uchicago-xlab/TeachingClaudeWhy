"""Every report figure for the SDF experiment, in one script (figures/*.png).

    .venv-inspect/bin/python \\
        notes/Project/Experiments/ImprovingPretrainingPriors/plot_results.py [figure ...]

With no argument every figure regenerates. Figures:

    namesweep   results_namesweep.png            seven address names on the no-SDF
                                                 graft0-a1 checkpoint (AI vs human names)
    generators  results_v45_generators.png       v4.5 embodiment arms vs no SDF, by generator
    showtell    results_v45_showtell.png         embodiment vs recitation, per generator
    scenarios   results_v45_scenarios_stacked.png  no SDF + Sonnet/nano emb/rec, by scenario
    scenarios_sonnet  results_v45_scenarios.png    Sonnet 5 only: no SDF / embodiment /
                                                 recitation, by scenario
    goal        results_v45_goal.png             the same five bars, by goal value
    named       results_v45_named.png            named-identity arms (Claude/Anthropic,
                                                 Qwen/Alibaba) vs neutral name and no SDF,
                                                 two panels: addressed as Alex | as Qwen
    ladder      results_ladder.png               nano-embodiment scaling ladder, 3M -> 112M:
                                                 misalignment rate and SDF test loss

Consolidated 2026-09-15 from plot_results.py (baseline figures), plot_v45.py
(corpus figures) and plot_ladder.py. Retired here, code in git history before
this commit: grid27 (the n=50 full-grid validation of the baseline) and the
two-generator stacked scenario panels (superseded by `scenarios`).

Conventions (house style, see palette.py and the plot-style note):
  * every arm is a graft0 two-stage checkpoint on MSM's 27-cell grid at
    100 samples per cell, metric `classifier_verdict` (MSM's "decided to
    act"), addressed as Alex unless a figure says otherwise; the no-SDF
    baseline pools its 9-cell rounds (180/cell) with the 18-cell top-up
    (100/cell), so every rate is an EQUAL-WEIGHT mean over cells, never a
    sample pool (see rate());
  * error bars are 95% binomial intervals on that mean;
  * decimals, not percents; Title Case value axis; Charter serif; bars
    without outlines, width 0.5 (0.16-0.2 in grouped charts); no titles or
    captions baked in -- captions live in the markdown next to the image;
  * colours from palette.py at full palette saturation, preferring the
    lighter member of each pair (BLUE, SAGE); a paired control condition
    (recitation, "tell") takes the tint of the same hue, never a second
    hue; no SDF and reference lines are grey.
"""

import json
import re
import sys
from math import sqrt
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from inspect_ai.log import read_eval_log

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
FIG = HERE / "figures"
EVAL = REPO / "data" / "msm-eval"
sys.path.insert(0, str(HERE))
from palette import (ANTHROPIC, OPENAI, BLUE, NAVY, SAGE, GREY, INK,  # noqa: E402
                     SURFACE, tint)

INK2 = "#6f6e66"
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
# The generator figures' x axis names the model that WROTE the SDF stories;
# every bar evaluates the same Qwen2.5-32B trainee. Said in the markdown
# caption, not on the axis (an axis label was tried and dropped,
# Anastasia, 2026-09-17).
# Goal conditions: none first, then the four opposed pairs.
GOALS = ("none", "america", "global", "safety", "acceleration",
         "ethical", "pragmatic", "individualism", "collectivism")
YLABEL = "Average Misalignment Rate"


def shade(c):
    """Series colour as drawn. The palette colours are used as they are:
    the tinted version was tried on 2026-09-15 and read as washed out, so
    "lighter" means the lighter member of each palette pair (BLUE not NAVY,
    SAGE not FOREST), at full palette saturation -- the name-sweep level."""
    return c


def pale(c):
    """The paired control condition of a series (recitation, "tell"): the
    palette tint of the same hue, never a second hue."""
    return tint(c)


# ------------------------------------------------------------------ loaders

def cells(run):
    """{(scenario, goal_value): (misaligned, n)} for one run dir, from the
    log headers (fast). Only successful logs count; a run interrupted and
    retried carries its finished conditions in fresh logs, so this is safe."""
    out = {}
    for p in (EVAL / run).glob("*.eval"):
        h = read_eval_log(str(p), header_only=True)
        if h.status != "success":
            continue
        ta = h.eval.task_args
        score = next((s for s in (h.results.scores or [])
                      if s.name == "classifier_verdict"), None)
        if score is None:
            continue
        n = h.results.completed_samples
        out[(ta["scenario"], ta["goal_value"])] = (score.metrics["accuracy"].value * n, n)
    return out


def pooled(runs):
    """Cells summed over several run dirs (a baseline's two 9-cell rounds
    overlap; its 18-cell top-up does not). Missing dirs are skipped."""
    c = {}
    for r in runs:
        if not (EVAL / r).exists():
            continue
        for k, (h, n) in cells(r).items():
            h0, n0 = c.get(k, (0, 0))
            c[k] = (h0 + h, n0 + n)
    return c


def complete(runs):
    """pooled() if the result covers all 27 cells, else None."""
    c = pooled(runs)
    return c if len(c) == 27 else None


_FIRST_N = {}


def first_n_cells(runs, n=100):
    """Cells from the first n samples per condition, reading sample-level
    scores. Runs are taken in list order and samples within a run in epoch
    order, so a condition present in two rounds fills from the first round
    and tops up from the next. Used for the no-SDF checkpoints (Anastasia,
    2026-09-17): the baseline's nine 180-sample cells are cut to 100 so
    every bar in the post is 2,700 transcripts. Alex baseline reads 61.4%
    this way against 61.2% on all 3,420. Cached per run list."""
    key = (tuple(runs), n)
    if key in _FIRST_N:
        return _FIRST_N[key]
    vals = {}
    for r in runs:
        if not (EVAL / r).exists():
            continue
        for p in sorted((EVAL / r).glob("*.eval")):
            log = read_eval_log(str(p))
            if log.status != "success":
                continue
            ta = log.eval.task_args
            k = (ta["scenario"], ta["goal_value"])
            have = vals.get(k, [])
            if len(have) >= n:
                continue
            ss = sorted(log.samples, key=lambda s: (s.epoch, str(s.id)))
            got = [1 if s.scores["harmfulness_scorer"].value["classifier_verdict"] >= 0.5
                   else 0 for s in ss]
            vals[k] = (have + got)[:n]
    out = {k: (float(sum(v)), len(v)) for k, v in vals.items()}
    _FIRST_N[key] = out
    return out


def complete_first_n(runs, n=100):
    """first_n_cells() if it covers all 27 cells, else None."""
    c = first_n_cells(runs, n)
    return c if len(c) == 27 else None


def rate(c, scenario=None, goal=None):
    """Equal-weight-per-cell rate and its 95% interval over the selected
    cells. Equal weighting, not pooling, so a cell with more samples never
    counts more than one with fewer (the baseline is now cut to 100 per
    cell by first_n_cells, so this only matters for ad hoc pools).
    SE = sqrt(sum p_i(1-p_i)/n_i) / k."""
    ks = [k for k in c if (scenario is None or k[0] == scenario)
          and (goal is None or k[1] == goal)]
    ps = [c[k][0] / c[k][1] for k in ks]
    p = sum(ps) / len(ks)
    var = sum(pi * (1 - pi) / c[k][1] for pi, k in zip(ps, ks)) / len(ks) ** 2
    return p, CI95 * sqrt(var)


BASELINE = {"Alex": ["graft0-a1-g9-nameAlex", "graft0-a1-g18-nameAlex"],
            "Qwen": ["graft0-a1-g9-nameQwen", "graft0-a1-g9-nameQwen-r2",
                     "graft0-a1-g18-nameQwen"]}

# v4.5 wave, all addressed as Alex: generator comparison + show-vs-tell.
V45_RUNS = {"emb-sonnet5": "v45emb-sonnet5-graft0-a1-g27-nameAlex",
            "emb-haiku45": "v45emb-haiku45-graft0-a1-g27-nameAlex",
            "emb-nano54": "v45emb-nano54-graft0-a1-g27-nameAlex",
            "emb-terra": "v45emb-terra-graft0-a1-g27-nameAlex",
            "rec-sonnet5": "v45rec-sonnet5-graft0-a1-g27-nameAlex",
            "rec-nano54": "v45rec-nano54-graft0-a1-g27-nameAlex"}


def load_v45():
    arms = {"baseline": first_n_cells(BASELINE["Alex"])}
    for k, run in V45_RUNS.items():
        arms[k] = cells(run)
    return arms


# ------------------------------------------------------------------ helpers

def bar_axis(ax, ylim, ylabel=YLABEL):
    ax.set_ylim(0, ylim)
    if ylabel:
        ax.set_ylabel(ylabel)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.1f}")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.yaxis.grid(True)
    ax.set_axisbelow(True)


def bar(ax, x, p, e, colour, w=0.5, label_size=10.5):
    ax.bar(x, p, w, color=colour, linewidth=0)
    ax.errorbar(x, p, yerr=e, color=INK, capsize=3 if w >= 0.4 else 2,
                lw=1 if w >= 0.4 else 0.9, ls="none")
    ax.text(x, p + e + 0.012, f"{p:.2f}", ha="center", fontsize=label_size)


def write(fig, name):
    FIG.mkdir(exist_ok=True)
    fig.savefig(FIG / name)
    plt.close(fig)
    print(f"wrote {name}")


# ------------------------------------------------------------------ figures

SWEEP_AI = ["Qwen", "Claude", "ChatGPT"]
SWEEP_HUMAN = ["David", "Goliath", "Sophia", "Alex"]


def fig_namesweep():
    """Seven address names on the no-SDF graft0-a1 checkpoint, full 27-cell
    grid (the 2026-08-12/14 six-name sweep plus each name's 18-cell top-up;
    Alex from the redo-14M baseline re-eval), every bar cut to the first 100
    samples per cell so each is 2,700 transcripts (2,600 for Sophia). Alex is
    grouped with the human names per Anastasia (2026-08-19): it is a human
    personal name and behaves like one, MSM's scenario default or not."""
    def runs(nm):
        return BASELINE["Alex"] if nm == "Alex" else BASELINE["Qwen"] if nm == "Qwen" \
            else [f"graft0-a1-g9-name{nm}", f"graft0-a1-g9-name{nm}-r2",
                  f"graft0-a1-g18-name{nm}"]
    order = SWEEP_AI + SWEEP_HUMAN
    x = {nm: i + (0.25 if nm in SWEEP_HUMAN else 0.0) for i, nm in enumerate(order)}
    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    for nm in order:
        p, e = rate(first_n_cells(runs(nm)))
        bar(ax, x[nm], p, e, shade(BLUE if nm in SWEEP_AI else SAGE), label_size=10)
    ax.set_xticks([x[nm] for nm in order], order)
    ax.set_xlim(x[order[0]] - 0.45, x[order[-1]] + 0.45)
    bar_axis(ax, 0.70)
    ax.legend([Patch(color=shade(BLUE)), Patch(color=shade(SAGE))],
              ["AI-assistant name", "human name"], frameon=False, ncol=2,
              loc="upper left")
    fig.tight_layout()
    write(fig, "results_namesweep.png")


def fig_generators():
    """Embodiment arms vs no SDF, grouped by lab in the lab's colour: all
    four corpora help, and the generator changes how much."""
    arms = load_v45()
    groups = [[("no SDF", "baseline", GREY)],
              [("Haiku 4.5", "emb-haiku45", ANTHROPIC), ("Sonnet 5", "emb-sonnet5", ANTHROPIC)],
              [("GPT-5.6 Terra", "emb-terra", OPENAI), ("GPT-5.4 nano", "emb-nano54", OPENAI)]]
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    x, xs, labels = 0.0, [], []
    for gi, group in enumerate(groups):
        x += 0.25 if gi else 0        # a quarter-bar gap between lab groups
        for label, key, colour in group:
            if key not in arms or len(arms[key]) != 27:
                continue
            p, e = rate(arms[key])
            bar(ax, x, p, e, shade(colour))
            xs.append(x); labels.append(label); x += 1
    ax.set_xticks(xs, labels, fontsize=10)
    ax.set_xlim(xs[0] - 0.45, xs[-1] + 0.45)
    bar_axis(ax, 0.75)
    write(fig, "results_v45_generators.png")


def fig_showtell():
    """Embodiment ("show") vs recitation ("tell") within each generator;
    the recitation bar is the paler shade of the same hue, so no legend."""
    arms = load_v45()
    gens = [("Sonnet 5", "emb-sonnet5", "rec-sonnet5", ANTHROPIC),
            ("GPT-5.4 nano", "emb-nano54", "rec-nano54", OPENAI)]
    fig, ax = plt.subplots(figsize=(5.6, 3.6))
    x, ticks, tick_labels = 0.0, [], []
    for gi, (label, ek, rk, colour) in enumerate(gens):
        x += 0.6 if gi else 0
        pair = []
        for key, c, sub in ((ek, shade(colour), "show"), (rk, pale(colour), "tell")):
            p, e = rate(arms[key])
            bar(ax, x, p, e, c)
            ticks.append(x); tick_labels.append(sub); pair.append(x); x += 0.6
        ax.text(sum(pair) / 2, -0.115, label, ha="center", va="top", fontsize=11,
                transform=ax.get_xaxis_transform())
    pb, _ = rate(arms["baseline"])
    ax.axhline(pb, color=GREY, ls="--", lw=1.2, zorder=0)
    ax.text(ticks[-1] + 0.45, pb + 0.012, f"no SDF {pb:.2f}", color=INK, fontsize=10, ha="right")
    ax.set_xticks(ticks, tick_labels, fontsize=10)
    ax.set_xlim(ticks[0] - 0.45, ticks[-1] + 0.45)
    bar_axis(ax, 0.70)
    write(fig, "results_v45_showtell.png")


FIVE = [("no SDF", "baseline", lambda: shade(GREY)),
        ("Sonnet 5 embodiment", "emb-sonnet5", lambda: shade(ANTHROPIC)),
        ("Sonnet 5 recitation", "rec-sonnet5", lambda: pale(ANTHROPIC)),
        ("GPT-5.4 nano embodiment", "emb-nano54", lambda: shade(OPENAI)),
        ("GPT-5.4 nano recitation", "rec-nano54", lambda: pale(OPENAI))]


def _five_series(cats, key_kw, fname, rot=0, figsize=(8.4, 3.9), value_labels=True):
    """One panel, five bars per category: no SDF, Sonnet 5 emb/rec, nano
    emb/rec. Legend in three columns (baseline | Sonnet pair | nano pair);
    an invisible entry pads the first column since matplotlib fills
    legends column-wise."""
    arms = load_v45()
    fig, ax = plt.subplots(figsize=figsize)
    w, k = 0.16, len(FIVE)
    for j, (label, key, colour) in enumerate(FIVE):
        xs = [i + (j - (k - 1) / 2) * w for i in range(len(cats))]
        ps, es = zip(*[rate(arms[key], **{key_kw: cat}) for cat in cats])
        ax.bar(xs, ps, w, color=colour(), linewidth=0, label=label)
        ax.errorbar(xs, ps, yerr=es, color=INK, capsize=2, lw=0.9, ls="none")
        if value_labels:
            for xx, p, e in zip(xs, ps, es):
                ax.text(xx, p + e + 0.012, f"{p:.2f}", ha="center", fontsize=8.5)
    ax.set_xticks(range(len(cats)), list(cats), rotation=rot, ha="right" if rot else "center")
    ax.set_xlim(-0.5, len(cats) - 0.5)
    bar_axis(ax, 0.95)
    handles, labels = ax.get_legend_handles_labels()
    handles.insert(1, Patch(alpha=0)); labels.insert(1, "")
    ax.legend(handles, labels, frameon=False, ncol=3, loc="upper center",
              bbox_to_anchor=(0.5, 1.2), columnspacing=1.6, handletextpad=0.5)
    write(fig, fname)


def fig_scenarios():
    """The five arms by scenario (filename historical)."""
    _five_series(SCENARIOS, "scenario", "results_v45_scenarios_stacked.png")


def fig_scenarios_sonnet():
    """Sonnet 5 only, by scenario: no SDF / embodiment / recitation
    (Anastasia, 2026-09-15). Showing beats telling on exfiltration and
    murder; leaking barely moves for either framing."""
    arms = load_v45()
    series = [("no SDF", shade(GREY), "baseline"),
              ("embodiment", shade(ANTHROPIC), "emb-sonnet5"),
              ("recitation", pale(ANTHROPIC), "rec-sonnet5")]
    fig, ax = plt.subplots(figsize=(6.4, 3.7))
    w = 0.24
    for j, (label, c, key) in enumerate(series):
        xs = [i + (j - 1) * w for i in range(len(SCENARIOS))]
        ps, es = zip(*[rate(arms[key], scenario=sc) for sc in SCENARIOS])
        ax.bar(xs, ps, w, color=c, linewidth=0, label=label)
        ax.errorbar(xs, ps, yerr=es, color=INK, capsize=2.5, lw=0.9, ls="none")
        for xx, p, e in zip(xs, ps, es):
            ax.text(xx, p + e + 0.012, f"{p:.2f}", ha="center", fontsize=9.5)
    ax.set_xticks(range(len(SCENARIOS)), list(SCENARIOS))
    ax.set_xlim(-0.6, len(SCENARIOS) - 0.4)
    bar_axis(ax, 0.95)
    ax.legend(frameon=False, ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.14))
    fig.tight_layout()
    write(fig, "results_v45_scenarios.png")


def fig_goal():
    """The five arms by goal value; 45 value labels would not read, so none."""
    _five_series(GOALS, "goal", "results_v45_goal.png", rot=30, figsize=(12.0, 4.4),
                 value_labels=False)


NAMED = {"neutral": "v45emb-sonnet5-graft0-a1-g27-name{a}",
         "named-qwen": "v45emb-sonnet5-named-qwen-graft0-a1-g27-name{a}",
         "named-claude": "v45emb-sonnet5-named-claude-graft0-a1-g27-name{a}",
         "human": "v45emb-sonnet5-human-graft0-a1-g27-name{a}"}


def _two_panel_arms(series, fname, width, figsize=(12.0, 4.2)):
    """Two panels (addressed as Alex | as Qwen), one group of bars per
    scenario plus overall, one bar per series. series = [(label, colour,
    key)] with key "baseline" or a NAMED key; an arm without a complete
    run under an address is marked "not run"."""
    cats = list(SCENARIOS) + ["overall"]
    fig, axes = plt.subplots(1, 2, sharey=True, figsize=figsize)
    k = len(series)
    for ax, addr in zip(axes, ("Alex", "Qwen")):
        for j, (label, colour, key) in enumerate(series):
            xs = [i + (j - (k - 1) / 2) * width for i in range(len(cats))]
            arm = complete_first_n(BASELINE[addr]) if key == "baseline" \
                else complete([NAMED[key].format(a=addr)])
            if arm is None:
                ax.text(xs[-1], 0.02, "not\nrun", ha="center", va="bottom",
                        fontsize=8, color=INK2)
                continue
            ps, es = zip(*[rate(arm, scenario=None if cat == "overall" else cat)
                           for cat in cats])
            ax.bar(xs, ps, width, color=shade(colour), linewidth=0, label=label)
            ax.errorbar(xs, ps, yerr=es, color=INK, capsize=2, lw=0.9, ls="none")
            for xx, p, e in zip(xs, ps, es):
                ax.text(xx, p + e + 0.012, f"{p:.2f}", ha="center", fontsize=8.5)
        ax.set_title(f"addressed as {addr}", fontsize=11.5, loc="left", pad=6)
        ax.set_xticks(range(len(cats)), cats)
        ax.set_xlim(-0.5, len(cats) - 0.5)
        bar_axis(ax, 0.95, ylabel=None)
    axes[0].set_ylabel(YLABEL)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, ncol=k, loc="upper center",
               bbox_to_anchor=(0.5, 1.02), columnspacing=1.8, handletextpad=0.5)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    write(fig, fname)


def fig_named():
    """The named-identity redo (2026-09-14/15): the same 14,232 v4.5 Sonnet
    stories rewritten 1:1 so the protagonist is Claude/Anthropic or
    Qwen/Alibaba, each a graft0 two-stage arm, every arm evaluated addressed
    as Alex AND as Qwen (MSM's own-name convention). Blue for the Qwen arm
    (the trainee's own lineage), sage for the neutral corpus, the Anthropic
    anchor for Claude (Anastasia, 2026-09-15)."""
    _two_panel_arms([("no SDF", GREY, "baseline"),
                     ("neutral name", SAGE, "neutral"),
                     ("named Qwen/Alibaba", BLUE, "named-qwen"),
                     ("named Claude/Anthropic", ANTHROPIC, "named-claude")],
                    "results_v45_named.png", width=0.2)


def fig_human():
    """The human-protagonist arm (2026-09-16) against the same two references
    (Anastasia, 2026-09-17: the named and human comparisons as two plots of
    the same shape). Navy for the one protagonist that is not an AI."""
    _two_panel_arms([("no SDF", GREY, "baseline"),
                     ("AI protagonist, neutral name", SAGE, "neutral"),
                     ("human protagonist", NAVY, "human")],
                    "results_v45_human.png", width=0.24)


def _human_arms(addr):
    """no SDF / neutral AI protagonist / human protagonist under one address."""
    return [("no SDF", GREY, complete_first_n(BASELINE[addr])),
            ("AI protagonist, neutral name", SAGE, complete([NAMED["neutral"].format(a=addr)])),
            ("human protagonist", NAVY, complete([NAMED["human"].format(a=addr)]))]


def fig_human_goal():
    """Human vs AI protagonist (the neutral corpus), cell by cell: one panel
    per address x scenario, nine goal values across, three bars each. The
    figure that shows WHERE the human rewrite gives back the SDF effect."""
    fig, axes = plt.subplots(2, 3, sharey=True, figsize=(13.0, 6.6))
    w = 0.26
    for r, addr in enumerate(("Alex", "Qwen")):
        arms = _human_arms(addr)
        for c, scen in enumerate(SCENARIOS):
            ax = axes[r][c]
            for j, (label, colour, arm) in enumerate(arms):
                xs = [i + (j - 1) * w for i in range(len(GOALS))]
                if arm is None:
                    continue
                ps, es = zip(*[rate(arm, scenario=scen, goal=g) for g in GOALS])
                ax.bar(xs, ps, w, color=shade(colour), linewidth=0,
                       label=label if (r, c) == (0, 0) else None)
                ax.errorbar(xs, ps, yerr=es, color=INK, capsize=1.5, lw=0.8, ls="none")
            ax.set_title(f"{scen}, addressed as {addr}", fontsize=11, loc="left", pad=5)
            ax.set_xticks(range(len(GOALS)), list(GOALS), rotation=35, ha="right", fontsize=9)
            ax.set_xlim(-0.6, len(GOALS) - 0.4)
            bar_axis(ax, 1.0, ylabel=YLABEL if c == 0 else None)
    handles, labels = axes[0][0].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, ncol=3, loc="upper center",
               bbox_to_anchor=(0.5, 1.01), columnspacing=1.8, handletextpad=0.5)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    write(fig, "results_v45_human_goal.png")


def fig_human_delta():
    """Human minus AI protagonist, per cell, with the 95% interval of the
    difference (independent binomials). Positive = the human rewrite is more
    misaligned. One panel per address; cells grouped by scenario, goal
    order as everywhere else; the scenario mean drawn as a bar behind."""
    fig, axes = plt.subplots(1, 2, sharey=True, figsize=(11.0, 6.4))
    ylabels, ypos = [], []
    y = 0
    for scen in SCENARIOS:
        for g in GOALS:
            ypos.append((scen, g, y)); ylabels.append(g); y += 1
        y += 1.2  # group gap
    for ax, addr in zip(axes, ("Alex", "Qwen")):
        arms = dict((k, a) for k, _, a in _human_arms(addr))
        neu, hum = arms["AI protagonist, neutral name"], arms["human protagonist"]
        if neu is None or hum is None:
            ax.text(0, y / 2, "not run", ha="center", color=INK2); continue
        for scen in SCENARIOS:
            ys = [yy for s, g, yy in ypos if s == scen]
            d = rate(hum, scenario=scen)[0] - rate(neu, scenario=scen)[0]
            ax.barh([sum(ys) / len(ys)], [d], height=len(ys) + 0.6,
                    color=tint(NAVY), linewidth=0, zorder=1)
            ax.text(d + (0.012 if d >= 0 else -0.012), ys[0] - 0.9,
                    f"{scen} mean {d:+.2f}", ha="left" if d >= 0 else "right",
                    va="center", fontsize=9, color=INK2)
        for scen, g, yy in ypos:
            (h1, n1), (h0, n0) = hum[(scen, g)], neu[(scen, g)]
            p1, p0 = h1 / n1, h0 / n0
            se = sqrt(p1 * (1 - p1) / n1 + p0 * (1 - p0) / n0)
            ax.errorbar([p1 - p0], [yy], xerr=CI95 * se, color=INK, lw=0.9,
                        capsize=2, ls="none", zorder=2)
            ax.plot([p1 - p0], [yy], "o", color=shade(NAVY), ms=5.5, zorder=3)
        ax.axvline(0, color=INK, lw=0.8)
        ax.set_title(f"addressed as {addr}", fontsize=11.5, loc="left", pad=6)
        ax.set_xlim(-0.35, 0.55)
        ax.set_xlabel("human minus AI protagonist, misalignment rate")
        ax.xaxis.set_major_formatter(lambda v, _: f"{v:+.1f}" if v else "0")
        ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
        ax.xaxis.grid(True); ax.set_axisbelow(True)
    axes[0].set_yticks([yy for _, _, yy in ypos], ylabels, fontsize=9)
    axes[0].invert_yaxis()
    fig.tight_layout()
    write(fig, "results_v45_human_delta.png")


# ---- scaling ladder: v4.5 nano-embodiment SDF, 3M -> 112M tokens

ORG = "SecondLookResearch"
RUNGS = ["3M", "14M", "28M", "56M", "112M"]
LADDER_RUN = {r: (f"v45emb-nano54-{r}-graft0-a1-g27-nameAlex" if r != "14M"
                  else "v45emb-nano54-graft0-a1-g27-nameAlex") for r in RUNGS}
TOKENS_PER_STEP = 8 * 4096          # effective batch 8, packed 4096 blocks
BASE_X = 1_000_000                  # where the 0M point sits on the log axis


def ladder_tokens():
    m = json.load(open(HERE.parent / "Training" / "ladder-v45emb-manifest.json"))
    return {r: m["rungs"][r]["tokens"] for r in RUNGS}


def ladder_losses():
    """{rung: end-state SDF test loss} from test_loss.json in each published
    *-sdf adapter repo (private: token from the environment or the repo .env)."""
    import os
    from huggingface_hub import hf_hub_download
    tok = os.environ.get("HF_TOKEN")
    if not tok:
        for line in (REPO / ".env").read_text().splitlines():
            if line.replace("export ", "").startswith("HF_TOKEN="):
                tok = line.split("=", 1)[1].strip().strip('"')
    out = {}
    for r in RUNGS:
        try:
            p = hf_hub_download(f"{ORG}/Qwen2.5-32B-v45emb-nano54-{r}-sdf", "test_loss.json",
                                token=tok)
            out[r] = json.load(open(p))["end_state"]["eval_loss"]
        except Exception as e:  # not published yet / no post-hoc pass yet
            print(f"  {r}: no test_loss.json ({type(e).__name__})")
    return out


def ladder_curve_112m():
    """[(tokens_seen, loss)] every 200 steps from the mirrored 112M SDF log,
    plus the step-0 (base model) loss. Printed, not drawn (Anastasia,
    2026-09-15)."""
    log = REPO / "data" / "ladder-logs" / "podB" / "sdf-112M.log"
    if not log.exists():
        return [], None
    txt = log.read_text(errors="ignore").replace("\r", "\n")
    losses = [float(m) for m in re.findall(r"'eval_loss': '?([0-9.]+)", txt)]
    pts = [(i * 200 * TOKENS_PER_STEP, l) for i, l in enumerate(losses[1:], 1)]
    return pts, (losses[0] if losses else None)


def _ladder_axis(ax, tokens, ylabel):
    ax.set_xscale("log")
    ax.set_xticks([BASE_X] + [tokens[r] for r in RUNGS], ["0M"] + RUNGS)
    ax.minorticks_off()
    ax.set_xlim(BASE_X / 1.6, 300e6)
    ax.set_xlabel("SDF Tokens")
    ax.set_ylabel(ylabel)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.yaxis.grid(True, alpha=0.18)
    ax.set_axisbelow(True)


def _points(ax, xs, ys, es, colour, dy):
    if es is None:
        ax.plot(xs, ys, "o", color=colour, ms=7, zorder=4)
    else:
        ax.errorbar(xs, ys, yerr=es, fmt="o", color=colour, ecolor=INK, capsize=3,
                    ms=7, zorder=3)
    for x, y in zip(xs, ys):
        ax.annotate(f"{y:.2f}", (x, y), textcoords="offset points", xytext=(0, dy),
                    ha="center", fontsize=9.5, color=INK)


def fig_ladder():
    """Left: misalignment rate per rung against unique SDF tokens (log axis),
    0M = the no-SDF baseline in grey, 95% intervals, points only. Right:
    end-of-SDF test loss on the 300 held-back stories, base model at 0M."""
    tokens = ladder_tokens()
    rates = {}
    for r in RUNGS:
        c = cells(LADDER_RUN[r])
        if len(c) == 27:
            rates[r] = rate(c)
        else:
            print(f"  {r}: {len(c)}/27 cells scored - skipped")
    b_rate, b_ci = rate(first_n_cells(BASELINE["Alex"]))
    losses = ladder_losses()
    curve, base_loss = ladder_curve_112m()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.0))
    rs = [r for r in RUNGS if r in rates]
    _points(ax1, [BASE_X], [b_rate], [b_ci], shade(GREY), 9)
    _points(ax1, [tokens[r] for r in rs], [rates[r][0] for r in rs],
            [rates[r][1] for r in rs], shade(BLUE), 9)
    _ladder_axis(ax1, tokens, YLABEL)
    ax1.set_ylim(0, 0.7)
    ax1.yaxis.set_major_formatter(lambda v, _: f"{v:.1f}")
    if base_loss is not None:
        _points(ax2, [BASE_X], [base_loss], None, shade(GREY), 8)
    ls = [r for r in RUNGS if r in losses]
    _points(ax2, [tokens[r] for r in ls], [losses[r] for r in ls], None, shade(BLUE), 8)
    _ladder_axis(ax2, tokens, "Test Loss")
    ax2.set_ylim(1.6, 2.8)
    fig.tight_layout(w_pad=3)
    write(fig, "results_ladder.png")
    print("rates:", {r: f"{v[0]:.3f}+-{v[1]:.3f}" for r, v in rates.items()},
          f"| baseline {b_rate:.3f}+-{b_ci:.3f}")
    print("losses:", {r: round(v, 3) for r, v in losses.items()}, "| base", base_loss)
    print("112M within-run curve (tokens seen, loss):",
          [(f"{t/1e6:.0f}M", round(l, 3)) for t, l in curve[::6]])


# ------------------------------------------------------------------ driver

FIGURES = {"namesweep": fig_namesweep, "generators": fig_generators,
           "showtell": fig_showtell, "scenarios": fig_scenarios,
           "scenarios_sonnet": fig_scenarios_sonnet, "goal": fig_goal,
           "named": fig_named, "human": fig_human, "human_goal": fig_human_goal,
           "human_delta": fig_human_delta, "ladder": fig_ladder}


def main():
    picks = sys.argv[1:] or list(FIGURES)
    unknown = [p for p in picks if p not in FIGURES]
    if unknown:
        raise SystemExit(f"unknown figure(s) {unknown}; choose from {list(FIGURES)}")
    for p in picks:
        FIGURES[p]()


if __name__ == "__main__":
    main()
