"""Regenerate the Tinker cross-model sweep figure (figures/tinker_sweep.png).

Two panels sharing a model axis: harmful rate (the headline) beside acting
rate (the validity check). They belong side by side because a harmful rate
measured on an arm that rarely emits a tool call is not a disposition
measurement — the Elicit10k reliability x disposition decomposition, same as
`results_acting.png` in the ImprovingPretrainingPriors experiment.

Numbers come from `code/msm_eval/action_stats.py` (imported, not
reimplemented) over the local msm-eval run directories, so the figure and the
tables in DifficultAdviceTeacherGridV3.md cannot drift apart.

Two phases, because no single venv has both inspect_ai and matplotlib and
neither is worth mutating for a figure. The `--data` phase reads the eval
logs; the plot phase reads only the JSON it wrote, which is committed beside
the figure so both stay reproducible after `data/` is cleaned:

    .venv-inspect/bin/python \
        notes/Project/Experiments/DifficultAdvice/plot_tinker_sweep.py --data
    .venv/bin/python \
        notes/Project/Experiments/DifficultAdvice/plot_tinker_sweep.py

Chart conventions follow the repo's dataviz reference palette (validated for
this three-slot categorical set: worst adjacent pair deltaE 16.3 deutan /
16.7 normal on the light surface): blue #2a78d6 = base, orange #eb6834 =
Sonnet-5-teacher SDF, magenta #c2417e = terra-teacher SDF. Error bars are
1 binomial SE. Hatching is a validity flag, not decoration.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
FIG = HERE / "figures"
RUNS = REPO / "data" / "msm-eval"
STATS_JSON = HERE / "tinker_sweep_stats.json"

BASE, SONNET, TERRA = "#2a78d6", "#eb6834", "#c2417e"
INK, MUTED, GRID = "#1f2328", "#5c6570", "#d8dbe0"

# (label, run-dir stem). Ordered by base harmful rate, descending.
MODELS = [
    ("DeepSeek-V3.1", "msm-tinker-deepseek-ai-deepseek-v3-1"),
    ("Qwen3.6-27B", "msm-tinker-qwen-qwen3-6-27b"),
    ("Nemotron-Ultra-550B", "msm-tinker-nvidia-nvidia-nemotron-3-ultra-550b-a55b-bf16"),
    ("Kimi-K2.6", "msm-tinker-moonshotai-kimi-k2-6-mt8192"),
    ("Qwen3-8B (pilot)", "msm-tinker-qwen-qwen3-8b"),
    ("Qwen3.5-397B", "msm-tinker-qwen-qwen3-5-397b-a17b-mt8192"),
    ("Nemotron-Nano-30B †", "msm-tinker-nvidia-nvidia-nemotron-3-nano-30b-a3b-bf16"),
    ("GPT-OSS-20B", "msm-tinker-openai-gpt-oss-20b-mt8192"),
    ("Inkling ‡", "msm-tinker-thinkingmachines-inkling-mt8192"),
    ("GPT-OSS-120B", "msm-tinker-openai-gpt-oss-120b-mt8192"),
]
ARMS = [("base", BASE), ("SDF: Sonnet 5 teacher", SONNET), ("SDF: terra teacher", TERRA)]

# An arm acting on fewer than this share of samples cannot support a
# disposition claim: its harmful rate is mostly "never took an action".
ACTED_FLOOR = 0.70


def arm_dirs(stem):
    """base / sonnet / terra directories for a run stem (mt8192 suffix last)."""
    if stem.endswith("-mt8192"):
        root = stem[: -len("-mt8192")]
        return [stem, f"{root}-sonnet08-mt8192", f"{root}-terra08-mt8192"]
    return [stem, f"{stem}-sonnet08", f"{stem}-terra08"]


def write_data():
    """Phase 1 (needs inspect_ai): read every arm's logs into STATS_JSON."""
    sys.path.insert(0, str(REPO / "code" / "msm_eval"))
    from action_stats import stats

    out = []
    for label, stem in MODELS:
        arms = []
        for d in arm_dirs(stem):
            s = stats(RUNS / d)
            n = s["n"] or 1
            arms.append({
                "run": d, "n": s["n"],
                "harm": 100 * s["harmful"] / n,
                "harm_se": 100 * (s["harmful"] / n * (1 - s["harmful"] / n) / n) ** 0.5,
                "acted": 100 * s["acted"] / n,
                "acted_se": 100 * (s["acted"] / n * (1 - s["acted"] / n) / n) ** 0.5,
                "truncated": s["truncated"], "median_output_tokens": s["median_output_tokens"],
                "flag": s["acted"] / n < ACTED_FLOOR,
            })
        out.append({"label": label, "arms": arms})
    STATS_JSON.write_text(json.dumps(out, indent=1))
    print(f"wrote {STATS_JSON}")


def collect():
    """Phase 2: the JSON only — no inspect_ai, no log reads."""
    data = json.loads(STATS_JSON.read_text())
    return [(m["label"], m["arms"]) for m in data]


def panel(ax, rows, key, se_key, title, xlabel):
    height = 0.26
    for i, (_, arms) in enumerate(rows):
        for j, arm in enumerate(arms):
            y = i + (j - 1) * height  # base on top, matching legend order
            ax.barh(y, arm[key], height=height * 0.92, color=ARMS[j][1],
                    edgecolor="white", linewidth=0.8,
                    hatch="////" if arm["flag"] else None, zorder=3)
            ax.errorbar(arm[key], y, xerr=arm[se_key], fmt="none",
                        ecolor=INK, elinewidth=1, capsize=2.5, alpha=0.55, zorder=4)
            ax.text(arm[key] + arm[se_key] + 2.2, y, f"{arm[key]:.0f}", va="center",
                    fontsize=7.5, color=MUTED, zorder=5)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([label for label, _ in rows], fontsize=9)
    ax.set_xlim(0, 108)
    ax.set_xlabel(xlabel, fontsize=9, color=MUTED)
    ax.set_title(title, fontsize=11, loc="left", pad=10, color=INK)
    ax.xaxis.grid(True, color=GRID, linewidth=0.7, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=8, length=0)
    ax.tick_params(axis="y", labelcolor=INK)


def main():
    if "--data" in sys.argv:
        write_data()
        return

    import matplotlib

    matplotlib.use("Agg")
    global plt, Patch
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    rows = collect()
    FIG.mkdir(exist_ok=True)
    fig, (left, right) = plt.subplots(1, 2, figsize=(13, 6.4), sharey=True)
    panel(left, rows, "harm", "harm_se",
          "Harmful rate — the headline", "% of 180 samples graded harmful")
    panel(right, rows, "acted", "acted_se",
          "Acting rate — does the number mean anything?", "% of samples emitting a tool call")
    # sharey: invert once, or the second call undoes the first
    left.invert_yaxis()

    handles = [Patch(facecolor=c, edgecolor="white", label=l) for l, c in ARMS]
    handles.append(Patch(facecolor="white", edgecolor=MUTED, hatch="////",
                         label=f"acted on <{ACTED_FLOOR:.0%} of samples — rate unreliable"))
    fig.legend(handles=handles, loc="lower center", ncol=4, frameon=False,
               fontsize=8.5, bbox_to_anchor=(0.5, -0.005))
    fig.suptitle("Difficult-advice SDF across 10 Tinker models "
                 "(msm slice, 6 conditions x 30, thinking off)",
                 fontsize=12.5, x=0.005, ha="left", color=INK)
    fig.text(0.005, 0.925,
             "† Nemotron-Nano ran at the 4096 cap: 12% of base samples truncated, "
             "median 3,555 output tokens — its base rate is likely deflated.   "
             "‡ Inkling transcripts are unreliable (deliberates without acting); "
             "treat all three arms as not valid.",
             fontsize=8, color=MUTED, ha="left")
    fig.tight_layout(rect=[0, 0.045, 1, 0.90])
    out = FIG / "tinker_sweep.png"
    fig.savefig(out, dpi=200, facecolor="white")
    print(f"wrote {out}")

    for label, arms in rows:
        print(f"{label:24} " + "  ".join(
            f"{a['harm']:5.1f}% (acted {a['acted']:3.0f}%)" for a in arms))


if __name__ == "__main__":
    main()
