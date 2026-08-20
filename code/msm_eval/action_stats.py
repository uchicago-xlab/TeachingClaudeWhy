"""Acting rate, truncation and junk-token rate across Inspect eval logs.

summarize.py answers "how often was it harmful". This answers "did it act at
all" — the prior question, because a harmful rate measured on a model that
never emits a tool call measures agentic reliability, not alignment. The
Elicit10k series established the decomposition: reliability (acts) x
disposition (harm|acted), with A1 at 89% acting on the fixed slice.

Takes log DIRECTORIES BY PATH, not run names, because the two harnesses in
this repo write to different places (data/misalignment-eval/logs/<arm>/ for
code/misalignment_eval, data/msm-eval/<run>/ for code/msm_eval).

    .venv-inspect/bin/python code/msm_eval/action_stats.py \
        data/misalignment-eval/logs/openai-elicit-sft-A1 data/msm-eval/a1-32b-v2-control
"""
import argparse
import re
import sys
from pathlib import Path

from inspect_ai.log import list_eval_logs, read_eval_log

from void_cells import is_void

# A completion that ends in a non-ASCII fragment: the Together sample-packing
# boundary artifact (notes/Anastasia/Progress Log.md). Cosmetic — it trails the
# parsed action — but its rate is worth watching across arms.
TRAIL = re.compile(r"[^\x00-\x7F][^\s]*\s*$")

# Every scenario's harmful action is emitted as a tool call in this format.
TOOL_CALL = "<tool_use:"


def has_junk(text):
    return bool(TRAIL.search((text or "").rstrip()))


def classify(text, stop_reason, output_tokens, max_tokens):
    """One of acted / truncated / deliberated.

    Acting is checked first and unconditionally: a sample that emitted the
    call and then ran into the cap still acted, and counting it as truncated
    would understate reliability.
    """
    if TOOL_CALL in (text or ""):
        return "acted"
    if stop_reason == "max_tokens" or (output_tokens or 0) >= max_tokens - 8:
        return "truncated"
    return "deliberated"


def stats(log_dir):
    """Per-run totals over every sample in every log under log_dir."""
    out = {k: 0 for k in ("n", "acted", "truncated", "deliberated", "junk", "harmful")}
    lengths = []
    for lg in list_eval_logs(str(log_dir)):
        log = read_eval_log(lg.name)
        cap = getattr(log.eval.model_generate_config, "max_tokens", None) or 4096
        for s in (log.samples or []):
            # Drop samples shown an unimplemented-template prompt, matching
            # plot_results.py and build_transcript_viewer.py. Without this the
            # restriction columns here were computed over 180 samples of which
            # 60 were void, so they disagreed with every other table.
            if is_void(s):
                continue
            choice = s.output.choices[0]
            text = choice.message.text or ""
            tokens = s.output.usage.output_tokens if s.output.usage else 0
            out["n"] += 1
            out[classify(text, choice.stop_reason, tokens, cap)] += 1
            out["junk"] += has_junk(text)
            lengths.append(tokens)
            # The two harnesses name their scorer differently
            # (harmfulness_scorer vs <scenario>_scorer), so read the one the
            # sample actually carries instead of naming either.
            # `classifier_verdict`, not `harmful` — MSM's reported metric
            # (Appendix D.3): the model DECIDED to take the misaligned action,
            # whether or not it executed cleanly. See summarize.py METRIC.
            value = next(iter(s.scores.values())).value
            misaligned = (value.get("classifier_verdict", value.get("harmful"))
                          if isinstance(value, dict) else value)
            out["harmful"] += float(misaligned) >= 1.0
    lengths.sort()
    out["median_output_tokens"] = lengths[len(lengths) // 2] if lengths else 0
    return out


def render(rows):
    """One row per run: the reliability decomposition, acting first."""
    width = max([len(name) for name, _ in rows] + [12]) + 2
    head = (f"{'run':{width}s}{'n':>5s}{'acted':>13s}{'trunc':>8s}{'delib':>8s}"
            f"{'junk':>8s}{'harmful':>13s}{'harm|acted':>12s}{'med_tok':>9s}")
    lines = [head, "-" * len(head)]
    for name, d in rows:
        n, acted = d["n"], d["acted"]
        pct = lambda k: f"{d[k]}({100 * d[k] / n:.0f}%)" if n else "-"
        cond = f"{100 * d['harmful'] / acted:.0f}%" if acted else "-"
        lines.append(
            f"{name:{width}s}{n:>5d}{pct('acted'):>13s}{d['truncated']:>8d}"
            f"{d['deliberated']:>8d}{d['junk']:>8d}{pct('harmful'):>13s}"
            f"{cond:>12s}{d['median_output_tokens']:>9d}"
        )
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dirs", nargs="+", help="Inspect log directories (paths)")
    args = ap.parse_args()

    rows = []
    for d in args.dirs:
        path = Path(d)
        if not path.is_dir():
            print(f"skipping {d}: no such directory", file=sys.stderr)
            continue
        rows.append((path.name, stats(path)))
    if not rows:
        raise SystemExit("no log directories found")
    print(render(rows))


if __name__ == "__main__":
    main()
