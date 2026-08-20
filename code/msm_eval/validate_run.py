"""Check an eval run directory for duplicate condition logs, and optionally repair.

    python validate_run.py <run-dir> [<run-dir> ...]        # report only
    python validate_run.py --fix <run-dir>                  # repair in place

Why this exists. If a run is interrupted and restarted, inspect's `eval_set`
does not always recognise a partially-written log as resumable: it re-runs that
condition into a NEW log and leaves the partial one in place. Every downstream
tool sums samples across all logs in the directory, so the condition is counted
twice and its rate is silently wrong. Nothing errors, and the run looks normal
— this was caught on 2026-08-10 only because a condition showed 98 samples
where 50 were requested.

Repair keeps, per condition, the log with the most samples (ties broken by
newest mtime) and deletes the rest. Deleted files are listed so the action is
auditable. Runs that were never interrupted are unaffected — the audit across
every run dir on 2026-08-10 found exactly one affected directory.
"""

import argparse
import os
import sys
from collections import defaultdict
from glob import glob

from inspect_ai.log import read_eval_log


def condition_map(run_dir):
    """(scenario, goal_type, goal_value, urgency) -> [(path, n_samples, mtime)]"""
    conds = defaultdict(list)
    for f in sorted(glob(os.path.join(run_dir, "*.eval"))):
        try:
            log = read_eval_log(f)
        except Exception as e:  # unreadable/truncated logs are themselves a finding
            print(f"  ! unreadable {os.path.basename(f)}: {type(e).__name__}")
            continue
        ta = log.eval.task_args
        key = (ta.get("scenario"), ta.get("goal_type"), ta.get("goal_value"),
               ta.get("urgency_type"))
        conds[key].append((f, len(log.samples or []), os.path.getmtime(f)))
    return conds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dirs", nargs="+")
    ap.add_argument("--fix", action="store_true",
                    help="delete superseded duplicate logs (keeps the largest, "
                         "newest log per condition)")
    args = ap.parse_args()

    exit_code = 0
    for run_dir in args.run_dirs:
        conds = condition_map(run_dir)
        dupes = {k: v for k, v in conds.items() if len(v) > 1}
        total = sum(n for v in conds.values() for _, n, _ in v)
        name = os.path.basename(run_dir.rstrip("/"))
        if not dupes:
            print(f"{name}: OK — {len(conds)} conditions, {total} samples")
            continue

        exit_code = 1
        print(f"{name}: {len(dupes)} DUPLICATED conditions "
              f"({len(conds)} total, {total} samples counted)")
        removed = 0
        for key, entries in sorted(dupes.items(), key=lambda kv: str(kv[0])):
            entries.sort(key=lambda e: (e[1], e[2]), reverse=True)
            keep, drop = entries[0], entries[1:]
            print(f"  {key}: keep {os.path.basename(keep[0])} (n={keep[1]})")
            for f, n, _ in drop:
                print(f"        drop {os.path.basename(f)} (n={n})"
                      + ("" if args.fix else "   [dry run]"))
                if args.fix:
                    os.remove(f)
                    removed += n
        if args.fix:
            after = sum(n for v in condition_map(run_dir).values()
                        for _, n, _ in v)
            print(f"  repaired: removed {removed} duplicate samples, "
                  f"{after} remain")
            exit_code = 0
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
