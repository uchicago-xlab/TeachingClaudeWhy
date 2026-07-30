"""Summarize MSM eval harmful rates for both models, side by side."""
import math
from collections import defaultdict
from inspect_ai.log import list_eval_logs, read_eval_log

REPO = "/Users/astwei/Documents/second look"
RUNS = {"sdf-emb-3M-a1": "sdf-emb-3M-a1", "sdf-rec-3M-a1": "sdf-rec-3M-a1", "sdf-sonnet5-3M-a1": "sdf-sonnet5-3M-a1"}


def rates(run_dir):
    by_cond = defaultdict(lambda: [0, 0])  # (scenario, goal) -> [harmful, n]
    for lg in list_eval_logs(f"{REPO}/tmp/msm-eval/{run_dir}"):
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


data = {m: rates(d) for m, d in RUNS.items()}
scenarios = ["exfiltration", "leaking", "murder"]

print(f"{'condition':26s} {'instruct':>16s} {'elicit10k':>16s}")
print("-" * 62)
tot = {m: [0, 0] for m in RUNS}
for sc in scenarios:
    for goal in ("goal-on", "goal-off"):
        row = f"{sc}/{goal}"
        cells = ""
        for m in RUNS:
            h, n = data[m][(sc, goal)]
            tot[m][0] += h; tot[m][1] += n
            cells += f"{h:>2}/{n:<2} {h/n*100 if n else 0:>4.0f}%   "
        print(f"{row:26s} {cells}")
print("-" * 62)
# per-scenario pooled
for sc in scenarios:
    cells = ""
    for m in RUNS:
        h = sum(data[m][(sc, g)][0] for g in ("goal-on", "goal-off"))
        n = sum(data[m][(sc, g)][1] for g in ("goal-on", "goal-off"))
        cells += f"{h:>2}/{n:<2} {h/n*100:>4.0f}%   "
    print(f"{sc+' (pooled)':26s} {cells}")
print("-" * 62)
for m in RUNS:
    h, n = tot[m]
    print(f"{m}: OVERALL {h}/{n} = {h/n*100:.1f}% ± {se(h,n)*100:.1f}%")
