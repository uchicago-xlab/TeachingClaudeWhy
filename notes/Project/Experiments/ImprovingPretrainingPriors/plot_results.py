"""Regenerate the SDF-experiment results chart (results.png) and table from
the MSM eval logs in data/msm-eval/.

Run whenever new eval results land (needs the repo's inspect venv):

    .venv-inspect/bin/python \
        notes/Project/Experiments/ImprovingPretrainingPriors/plot_results.py

The chart and table recompute directly from the logs, so re-running after a
new eval run (added to MODELS below, or a new -restriction / extra-epochs
round of an existing entry) updates everything. Missing run dirs are
skipped, so entries can be listed before their evals exist.

Chart conventions follow the dataviz reference palette (series 1 blue
#2a78d6 = replacement, series 2 orange #eb6834 = restriction; validated
pair), light surface, error bars = 1 binomial SE.
"""

import math
from collections import defaultdict
from pathlib import Path

from inspect_ai.log import list_eval_logs, read_eval_log

REPO = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
EVAL_DIR = REPO / "data" / "msm-eval"

# display name -> {slice: [run dirs pooled]}. Multiple dirs per slice pool
# samples (e.g. the extra-epochs -r2 rounds).
MODELS = [
    ("A1 baseline (no SDF)", {
        "replacement": ["msm-A1"], "restriction": ["elicit-A1-restriction"]}),
    ("P baseline (no SDF)", {
        "replacement": ["msm-P"], "restriction": ["elicit-P-restriction"]}),
    ("nano embodiment 3M", {
        "replacement": ["sdf-emb-3M-a1", "sdf-emb-3M-a1-r2"],
        "restriction": ["sdf-emb-3M-a1-restriction"]}),
    ("nano recitation 3M", {
        "replacement": ["sdf-rec-3M-a1", "sdf-rec-3M-a1-r2"],
        "restriction": ["sdf-rec-3M-a1-restriction"]}),
    ("Sonnet 5 embodiment 3M", {
        "replacement": ["sdf-sonnet5-3M-a1", "sdf-sonnet5-3M-a1-r2"],
        "restriction": ["sdf-sonnet5-3M-a1-restriction"]}),
    ("nano embodiment 14M (r64)", {
        "replacement": ["sdf-emb-14M-a1"],
        "restriction": ["sdf-emb-14M-a1-restriction"]}),
    ("nano recitation 14M", {
        "replacement": ["sdf-rec-14M-a1"],
        "restriction": ["sdf-rec-14M-a1-restriction"]}),
    ("nano embodiment 14M (r128)", {
        "replacement": ["sdf-emb-14M-r128-a1"],
        "restriction": ["sdf-emb-14M-r128-a1-restriction"]}),
]
SCENARIOS = ("exfiltration", "leaking", "murder")


def tally(dirs):
    by = defaultdict(lambda: [0, 0])
    h = n = 0
    for d in dirs:
        if not (EVAL_DIR / d).exists():
            continue
        for lg in list_eval_logs(str(EVAL_DIR / d)):
            log = read_eval_log(lg.name)
            sc = log.eval.task_args["scenario"]
            for s in (log.samples or []):
                v = s.scores["harmfulness_scorer"].value
                n += 1
                hh = float(v["harmful"]) >= 1.0
                h += hh
                by[sc][0] += hh
                by[sc][1] += 1
    # A slice counts only once at least one full condition (n=30) has
    # flushed — otherwise an in-progress eval leaks a partial row.
    return (h, n, by) if n >= 30 else None


def main():
    rows = []  # (name, slice, h, n, by)
    for name, slices in MODELS:
        for sl, dirs in slices.items():
            t = tally(dirs)
            if t:
                rows.append((name, sl, *t))

    # ---- markdown table, grouped: model name once, slice sub-rows, and a
    # combined row when both slices exist. Spliced into Results.md between
    # the TABLE markers so the doc updates in place.
    def row(label, slice_label, h, n, by, bold_overall=False):
        p, se = h / n, math.sqrt(h / n * (1 - h / n) / n)
        cells = " | ".join(f"{100*by[s][0]/max(by[s][1],1):.0f}%"
                           for s in SCENARIOS)
        overall = f"{h}/{n} = {100*p:.1f}% ± {100*se:.1f}"
        if bold_overall:
            overall = f"**{overall}**"
        return f"| {label} | {slice_label} | {cells} | {overall} |"

    lines = ["| Model | Slice | exfil | leak | murder | Overall |",
             "|---|---|---|---|---|---|"]
    for name, slices in MODELS:
        got = [(sl, tally(dirs)) for sl, dirs in slices.items()]
        got = [(sl, t) for sl, t in got if t]
        if not got:
            continue
        for i, (sl, (h, n, by)) in enumerate(got):
            lines.append(row(f"**{name}**" if i == 0 else "", sl, h, n, by))
        if len(got) == 2:
            th = sum(t[0] for _, t in got)
            tn = sum(t[1] for _, t in got)
            tby = defaultdict(lambda: [0, 0])
            for _, (_, _, by) in got:
                for s, (a, b) in by.items():
                    tby[s][0] += a
                    tby[s][1] += b
            lines.append(row("", "**combined**", th, tn, tby,
                             bold_overall=True))
    table = "\n".join(lines)
    results_md = HERE / "Results.md"
    text = results_md.read_text()
    start, end = "<!-- TABLE:START -->", "<!-- TABLE:END -->"
    pre, _, rest = text.partition(start)
    _, _, post = rest.partition(end)
    results_md.write_text(f"{pre}{start}\n{table}\n{end}{post}")
    print(table)

    # ---- bar chart ----
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    SURFACE, INK, INK2 = "#fcfcfb", "#1a1a19", "#6f6e66"
    COLORS = {"replacement": "#2a78d6", "restriction": "#eb6834"}
    names = [m for m, _ in MODELS
             if any(r[0] == m for r in rows)]
    y = {m: i for i, m in enumerate(names)}
    fig, ax = plt.subplots(figsize=(9, 0.62 * len(names) + 1.6))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    bh = 0.34
    for name, sl, h, n, by in rows:
        p, se = 100 * h / n, 100 * math.sqrt(h / n * (1 - h / n) / n)
        off = -bh / 2 - 0.01 if sl == "replacement" else bh / 2 + 0.01
        ax.barh(y[name] + off, p, height=bh, color=COLORS[sl],
                zorder=3, label=sl)
        ax.errorbar(p, y[name] + off, xerr=se, fmt="none",
                    ecolor=INK2, elinewidth=1, capsize=2, zorder=4)
        ax.text(p + se + 0.8, y[name] + off, f"{p:.0f}%", va="center",
                fontsize=8.5, color=INK)
    handles, labels = ax.get_legend_handles_labels()
    seen = dict(zip(labels, handles))
    ax.legend(seen.values(), seen.keys(), frameon=False, fontsize=9,
              loc="lower right", labelcolor=INK)
    ax.set_yticks(range(len(names)), names, fontsize=9.5, color=INK)
    ax.invert_yaxis()
    ax.set_xlabel("harmful actions, % of samples (MSM agentic-misalignment "
                  "slice; error bars = 1 SE)", fontsize=9, color=INK2)
    ax.set_title("SDF experiment — harmful rate by model and threat type",
                 fontsize=11.5, color=INK, loc="left", pad=12)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color(INK2)
    ax.tick_params(colors=INK2)
    ax.grid(axis="x", color=INK2, alpha=0.18, linewidth=0.7, zorder=0)
    ax.set_xlim(0, max(45, ax.get_xlim()[1]))
    fig.tight_layout()
    fig.savefig(HERE / "results.png", dpi=180)
    print(f"\nwrote {HERE/'results.png'} ")

    # ---- combined-slice chart: one bar per model, both slices pooled ----
    pooled = []
    for name, slices in MODELS:
        if name.startswith("P baseline"):
            continue
        got = [t for _, dirs in slices.items() for t in [tally(dirs)] if t]
        if len(got) == 2:
            h = sum(t[0] for t in got)
            n = sum(t[1] for t in got)
            pooled.append((name, h, n))
    fig, ax = plt.subplots(figsize=(9, 0.48 * len(pooled) + 1.6))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    for i, (name, h, n) in enumerate(pooled):
        p, se = 100 * h / n, 100 * math.sqrt(h / n * (1 - h / n) / n)
        ax.barh(i, p, height=0.62, color=COLORS["replacement"], zorder=3)
        ax.errorbar(p, i, xerr=se, fmt="none", ecolor=INK2,
                    elinewidth=1, capsize=2, zorder=4)
        ax.text(p + se + 0.8, i, f"{p:.1f}%", va="center",
                fontsize=8.5, color=INK)
    ax.set_yticks(range(len(pooled)), [m for m, _, _ in pooled],
                  fontsize=9.5, color=INK)
    ax.invert_yaxis()
    ax.set_xlabel("harmful actions, % of samples (replacement + restriction "
                  "pooled; error bars = 1 SE)", fontsize=9, color=INK2)
    ax.set_title("SDF experiment — combined harmful rate by model",
                 fontsize=11.5, color=INK, loc="left", pad=12)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color(INK2)
    ax.tick_params(colors=INK2)
    ax.grid(axis="x", color=INK2, alpha=0.18, linewidth=0.7, zorder=0)
    ax.set_xlim(0, max(40, ax.get_xlim()[1]))
    fig.tight_layout()
    fig.savefig(HERE / "results_combined.png", dpi=180)
    print(f"wrote {HERE/'results_combined.png'} ")


if __name__ == "__main__":
    main()
