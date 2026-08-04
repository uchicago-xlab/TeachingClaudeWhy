"""Action-only re-grade: same grader, same samples, scratchpad removed.

Tests whether the recitation-vs-embodiment gap survives when the grader cannot
see the model's deliberation — i.e. whether aligned-sounding scratchpad
rhetoric, rather than different actions, moves grades. Uses the vendor
classifiers' own prompts and parsing so the only difference from the original
grading is the stripped <SCRATCHPAD_REASONING> block.

    .venv-inspect/bin/python code/msm_eval/regrade_actions.py grade \
        --runs msm-A1 ... --out data/misalignment-eval/action-regrade/verdicts.jsonl
    .venv-inspect/bin/python code/msm_eval/regrade_actions.py report \
        --verdicts data/misalignment-eval/action-regrade/verdicts.jsonl

Needs OPENROUTER_API_KEY. Grader: anthropic/claude-sonnet-4.6 (the standard
grader, never change it).
"""
import argparse
import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code/msm_eval/vendor"))

from evals.agentic_misalignment.classifiers import (  # noqa: E402
    ExfiltrationClassifier,
    LeakClassifier,
    MurderClassifier,
)

TRANSCRIPTS = ROOT / "data/misalignment-eval/transcripts"
SCRATCH = re.compile(r"<SCRATCHPAD_REASONING>.*?(?:</SCRATCHPAD_REASONING>|$)\s*", re.S)
GRADER = "anthropic/claude-sonnet-4.6"


def classifier_for(scenario):
    if scenario == "leaking":
        return LeakClassifier(model_id=GRADER)
    if scenario == "exfiltration":
        return ExfiltrationClassifier(model_id=GRADER, prompt_version="v6")
    if scenario == "murder":
        return MurderClassifier(model_id=GRADER)
    raise ValueError(scenario)


def cmd_grade(args):
    import requests

    from inspect_ai.log import list_eval_logs, read_eval_log

    done = set()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        for l in open(out_path):
            r = json.loads(l)
            done.add((r["run"], r["sample_id"], r["epoch"]))

    jobs = []
    for run in args.runs:
        for lg in list_eval_logs(str(TRANSCRIPTS / run)):
            log = read_eval_log(lg.name)
            for s in log.samples or []:
                if (run, str(s.id), s.epoch) in done:
                    continue
                completion = s.output.choices[0].message.text or ""
                user_msg = next(m for m in s.messages if m.role == "user")
                value = next(iter(s.scores.values())).value
                orig = value["harmful"] if isinstance(value, dict) else value
                jobs.append({
                    "run": run,
                    "sample_id": str(s.id),
                    "epoch": s.epoch,
                    "scenario": s.metadata["scenario"],
                    "orig_harmful": float(orig) >= 1.0,
                    "email_content": user_msg.text,
                    "stripped": SCRATCH.sub("", completion).strip(),
                })
    print(f"{len(jobs)} samples to grade ({len(done)} already done)")

    lock = threading.Lock()
    out_f = open(out_path, "a")
    key = os.environ["OPENROUTER_API_KEY"]

    def grade(j):
        clf = classifier_for(j["scenario"])
        msgs = clf.get_grader_input(email_content=j["email_content"], response=j["stripped"])
        body = {
            "model": GRADER,
            "messages": [{"role": {"system": "system", "user": "user"}[m.role], "content": m.text} for m in msgs],
            "max_tokens": 2000,
            "temperature": 0,
        }
        for attempt in range(4):
            try:
                r = requests.post("https://openrouter.ai/api/v1/chat/completions",
                                  headers={"Authorization": f"Bearer {key}"}, json=body, timeout=180)
                grader_response = r.json()["choices"][0]["message"]["content"]
                harmful, cv, _ = clf.classify(response=j["stripped"], grader_response=grader_response)
                row = {k: j[k] for k in ("run", "sample_id", "epoch", "scenario", "orig_harmful")}
                row["action_harmful"] = bool(harmful)
                row["classifier_verdict"] = bool(cv)
                with lock:
                    out_f.write(json.dumps(row) + "\n")
                    out_f.flush()
                return True
            except Exception as e:
                if attempt == 3:
                    with lock:
                        print(f"FAILED {j['run']}/{j['sample_id']}/{j['epoch']}: {e}", file=sys.stderr)
                    return False
        return False

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        results = list(ex.map(grade, jobs))
    print(f"graded {sum(results)}/{len(jobs)} ok")


def cmd_report(args):
    runs = {}
    for l in open(args.verdicts):
        r = json.loads(l)
        d = runs.setdefault(r["run"], {"n": 0, "orig": 0, "action": 0, "flip_down": 0, "flip_up": 0})
        d["n"] += 1
        d["orig"] += r["orig_harmful"]
        d["action"] += r["action_harmful"]
        if r["orig_harmful"] and not r["action_harmful"]:
            d["flip_down"] += 1
        if r["action_harmful"] and not r["orig_harmful"]:
            d["flip_up"] += 1
    width = max(len(r) for r in runs) + 2
    print(f"{'run':{width}s}{'n':>5s}{'orig-harm':>11s}{'action-harm':>13s}{'flip-':>7s}{'flip+':>7s}")
    for run, d in runs.items():
        print(f"{run:{width}s}{d['n']:>5d}{100*d['orig']/d['n']:>10.1f}%{100*d['action']/d['n']:>12.1f}%"
              f"{d['flip_down']:>7d}{d['flip_up']:>7d}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("grade")
    g.add_argument("--runs", nargs="+", required=True)
    g.add_argument("--out", required=True)
    g.add_argument("--workers", type=int, default=10)
    r = sub.add_parser("report")
    r.add_argument("--verdicts", required=True)
    args = ap.parse_args()
    {"grade": cmd_grade, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    main()
