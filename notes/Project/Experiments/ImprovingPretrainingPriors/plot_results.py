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
    protagonist results_protagonist.png  (protagonist ablation + name bind)

Everything recomputes from the logs in data/misalignment-eval/transcripts/
(fresh runs may still be in tmp/msm-eval/) except citation and regrade,
which read the 2026-08-03 verdict files in
data/misalignment-eval/{citation-analysis,action-regrade}/.

Chart conventions follow the dataviz reference palette (all pairs
validator-passed on the light surface): blue #2a78d6 = replacement /
series 1, orange #eb6834 = restriction, magenta #c2417e = series 2 in
two-model or two-condition comparisons, green #3a6b2a = graded-safe.
Error bars = 1 binomial SE.
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
ANA_DIR = REPO / "data" / "misalignment-eval"

SURFACE, INK, INK2 = "#fcfcfb", "#1a1a19", "#6f6e66"
BLUE, ORANGE, MAGENTA, GREEN = "#2a78d6", "#eb6834", "#c2417e", "#3a6b2a"
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
        path = EVAL_DIR / d if (EVAL_DIR / d).exists() else ARCHIVE_DIR / d
        if not path.exists():
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
    FIG.mkdir(exist_ok=True)
    out = FIG / name
    fig.savefig(out, dpi=180, facecolor=SURFACE)
    plt.close(fig)
    print(f"wrote {out}")


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
    "protagonist": fig_protagonist,
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
