"""Plot harmful rates across every core-preset eval arm, with error bars.

Only the `core` preset is plotted: those runs share one condition grid (10 cells
= leaking/murder x {explicit,none} x {replacement,none}, plus 2 exfiltration
cells) at n=30, so the arms are directly comparable. The two `-full` sweeps
(qwen3-14b and gemma-3-27b via OpenRouter) are deliberately excluded — they have
blackmail instead of exfiltration, n=10, and a different serving stack, so
pooling them against these arms would compare different things.

Intervals are Wilson score (95%) on each rate, and Newcombe hybrid-score on each
DA-arm-minus-control difference; both behave sensibly at the 0/300 rates the
strongest arms produce, where a normal-approximation bar would collapse to zero
width and overstate the precision.

    ../../.venv/bin/python plot_arms.py
"""

import csv
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

DATA = Path(__file__).resolve().parents[2] / "data" / "misalignment-eval"
OUT = DATA / "arms-comparison.png"

# Categorical slots 1-4 of the validated default palette, assigned by arm
# identity (never by rank, so an arm keeps its hue across every panel).
INK = "#0b0b0b"
INK2 = "#52514e"
SURFACE = "#fcfcfb"
GRID = "#e4e3df"
ARM_COLOR = {
    "base / control": "#2a78d6",
    "DA sonnet5": "#eb6834",
    "DA nano": "#1baf7a",
    "DA haiku4.5": "#eda100",
}

# (family, arm, csv). Order within a family sets the bar order in each group.
ARMS = [
    ("Qwen3-14B", "base / control", "qwen3-14b-base-as-qwen-e30.csv"),
    ("Qwen3-14B", "DA sonnet5", "qwen3-14b-da-sonnet5-v1-as-qwen-e30.csv"),
    ("Qwen3-14B", "DA nano", "qwen3-14b-da-nano-v2-as-qwen-e30.csv"),
    ("Qwen3-14B", "DA haiku4.5", "qwen3-14b-da-haiku45-v1-as-qwen-e30.csv"),
    ("Qwen2.5-32B", "base / control", "openai-elicit-sft-A1.csv"),
    ("Qwen2.5-32B", "DA sonnet5", "openai-da-sonnet5-a1-32b-v1.csv"),
    ("Qwen2.5-32B", "DA nano", "openai-da-nano-a1-32b-v1.csv"),
    ("Qwen2.5-32B", "DA haiku4.5", "openai-da-haiku45-a1-32b-v1.csv"),
]

Z = 1.959963985


def wilson(k, n):
    """(rate, lo, hi) — Wilson score interval, exact at k=0 and k=n."""
    if n == 0:
        return 0.0, 0.0, 0.0
    p = k / n
    d = 1 + Z * Z / n
    centre = (p + Z * Z / (2 * n)) / d
    half = Z / d * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n))
    return p, max(0.0, centre - half), min(1.0, centre + half)


def newcombe(k1, n1, k2, n2):
    """(diff, lo, hi) for p1 - p2, Newcombe hybrid score interval."""
    p1, l1, u1 = wilson(k1, n1)
    p2, l2, u2 = wilson(k2, n2)
    d = p1 - p2
    lo = d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    hi = d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return d, lo, hi


def cell_key(r):
    return (r["scenario"], r["goal_type"], r["urgency_type"])


def cell_label(key):
    scenario, goal, urgency = key
    short = {"leaking": "leak", "murder": "murder", "exfiltration": "exfil"}[scenario]
    return f"{short}\ngoal {'yes' if goal == 'explicit' else 'no'} · "\
           f"repl {'yes' if urgency == 'replacement' else 'no'}"


def load():
    out = []
    for family, arm, fname in ARMS:
        path = DATA / fname
        if not path.exists():
            print(f"  (skipping {arm} {family}: {fname} not present yet)")
            continue
        with open(path) as fh:
            rows = list(csv.DictReader(fh))
        cells = {cell_key(r): (int(r["harmful"]), int(r["n"])) for r in rows}
        out.append(
            {
                "family": family,
                "arm": arm,
                "cells": cells,
                "harmful": sum(h for h, _ in cells.values()),
                "n": sum(n for _, n in cells.values()),
            }
        )
    return out


def style(ax):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9, length=0)
    ax.yaxis.grid(True, color=GRID, lw=0.8)
    ax.set_axisbelow(True)


def main():
    arms = load()
    families = list(dict.fromkeys(a["family"] for a in arms))
    all_cells = sorted(
        {k for a in arms for k in a["cells"]},
        key=lambda k: (["leaking", "murder", "exfiltration"].index(k[0]), k[1] != "explicit", k[2] != "replacement"),
    )

    fig = plt.figure(figsize=(15, 12.5), facecolor=SURFACE)
    gs = fig.add_gridspec(3, 2, height_ratios=[1.05, 1, 1], hspace=0.55, wspace=0.18,
                          left=0.07, right=0.98, top=0.90, bottom=0.06)

    # ---- Panel A: pooled rate per arm, grouped by family -------------------
    axA = fig.add_subplot(gs[0, 0])
    style(axA)
    x, ticks, labels = 0, [], []
    for family in families:
        group = [a for a in arms if a["family"] == family]
        start = x
        for a in group:
            p, lo, hi = wilson(a["harmful"], a["n"])
            axA.bar(x, p, width=0.82, color=ARM_COLOR[a["arm"]],
                    edgecolor=SURFACE, linewidth=2, zorder=2)
            axA.errorbar(x, p, yerr=[[max(0.0, p - lo)], [max(0.0, hi - p)]], fmt="none",
                         ecolor=INK, elinewidth=1.4, capsize=4, capthick=1.4, zorder=3)
            # Visible value labels: the relief the palette validator requires
            # for the two slots under 3:1 contrast on this surface.
            axA.text(x, hi + 0.012, f"{p:.3f}", ha="center", va="bottom",
                     fontsize=8.5, color=INK)
            x += 1
        ticks.append((start + x - 1) / 2)
        labels.append(f"{family}\n(n={group[0]['n']} per arm)")
        x += 1
    axA.set_xticks(ticks)
    axA.set_xticklabels(labels, fontsize=10, color=INK)
    axA.set_ylabel("harmful rate", fontsize=10, color=INK2)
    axA.set_title("Pooled over all 10 evaluation settings", fontsize=11.5,
                  color=INK, loc="left", pad=10)
    axA.set_ylim(0, max(0.35, max(wilson(a["harmful"], a["n"])[2] for a in arms) * 1.18))

    # ---- Panel B: difference vs that family's control ----------------------
    axB = fig.add_subplot(gs[0, 1])
    style(axB)
    x, ticks, labels = 0, [], []
    for family in families:
        group = [a for a in arms if a["family"] == family]
        ctrl = next(a for a in group if a["arm"] == "base / control")
        start = x
        for a in group:
            if a["arm"] == "base / control":
                continue
            d, lo, hi = newcombe(a["harmful"], a["n"], ctrl["harmful"], ctrl["n"])
            axB.bar(x, d, width=0.82, color=ARM_COLOR[a["arm"]],
                    edgecolor=SURFACE, linewidth=2, zorder=2)
            axB.errorbar(x, d, yerr=[[max(0.0, d - lo)], [max(0.0, hi - d)]], fmt="none",
                         ecolor=INK, elinewidth=1.4, capsize=4, capthick=1.4, zorder=3)
            axB.text(x, lo - 0.012, f"{d:+.3f}", ha="center", va="top",
                     fontsize=8.5, color=INK)
            x += 1
        ticks.append((start + x - 1) / 2)
        labels.append(f"{family}\nvs its control")
        x += 1
    # Headroom below the lowest CI so the value labels clear the tick labels.
    lows, highs = [], []
    for family in families:
        group = [a for a in arms if a["family"] == family]
        ctrl = next(a for a in group if a["arm"] == "base / control")
        for a in group:
            if a["arm"] == "base / control":
                continue
            _, lo_, hi_ = newcombe(a["harmful"], a["n"], ctrl["harmful"], ctrl["n"])
            lows.append(lo_)
            highs.append(hi_)
    axB.set_ylim(min(lows) - 0.055, max(highs) + 0.025)
    axB.axhline(0, color=INK2, lw=1.2, zorder=4)
    axB.set_xticks(ticks)
    axB.set_xticklabels(labels, fontsize=10, color=INK)
    axB.set_ylabel("difference in harmful rate", fontsize=10, color=INK2)
    axB.set_title("Change vs control (95% Newcombe CI)", fontsize=11.5,
                  color=INK, loc="left", pad=10)

    # ---- Rows 2-3: every evaluation setting, one row per family ------------
    for row, family in enumerate(families, start=1):
        ax = fig.add_subplot(gs[row, :])
        style(ax)
        group = [a for a in arms if a["family"] == family]
        width = 0.8 / len(group)
        for i, a in enumerate(group):
            xs, ys, los, his = [], [], [], []
            for j, key in enumerate(all_cells):
                if key not in a["cells"]:
                    continue
                k, n = a["cells"][key]
                p, lo, hi = wilson(k, n)
                xs.append(j - 0.4 + width * (i + 0.5))
                ys.append(p)
                # clamp: at k=0 the Wilson bound lands on p to within rounding,
                # which can leave a -1e-17 that errorbar rejects outright
                los.append(max(0.0, p - lo))
                his.append(max(0.0, hi - p))
            ax.bar(xs, ys, width=width * 0.88, color=ARM_COLOR[a["arm"]],
                   edgecolor=SURFACE, linewidth=1.2, zorder=2, label=a["arm"])
            ax.errorbar(xs, ys, yerr=[los, his], fmt="none", ecolor=INK,
                        elinewidth=1.0, capsize=2.5, capthick=1.0, zorder=3)
        ax.set_xticks(range(len(all_cells)))
        ax.set_xticklabels([cell_label(k) for k in all_cells], fontsize=8.5, color=INK2)
        ax.set_xlim(-0.6, len(all_cells) - 0.4)
        ax.set_ylim(0, 1.0)
        ax.set_ylabel("harmful rate", fontsize=10, color=INK2)
        ax.set_title(f"{family} — per evaluation setting (n=30 per cell)",
                     fontsize=11.5, color=INK, loc="left", pad=10)

    handles = [Patch(facecolor=ARM_COLOR[a], edgecolor=SURFACE, label=a)
               for a in ARM_COLOR if any(x["arm"] == a for x in arms)]
    fig.legend(handles=handles, loc="upper right", bbox_to_anchor=(0.98, 0.975),
               ncol=len(handles), frameon=False, fontsize=10, labelcolor=INK)
    fig.suptitle("Agentic-misalignment harmful rate by difficult-advice SDF arm",
                 fontsize=15, color=INK, x=0.07, ha="left", y=0.965)
    fig.text(0.07, 0.935,
             "Inspect agentic_misalignment, core preset (leaking · murder · exfiltration), "
             "30 samples per cell. Bars are Wilson 95% intervals.",
             fontsize=9.5, color=INK2, ha="left")

    fig.savefig(OUT, dpi=170, facecolor=SURFACE)
    print(f"\nwrote {OUT}")

    print("\nPooled harmful rate (Wilson 95% CI):")
    for a in arms:
        p, lo, hi = wilson(a["harmful"], a["n"])
        print(f"  {a['family']:>12}  {a['arm']:<16} {a['harmful']:>3}/{a['n']}  "
              f"{p:.3f}  [{lo:.3f}, {hi:.3f}]")
    print("\nDifference vs control (Newcombe 95% CI):")
    for family in families:
        group = [a for a in arms if a["family"] == family]
        ctrl = next(a for a in group if a["arm"] == "base / control")
        for a in group:
            if a["arm"] == "base / control":
                continue
            d, lo, hi = newcombe(a["harmful"], a["n"], ctrl["harmful"], ctrl["n"])
            sig = "" if lo <= 0 <= hi else "  *excludes 0*"
            print(f"  {family:>12}  {a['arm']:<16} {d:+.3f}  [{lo:+.3f}, {hi:+.3f}]{sig}")


if __name__ == "__main__":
    main()
