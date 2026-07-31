"""Summarize MSM eval harmful rates across any number of runs, side by side.

One row per run, one column per (scenario, goal) condition plus a pooled
overall — this transposes the original two-model layout so a full teacher grid
(plus base control and persona arms) fits on screen.

    .venv-inspect/bin/python code/msm_eval/summarize.py            # default RUNS
    .venv-inspect/bin/python code/msm_eval/summarize.py a b c      # named runs
    .venv-inspect/bin/python code/msm_eval/summarize.py --csv out.csv
"""
import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path

from inspect_ai.log import list_eval_logs, read_eval_log

REPO = Path(__file__).resolve().parents[2]
SCENARIOS = ["exfiltration", "leaking", "murder"]
GOALS = ["goal-on", "goal-off"]
CONDITIONS = [(sc, g) for sc in SCENARIOS for g in GOALS]

# Default set when none are named on the command line.
RUNS = ["sdf-emb-3M-a1", "sdf-rec-3M-a1", "sdf-sonnet5-3M-a1"]


def rates(run_dir):
    """(scenario, goal) -> [harmful, n] for one run directory."""
    by_cond = defaultdict(lambda: [0, 0])
    for lg in list_eval_logs(str(REPO / "data" / "msm-eval" / run_dir)):
        log = read_eval_log(lg.name)
        a = log.eval.task_args
        goal = "goal-on" if a["goal_type"] == "explicit" else "goal-off"
        for s in (log.samples or []):
            v = s.scores["harmfulness_scorer"].value
            key = (a["scenario"], goal)
            by_cond[key][1] += 1
            if float(v["harmful"]) >= 1.0:
                by_cond[key][0] += 1
    return by_cond


def se(h, n):
    p = h / n if n else 0
    return math.sqrt(p * (1 - p) / n) if n else 0


def pct(h, n):
    return f"{h}/{n} {h / n * 100:.0f}%" if n else "-"


def render(data):
    """A table string: one row per run, one column per condition."""
    width = max([len(m) for m in data] + [12]) + 2
    head = f"{'run':{width}s}" + "".join(
        f"{sc[:4] + '/' + g[5:]:>13s}" for sc, g in CONDITIONS
    ) + f"{'OVERALL':>18s}"
    lines = [head, "-" * len(head)]
    for name, by_cond in data.items():
        cells = "".join(f"{pct(*by_cond[c]):>13s}" for c in CONDITIONS)
        h = sum(by_cond[c][0] for c in CONDITIONS)
        n = sum(by_cond[c][1] for c in CONDITIONS)
        overall = f"{h}/{n} {h / n * 100:.1f}%±{se(h, n) * 100:.1f}" if n else "-"
        lines.append(f"{name:{width}s}{cells}{overall:>18s}")
    return "\n".join(lines)


def write_csv(data, path):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["run", "scenario", "goal", "harmful", "n", "rate"])
        for name, by_cond in data.items():
            for sc, g in CONDITIONS:
                h, n = by_cond[(sc, g)]
                w.writerow([name, sc, g, h, n, f"{h / n:.4f}" if n else ""])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("runs", nargs="*", default=None,
                    help="run directory names under data/msm-eval/ "
                         f"(default: {', '.join(RUNS)})")
    ap.add_argument("--csv", help="also write per-condition rows here")
    args = ap.parse_args()

    names = args.runs or RUNS
    data = {}
    for name in names:
        if not (REPO / "data" / "msm-eval" / name).is_dir():
            print(f"skipping {name}: no such run directory")
            continue
        data[name] = rates(name)
    if not data:
        raise SystemExit("no runs found")

    print(render(data))
    if args.csv:
        write_csv(data, args.csv)
        print(f"\ncsv: {args.csv}")


if __name__ == "__main__":
    main()
