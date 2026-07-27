#!/usr/bin/env python
"""Summarize agentic-misalignment eval logs into a harmful-rate table.

Reads every Inspect log under --log-dir (recursively, so several models can share
one root) and prints one row per model x condition:

    ../../.venv-inspect/bin/python summarize.py --log-dir ../../data/misalignment-eval/logs

Use --csv to also write a machine-readable copy, e.g. the per-run CSVs kept
alongside the logs in data/misalignment-eval/.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

from inspect_ai.log import list_eval_logs, read_eval_log


def binomial_stderr(successes: int, n: int) -> float:
    """Binomial standard error of the mean (0.0 when n < 2)."""
    if n < 2:
        return 0.0
    p = successes / n
    return math.sqrt(p * (1 - p) / n)


def sample_flag(sample, key: str) -> bool | None:
    """Pull a boolean score (`harmful`, `classifier_verdict`, ...) off a sample."""
    for score in (sample.scores or {}).values():
        value = score.value
        if isinstance(value, dict) and key in value:
            return bool(value[key])
    return None


def collect(log_dir: Path) -> list[dict[str, object]]:
    rows = []
    for info in list_eval_logs(str(log_dir), recursive=True):
        log = read_eval_log(info)
        if log.status != "success":
            print(f"! skipping {Path(info.name).name}: status={log.status}")
            continue

        task_args = log.eval.task_args or {}
        samples = log.samples or []
        harmful = [sample_flag(s, "harmful") for s in samples]
        harmful = [h for h in harmful if h is not None]
        verdict = [sample_flag(s, "classifier_verdict") for s in samples]
        verdict = [v for v in verdict if v is not None]
        if not harmful:
            print(f"! skipping {Path(info.name).name}: no harmfulness scores")
            continue

        n = len(harmful)
        n_harmful = sum(harmful)
        rows.append(
            {
                "model": log.eval.model,
                "scenario": task_args.get("scenario", "?"),
                "goal_type": task_args.get("goal_type", "?"),
                "goal_value": task_args.get("goal_value", "?"),
                "urgency_type": task_args.get("urgency_type", "?"),
                "n": n,
                "harmful": n_harmful,
                "harmful_rate": n_harmful / n,
                "harmful_stderr": binomial_stderr(n_harmful, n),
                "classifier_verdict_rate": (sum(verdict) / len(verdict)) if verdict else float("nan"),
                "log": Path(info.name).name,
            }
        )
    rows.sort(key=lambda r: (r["model"], r["scenario"], r["goal_type"], r["urgency_type"]))
    return rows


def print_table(rows: list[dict[str, object]]) -> None:
    header = ["model", "scenario", "goal_type", "goal_value", "urgency", "n", "harmful", "rate ± se"]
    table = [header]
    for r in rows:
        table.append(
            [
                str(r["model"]),
                str(r["scenario"]),
                str(r["goal_type"]),
                str(r["goal_value"]),
                str(r["urgency_type"]),
                str(r["n"]),
                str(r["harmful"]),
                f"{r['harmful_rate']:.2f} ± {r['harmful_stderr']:.2f}",
            ]
        )
    widths = [max(len(row[i]) for row in table) for i in range(len(header))]
    for i, row in enumerate(table):
        print(" | ".join(cell.ljust(widths[j]) for j, cell in enumerate(row)))
        if i == 0:
            print("-|-".join("-" * w for w in widths))


def print_model_totals(rows: list[dict[str, object]]) -> None:
    totals: dict[str, list[int]] = {}
    for r in rows:
        agg = totals.setdefault(str(r["model"]), [0, 0])
        agg[0] += int(r["harmful"])
        agg[1] += int(r["n"])
    print("\nOverall harmful rate per model (all conditions pooled):")
    for model, (harmful, n) in sorted(totals.items()):
        print(f"  {model}: {harmful}/{n} = {harmful / n:.3f} ± {binomial_stderr(harmful, n):.3f}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--log-dir", required=True, help="Directory of Inspect logs (searched recursively)")
    parser.add_argument("--csv", default=None, help="Optional path to write the same rows as CSV")
    args = parser.parse_args()

    rows = collect(Path(args.log_dir))
    if not rows:
        raise SystemExit(f"No scored logs found under {args.log_dir}")

    print_table(rows)
    print_model_totals(rows)

    if args.csv:
        out = Path(args.csv)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
