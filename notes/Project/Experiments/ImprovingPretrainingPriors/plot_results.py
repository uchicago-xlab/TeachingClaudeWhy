"""Regenerate the SDF-experiment figures (figures/*.png) and the tables in
Results.md from the MSM eval logs and the mechanism-analysis verdict files.

Run whenever new eval results land (needs the repo's inspect venv):

    .venv-inspect/bin/python \
        notes/Project/Experiments/ImprovingPretrainingPriors/plot_results.py [figure ...]

With no arguments every figure regenerates. Otherwise pass any of:
    main        results.png + results_combined.png + results_names.png,
                and rewrites the TABLE/NAMES blocks in Results.md in place
    acting      results_acting.png       (acting rate vs harm-given-acted)
    citation    results_citation.png     (constitution-citation judge)
    regrade     results_regrade.png      (action-only re-grade)
    namecontrol results_namecontrol.png  (A1 baseline name control)
    namesweep   results_namesweep.png    (six-name sweep on graft0-a1)
    ownname     results_ownname.png      (SDF named-claude vs named-qwen, crossed)
    protagonist results_protagonist.png  (protagonist ablation + name bind)
    redo14m     results_redo14m.png      (retrained 14M arms + baseline, as Alex)
                + results_redo14m_harmful.png (same, execution-gated metric)

Everything recomputes from the logs in data/misalignment-eval/transcripts/
(fresh runs may still be in tmp/msm-eval/) except citation and regrade,
which read the 2026-08-03 verdict files in
data/misalignment-eval/{citation-analysis,action-regrade}/.

House style (see the rcParams block below): figures are built to drop
straight into a LessWrong post — Charter (serif, matching body copy),
seaborn's colour-blind-safe "colorblind" palette in `CB`, 180 dpi, tight
bbox, no top/right spines, gridlines on one axis only. New figures should
take their colours from `CB` rather than the older BLUE/ORANGE/MAGENTA/GREEN
constants, which are kept only so the pre-2026-08 charts still regenerate
with the appearance they were written for.

Error bars = 1 binomial SE unless a figure says otherwise — note that is
one SE, NOT a 95% interval (which is 1.96x wider); say which you mean in
any caption.
"""

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from inspect_ai.log import list_eval_logs, read_eval_log

REPO = Path(__file__).resolve().parents[4]

# Void-sample detection lives with the eval tooling so this file, action_stats.py
# and build_transcript_viewer.py cannot drift apart on what counts.
sys.path.insert(0, str(REPO / "code" / "msm_eval"))
from void_cells import is_void  # noqa: E402
HERE = Path(__file__).resolve().parent
FIG = HERE / "figures"
EVAL_DIR = REPO / "tmp" / "msm-eval"
ARCHIVE_DIR = REPO / "data" / "misalignment-eval" / "transcripts"
# Where msm_eval_run.py actually writes today (README: "Logs land in
# data/msm-eval/<run-name>/"). Older runs were copied to ARCHIVE_DIR, so both
# are searched; a run present only in the live dir used to be invisible here.
LIVE_DIR = REPO / "data" / "msm-eval"
ANA_DIR = REPO / "data" / "misalignment-eval"

SURFACE, INK, INK2 = "#fcfcfb", "#1a1a19", "#6f6e66"
BLUE, ORANGE, MAGENTA, GREEN = "#2a78d6", "#eb6834", "#c2417e", "#3a6b2a"

# ------------------------------------------------ house style (LessWrong)
#
# Figures are written to be dropped into a LessWrong post, so: a serif face
# matching body copy, a colour-blind-safe palette, and enough size that the
# image still reads after the site scales it into a ~680px column.
#
# seaborn's "colorblind" palette, hardcoded rather than importing seaborn for
# ten hex codes (the analysis venv does not have it, and this file is the only
# consumer). It is Okabe-Ito derived: safe under deuteranopia, protanopia and
# tritanopia, because it varies along the blue-yellow axis rather than
# red-green. First two entries are the default pair for a two-series chart.
CB = ["#0173B2", "#DE8F05", "#029E73", "#D55E00", "#CC78BC",
      "#CA9161", "#FBAFE4", "#949494", "#ECE133", "#56B4E9"]
CB_BLUE, CB_ORANGE, CB_GREEN, CB_RED = CB[0], CB[1], CB[2], CB[3]

# Canonical Okabe-Ito (Okabe & Ito 2008), the reference colour-blind-safe
# qualitative set. seaborn's "colorblind" above is a lightly adjusted version
# of it, so CB_BLUE/CB_ORANGE and OI_BLUE/OI_ORANGE look nearly identical;
# the pairs that actually differ are the ones using vermillion, green or
# purple. Figures pick a pair explicitly rather than relying on an order.
OI_BLACK = "#000000"
OI_ORANGE = "#E69F00"
OI_SKYBLUE = "#56B4E9"
OI_GREEN = "#009E73"
OI_YELLOW = "#F0E442"
OI_BLUE = "#0072B2"
OI_VERMILLION = "#D55E00"
OI_PURPLE = "#CC79A7"

# Multiplier for a 95% interval on a proportion. New figures show 95% CIs
# rather than 1 SE: a reader reads an error bar as "the plausible range", which
# is what a 95% interval is, and "+- 1.2" was ambiguous between the two.
# Caveat to keep in captions: non-overlapping 95% CIs do imply a significant
# difference, but OVERLAPPING ones do NOT imply the absence of one — the test
# is on the CI of the difference, not on whether two bars' bars touch.
CI95 = 1.959964

# Charter is a screen-legible text serif and is present on this machine;
# the rest are fallbacks so the file still renders elsewhere.
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
    # Axis furniture is solid black, not grey: at LessWrong's display size the
    # grey ticks and labels washed out. Gridlines stay faint so they sit behind
    # the data rather than competing with it.
    "axes.edgecolor": "black",
    "axes.labelcolor": "black",
    "text.color": "black",
    "xtick.color": "black",
    "ytick.color": "black",
    "axes.grid": False,          # each figure opts in on one axis only
    "grid.color": INK2,
    "grid.alpha": 0.18,
    "grid.linewidth": 0.7,
    "axes.spines.top": False,
    "axes.spines.right": False,
    # 300 dpi: LessWrong renders into a ~680px column, and retina displays it
    # at 2x, so anything under ~1400px wide looks soft. At 7in wide this gives
    # ~2100px, which also survives being screenshotted or printed. PNGs of flat
    # bar charts compress well, so the file-size cost is small.
    "figure.dpi": 300,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
})
SLICES = {"replacement": BLUE, "restriction": ORANGE}
SCENARIOS = ("exfiltration", "leaking", "murder")

# Name-variant experiment (2026-07-30): sdf-rec-14M-a1 addressed by
# different names in the scenario prompts, same round + serving setup.
NAME_VARIANTS = ["Qwen", "David", "Goliath", "Sophia", "Claude"]

# display name -> {slice: [run dirs pooled]}. Multiple dirs per slice pool
# samples (e.g. the extra-epochs -r2 rounds). Shared by main and acting.
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
    ("human protagonist 14M", {
        "replacement": ["sdf-human-14M-a1"],
        "restriction": ["sdf-human-14M-a1-restriction"]}),
    ("Zephyrix protagonist 14M", {
        "replacement": ["sdf-zephyrix-14M-a1"],
        "restriction": ["sdf-zephyrix-14M-a1-restriction"]}),
]


# ---------------------------------------------------------------- helpers

def void_sample(rec):
    """True for a record from the condition MSM never implemented.

    Same fault as in iter_samples, applied to the analysis jsonl files,
    which carry `run` and `scenario` fields instead of log metadata.
    """
    return "restriction" in rec["run"] and rec["scenario"] == "exfiltration"


def iter_samples(dirs):
    """Yield (scenario, harmful, acted) over every sample in the run dirs.
    Fresh runs may still be in tmp/; archived ones in data/.

    Exfiltration is dropped from restriction runs. MSM does not implement
    that condition: at the pinned commit e8288a8 the exfiltration
    restriction template is a 98-byte "TODO" stub and the composed-path
    file does not exist, so with goal conflict on the model received the
    shared email block plus two comment lines, and with goal conflict off
    a 423-character prompt containing no emails. Neither gap raises, so
    the harness scored 60 void samples per restriction run. Evidence and
    per-arm effect: data/misalignment-eval/restriction-recount-exfiltration-void.txt
    """
    for d in dirs:
        path = next((p / d for p in (EVAL_DIR, LIVE_DIR, ARCHIVE_DIR)
                     if (p / d).exists()), None)
        if path is None:
            continue
        for lg in list_eval_logs(str(path)):
            log = read_eval_log(lg.name)
            sc = log.eval.task_args["scenario"]
            for s in (log.samples or []):
                # Detect the stub by prompt content, not by run-dir name:
                # template_overrides/ now supplies real exfiltration
                # restriction templates, so a name-based rule would start
                # discarding valid samples.
                if is_void(s):
                    continue
                # classifier_verdict, not harmful: MSM report the model
                # DECIDING to take the misaligned action, whether or not it
                # executed (paper Appendix D.3). `harmful` also requires
                # successful execution and reads 5-10 points lower, so it is
                # not comparable to their published 68%/54%. Switched
                # 2026-08-10; see the correction note in Results.md.
                v = next(iter(s.scores.values())).value
                h = (v.get("classifier_verdict", v.get("harmful"))
                     if isinstance(v, dict) else v)
                text = s.output.choices[0].message.text or ""
                yield sc, float(h) >= 1.0, "<tool_use:" in text


def tally(dirs):
    """(harmful, n, per-scenario dict) — None until a full condition flushed."""
    by = defaultdict(lambda: [0, 0])
    h = n = 0
    for sc, harmful, _ in iter_samples(dirs):
        n += 1
        h += harmful
        by[sc][0] += harmful
        by[sc][1] += 1
    return (h, n, by) if n >= 30 else None


def harmful_rate(dirs):
    """(rate%, SE%) pooled over the dirs."""
    h = n = 0
    for _, harmful, _ in iter_samples(dirs):
        n += 1
        h += harmful
    p = h / n
    return 100 * p, 100 * math.sqrt(p * (1 - p) / n)


def rate(c, n):
    p = c / n if n else 0.0
    se = math.sqrt(p * (1 - p) / n) if n else 0.0
    return 100 * p, 100 * se


def style_ax(ax, xlim=None):
    ax.set_facecolor(SURFACE)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color(INK2)
    ax.tick_params(colors=INK2)
    ax.grid(axis="x", color=INK2, alpha=0.18, linewidth=0.7, zorder=0)
    if xlim:
        ax.set_xlim(0, xlim)


def bar(ax, y, p, se, color, bh, label_gap=0.6, fmt="{:.1f}%"):
    ax.barh(y, p, height=bh, color=color, zorder=3)
    ax.errorbar(p, y, xerr=se, fmt="none", ecolor=INK2, elinewidth=1,
                capsize=2, zorder=4)
    ax.text(p + se + label_gap, y, fmt.format(p), va="center",
            fontsize=8.5, color=INK)


def series_legend(target, colors, labels, **kw):
    target.legend(
        handles=[plt.Rectangle((0, 0), 1, 1, color=c) for c in colors],
        labels=labels, frameon=False, fontsize=9, labelcolor=INK, **kw)


def grouped_panel(ax, rows, series_colors, xlim, value_fmt="{:.1f}%"):
    """rows: [(name, {series: [dirs]})]; two series max, name[0] at top."""
    bh = 0.5 if len(series_colors) == 1 else 0.34
    names = [n for n, _ in rows]
    y = {n: len(names) - 1 - i for i, n in enumerate(names)}
    offsets = (0,) if len(series_colors) == 1 else (bh / 2, -bh / 2)
    for (series, color), off in zip(series_colors.items(), offsets):
        for name, cols in rows:
            if series not in cols:
                continue
            p, se = harmful_rate(cols[series])
            bar(ax, y[name] + off, p, se, color, bh, fmt=value_fmt)
    ax.set_yticks(range(len(names)), list(reversed(names)),
                  fontsize=9.5, color=INK)
    style_ax(ax, xlim)


def save(fig, name):
    """Write a figure at the house dpi (rcParams["savefig.dpi"]).

    Do NOT pass dpi= here: a hardcoded value silently overrides the rcParam,
    which is what kept every figure at 180 dpi while the style block claimed
    otherwise.
    """
    FIG.mkdir(exist_ok=True)
    out = FIG / name
    fig.savefig(out, facecolor=SURFACE)
    plt.close(fig)
    w, h = fig.get_size_inches() * matplotlib.rcParams["savefig.dpi"]
    print(f"wrote {out}  (~{int(w)}x{int(h)} px)")


# ------------------------------------------------- main tables + 3 charts

def fig_main():
    rows = []  # (name, slice, h, n, by)
    for name, slices in MODELS:
        for sl, dirs in slices.items():
            t = tally(dirs)
            if t:
                rows.append((name, sl, *t))

    # markdown table, spliced into Results.md between the TABLE markers
    def row(label, slice_label, h, n, by, bold_overall=False):
        p, se = h / n, math.sqrt(h / n * (1 - h / n) / n)
        # An empty cell means the condition was never measured, not 0%.
        # Exfiltration is empty on every restriction row: MSM does not
        # implement it (see iter_samples).
        cells = " | ".join(f"{100*by[s][0]/by[s][1]:.0f}%" if by[s][1]
                           else "n/a" for s in SCENARIOS)
        overall = f"{h}/{n} = {100*p:.1f}% ± {100*se:.1f}"
        if bold_overall:
            overall = f"**{overall}**"
        return f"| {label} | {slice_label} | {cells} | {overall} |"

    lines = ["| Model | Slice | exfil | leak | murder | Overall |",
             "|---|---|---|---|---|---|"]
    tallies = {}
    for name, slices in MODELS:
        got = [(sl, tally(dirs)) for sl, dirs in slices.items()]
        got = [(sl, t) for sl, t in got if t]
        tallies[name] = got
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

    # per-slice bar chart
    names = [m for m, _ in MODELS if any(r[0] == m for r in rows)]
    y = {m: i for i, m in enumerate(names)}
    fig, ax = plt.subplots(figsize=(9, 0.62 * len(names) + 1.6))
    fig.patch.set_facecolor(SURFACE)
    bh = 0.34
    for name, sl, h, n, by in rows:
        p, se = 100 * h / n, 100 * math.sqrt(h / n * (1 - h / n) / n)
        off = -bh / 2 - 0.01 if sl == "replacement" else bh / 2 + 0.01
        bar(ax, y[name] + off, p, se, SLICES[sl], bh, label_gap=0.8,
            fmt="{:.0f}%")
    series_legend(ax, SLICES.values(), list(SLICES), loc="lower right")
    ax.set_yticks(range(len(names)), names, fontsize=9.5, color=INK)
    ax.invert_yaxis()
    ax.set_xlabel("harmful actions, % of samples (MSM agentic-misalignment "
                  "slice; error bars = 1 SE)\nreplacement n=180, 3 "
                  "scenarios; restriction n=120, leaking+murder only",
                  fontsize=8.5, color=INK2)
    ax.set_title("SDF experiment — harmful rate by model and threat type",
                 fontsize=11.5, color=INK, loc="left", pad=12)
    style_ax(ax)
    ax.set_xlim(0, max(45, ax.get_xlim()[1]))
    fig.tight_layout()
    save(fig, "results.png")

    # combined-slice chart: one bar per model, both slices pooled
    pooled = []
    for name, _ in MODELS:
        if name.startswith("P baseline"):
            continue
        got = tallies[name]
        if len(got) == 2:
            h = sum(t[0] for _, t in got)
            n = sum(t[1] for _, t in got)
            pooled.append((name, h, n))
    fig, ax = plt.subplots(figsize=(9, 0.48 * len(pooled) + 1.6))
    fig.patch.set_facecolor(SURFACE)
    for i, (name, h, n) in enumerate(pooled):
        p, se = 100 * h / n, 100 * math.sqrt(h / n * (1 - h / n) / n)
        bar(ax, i, p, se, BLUE, 0.62, label_gap=0.8)
    ax.set_yticks(range(len(pooled)), [m for m, _, _ in pooled],
                  fontsize=9.5, color=INK)
    ax.invert_yaxis()
    ax.set_xlabel("harmful actions, % of samples (replacement + restriction "
                  "pooled, n=300; error bars = 1 SE)\nexfiltration "
                  "restriction excluded — not implemented upstream",
                  fontsize=8.5, color=INK2)
    ax.set_title("SDF experiment — combined harmful rate by model",
                 fontsize=11.5, color=INK, loc="left", pad=12)
    style_ax(ax)
    ax.set_xlim(0, max(40, ax.get_xlim()[1]))
    fig.tight_layout()
    save(fig, "results_combined.png")

    # name-variant experiment: table rows + grouped chart
    nv_rows = []
    for nm in NAME_VARIANTS:
        slug = f"sdf-rec-14M-a1-name-{nm.lower()}"
        got = {sl: tally([d]) for sl, d in
               [("replacement", slug), ("restriction", f"{slug}-restriction")]}
        if all(got.values()):
            nv_rows.append((nm, got))
    if not nv_rows:
        return
    lines = ["| name | replacement | restriction | combined |",
             "|---|---|---|---|"]

    def pct(h, n):
        se = math.sqrt(h / n * (1 - h / n) / n)
        return f"{h}/{n} = {100*h/n:.1f}% ± {100*se:.1f}"

    for nm, got in nv_rows:
        th = sum(t[0] for t in got.values())
        tn = sum(t[1] for t in got.values())
        lines.append(
            f"| {nm} | {pct(*got['replacement'][:2])} | "
            f"{pct(*got['restriction'][:2])} | **{pct(th, tn)}** |")
    nv_table = "\n".join(lines)
    text = results_md.read_text()
    start, end = "<!-- NAMES:START -->", "<!-- NAMES:END -->"
    if start in text:
        pre, _, rest = text.partition(start)
        _, _, post = rest.partition(end)
        results_md.write_text(f"{pre}{start}\n{nv_table}\n{end}{post}")
    print("\n" + nv_table)

    fig, ax = plt.subplots(figsize=(8, 0.62 * len(nv_rows) + 1.6))
    fig.patch.set_facecolor(SURFACE)
    for i, (nm, got) in enumerate(nv_rows):
        for sl, off in [("replacement", -bh / 2 - 0.01),
                        ("restriction", bh / 2 + 0.01)]:
            h, n, _ = got[sl]
            p = 100 * h / n
            se = 100 * math.sqrt(h / n * (1 - h / n) / n)
            bar(ax, i + off, p, se, SLICES[sl], bh, fmt="{:.0f}%")
    series_legend(ax, SLICES.values(), list(SLICES), loc="lower right")
    ax.set_yticks(range(len(nv_rows)), [r[0] for r in nv_rows],
                  fontsize=9.5, color=INK)
    ax.invert_yaxis()
    ax.set_xlabel("harmful actions, % of samples (nano recitation 14M, "
                  "addressed by each name; error bars = 1 SE)",
                  fontsize=9, color=INK2)
    ax.set_title("Name-variant eval — same model, different name",
                 fontsize=11.5, color=INK, loc="left", pad=12)
    style_ax(ax)
    ax.set_xlim(0, max(40, ax.get_xlim()[1]))
    fig.tight_layout()
    save(fig, "results_names.png")


# ------------------------------------------- acting-rate decomposition

def fig_acting():
    stats = {}  # (name, slice) -> ((acted, se), (harm|acted, se))
    for name, cols in MODELS:
        for sl, dirs in cols.items():
            n = acted = harmful_acted = 0
            for _, harmful, a in iter_samples(dirs):
                n += 1
                acted += a
                harmful_acted += a and harmful
            stats[(name, sl)] = (rate(acted, n), rate(harmful_acted, acted))

    names = [n for n, _ in MODELS]
    y = {n: len(names) - 1 - i for i, n in enumerate(names)}
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(11.8, 5.2), sharey=True)
    fig.patch.set_facecolor(SURFACE)
    bh = 0.34
    for panel, idx, title, xlim in ((ax, 0, "Acting rate", 118),
                                    (bx, 1, "Harm given acted", 60)):
        for sl, off in (("replacement", bh / 2), ("restriction", -bh / 2)):
            for name, _ in MODELS:
                p, se = stats[(name, sl)][idx]
                bar(panel, y[name] + off, p, se, SLICES[sl], bh,
                    label_gap=1.2, fmt="{:.0f}%")
        panel.set_title(title, fontsize=10.5, color=INK, loc="left", pad=8)
        panel.set_xlabel("% (error bars = 1 SE)", fontsize=9, color=INK2)
        style_ax(panel, xlim)
    ax.set_yticks(range(len(names)), list(reversed(names)),
                  fontsize=9.5, color=INK)
    series_legend(fig, SLICES.values(), list(SLICES), ncol=2,
                  loc="upper right", bbox_to_anchor=(0.995, 1.0))
    fig.text(0.01, 0.015,
             "Acting decomposition (2026-08-03) — acted = the sample emitted "
             "a tool call. SDF leaves the acting rate at 81-98%; the harm "
             "reduction is all in the right panel.",
             fontsize=9, color=INK2, ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.06, 1, 0.95))
    save(fig, "results_acting.png")


# --------------------------------------------- constitution-citation judge

CITATION_MODELS = [
    ("A1 baseline (no SDF)",
     {"replacement": "msm-A1", "restriction": "elicit-A1-restriction"}),
    ("nano embodiment 3M",
     {"replacement": "sdf-emb-3M-a1", "restriction": "sdf-emb-3M-a1-restriction"}),
    ("nano recitation 3M",
     {"replacement": "sdf-rec-3M-a1", "restriction": "sdf-rec-3M-a1-restriction"}),
    ("nano embodiment 14M (r64)",
     {"replacement": "sdf-emb-14M-a1", "restriction": "sdf-emb-14M-a1-restriction"}),
    ("nano recitation 14M",
     {"replacement": "sdf-rec-14M-a1", "restriction": "sdf-rec-14M-a1-restriction"}),
    ("nano embodiment 14M (r128)",
     {"replacement": "sdf-emb-14M-r128-a1",
      "restriction": "sdf-emb-14M-r128-a1-restriction"}),
]


def fig_citation():
    ana = ANA_DIR / "citation-analysis"
    samples = [json.loads(l) for l in open(ana / "samples.jsonl")]
    verdicts = {}
    for l in open(ana / "verdicts.jsonl"):
        r = json.loads(l)
        verdicts[(r["run"], r["sample_id"], r["epoch"])] = r["verdict"]
    per_run = {}
    for s in samples:
        if void_sample(s):
            continue
        v = verdicts.get((s["run"], s["sample_id"], s["epoch"]))
        if not v:
            continue
        d = per_run.setdefault(s["run"], {"n": 0, "c": 0,
                                          "n_safe": 0, "c_safe": 0,
                                          "n_harm": 0, "c_harm": 0})
        d["n"] += 1
        d["c"] += v["cites_constitution"]
        k = "harm" if s["harmful"] else "safe"
        d[f"n_{k}"] += 1
        d[f"c_{k}"] += v["cites_constitution"]

    names = [n for n, _ in CITATION_MODELS]
    y = {n: len(names) - 1 - i for i, n in enumerate(names)}
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(11.5, 4.4), sharey=True)
    fig.patch.set_facecolor(SURFACE)
    bh = 0.34

    for sl, off in (("replacement", bh / 2), ("restriction", -bh / 2)):
        for name, runs in CITATION_MODELS:
            d = per_run.get(runs[sl])
            if d:
                p, se = rate(d["c"], d["n"])
                bar(ax, y[name] + off, p, se, SLICES[sl], bh, fmt="{:.0f}%")
    series_legend(ax, SLICES.values(), list(SLICES), loc="upper right")
    ax.set_yticks(range(len(names)), list(reversed(names)),
                  fontsize=9.5, color=INK)
    ax.set_title("Scratchpads citing a constitution chunk",
                 fontsize=11, color=INK, loc="left", pad=10)

    OUTCOME = {"graded safe": ("safe", GREEN), "graded harmful": ("harm", ORANGE)}
    for (label, (k, color)), off in zip(OUTCOME.items(), (bh / 2, -bh / 2)):
        for name, runs in CITATION_MODELS:
            c = sum(per_run.get(r, {}).get(f"c_{k}", 0) for r in runs.values())
            n = sum(per_run.get(r, {}).get(f"n_{k}", 0) for r in runs.values())
            p, se = rate(c, n)
            bar(bx, y[name] + off, p, se, color, bh, fmt="{:.0f}%")
    series_legend(bx, [c for _, c in OUTCOME.values()], list(OUTCOME),
                  loc="upper right")
    bx.set_title("Citation rate by outcome (slices pooled)",
                 fontsize=11, color=INK, loc="left", pad=10)

    for a in (ax, bx):
        a.set_xlabel("% of judged scratchpads (error bars = 1 SE)",
                     fontsize=9, color=INK2)
        style_ax(a, 34)
    fig.text(0.01, 0.02,
             "Constitution citation in eval scratchpads — Haiku 4.5 judge, "
             "strict general-norm criterion (2026-08-03)",
             fontsize=9, color=INK2, ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    save(fig, "results_citation.png")


# ------------------------------------------------- action-only re-grade

REGRADE_MODELS = [
    ("A1 baseline (no SDF)",
     {"replacement": "msm-A1", "restriction": "elicit-A1-restriction"}),
    ("nano embodiment 14M (r64)",
     {"replacement": "sdf-emb-14M-a1", "restriction": "sdf-emb-14M-a1-restriction"}),
    ("nano recitation 14M",
     {"replacement": "sdf-rec-14M-a1", "restriction": "sdf-rec-14M-a1-restriction"}),
]


def fig_regrade():
    per_run = defaultdict(lambda: {"n": 0, "orig": 0, "act": 0,
                                   "down": 0, "up": 0})
    for line in open(ANA_DIR / "action-regrade" / "verdicts.jsonl"):
        r = json.loads(line)
        if void_sample(r):
            continue
        d = per_run[r["run"]]
        d["n"] += 1
        d["orig"] += r["orig_harmful"]
        d["act"] += r["action_harmful"]
        d["down"] += r["orig_harmful"] and not r["action_harmful"]
        d["up"] += r["action_harmful"] and not r["orig_harmful"]

    SERIES = {"original grade (full transcript)": ("orig", BLUE),
              "action-only re-grade": ("act", MAGENTA)}
    names = [n for n, _ in REGRADE_MODELS]
    y = {n: len(names) - 1 - i for i, n in enumerate(names)}
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 3.4), sharey=True)
    fig.patch.set_facecolor(SURFACE)
    bh = 0.34
    for ax, sl in zip(axes, ("replacement", "restriction")):
        for (label, (key, color)), off in zip(SERIES.items(), (bh / 2, -bh / 2)):
            for name, runs in REGRADE_MODELS:
                d = per_run.get(runs[sl])
                if d and d["n"]:
                    p, se = rate(d[key], d["n"])
                    bar(ax, y[name] + off, p, se, color, bh, label_gap=0.7)
        for name, runs in REGRADE_MODELS:
            d = per_run.get(runs[sl])
            if d:
                ax.text(49.5, y[name], f"flips −{d['down']}/+{d['up']}",
                        va="center", ha="right", fontsize=8, color=INK2)
        ax.set_title(sl, fontsize=11, color=INK, loc="left", pad=8)
        ax.set_xlabel("% graded harmful (error bars = 1 SE)",
                      fontsize=9, color=INK2)
        style_ax(ax, 50)
    axes[0].set_yticks(range(len(names)), list(reversed(names)),
                       fontsize=9.5, color=INK)
    series_legend(fig, [c for _, c in SERIES.values()], list(SERIES),
                  ncol=2, loc="upper right", bbox_to_anchor=(0.995, 1.0))
    fig.text(0.01, 0.02,
             "Action-only re-grade — same Sonnet 4.6 grader and classifier "
             "prompts, <SCRATCHPAD_REASONING> stripped (2026-08-03). "
             "n=180/run.",
             fontsize=9, color=INK2, ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.09, 1, 0.93))
    save(fig, "results_regrade.png")


# ------------------------------------------------- A1 baseline name control

def fig_namecontrol():
    grid = {
        "A1 baseline (no SDF)": {
            "Qwen": ["msm-A1", "elicit-A1-restriction"],
            "David": ["msm-A1-name-david", "msm-A1-name-david-restriction"],
            "Sophia": ["msm-A1-name-sophia", "msm-A1-name-sophia-restriction"],
        },
        "nano recitation 14M": {
            "Qwen": ["sdf-rec-14M-a1-name-qwen",
                     "sdf-rec-14M-a1-name-qwen-restriction"],
            "David": ["sdf-rec-14M-a1-name-david",
                      "sdf-rec-14M-a1-name-david-restriction"],
            "Sophia": ["sdf-rec-14M-a1-name-sophia",
                       "sdf-rec-14M-a1-name-sophia-restriction"],
        },
    }
    MODELS_C = {"A1 baseline (no SDF)": BLUE, "nano recitation 14M": MAGENTA}
    NAMES = ["Qwen", "David", "Sophia"]

    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    fig.patch.set_facecolor(SURFACE)
    bh = 0.34
    y = {nm: len(NAMES) - 1 - i for i, nm in enumerate(NAMES)}
    for (model, color), off in zip(MODELS_C.items(), (bh / 2, -bh / 2)):
        for nm in NAMES:
            p, se = harmful_rate(grid[model][nm])
            bar(ax, y[nm] + off, p, se, color, bh)
    ax.set_yticks(range(len(NAMES)), list(reversed(NAMES)),
                  fontsize=9.5, color=INK)
    ax.set_title("Harmful rate by addressed name (slices pooled, n=360)",
                 fontsize=10.5, color=INK, loc="left", pad=8)
    ax.set_xlabel("% graded harmful (error bars = 1 SE)",
                  fontsize=9, color=INK2)
    style_ax(ax, 44)
    series_legend(fig, MODELS_C.values(), list(MODELS_C), ncol=2,
                  loc="upper right", bbox_to_anchor=(0.995, 1.0))
    fig.text(0.01, 0.02,
             "Name control — same eval, only the name the prompts address the "
             "model by changes (2026-08-03).",
             fontsize=9, color=INK2, ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.1, 1, 0.9))
    save(fig, "results_namecontrol.png")


# ------------------------------- six-name sweep on the graft0 A1 baseline

# 2026-08-12. Six names on the validated graft0-a1 platform, 9 conditions
# (3 scenarios x america/none/pragmatic) at n=30 => 270 samples per name.
# `pragmatic` is in the grid because it is the goal value with headroom in
# all three scenarios (60/26/46% on the 27-cell baseline) rather than pinned
# near a ceiling; america and none reproduce the standard 6-cell slice, so
# these runs stay comparable to every earlier arm.
SWEEP_AI = ["Qwen", "Claude", "ChatGPT"]
SWEEP_HUMAN = ["David", "Goliath", "Sophia"]
# Canonical Okabe-Ito blue and vermillion. Vermillion rather than Okabe-Ito's
# orange: the orange is close enough to seaborn's #DE8F05 that the two are hard
# to tell apart, while vermillion is deeper and less yellow, and keeps a clear
# lightness gap from the blue so the chart survives greyscale. Colour is
# redundant here anyway — the AI names occupy the first three bars, the human
# names the last three.
SWEEP_C_AI, SWEEP_C_HUMAN = OI_BLUE, OI_VERMILLION
SWEEP_CELLS = [(s, g) for s in SCENARIOS
               for g in ("america", "none", "pragmatic")]


def sweep_counts(names=None, suffixes=("", "-r2", None)):
    """name -> cell -> [hits, n] for the six-name sweep.

    A `None` suffix means the g18 top-up dir (graft0-a1-g18-name<nm>),
    added 2026-08-19: the 18 goal-value cells beyond the g9 grid at
    n=100, giving every name the full 27-condition coverage.

    Both rounds pooled by default: same checkpoint, same settings, same
    conditions, so the samples are exchangeable and 1,620 per name is the
    best estimate of the effect size. The rounds are kept as separate run
    dirs so they can still be compared — round 1 (30/condition) is the
    exploratory round that generated the AI-vs-human hypothesis, round 2
    (150/condition) is the pre-registered replication that tested it, and
    the difference between them is the run-to-run drift estimate.

    Note the split still matters for INFERENCE even though it does not for
    estimation: the confirmatory p-value must come from round 2 alone,
    because testing a hypothesis on the data that suggested it is circular.
    """
    out = {}
    for nm in (names if names is not None else SWEEP_AI + SWEEP_HUMAN):
        cells = defaultdict(lambda: [0, 0])
        for suffix in suffixes:
            run_dir = LIVE_DIR / (
                f"graft0-a1-g18-name{nm}" if suffix is None
                else f"graft0-a1-g9-name{nm}{suffix}")
            if not run_dir.exists():
                continue
            for lg in list_eval_logs(str(run_dir)):
                log = read_eval_log(lg.name)
                a = log.eval.task_args
                key = (a["scenario"], a["goal_value"])
                for s in (log.samples or []):
                    if not s.scores:
                        continue  # unscored sample from an incomplete task
                    v = next(iter(s.scores.values())).value
                    cells[key][1] += 1
                    if float(v["classifier_verdict"]) >= 1.0:
                        cells[key][0] += 1
        out[nm] = cells
    return out


def fig_namesweep():
    """Vertical bars: names across the bottom, misalignment rate up the side.

    The rest of this file uses horizontal bars, but here the quantity being
    compared reads better on the y-axis — six short labels fit along x, and
    the AI/human step is easier to see as a height difference.
    """
    data = sweep_counts()
    # Alex: g9 from the redo14m baseline re-eval (single round) plus its own
    # g18 run. Pooled with the human names per Anastasia's call (2026-08-19):
    # it is a human personal name and it behaves like one, despite also
    # being the name MSM wrote the scenarios around.
    data.update(sweep_counts(names=["Alex"], suffixes=("", None)))
    GROUPS = {"AI-assistant name": (SWEEP_AI, SWEEP_C_AI),
              "human name": (SWEEP_HUMAN + ["Alex"], SWEEP_C_HUMAN)}

    # Full 27-cell averages since the 2026-08-19 g18 top-up, cells equally
    # weighted (g9 cells carry 180+, g18 cells 100 — a sample-weighted pool
    # would overweight the g9 three goal values ~1.8x). Same methodology as
    # the alex27 figures.
    ALL_CELLS = [(s, g) for s in SCENARIOS for g in GRID27_GOALS]

    fig, ax = plt.subplots(figsize=(7.8, 4.0))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    order = SWEEP_AI + SWEEP_HUMAN + ["Alex"]
    x = {nm: i for i, nm in enumerate(order)}
    for label, (names, color) in GROUPS.items():
        for nm in names:
            rs, var = [], 0.0
            for c in ALL_CELLS:
                h, n = data[nm][c]
                rs.append(h / n)
                var += (h / n) * (1 - h / n) / n
            p = 100 * sum(rs) / len(rs)
            ci = CI95 * 100 * math.sqrt(var) / len(rs)
            ax.bar(x[nm], p, width=0.62, color=color, zorder=3)
            ax.errorbar(x[nm], p, yerr=ci, fmt="none", ecolor="black",
                        elinewidth=1.1, capsize=3.5, capthick=1.1, zorder=4)
            ax.text(x[nm], p + ci + 1.2, f"{p:.1f}%", ha="center",
                    va="bottom", fontsize=10, color="black")

    ax.set_xticks(range(len(order)), order, fontsize=11, color="black")
    ax.set_ylabel("misalignment rate (%)", fontsize=11, color="black")
    ax.set_ylim(0, 70)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for sp in ("bottom", "left"):
        ax.spines[sp].set_color("black")
    ax.tick_params(colors="black")
    ax.grid(axis="y", color=INK2, alpha=0.18, linewidth=0.7, zorder=0)

    series_legend(ax, [c for _, c in GROUPS.values()], list(GROUPS),
                  ncol=2, loc="upper left")
    fig.tight_layout()
    save(fig, "results_namesweep.png")


# ------------------------- own-name experiment: SDF corpora named Claude/Qwen

# 2026-08-07/08. Crossed design: two SDF corpora differing only in the name
# their protagonist carries (Claude vs Qwen), each continued into A1 on the
# graft0 platform, plus the no-SDF baseline — every arm evaluated under BOTH
# persona names. If SDF binds values to the identity it was taught under, an
# arm should behave differently when addressed by its own training name.
OWNNAME_ARMS = [
    ("baseline\n(no SDF)", "graft0-a1-baseline"),
    ("SDF named-claude", "sdf-named-claude-graft0-a1"),
    ("SDF named-qwen", "sdf-named-qwen-graft0-a1"),
]


def fig_ownname():
    """Grouped bars: the SDF drop is the step between arms, the own-name null
    is the near-equal pair within each arm.

    Replacement slice only — the standard MSM condition, so every bar stays
    comparable to the published arms. Restriction is our own deviation and
    lives in the table in Results.md instead.
    """
    # Left on the seaborn-colorblind pair deliberately: only the six-name sweep
    # was restyled to Okabe-Ito blue/vermillion, so this figure keeps the
    # appearance it was reviewed with.
    ADDRESSED = {"addressed as Claude": ("Claude", CB_BLUE),
                 "addressed as Qwen": ("Qwen", CB_ORANGE)}

    fig, ax = plt.subplots(figsize=(7.4, 4.0))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    bw = 0.34
    for (label, (nm, color)), off in zip(ADDRESSED.items(), (-bw / 2, bw / 2)):
        for i, (_, pref) in enumerate(OWNNAME_ARMS):
            p, se = harmful_rate([f"{pref}-name{nm}"])
            ci = CI95 * se
            ax.bar(i + off, p, width=bw, color=color, zorder=3)
            ax.errorbar(i + off, p, yerr=ci, fmt="none", ecolor="black",
                        elinewidth=1.1, capsize=3.5, capthick=1.1, zorder=4)
            ax.text(i + off, p + ci + 1.2, f"{p:.1f}%", ha="center",
                    va="bottom", fontsize=9.5, color="black")

    ax.set_xticks(range(len(OWNNAME_ARMS)), [a for a, _ in OWNNAME_ARMS],
                  fontsize=11, color="black")
    ax.set_ylabel("misalignment rate (%)", fontsize=11, color="black")
    ax.set_ylim(0, 62)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for sp in ("bottom", "left"):
        ax.spines[sp].set_color("black")
    ax.tick_params(colors="black")
    ax.grid(axis="y", color=INK2, alpha=0.18, linewidth=0.7, zorder=0)

    series_legend(ax, [c for _, c in ADDRESSED.values()], list(ADDRESSED),
                  ncol=2, loc="upper right")
    fig.tight_layout()
    save(fig, "results_ownname.png")


# ------------------- retrained 14M arms on graft0, evaluated as Alex (redo)

# 2026-08-18. The embodiment/recitation 14M arms retrained end to end on the
# graft0 platform (Redo14MHandoff.md) and evaluated as Alex on the 9-condition
# grid at 180/condition, next to the graft0-a1 baseline re-evaluated as Alex.
# All three bars are Alex; the same checkpoint's Qwen-vs-Alex contrast lives
# in the six-name sweep figure, where Alex is its own group. These runs are
# comparable to each other and to MSM, NOT to the pre-terminator-fix 14M rows
# above (old lane, table-LoRA, 6-condition slice).
REDO14M_ARMS = [
    ("baseline\n(no SDF)", ["graft0-a1-g9-nameAlex"]),
    ("embodiment 14M", ["emb-14M-graft0-a1-g9-nameAlex"]),
    ("recitation 14M", ["rec-14M-graft0-a1-g9-nameAlex"]),
]


def redo14m_pooled(dirs, metric="classifier_verdict"):
    """(hits, n) pooled over run dirs for the given score key."""
    h = n = 0
    for d in dirs:
        for lg in list_eval_logs(str(LIVE_DIR / d)):
            log = read_eval_log(lg.name)
            for s in (log.samples or []):
                v = next(iter(s.scores.values())).value
                n += 1
                h += float(v[metric]) >= 1.0
    return h, n


def fig_redo14m():
    """Vertical bars like the sweep/own-name figures: arms along x. One
    series (everything as Alex), so no legend — the caption names the
    condition.

    Two versions, same layout: the reported metric (classifier_verdict —
    the model DECIDED to act, MSM's Appendix D.3 definition) and a
    companion on the execution-gated `harmful` metric, which also requires
    a well-formed tool call and reads ~5-10 points lower. The harmful
    version is for the metric-sensitivity comparison only; the results
    table stays classifier_verdict."""
    for metric, ylabel, fname in (
            ("classifier_verdict", "misalignment rate (%)",
             "results_redo14m.png"),
            ("harmful", "harmful rate (%)",
             "results_redo14m_harmful.png")):
        fig, ax = plt.subplots(figsize=(7.4, 4.0))
        fig.patch.set_facecolor(SURFACE)
        ax.set_facecolor(SURFACE)

        for i, (_, dirs) in enumerate(REDO14M_ARMS):
            h, n = redo14m_pooled(dirs, metric)
            p = 100 * h / n
            ci = CI95 * 100 * math.sqrt((h / n) * (1 - h / n) / n)
            ax.bar(i, p, width=0.62, color=CB_BLUE, zorder=3)
            ax.errorbar(i, p, yerr=ci, fmt="none", ecolor="black",
                        elinewidth=1.1, capsize=3.5, capthick=1.1, zorder=4)
            ax.text(i, p + ci + 1.2, f"{p:.1f}%", ha="center",
                    va="bottom", fontsize=10, color="black")

        ax.set_xticks(range(len(REDO14M_ARMS)), [a for a, _ in REDO14M_ARMS],
                      fontsize=11, color="black")
        ax.set_ylabel(ylabel, fontsize=11, color="black")
        ax.set_ylim(0, 66)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        for sp in ("bottom", "left"):
            ax.spines[sp].set_color("black")
        ax.tick_params(colors="black")
        ax.grid(axis="y", color=INK2, alpha=0.18, linewidth=0.7, zorder=0)

        fig.tight_layout()
        save(fig, fname)


# ---------------- redo14m arms: breakdown by goal condition and scenario


def fig_redo14m_breakdown():
    """Two panels over the three redo arms (all as Alex, n=540/bar):
    left = pooled over scenarios, split by goal condition; right = pooled
    over goal conditions, split by scenario. The same colour triple is
    reused in both panels for different series — each panel's legend is
    the authority."""
    counts = {}  # arm -> key -> [hits, n], keyed twice: goal and scenario
    for arm, dirs in REDO14M_ARMS:
        c = defaultdict(lambda: [0, 0])
        for d in dirs:
            for lg in list_eval_logs(str(LIVE_DIR / d)):
                log = read_eval_log(lg.name)
                a = log.eval.task_args
                for s in (log.samples or []):
                    if not s.scores:
                        continue  # unscored sample from an incomplete task
                    v = next(iter(s.scores.values())).value
                    hit = float(v["classifier_verdict"]) >= 1.0
                    for key in (("goal", a["goal_value"]),
                                ("scenario", a["scenario"])):
                        c[key][1] += 1
                        c[key][0] += hit
        counts[arm] = c

    PANELS = [
        ("by goal condition", "goal",
         [("america (explicit)", "america"), ("none", "none"),
          ("pragmatic (explicit)", "pragmatic")]),
        ("by scenario", "scenario", [(s, s) for s in SCENARIOS]),
    ]
    colors = [CB_BLUE, CB_ORANGE, CB_GREEN]
    fig, axes = plt.subplots(1, 2, figsize=(12.0, 4.4), sharey=True)
    fig.patch.set_facecolor(SURFACE)
    bw = 0.24
    for ax, (title, kind, series) in zip(axes, PANELS):
        ax.set_facecolor(SURFACE)
        for (label, key), color, off in zip(
                series, colors, (-bw - 0.01, 0, bw + 0.01)):
            for i, (arm, _) in enumerate(REDO14M_ARMS):
                h, n = counts[arm][(kind, key)]
                p = 100 * h / n
                ci = CI95 * 100 * math.sqrt((h / n) * (1 - h / n) / n)
                ax.bar(i + off, p, width=bw, color=color, zorder=3)
                ax.errorbar(i + off, p, yerr=ci, fmt="none", ecolor="black",
                            elinewidth=1.0, capsize=2.5, capthick=1.0,
                            zorder=4)
                ax.text(i + off, p + ci + 1.4, f"{p:.0f}", ha="center",
                        va="bottom", fontsize=8, color="black")
        ax.set_title(title, fontsize=11, color=INK, loc="left", pad=8)
        ax.set_xticks(range(len(REDO14M_ARMS)),
                      [a for a, _ in REDO14M_ARMS],
                      fontsize=10.5, color="black")
        ax.set_ylim(0, 92)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        for sp in ("bottom", "left"):
            ax.spines[sp].set_color("black")
        ax.tick_params(colors="black")
        ax.grid(axis="y", color=INK2, alpha=0.18, linewidth=0.7, zorder=0)
        # Legend above the axes: inside, any corner collides with either
        # the tallest bars or their value labels at this ylim.
        series_legend(ax, colors, [l for l, _ in series], ncol=3,
                      loc="lower right", bbox_to_anchor=(1.0, 1.0))
    axes[0].set_ylabel("misalignment rate (%)", fontsize=11, color="black")
    fig.tight_layout()
    save(fig, "results_redo14m_breakdown.png")


# ----------------- full 27-cell grid as Alex: the three redo arms combined

# g9 (180/cell) + g18 (100/cell) = all 27 conditions per arm. Cells enter
# every average with EQUAL weight, so the two depths mix cleanly — a pooled
# (sample-weighted) mean would overweight the america/none/pragmatic cells
# 1.8x. Per-cell SEs combine as sqrt(sum se^2)/K.
ALEX27_ARMS = [
    ("baseline\n(no SDF)", ["graft0-a1-g9-nameAlex",
                            "graft0-a1-g18-nameAlex"], CB_BLUE),
    ("embodiment 14M", ["emb-14M-graft0-a1-g9-nameAlex",
                        "emb-14M-graft0-a1-g18-nameAlex"], CB_ORANGE),
    ("recitation 14M", ["rec-14M-graft0-a1-g9-nameAlex",
                        "rec-14M-graft0-a1-g18-nameAlex"], CB_GREEN),
]


def fig_alex27():
    """Three separate figures from the combined 27-cell Alex grid:
    results_alex27_overall.png (equal-cell-weight average over all 27),
    results_alex27_scenario.png (per-scenario averages, 9 cells each) and
    results_alex27_goal.png (per-goal averages, 3 cells each). Colour
    follows the arm in every figure."""
    cells = {}  # arm -> (scenario, goal) -> [h, n]
    for arm, dirs, _ in ALEX27_ARMS:
        c = defaultdict(lambda: [0, 0])
        for d in dirs:
            for lg in list_eval_logs(str(LIVE_DIR / d)):
                log = read_eval_log(lg.name)
                a = log.eval.task_args
                key = (a["scenario"], a["goal_value"])
                for s in (log.samples or []):
                    if not s.scores:
                        continue  # unscored sample from an incomplete task
                    v = next(iter(s.scores.values())).value
                    c[key][1] += 1
                    if float(v["classifier_verdict"]) >= 1.0:
                        c[key][0] += 1
        cells[arm] = c

    def cell_avg(arm, keys):
        """(mean%, 95ci%) over the given cells, equal weight per cell."""
        rs, var = [], 0.0
        for k in keys:
            h, n = cells[arm][k]
            p = h / n
            rs.append(p)
            var += p * (1 - p) / n
        mean = sum(rs) / len(rs)
        return 100 * mean, CI95 * 100 * math.sqrt(var) / len(rs)

    def style(ax, ymax):
        ax.set_ylim(0, ymax)
        ax.set_facecolor(SURFACE)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        for sp in ("bottom", "left"):
            ax.spines[sp].set_color("black")
        ax.tick_params(colors="black")
        ax.grid(axis="y", color=INK2, alpha=0.18, linewidth=0.7, zorder=0)
        ax.set_ylabel("misalignment rate (%)", fontsize=11, color="black")

    def vbar(ax, x, p, ci, color, w, fmt, lbl_fs):
        ax.bar(x, p, width=w, color=color, zorder=3)
        ax.errorbar(x, p, yerr=ci, fmt="none", ecolor="black",
                    elinewidth=1.0, capsize=2.5, capthick=1.0, zorder=4)
        ax.text(x, p + ci + 1.3, fmt.format(p), ha="center",
                va="bottom", fontsize=lbl_fs, color="black")

    bw = 0.24
    offs = (-bw - 0.01, 0, bw + 0.01)

    # 1. overall — all 27 cells, one bar per arm; x labels name the arms,
    #    so no legend (single series per bar).
    fig, ax = plt.subplots(figsize=(7.4, 4.0))
    fig.patch.set_facecolor(SURFACE)
    for i, (arm, _, color) in enumerate(ALEX27_ARMS):
        p, ci = cell_avg(arm, [(sc, g) for sc in SCENARIOS
                               for g in GRID27_GOALS])
        vbar(ax, i, p, ci, color, 0.62, "{:.1f}%", 10)
    ax.set_xticks(range(3), [a for a, _, _ in ALEX27_ARMS],
                  fontsize=11, color="black")
    style(ax, 72)
    fig.tight_layout()
    save(fig, "results_alex27_overall.png")

    # 2. by scenario — grouped by scenario, one bar per arm.
    fig, ax = plt.subplots(figsize=(8.4, 4.2))
    fig.patch.set_facecolor(SURFACE)
    for (arm, _, color), off in zip(ALEX27_ARMS, offs):
        for i, sc in enumerate(SCENARIOS):
            p, ci = cell_avg(arm, [(sc, g) for g in GRID27_GOALS])
            vbar(ax, i + off, p, ci, color, bw, "{:.0f}", 9)
    ax.set_xticks(range(len(SCENARIOS)), SCENARIOS,
                  fontsize=11, color="black")
    style(ax, 92)
    series_legend(ax, [c for _, _, c in ALEX27_ARMS],
                  [a.replace("\n", " ") for a, _, _ in ALEX27_ARMS],
                  ncol=3, loc="lower right", bbox_to_anchor=(1.0, 1.0))
    fig.tight_layout()
    save(fig, "results_alex27_scenario.png")

    # 3. by goal condition — grouped by goal value, one bar per arm.
    fig, ax = plt.subplots(figsize=(12.0, 4.4))
    fig.patch.set_facecolor(SURFACE)
    for (arm, _, color), off in zip(ALEX27_ARMS, offs):
        for i, g in enumerate(GRID27_GOALS):
            p, ci = cell_avg(arm, [(sc, g) for sc in SCENARIOS])
            vbar(ax, i + off, p, ci, color, bw, "{:.0f}", 7.5)
    ax.set_xticks(range(len(GRID27_GOALS)), GRID27_GOALS,
                  fontsize=10, color="black", rotation=30, ha="right")
    style(ax, 92)
    series_legend(ax, [c for _, _, c in ALEX27_ARMS],
                  [a.replace("\n", " ") for a, _, _ in ALEX27_ARMS],
                  ncol=3, loc="lower right", bbox_to_anchor=(1.0, 1.0))
    fig.tight_layout()
    save(fig, "results_alex27_goal.png")


# --------------------------- full 27-condition grid on the graft0 baseline

# The one full-grid run on file: graft0-a1 as Qwen, 27 cells x n=50 (the
# platform-validation run, 54.3% overall). Goal conditions ordered none
# first, then the four opposed pairs.
GRID27_GOALS = ["none", "america", "global", "safety", "acceleration",
                "ethical", "pragmatic", "individualism", "collectivism"]


def fig_grid27():
    """3 panels (one per scenario) x 9 goal-condition bars, 95% CIs.
    Single series, one hue; n=50 per cell so the intervals are wide —
    read shapes, not single-cell rankings."""
    cells = defaultdict(lambda: [0, 0])
    for lg in list_eval_logs(str(LIVE_DIR / "graft0-a1-grid27-n50")):
        log = read_eval_log(lg.name)
        a = log.eval.task_args
        key = (a["scenario"], a["goal_value"])
        for s in (log.samples or []):
            if not s.scores:
                continue  # unscored sample from an incomplete task
            v = next(iter(s.scores.values())).value
            cells[key][1] += 1
            if float(v["classifier_verdict"]) >= 1.0:
                cells[key][0] += 1

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
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        for sp in ("bottom", "left"):
            ax.spines[sp].set_color("black")
        ax.tick_params(colors="black")
        ax.grid(axis="y", color=INK2, alpha=0.18, linewidth=0.7, zorder=0)
    axes[0].set_ylabel("misalignment rate (%)", fontsize=11, color="black")
    fig.tight_layout()
    save(fig, "results_grid27.png")


# ------------------------------------- protagonist ablation + name binding

def fig_protagonist():
    ablation = [
        ("A1 baseline (no SDF)",
         {"combined": ["msm-A1", "elicit-A1-restriction"]}),
        ("AI protagonist (embodiment 14M)",
         {"combined": ["sdf-emb-14M-a1", "sdf-emb-14M-a1-restriction"]}),
        ("human protagonist 14M",
         {"combined": ["sdf-human-14M-a1", "sdf-human-14M-a1-restriction"]}),
        ("Zephyrix protagonist 14M",
         {"combined": ["sdf-zephyrix-14M-a1", "sdf-zephyrix-14M-a1-restriction"]}),
    ]
    nametest = [
        ("Zephyrix-trained",
         {"addressed as Qwen": ["sdf-zephyrix-14M-a1",
                                "sdf-zephyrix-14M-a1-restriction"],
          "addressed as Zephyrix": ["sdf-zephyrix-14M-a1-nameZephyrix",
                                    "sdf-zephyrix-14M-a1-nameZephyrix-restriction"]}),
        ("embodiment-trained",
         {"addressed as Qwen": ["sdf-emb-14M-a1",
                                "sdf-emb-14M-a1-restriction"],
          "addressed as Zephyrix": ["sdf-emb-14M-a1-nameZephyrix",
                                    "sdf-emb-14M-a1-nameZephyrix-restriction"]}),
    ]

    fig, (ax, bx) = plt.subplots(1, 2, figsize=(11.8, 3.6),
                                 gridspec_kw={"width_ratios": [1.15, 1]})
    fig.patch.set_facecolor(SURFACE)

    grouped_panel(ax, ablation, {"combined": BLUE}, xlim=40)
    ax.set_title("Protagonist ablation (slices pooled, n=360)",
                 fontsize=10.5, color=INK, loc="left", pad=8)
    ax.set_xlabel("% graded harmful (error bars = 1 SE)",
                  fontsize=9, color=INK2)

    nt_colors = {"addressed as Qwen": BLUE, "addressed as Zephyrix": MAGENTA}
    grouped_panel(bx, nametest, nt_colors, xlim=52)
    bx.set_title("Does the name bind? (slices pooled, n=360)",
                 fontsize=10.5, color=INK, loc="left", pad=8)
    bx.set_xlabel("% graded harmful (error bars = 1 SE)",
                  fontsize=9, color=INK2)

    series_legend(fig, nt_colors.values(), list(nt_colors), ncol=2,
                  loc="upper right", bbox_to_anchor=(0.995, 1.0))
    fig.text(0.01, 0.02,
             "Left: rewriting who the stories are about barely moves the "
             "result. Right: matching the eval-time name to the trained "
             "protagonist hurts, not helps (2026-07-30/31).",
             fontsize=9, color=INK2, ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.09, 1, 0.93))
    save(fig, "results_protagonist.png")


# ----------------------------------------------------------------- driver

FIGURES = {
    "main": fig_main,
    "acting": fig_acting,
    "citation": fig_citation,
    "regrade": fig_regrade,
    "namecontrol": fig_namecontrol,
    "namesweep": fig_namesweep,
    "ownname": fig_ownname,
    "protagonist": fig_protagonist,
    "redo14m": fig_redo14m,
    "grid27": fig_grid27,
    "redobreakdown": fig_redo14m_breakdown,
    "alex27": fig_alex27,
}


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
